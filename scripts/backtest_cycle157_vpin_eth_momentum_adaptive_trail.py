"""
vpin_eth 사이클 157 — 모멘텀 강도 기반 적응형 트레일링 스톱
- 기반: c152 최적 vl=0.3 vm=0.0005 hold=24 trail=0.012 minP=0.02 SL=0.005 cool=6
  c152 기준선 OOS: Fold1 +11.701 (WR=32.4% n=34), Fold2 +6.572 (WR=20% n=25)
- c155 실패: BTC 레짐게이트 + 볼륨스파이크 이중 필터 → OOS -39.270, 거래 12건 급감
- 교훈: 진입 필터 추가는 거래수 파괴 → 과적합. 진입이 아닌 청산(exit) 개선에 집중
- 가설:
  1) 강한 모멘텀 진입 → 추세 지속 가능성↑ → 넓은 트레일(수익 극대화)
  2) 약한 모멘텀 진입 → 추세 약할 수 있음 → 좁은 트레일(빠른 청산)
  3) trail_pct = base_trail + mom_scale * (entry_momentum / mom_norm)
     → 1개 신규 파라미터(mom_scale), 과적합 위험 최소
  4) VPIN 강도에 따라 min_profit도 적응 → 높은 VPIN 불균형 = 강한 신호 = 넓은 min_profit
- c152 고정 파라미터 유지, 탐색: base_trail, mom_scale, min_profit_base/scale, SL
- 2-fold walkforward + 슬리피지 스트레스
- 진입: next_bar open
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

# ── 고정값 (c152 검증 완료) ──────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

# ── 탐색 그리드 ──────────────────────────────────────────────────────────────
# c152 최적 근방 (진입 파라미터 고정 범위)
VPIN_LOW_LIST = [0.25, 0.30, 0.35]
VPIN_MOM_LIST = [0.0003, 0.0005, 0.0007]
MAX_HOLD_LIST = [18, 24, 30]

# 적응형 트레일링: trail_pct = base_trail + mom_scale * norm_momentum
# norm_momentum = entry_mom / median_mom (0~2 정규화, 중위값 기준)
BASE_TRAIL_LIST = [0.008, 0.010, 0.012, 0.015]
MOM_SCALE_LIST = [0.0, 0.005, 0.010, 0.015, 0.020]
# mom_scale=0 → 고정 트레일 (c152와 동일, 기준선 역할)

# min_profit: 트레일 활성화 최소 수익
MIN_PROFIT_LIST = [0.015, 0.02, 0.025, 0.03]

SL_LIST = [0.004, 0.005, 0.006, 0.008]
COOLDOWN_BARS_LIST = [0, 6]

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


# ── 백테스트 (적응형 트레일링) ────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    vpin_low: float,
    vpin_mom_thresh: float,
    max_hold: int,
    base_trail: float,
    mom_scale: float,
    min_profit: float,
    sl: float,
    cooldown_bars: int,
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

    # 모멘텀 중위값 계산 (정규화 기준)
    valid_mom = mom_arr[~np.isnan(mom_arr)]
    positive_mom = valid_mom[valid_mom > 0]
    if len(positive_mom) > 10:
        mom_median = float(np.median(positive_mom))
    else:
        mom_median = 0.005  # fallback

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if cooldown_bars > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)):
            i += 1
            continue

        # 진입 조건 (c152 동일)
        entry_ok = (
            vpin_val < vpin_low
            and mom_val >= vpin_mom_thresh
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )

        if entry_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy

            # ★ 적응형 트레일링: 진입 모멘텀 강도에 비례
            norm_mom = min(mom_val / (mom_median + 1e-9), 2.0)  # cap at 2x
            adaptive_trail = base_trail + mom_scale * norm_mom

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]
                ret = current_price / buy - 1

                # 스톱로스
                if ret <= -sl:
                    exit_ret = -sl - FEE - slippage
                    i = j
                    break

                # 최고가 갱신
                if current_price > peak_price:
                    peak_price = current_price

                # 적응형 트레일링 스톱
                peak_ret = peak_price / buy - 1
                if peak_ret >= min_profit:
                    drawdown_from_peak = (peak_price - current_price) / peak_price
                    if drawdown_from_peak >= adaptive_trail:
                        exit_ret = ret - FEE - slippage
                        i = j
                        break

            if exit_ret is None:
                hold_end = min(i + max_hold, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)

            if exit_ret < 0:
                consecutive_losses += 1
                if consecutive_losses >= COOLDOWN_LOSSES and cooldown_bars > 0:
                    cooldown_until = i + cooldown_bars
                    consecutive_losses = 0
            else:
                consecutive_losses = 0
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
    print("=== vpin_eth 사이클 157 — 모멘텀 강도 기반 적응형 트레일링 스톱 ===")
    print(f"심볼: {SYMBOL}  목표: OOS Sharpe ≥ 5.0, c152 기준선 개선")
    print("가설: 강한 모멘텀 → 넓은 트레일, 약한 모멘텀 → 좁은 트레일")
    print("기준선: c152 OOS Fold1=+11.701 Fold2=+6.572 (고정 트레일)")
    print("=" * 80)

    # ── Phase 1: train 그리드 서치 ────────────────────────────────────────────
    train_start, train_end = WF_FOLDS[0]["train"]
    df_train = load_historical(SYMBOL, "240m", train_start, train_end)
    if df_train.empty:
        print("train 데이터 없음.")
        return
    print(f"\ntrain 데이터: {len(df_train)}행 ({train_start} ~ {train_end})")
    bh_train = buy_and_hold(df_train)
    print(f"Buy-and-Hold (train): {bh_train * 100:+.1f}%")

    # c152 기준선 재현 (mom_scale=0 = 고정 트레일)
    print("\n--- c152 기준선 (고정 trail=0.012 minP=0.02 SL=0.005 cool=6) ---")
    base = backtest(df_train, 0.30, 0.0005, 24, 0.012, 0.0, 0.02, 0.005, 6)
    print(f"  Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"n={base['trades']}")

    combos = list(product(
        VPIN_LOW_LIST, VPIN_MOM_LIST, MAX_HOLD_LIST,
        BASE_TRAIL_LIST, MOM_SCALE_LIST, MIN_PROFIT_LIST,
        SL_LIST, COOLDOWN_BARS_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (vl, vm, mh, bt, ms, mp, sl, cb) in enumerate(combos):
        if idx % 2000 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        r = backtest(df_train, vl, vm, mh, bt, ms, mp, sl, cb)
        results.append({
            "vpin_low": vl, "vpin_mom": vm, "max_hold": mh,
            "base_trail": bt, "mom_scale": ms, "min_profit": mp,
            "sl": sl, "cooldown_bars": cb, **r,
        })

    valid = [r for r in results
             if r["trades"] >= 30
             and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥30): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 20 (Sharpe 기준) ===")
    hdr = (f"{'vl':>5} {'vm':>7} {'hold':>4} {'bTr':>5} {'mSc':>5} "
           f"{'minP':>5} {'SL':>6} {'cool':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['vpin_low']:>5.2f} {r['vpin_mom']:>7.4f} {r['max_hold']:>4} "
            f"{r['base_trail']:>5.3f} {r['mom_scale']:>5.3f} "
            f"{r['min_profit']:>5.3f} "
            f"{r['sl']:>6.3f} {r['cooldown_bars']:>4} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # ── Phase 2: OOS Walk-Forward (Top 20 고유 조합) ─────────────────────────
    seen = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["vpin_low"], r["vpin_mom"], r["max_hold"],
               r["base_trail"], r["mom_scale"], r["min_profit"],
               r["sl"], r["cooldown_bars"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 20:
            break

    print(f"\n{'=' * 80}")
    print(f"=== OOS Walk-Forward 검증 (Top {len(unique_top)} 고유, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        vl = params["vpin_low"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        bt = params["base_trail"]
        ms = params["mom_scale"]
        mp = params["min_profit"]
        sl = params["sl"]
        cb = params["cooldown_bars"]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                continue
            r = backtest(df_test, vl, vm, mh, bt, ms, mp, sl, cb)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            all_pass = all(s >= 5.0 for s in oos_sharpes)
            print(f"  #{rank}: vl={vl} vm={vm} hold={mh} "
                  f"bTr={bt} mSc={ms} minP={mp} SL={sl} cool={cb} | "
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

    if not wf_results:
        print("\nWF 검증 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # ── Phase 3: 슬리피지 스트레스 (OOS Top 3) ──────────────────────────────
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                        reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS Top 3) ===")

    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    for rank, params in enumerate(wf_top3, 1):
        vl = params["vpin_low"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        bt = params["base_trail"]
        ms = params["mom_scale"]
        mp = params["min_profit"]
        sl = params["sl"]
        cb = params["cooldown_bars"]
        print(f"\n--- #{rank}: vl={vl} vm={vm} hold={mh} "
              f"bTr={bt} mSc={ms} minP={mp} SL={sl} cool={cb} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_full, vl, vm, mh, bt, ms, mp, sl, cb,
                         slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 적응형 vs 고정 트레일 비교 ───────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 적응형 vs 고정 트레일 OOS 비교 ===")
    # c152 기준선 (고정 trail, mom_scale=0)
    for fold_i, fold in enumerate(WF_FOLDS):
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if not df_test.empty:
            r = backtest(df_test, 0.30, 0.0005, 24, 0.012, 0.0, 0.02,
                         0.005, 6)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  [고정] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  "
                  f"MDD={r['max_dd'] * 100:+.2f}%")
    best = wf_sorted[0]
    for fold_i, fd in enumerate(best["fold_details"]):
        sh = best["oos_sharpes"][fold_i]
        print(f"  [적응] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
              f"WR={fd['wr']:.1%}  n={best['oos_trades'][fold_i]}  "
              f"avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: vl={best['vpin_low']} vm={best['vpin_mom']} "
          f"hold={best['max_hold']} bTr={best['base_trail']} "
          f"mSc={best['mom_scale']} minP={best['min_profit']} "
          f"SL={best['sl']} cool={best['cooldown_bars']}")
    oos_avg = best["avg_oos_sharpe"]
    status = "✅ ≥5.0 달성" if oos_avg >= 5.0 else "❌ <5.0"
    print(f"  avg OOS Sharpe: {oos_avg:+.3f} {status}")
    print(f"  train Sharpe: {best['train_sharpe']:+.3f}")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={best['oos_trades'][fi]}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    total_trades = sum(best["oos_trades"])
    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))

    print(f"\nSharpe: {oos_avg:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
