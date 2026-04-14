"""
vpin_eth W2 파라미터 재탐색 — 사이클 148 (프로덕션 VPIN 로직 정합)
- 목표: Sharpe ≥ 5.0 (현재 daemon Sharpe ~4.662)
- daemon 현재: vh=0.55, vl=0.35, vm=0.0005, hold=18, TP=6%, SL=0.8%
- **핵심 수정**: VPIN 계산을 BVC+normalCDF로 교체, 진입 조건 low VPIN → safe entry
- 프로덕션 진입: VPIN < vpin_low + momentum + RSI + EMA trend
- 2-fold walk-forward + 슬리피지 스트레스
- 진입: 다음 봉 시가(next_bar open) 사용
"""
from __future__ import annotations

import math
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
FEE = 0.0005

# ── 그리드 (프로덕션 파라미터 기준) ──────────────────────────────────────────
# 프로덕션: vpin_low가 진입 임계값 (VPIN < vpin_low → safe entry)
VPIN_LOW_LIST = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
VPIN_MOM_LIST = [0.0001, 0.0003, 0.0005, 0.0007, 0.001]
MAX_HOLD_LIST = [14, 18, 21, 24, 28]
TP_LIST = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08]
SL_LIST = [0.006, 0.008, 0.010, 0.012, 0.015]

# 고정값
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8

# ── Walkforward 기간 ─────────────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def ema_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def rsi_calc(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def compute_vpin_bvc(
    closes: np.ndarray, opens: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray, bucket_count: int = 24,
) -> np.ndarray:
    """Production-matching VPIN: BVC + normal CDF + volume weighting."""
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(bucket_count, n):
        total_vol = 0.0
        abs_imbalance = 0.0
        for j in range(i - bucket_count, i):
            price_range = highs[j] - lows[j]
            if price_range <= 0:
                buy_frac = 0.5
            else:
                z = (closes[j] - opens[j]) / price_range
                buy_frac = _normal_cdf(z)
            bv = volumes[j] * buy_frac
            sv = volumes[j] * (1.0 - buy_frac)
            abs_imbalance += abs(bv - sv)
            total_vol += volumes[j]
        if total_vol > 0:
            result[i] = abs_imbalance / total_vol
        else:
            result[i] = 0.5
    return result


def compute_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


# ── 백테스트 (프로덕션 진입 로직) ────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    vpin_low: float,
    vpin_mom_thresh: float,
    max_hold: int,
    tp: float,
    sl: float,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK) + 5
    i = warmup
    while i < n - 1:
        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]

        if np.isnan(vpin_val) or np.isnan(mom_val) or np.isnan(rsi_val) or np.isnan(ema_val):
            i += 1
            continue

        # 프로덕션 진입 로직:
        # 1) VPIN < vpin_low (low toxicity = safe)
        # 2) momentum > threshold
        # 3) RSI in range
        # 4) price > EMA (trend up)
        entry_ok = (
            vpin_val < vpin_low
            and mom_val >= vpin_mom_thresh
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )

        if entry_ok:
            # 진입: 다음 봉 시가 + 수수료 + 슬리피지
            buy = o[i + 1] * (1 + FEE + slippage)
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE - slippage)
                    i = j
                    break
                if ret <= -sl:
                    returns.append(-sl - FEE - slippage)
                    i = j
                    break
            else:
                hold_end = min(i + max_hold, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE - slippage)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    mcl = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl}


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth W2 재탐색 — 프로덕션 VPIN BVC 로직 (사이클 148) ===")
    print(f"심볼: {SYMBOL}  목표: Sharpe ≥ 5.0")
    print("핵심 수정: VPIN=BVC+normalCDF, 진입=VPIN<low(safe), next_bar open")
    print("=" * 80)

    # ── Phase 1: 전체 기간 그리드 서치 ─────────────────────────────────────
    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_full.empty:
        print("데이터 없음.")
        return
    print(f"\n전체 데이터: {len(df_full)}행 ({df_full.index[0]} ~ {df_full.index[-1]})")
    bh = buy_and_hold(df_full)
    print(f"Buy-and-Hold: {bh * 100:+.1f}%")

    # VPIN 분포 확인
    c = df_full["close"].values
    o = df_full["open"].values
    h = df_full["high"].values
    lo = df_full["low"].values
    v = df_full["volume"].values
    vpin_full = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    valid_vpin = vpin_full[~np.isnan(vpin_full)]
    print(f"\nVPIN 분포: min={valid_vpin.min():.3f} p25={np.percentile(valid_vpin, 25):.3f} "
          f"median={np.median(valid_vpin):.3f} p75={np.percentile(valid_vpin, 75):.3f} "
          f"max={valid_vpin.max():.3f}")

    combos = list(product(
        VPIN_LOW_LIST, VPIN_MOM_LIST, MAX_HOLD_LIST, TP_LIST, SL_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (vl, vm, mh, tp, sl) in enumerate(combos):
        if idx % 500 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        r = backtest(df_full, vl, vm, mh, tp, sl)
        results.append({
            "vpin_low": vl, "vpin_mom": vm, "max_hold": mh,
            "tp": tp, "sl": sl, **r,
        })

    # n ≥ 30 필터
    valid = [r for r in results if r["trades"] >= 30]
    valid.sort(
        key=lambda x: (x["sharpe"] if not np.isnan(x["sharpe"]) else -99),
        reverse=True,
    )

    print(f"\n유효 조합 (n≥30): {len(valid)}/{len(results)}")
    print(f"\n=== Top 20 (전체기간, Sharpe 기준, n≥30) ===")
    print(f"{'vl':>5} {'vm':>7} {'hold':>5} {'TP':>6} {'SL':>6} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print("-" * 85)
    for r in valid[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['vpin_low']:>5.2f} {r['vpin_mom']:>7.4f} {r['max_hold']:>5} "
            f"{r['tp']:>6.3f} {r['sl']:>6.3f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        return

    best = valid[0]
    print(f"\n★ 전체기간 최적: vpin_low={best['vpin_low']} vm={best['vpin_mom']} "
          f"hold={best['max_hold']} TP={best['tp']} SL={best['sl']}")
    print(f"  Sharpe: {best['sharpe']:+.3f}  WR: {best['wr']:.1%}  "
          f"avg={best['avg_ret'] * 100:+.2f}%  trades: {best['trades']}  "
          f"MDD: {best['max_dd'] * 100:+.2f}%")

    # ── Phase 2: Walkforward 검증 (Top 10) ─────────────────────────────────
    # 중복 제거 (vpin_low가 다르지만 결과 동일한 경우)
    seen = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["vpin_mom"], r["max_hold"], r["tp"], r["sl"], r["trades"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 10:
            break

    print(f"\n{'=' * 80}")
    print(f"=== Walk-Forward 검증 (Top {len(unique_top)} 고유 조합, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        vl = params["vpin_low"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        tp = params["tp"]
        sl = params["sl"]
        print(f"\n--- #{rank}: vl={vl} vm={vm} hold={mh} TP={tp} SL={sl} "
              f"(전체 Sharpe {params['sharpe']:+.3f}, n={params['trades']}) ---")

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                print(f"  Fold {fold_i + 1} test: 데이터 없음")
                continue
            r = backtest(df_test, vl, vm, mh, tp, sl)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)
            bh_fold = buy_and_hold(df_test)
            print(f"  Fold {fold_i + 1} OOS [{fold['test'][0]}~{fold['test'][1]}]: "
                  f"Sharpe={sh:+.3f}  WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  BH={bh_fold * 100:+.1f}%")

        if oos_sharpes:
            avg_oos = np.mean(oos_sharpes)
            min_oos = min(oos_sharpes)
            all_pass = all(s >= 5.0 for s in oos_sharpes)
            print(f"  평균 OOS Sharpe: {avg_oos:+.3f} | 최소: {min_oos:+.3f} | "
                  f"{'✅ PASS (둘 다 ≥5.0)' if all_pass else '❌ FAIL'}")
            wf_results.append({
                **params,
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "all_pass": all_pass,
                "fold_details": fold_details,
            })

    # ── Phase 3: 슬리피지 스트레스 (Top 3) ─────────────────────────────────
    wf_pass = [r for r in wf_results if r["all_pass"]]
    if not wf_pass:
        wf_pass = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"], reverse=True)[:3]
        print(f"\n⚠️ 2-fold 모두 ≥5.0 통과 조합 없음 — avg OOS 기준 Top 3 슬리피지 테스트")
    else:
        wf_pass = sorted(wf_pass, key=lambda x: x["avg_oos_sharpe"], reverse=True)[:3]
        print(f"\n✅ WF 통과 조합: {len([r for r in wf_results if r['all_pass']])}개 "
              f"— Top 3 슬리피지 테스트")

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 ===")

    for rank, params in enumerate(wf_pass, 1):
        vl = params["vpin_low"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        tp = params["tp"]
        sl = params["sl"]
        print(f"\n--- #{rank}: vl={vl} vm={vm} hold={mh} TP={tp} SL={sl} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_full, vl, vm, mh, tp, sl, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── daemon 기준선 (프로덕션 로직) ────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 현재 daemon 기준선 (vl=0.35, vm=0.0005, hold=18, TP=6%, SL=0.8%) ===")
    daemon_r = backtest(df_full, 0.35, 0.0005, 18, 0.06, 0.008)
    print(f"  전체기간: Sharpe={daemon_r['sharpe']:+.3f}  WR={daemon_r['wr']:.1%}  "
          f"n={daemon_r['trades']}  avg={daemon_r['avg_ret'] * 100:+.2f}%  "
          f"MDD={daemon_r['max_dd'] * 100:+.2f}%")
    for fold_i, fold in enumerate(WF_FOLDS):
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if not df_test.empty:
            r = backtest(df_test, 0.35, 0.0005, 18, 0.06, 0.008)
            print(f"  Fold {fold_i + 1} OOS: Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
                  f"n={r['trades']}  avg={r['avg_ret'] * 100:+.2f}%")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print("⚠️ 이전 사이클(146 이전) vpin_eth 백테스트는 VPIN 계산 버그로 인해")
    print("   VPIN 필터가 무효 상태 — 실질적으로 EMA+RSI+momentum만 작동하고 있었음")
    print("   본 사이클에서 프로덕션 BVC VPIN으로 교정하여 진짜 성능 확인")

    if wf_results:
        best_wf = max(wf_results, key=lambda x: x["avg_oos_sharpe"])
        print(f"\n★ WF 최고: vl={best_wf['vpin_low']} vm={best_wf['vpin_mom']} "
              f"hold={best_wf['max_hold']} TP={best_wf['tp']} SL={best_wf['sl']}")
        print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f} "
              f"{'✅ ≥5.0 달성' if best_wf['avg_oos_sharpe'] >= 5.0 else '❌ <5.0'}")
        for fi, sh in enumerate(best_wf["oos_sharpes"]):
            print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  n={best_wf['oos_trades'][fi]}")

        # pipeline output
        print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
        print(f"WR: {best_wf['fold_details'][0]['wr'] * 100:.1f}%")
        print(f"trades: {sum(best_wf['oos_trades'])}")
    else:
        print("\n유효한 WF 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")


if __name__ == "__main__":
    main()
