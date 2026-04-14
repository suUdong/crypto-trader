"""
momentum_sol MDD/drawdown 분석 — 사이클 147
- Sharpe 14.37 파라미터의 robustness 검증
- 2슬롯 비중 확대 전 MDD, 연속손실, 연도별 성과 분해
- W1 best: lookback=20, adx=20.0, vol_mult=1.5, TP=0.08, SL=0.03
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-SOL"
FEE = 0.0005

# ── W1 최적 파라미터 + 인접 grid ─────────────────────────────────────────────
# 최적 파라미터 고정 + robustness 테스트용 인접값
PARAM_SETS = [
    # (lookback, adx, vol_mult, tp, sl, label)
    (20, 20.0, 1.5, 0.08, 0.03, "W1-best"),
    (20, 20.0, 1.5, 0.10, 0.03, "TP-up"),
    (20, 20.0, 1.5, 0.08, 0.04, "SL-loose"),
    (20, 25.0, 1.5, 0.08, 0.03, "ADX-tight"),
    (16, 20.0, 1.5, 0.08, 0.03, "LB-short"),
    (24, 20.0, 1.5, 0.08, 0.03, "LB-long"),
    (20, 20.0, 2.0, 0.08, 0.03, "Vol-high"),
    (20, 15.0, 1.0, 0.08, 0.03, "Entry-loose"),
    (20, 20.0, 1.5, 0.06, 0.02, "Tight-TPSL"),
    (20, 20.0, 1.5, 0.12, 0.04, "Wide-TPSL"),
]

# 고정값
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
ENTRY_THRESHOLD = 0.005
MAX_HOLD = 48

# Walkforward
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-01")},
]


# ── 지표 ──────────────────────────────────────────────────────────────────────

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


def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]),
                   np.abs(lows[1:] - closes[:-1])),
    )
    dm_p = np.where(
        (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
        np.maximum(highs[1:] - highs[:-1], 0.0), 0.0,
    )
    dm_m = np.where(
        (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
        np.maximum(lows[:-1] - lows[1:], 0.0), 0.0,
    )
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period - 1] = tr[:period].sum()
    dip_s[period - 1] = dm_p[:period].sum()
    dim_s[period - 1] = dm_m[:period].sum()
    for i in range(period, n - 1):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        dip_s[i] = dip_s[i - 1] - dip_s[i - 1] / period + dm_p[i]
        dim_s[i] = dim_s[i - 1] - dim_s[i - 1] / period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dip_s / (atr_s + 1e-9)
        di_m = 100 * dim_s / (atr_s + 1e-9)
        dx = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2 * period - 2] = dx[period - 1:2 * period - 1].mean()
    for i in range(2 * period - 1, n - 1):
        adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


# ── 백테스트 (상세 트레이드 기록) ──────────────────────────────────────────────

def backtest_detailed(
    df: pd.DataFrame,
    lookback: int,
    adx_thresh: float,
    vol_mult: float,
    tp: float,
    sl: float,
) -> dict:
    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)
    idx = df.index

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n - lookback] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx(h, lo, c, 14)

    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > vol_mult * vol_ma

    returns: list[float] = []
    trade_dates: list[str] = []
    warmup = lookback + RSI_PERIOD + 28
    i = warmup
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            trade_dates.append(str(idx[i])[:10])
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE)
                    i = j
                    break
                if ret <= -sl:
                    returns.append(-sl - FEE)
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {
            "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
            "trades": 0, "max_dd": 0.0, "max_consec_loss": 0,
            "returns": [], "trade_dates": [],
        }

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())

    # max drawdown
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0

    # max consecutive losses
    max_consec = 0
    cur_consec = 0
    for r in arr:
        if r < 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd,
        "max_consec_loss": max_consec,
        "returns": arr.tolist(), "trade_dates": trade_dates,
    }


def main() -> None:
    print("=== momentum_sol MDD/drawdown 분석 (사이클 147) ===")
    print(f"심볼: {SYMBOL}  목적: 2슬롯 비중 확대 robustness 검증\n")

    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_full.empty:
        print("데이터 없음.")
        return
    print(f"전체 데이터: {len(df_full)}행\n")

    # ── Phase 1: 파라미터 세트별 전체기간 성과 ───────────────────────────────
    print("=== Phase 1: 파라미터 세트별 전체기간 성과 ===")
    print(f"{'label':>12} {'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD%':>7} "
          f"{'consec':>6} {'trades':>7}")
    print("-" * 65)

    all_results: list[tuple[str, dict, tuple]] = []
    for lb, adx_t, vm, tp, sl, label in PARAM_SETS:
        r = backtest_detailed(df_full, lb, adx_t, vm, tp, sl)
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{label:>12} {sh:>7} {r['wr']:>5.1%} "
            f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
            f"{r['max_consec_loss']:>6} {r['trades']:>7}"
        )
        all_results.append((label, r, (lb, adx_t, vm, tp, sl)))

    # ── Phase 2: W1-best 연도별 분해 ─────────────────────────────────────────
    print("\n=== Phase 2: W1-best 연도별 성과 분해 ===")
    w1_lb, w1_adx, w1_vm, w1_tp, w1_sl = 20, 20.0, 1.5, 0.08, 0.03
    for year in range(2022, 2027):
        start = f"{year}-01-01"
        end = f"{year}-12-31"
        df_yr = load_historical(SYMBOL, "240m", start, end)
        if df_yr.empty or len(df_yr) < 100:
            print(f"  {year}: 데이터 부족")
            continue
        r = backtest_detailed(df_yr, w1_lb, w1_adx, w1_vm, w1_tp, w1_sl)
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(f"  {year}: Sharpe={sh}  WR={r['wr']:.1%}  "
              f"MDD={r['max_dd'] * 100:+.2f}%  consec_loss={r['max_consec_loss']}  "
              f"trades={r['trades']}")

    # ── Phase 3: Walkforward OOS 검증 ─────────────────────────────────────────
    print("\n=== Phase 3: Walkforward OOS 검증 ===")
    for label, _, (lb, adx_t, vm, tp, sl) in all_results[:5]:
        oos_sharpes: list[float] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                continue
            r = backtest_detailed(df_test, lb, adx_t, vm, tp, sl)
            sh_val = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh_val)
            print(f"  {label} Fold {fold_i + 1}: Sharpe={sh_val:+.3f}  "
                  f"WR={r['wr']:.1%}  MDD={r['max_dd'] * 100:+.2f}%  "
                  f"trades={r['trades']}")
        if oos_sharpes:
            avg = np.mean(oos_sharpes)
            print(f"  → {label} 평균 OOS Sharpe: {avg:+.3f}")

    # ── Phase 4: 2슬롯 확대 리스크 요약 ───────────────────────────────────────
    best_label, best_r, _ = all_results[0]
    print("\n=== 2슬롯 비중 확대 리스크 요약 ===")
    print(f"  파라미터: {best_label}")
    print(f"  Sharpe: {best_r['sharpe']:+.3f}")
    mdd_pct = best_r['max_dd'] * 100
    print(f"  MDD: {mdd_pct:+.2f}%")
    print(f"  최대 연속 손실: {best_r['max_consec_loss']}회")
    safe = best_r['max_consec_loss'] <= 3
    print(f"  연속손실 ≤ 3 (SAFE_MAX_CONSECUTIVE_LOSSES): "
          f"{'✅ PASS' if safe else '❌ FAIL'}")
    mdd_safe = abs(mdd_pct) < 5.0
    print(f"  MDD < 5% (HARD_MAX_DAILY_LOSS_PCT): "
          f"{'✅ PASS' if mdd_safe else '⚠️ 주의'}")

    # ── 최종 결과 (파이프라인 출력 형식) ────────────────────────────────────
    print(f"\nSharpe: {best_r['sharpe']:+.3f}")
    print(f"WR: {best_r['wr'] * 100:.1f}%")
    print(f"trades: {best_r['trades']}")


if __name__ == "__main__":
    main()
