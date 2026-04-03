"""
Layer2/알트코인 momentum 스크리닝 (사이클 80)
- 신규 심볼: ARB, NEAR, OP, LINK, INJ
- SOL/ETH/XRP 확정 파라미터(lb=8,12, adx=25) 기준으로 walk-forward 스크리닝
- In-sample:      2022-05-01 ~ 2024-12-31
- Out-of-sample:  2025-01-01 ~ 2026-04-03
- 통과 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005

IS_START  = "2022-05-01"
IS_END    = "2024-12-31"
OOS_START = "2025-01-01"
OOS_END   = "2026-04-03"

SYMBOLS = ["KRW-ARB", "KRW-NEAR", "KRW-OP", "KRW-LINK", "KRW-INJ"]

# SOL/ETH/XRP 확정 파라미터 기준으로 검증
CANDIDATES = [
    {"lookback":  8, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "lb=8 adx=25 (XRP 확정)"},
    {"lookback": 12, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "lb=12 adx=25 (SOL/ETH 확정)"},
    {"lookback": 10, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "lb=10 adx=25"},
    {"lookback":  8, "adx": 20.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "lb=8 adx=20"},
    {"lookback": 12, "adx": 20.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "lb=12 adx=20"},
]

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
    print("=" * 80)
    print("Layer2/알트코인 momentum 스크리닝 (사이클 80)")
    print(f"In-Sample:       {IS_START} ~ {IS_END}")
    print(f"Out-of-Sample:   {OOS_START} ~ {OOS_END}")
    print("통과 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6")
    print("=" * 80)

    all_passed: list[dict] = []

    for symbol in SYMBOLS:
        print(f"\n{'─' * 80}")
        print(f"  심볼: {symbol}")
        print(f"{'─' * 80}")

        df_is  = load_historical(symbol, "240m", IS_START, IS_END)
        df_oos = load_historical(symbol, "240m", OOS_START, OOS_END)

        if df_is.empty or df_oos.empty:
            print(f"  ⚠️  데이터 없음 — 스킵")
            continue

        print(f"  IS 데이터:  {len(df_is)}행  |  OOS 데이터: {len(df_oos)}행")
        print(f"  {'파라미터':<40} | {'IS Sh':>8} {'IS WR':>7} {'IS T':>5} | {'OOS Sh':>8} {'OOS WR':>7} {'OOS T':>5} | {'판정':>6}")
        print(f"  {'-' * 100}")

        for p in CANDIDATES:
            lb, adx_t, vm, tp, sl = p["lookback"], p["adx"], p["vol_mult"], p["tp"], p["sl"]
            is_r  = backtest(df_is,  lb, adx_t, vm, tp, sl)
            oos_r = backtest(df_oos, lb, adx_t, vm, tp, sl)

            oos_ok = (
                not np.isnan(oos_r["sharpe"])
                and oos_r["sharpe"] > 3.0
                and oos_r["wr"] > 0.45
                and oos_r["trades"] >= 6
            )
            verdict = "✅ PASS" if oos_ok else "❌ FAIL"
            if oos_ok:
                all_passed.append({"symbol": symbol, **p,
                                   "oos_sharpe": oos_r["sharpe"],
                                   "oos_wr": oos_r["wr"],
                                   "oos_trades": oos_r["trades"]})

            is_sh  = f"{is_r['sharpe']:+.2f}"  if not np.isnan(is_r['sharpe'])  else "   nan"
            oos_sh = f"{oos_r['sharpe']:+.2f}" if not np.isnan(oos_r['sharpe']) else "   nan"
            label  = p["label"]
            print(
                f"  {label:<40} | {is_sh:>8} {is_r['wr']:>6.1%} {is_r['trades']:>5} | "
                f"{oos_sh:>8} {oos_r['wr']:>6.1%} {oos_r['trades']:>5} | {verdict:>6}"
            )

    print(f"\n{'=' * 80}")
    print("스크리닝 요약")
    print(f"{'=' * 80}")
    if all_passed:
        print(f"✅ PASS {len(all_passed)}개 — OOS Sharpe 순:")
        all_passed.sort(key=lambda x: x["oos_sharpe"], reverse=True)
        for r in all_passed:
            print(f"  {r['symbol']:<12} lb={r['lookback']:>2} adx={r['adx']:.0f}  "
                  f"OOS Sh={r['oos_sharpe']:+.3f}  WR={r['oos_wr']:.1%}  T={r['oos_trades']}")
    else:
        print("❌ PASS 없음 — 전 심볼 OOS 기준 미달")

    print()
    print("비교 기준 (기존 확정 파라미터):")
    print("  SOL  lb=12 adx=25  OOS Sh+18.0~23.8  WR=55.6%")
    print("  ETH  lb=12 adx=25  OOS Sh+17.4~23.4  WR=46.2~60.0%")
    print("  XRP  lb=8  adx=25  OOS Sh+8.5        WR=45.5%")


if __name__ == "__main__":
    main()
