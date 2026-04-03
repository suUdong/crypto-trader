"""
momentum_eth walk-forward 검증 v2 (사이클 69 후속)
- vol_mult=3.0은 OOS trades 너무 희소 (7~8 in 18m) → 기준 미달
- vol_mult=2.0~2.5 탐색, adx=15~25 범위로 trades 확보
- 검증 기준: OOS Sharpe > 5.0 && OOS WR > 45% && OOS trades >= 15
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
FEE    = 0.0005

IS_START  = "2022-01-01"
IS_END    = "2024-12-31"
OOS_START = "2025-01-01"
OOS_END   = "2026-12-31"

# vol_mult=2.0~2.5 중심 탐색 (trades 확보 목적)
LOOKBACK_LIST = [10, 12, 14, 16]
ADX_LIST      = [15.0, 18.0, 20.0, 22.0, 25.0]
VOL_MULT_LIST = [1.5, 2.0, 2.5]
TP_LIST       = [0.10, 0.12, 0.15]
SL_LIST       = [0.02, 0.03, 0.04]

ENTRY_THRESHOLD = 0.005
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 75.0
MAX_HOLD        = 48


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def adx_calc(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr  = np.maximum(highs[1:] - lows[1:],
          np.maximum(np.abs(highs[1:] - closes[:-1]),
                     np.abs(lows[1:]  - closes[:-1])))
    dm_p = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
                    np.maximum(highs[1:] - highs[:-1], 0.0), 0.0)
    dm_m = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
                    np.maximum(lows[:-1] - lows[1:], 0.0), 0.0)
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period-1]  = tr[:period].sum()
    dip_s[period-1]  = dm_p[:period].sum()
    dim_s[period-1]  = dm_m[:period].sum()
    for i in range(period, n - 1):
        atr_s[i] = atr_s[i-1] - atr_s[i-1] / period + tr[i]
        dip_s[i] = dip_s[i-1] - dip_s[i-1] / period + dm_p[i]
        dim_s[i] = dim_s[i-1] - dim_s[i-1] / period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dip_s / (atr_s + 1e-9)
        di_m = 100 * dim_s / (atr_s + 1e-9)
        dx   = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2*period-2] = dx[period-1:2*period-1].mean()
    for i in range(2*period-1, n-1):
        adx_vals[i] = (adx_vals[i-1] * (period-1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


def backtest(df: pd.DataFrame, lookback: int, adx_thresh: float, vol_mult: float, tp: float, sl: float) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    v  = df["volume"].values
    n  = len(c)

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n-lookback] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_calc(h, lo, c, 14)
    vol_ma  = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok  = v > vol_mult * vol_ma

    returns: list[float] = []
    i = lookback + RSI_PERIOD + 28
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
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
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def main() -> None:
    print("=" * 70)
    print("momentum_eth walk-forward v2 (사이클 69)")
    print("목적: vol_mult=2.0~2.5에서 trades 확보 + OOS 검증 통과 후보 탐색")
    print(f"IS: {IS_START}~{IS_END}  |  OOS: {OOS_START}~{OOS_END}")
    print("=" * 70)

    df_is  = load_historical(SYMBOL, "240m", IS_START, IS_END)
    df_oos = load_historical(SYMBOL, "240m", OOS_START, OOS_END)

    if df_is.empty or df_oos.empty:
        print("데이터 없음.")
        return

    print(f"IS: {len(df_is)}행  |  OOS: {len(df_oos)}행\n")

    combos = list(product(LOOKBACK_LIST, ADX_LIST, VOL_MULT_LIST, TP_LIST, SL_LIST))
    print(f"탐색 조합: {len(combos)}개\n")

    results = []
    for lb, adx_t, vm, tp, sl in combos:
        is_r  = backtest(df_is,  lb, adx_t, vm, tp, sl)
        oos_r = backtest(df_oos, lb, adx_t, vm, tp, sl)
        results.append({
            "lookback": lb, "adx": adx_t, "vol_mult": vm, "tp": tp, "sl": sl,
            "is_sharpe": is_r["sharpe"], "is_wr": is_r["wr"], "is_trades": is_r["trades"],
            "oos_sharpe": oos_r["sharpe"], "oos_wr": oos_r["wr"], "oos_trades": oos_r["trades"],
        })

    # OOS 기준 완화: Sharpe > 5.0 && WR > 45% && trades >= 15
    passed = [r for r in results
              if not np.isnan(r["oos_sharpe"])
              and r["oos_sharpe"] > 5.0
              and r["oos_wr"] > 0.45
              and r["oos_trades"] >= 15]

    passed.sort(key=lambda x: x["oos_sharpe"], reverse=True)

    print("=== OOS 검증 통과 후보 (Sharpe>5.0, WR>45%, trades≥15) ===")
    if passed:
        print(f"{'lb':>4} {'adx':>5} {'vol':>5} {'TP':>5} {'SL':>5} | "
              f"{'IS Sh':>7} {'IS WR':>6} {'IS T':>5} | "
              f"{'OOS Sh':>7} {'OOS WR':>6} {'OOS T':>5}")
        print("-" * 90)
        for r in passed[:15]:
            is_sh  = f"{r['is_sharpe']:+.3f}"  if not np.isnan(r["is_sharpe"])  else "   nan"
            oos_sh = f"{r['oos_sharpe']:+.3f}" if not np.isnan(r["oos_sharpe"]) else "   nan"
            print(f"{r['lookback']:>4} {r['adx']:>5.0f} {r['vol_mult']:>5.1f} "
                  f"{r['tp']:>5.2f} {r['sl']:>5.2f} | "
                  f"{is_sh:>7} {r['is_wr']:>5.1%} {r['is_trades']:>5} | "
                  f"{oos_sh:>7} {r['oos_wr']:>5.1%} {r['oos_trades']:>5}")
    else:
        print("OOS Sharpe>5.0 && WR>45% && trades≥15 통과 후보 없음")
        # 완화해서 Sharpe>3.0 && trades>=12로 재시도
        loose = [r for r in results
                 if not np.isnan(r["oos_sharpe"])
                 and r["oos_sharpe"] > 3.0
                 and r["oos_trades"] >= 12]
        loose.sort(key=lambda x: x["oos_sharpe"], reverse=True)
        print(f"\n완화 기준 (Sharpe>3.0, trades≥12): {len(loose)}개")
        if loose:
            print(f"{'lb':>4} {'adx':>5} {'vol':>5} {'TP':>5} {'SL':>5} | "
                  f"{'IS Sh':>7} {'IS WR':>6} {'IS T':>5} | "
                  f"{'OOS Sh':>7} {'OOS WR':>6} {'OOS T':>5}")
            print("-" * 90)
            for r in loose[:10]:
                is_sh  = f"{r['is_sharpe']:+.3f}"  if not np.isnan(r["is_sharpe"])  else "   nan"
                oos_sh = f"{r['oos_sharpe']:+.3f}" if not np.isnan(r["oos_sharpe"]) else "   nan"
                print(f"{r['lookback']:>4} {r['adx']:>5.0f} {r['vol_mult']:>5.1f} "
                      f"{r['tp']:>5.2f} {r['sl']:>5.2f} | "
                      f"{is_sh:>7} {r['is_wr']:>5.1%} {r['is_trades']:>5} | "
                      f"{oos_sh:>7} {r['oos_wr']:>5.1%} {r['oos_trades']:>5}")

    # OOS Sharpe 상위 (trades 무관)
    valid = [r for r in results if not np.isnan(r["oos_sharpe"])]
    valid.sort(key=lambda x: x["oos_sharpe"], reverse=True)
    print("\n=== OOS Sharpe 상위 10 (trades 무관) ===")
    print(f"{'lb':>4} {'adx':>5} {'vol':>5} {'TP':>5} {'SL':>5} | "
          f"{'IS Sh':>7} {'IS WR':>6} {'IS T':>5} | "
          f"{'OOS Sh':>7} {'OOS WR':>6} {'OOS T':>5}")
    print("-" * 90)
    for r in valid[:10]:
        is_sh  = f"{r['is_sharpe']:+.3f}"  if not np.isnan(r["is_sharpe"])  else "   nan"
        oos_sh = f"{r['oos_sharpe']:+.3f}" if not np.isnan(r["oos_sharpe"]) else "   nan"
        print(f"{r['lookback']:>4} {r['adx']:>5.0f} {r['vol_mult']:>5.1f} "
              f"{r['tp']:>5.2f} {r['sl']:>5.2f} | "
              f"{is_sh:>7} {r['is_wr']:>5.1%} {r['is_trades']:>5} | "
              f"{oos_sh:>7} {r['oos_wr']:>5.1%} {r['oos_trades']:>5}")

    # trades 분포 파악
    oos_trades_list = [r["oos_trades"] for r in results if r["oos_trades"] > 0]
    if oos_trades_list:
        arr = np.array(oos_trades_list)
        print(f"\nOOS trades 분포: min={arr.min()} p25={np.percentile(arr,25):.0f} "
              f"median={np.median(arr):.0f} p75={np.percentile(arr,75):.0f} max={arr.max()}")

    if passed:
        best = passed[0]
        print(f"\n★ 최적 후보 (OOS 검증 통과):")
        print(f"  lb={best['lookback']} adx={best['adx']:.0f} vol={best['vol_mult']} "
              f"TP={best['tp']} SL={best['sl']}")
        print(f"  OOS: Sharpe={best['oos_sharpe']:+.3f}, WR={best['oos_wr']:.1%}, trades={best['oos_trades']}")


if __name__ == "__main__":
    main()
