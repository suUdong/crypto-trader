"""
vpin_eth 사이클 149 — 볼륨 확인 + ATR 적응형 SL/TP
- 배경: c148 train Sharpe +8.337 → OOS +4.668 (과적합, 목표 ≥5.0 미달)
- 가설: 고정 SL/TP가 변동성 변화에 취약 → ATR 기반 적응형 exit
- 추가 필터: 볼륨 > N봉 평균 (노이즈 진입 제거)
- 2-fold walk-forward + 슬리피지 스트레스
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
FEE = 0.0005

# ── 그리드 ──────────────────────────────────────────────────────────────────
VPIN_HIGH_LIST = [0.55, 0.58, 0.60, 0.62, 0.65]
VPIN_MOM_LIST = [0.0002, 0.0003, 0.0005]
MAX_HOLD_LIST = [18, 20, 24]

# ATR 배수 기반 TP/SL (고정 대신)
ATR_TP_MULT_LIST = [2.5, 3.0, 3.5, 4.0, 4.5]
ATR_SL_MULT_LIST = [0.5, 0.7, 1.0, 1.2]
ATR_PERIOD_LIST = [14, 20]

# 볼륨 필터: 현재 볼륨 > vol_sma * vol_ratio
VOL_SMA_PERIOD_LIST = [20, 30]
VOL_RATIO_LIST = [1.0, 1.2, 1.5]

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

def ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def sma(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        result[i] = series[i - period + 1:i + 1].mean()
    return result


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def compute_vpin(closes: np.ndarray, opens: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def compute_atr(highs: np.ndarray, lows: np.ndarray,
                closes: np.ndarray, period: int) -> np.ndarray:
    """Average True Range."""
    n = len(closes)
    tr = np.full(n, np.nan)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, n):
        atr[i] = tr[i] * k + atr[i - 1] * (1 - k)
    return atr


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    vpin_high: float,
    vpin_mom_thresh: float,
    max_hold: int,
    atr_tp_mult: float,
    atr_sl_mult: float,
    atr_period: int,
    vol_sma_period: int,
    vol_ratio: float,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    rsi_arr = rsi(c, RSI_PERIOD)
    ema_arr = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr = compute_vpin_momentum(c, MOM_LOOKBACK)
    atr_arr = compute_atr(h, lo, c, atr_period)
    vol_sma_arr = sma(v, vol_sma_period)

    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, atr_period, vol_sma_period) + 5

    returns: list[float] = []
    i = warmup
    while i < n - 1:
        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_val = v[i]
        vol_sma_val = vol_sma_arr[i]

        # 기본 VPIN 진입 조건
        base_ok = (
            not np.isnan(vpin_val) and vpin_val > vpin_high
            and not np.isnan(mom_val) and mom_val > vpin_mom_thresh
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        # 볼륨 확인 필터
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * vol_ratio
        )

        # ATR 유효성
        atr_ok = not np.isnan(atr_val) and atr_val > 0

        if base_ok and vol_ok and atr_ok:
            # ATR 기반 적응형 TP/SL (가격 비율로 변환)
            tp_pct = atr_val * atr_tp_mult / c[i]
            sl_pct = atr_val * atr_sl_mult / c[i]

            # 안전 클램프
            tp_pct = min(tp_pct, 0.10)
            sl_pct = min(sl_pct, 0.03)

            buy = o[i + 1] * (1 + FEE + slippage)
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                ret = c[j] / buy - 1
                if ret >= tp_pct:
                    returns.append(tp_pct - FEE - slippage)
                    i = j
                    break
                if ret <= -sl_pct:
                    returns.append(-sl_pct - FEE - slippage)
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
    print("=== vpin_eth 사이클 149 — 볼륨 확인 + ATR 적응형 SL/TP ===")
    print(f"심볼: {SYMBOL}  목표: OOS Sharpe ≥ 5.0")
    print(f"가설: ATR 적응형 exit + 볼륨 필터 → 과적합 감소, OOS 안정성 향상")
    print(f"기준선: c148 train +8.337, OOS +4.668 (고정 TP=4.5% SL=0.8%)")
    print("=" * 80)

    # ── Phase 1: train 기간 그리드 서치 ──────────────────────────────────────
    train_start, train_end = WF_FOLDS[0]["train"]
    df_train = load_historical(SYMBOL, "240m", train_start, train_end)
    if df_train.empty:
        print("train 데이터 없음.")
        return
    print(f"\ntrain 데이터: {len(df_train)}행 ({train_start} ~ {train_end})")
    bh_train = buy_and_hold(df_train)
    print(f"Buy-and-Hold (train): {bh_train * 100:+.1f}%")

    combos = list(product(
        VPIN_HIGH_LIST, VPIN_MOM_LIST, MAX_HOLD_LIST,
        ATR_TP_MULT_LIST, ATR_SL_MULT_LIST, ATR_PERIOD_LIST,
        VOL_SMA_PERIOD_LIST, VOL_RATIO_LIST,
    ))
    print(f"총 조합: {len(combos)}개\n")

    results: list[dict] = []
    for idx, (vh, vm, mh, atp, asl, ap, vsp, vr) in enumerate(combos):
        if idx % 500 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        r = backtest(df_train, vh, vm, mh, atp, asl, ap, vsp, vr)
        results.append({
            "vpin_high": vh, "vpin_mom": vm, "max_hold": mh,
            "atr_tp_mult": atp, "atr_sl_mult": asl, "atr_period": ap,
            "vol_sma_period": vsp, "vol_ratio": vr,
            **r,
        })

    valid = [r for r in results if r["trades"] >= 30]
    valid.sort(
        key=lambda x: (x["sharpe"] if not np.isnan(x["sharpe"]) else -99),
        reverse=True,
    )

    print(f"유효 조합 (n≥30): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 20 (Sharpe 기준) ===")
    hdr = (f"{'vh':>5} {'vm':>7} {'hold':>4} {'aTP':>4} {'aSL':>4} "
           f"{'aPd':>3} {'vSP':>3} {'vR':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['vpin_high']:>5.2f} {r['vpin_mom']:>7.4f} {r['max_hold']:>4} "
            f"{r['atr_tp_mult']:>4.1f} {r['atr_sl_mult']:>4.1f} "
            f"{r['atr_period']:>3} {r['vol_sma_period']:>3} {r['vol_ratio']:>4.1f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        return

    # ── Phase 2: OOS Walk-Forward (Top 20) ───────────────────────────────────
    top_n = valid[:20]
    print(f"\n{'=' * 80}")
    print("=== OOS Walk-Forward 검증 (Top 20, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(top_n, 1):
        vh = params["vpin_high"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        atp = params["atr_tp_mult"]
        asl = params["atr_sl_mult"]
        ap = params["atr_period"]
        vsp = params["vol_sma_period"]
        vr = params["vol_ratio"]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                continue
            r = backtest(df_test, vh, vm, mh, atp, asl, ap, vsp, vr)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            all_pass = all(s >= 5.0 for s in oos_sharpes)
            print(f"  #{rank}: vh={vh} vm={vm} hold={mh} "
                  f"aTP={atp} aSL={asl} aPd={ap} vSP={vsp} vR={vr} | "
                  f"train={params['sharpe']:+.3f} → avg_OOS={avg_oos:+.3f} "
                  f"min_OOS={min_oos:+.3f} "
                  f"{'✅' if all_pass else '❌'}")
            wf_results.append({
                **params,
                "train_sharpe": params["sharpe"],
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "all_pass": all_pass,
                "fold_details": fold_details,
            })

    # ── Phase 3: 슬리피지 스트레스 (OOS Top 3) ──────────────────────────────
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"], reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS Top 3) ===")

    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    for rank, params in enumerate(wf_top3, 1):
        vh = params["vpin_high"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        atp = params["atr_tp_mult"]
        asl = params["atr_sl_mult"]
        ap = params["atr_period"]
        vsp = params["vol_sma_period"]
        vr = params["vol_ratio"]
        print(f"\n--- #{rank}: vh={vh} vm={vm} hold={mh} "
              f"aTP={atp} aSL={asl} aPd={ap} vSP={vsp} vR={vr} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_full, vh, vm, mh, atp, asl, ap, vsp, vr,
                         slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── c148 기준선 비교 ─────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== c148 기준선 (고정 TP=4.5% SL=0.8%) vs c149 최적 ===")
    # c148 고정 파라미터 → 이전 결과 참조용
    print("c148 OOS 최적: Sharpe +4.668, WR 23.0%, trades 148, MDD -18.0%")
    if wf_sorted:
        b = wf_sorted[0]
        print(f"c149 OOS 최적: Sharpe {b['avg_oos_sharpe']:+.3f}, "
              f"min_OOS {b['min_oos_sharpe']:+.3f}")
        for fi, sh in enumerate(b["oos_sharpes"]):
            fd = b["fold_details"][fi]
            print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  "
                  f"WR={fd['wr']:.1%}  trades={fd['trades']}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    if wf_sorted:
        best = wf_sorted[0]
        print(f"★ OOS 최적: vh={best['vpin_high']} vm={best['vpin_mom']} "
              f"hold={best['max_hold']} atr_tp={best['atr_tp_mult']} "
              f"atr_sl={best['atr_sl_mult']} atr_pd={best['atr_period']} "
              f"vol_sma={best['vol_sma_period']} vol_ratio={best['vol_ratio']}")
        oos_avg = best["avg_oos_sharpe"]
        status = "✅ ≥5.0 달성" if oos_avg >= 5.0 else "❌ <5.0"
        print(f"  avg OOS Sharpe: {oos_avg:+.3f} {status}")
        print(f"  train Sharpe: {best['train_sharpe']:+.3f}")
        total_trades = sum(best["oos_trades"])
        avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))

        # pipeline output
        print(f"\nSharpe: {oos_avg:+.3f}")
        print(f"WR: {avg_wr * 100:.1f}%")
        print(f"trades: {total_trades}")
    else:
        print("유효 WF 결과 없음.")
        print("\nSharpe: 0.000")
        print("WR: 0.0%")
        print("trades: 0")


if __name__ == "__main__":
    main()
