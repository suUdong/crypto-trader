"""
momentum_sol 4h 파라미터 그리드 탐색
- KRW-SOL 단일 심볼
- 기간: 2022~2026
- 그리드: momentum_lookback, adx_threshold, vol_mult, TP, SL
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

START = "2022-01-01"
END   = "2026-12-31"
SYMBOL = "KRW-SOL"
FEE   = 0.0005  # 0.05% 수수료

# ── 그리드 ─────────────────────────────────────────────────────────────────────
LOOKBACK_LIST  = [12, 16, 20, 24, 28]
ADX_LIST       = [15.0, 20.0, 25.0]
VOL_MULT_LIST  = [1.0, 1.5, 2.0]
TP_LIST        = [0.05, 0.08, 0.10, 0.12]
SL_LIST        = [0.02, 0.03, 0.04]

# 고정값 (daemon.toml 현재값)
ENTRY_THRESHOLD = 0.005
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 75.0
MAX_HOLD        = 48


# ── 지표 ──────────────────────────────────────────────────────────────────────

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


def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
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
    atr_s  = np.full(n - 1, np.nan)
    dip_s  = np.full(n - 1, np.nan)
    dim_s  = np.full(n - 1, np.nan)
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


def backtest(
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

    mom  = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n-lookback] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx(h, lo, c, 14)

    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > vol_mult * vol_ma

    returns: list[float] = []
    i = lookback + RSI_PERIOD + 28  # warm-up
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
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))  # 4h annualize
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def main() -> None:
    print(f"=== momentum_sol 4h 그리드 탐색 ===")
    print(f"심볼: {SYMBOL}  기간: {START} ~ {END}")

    df = load_historical(SYMBOL, "240m", START, END)
    if df.empty:
        print("데이터 없음. historical_loader 확인 필요.")
        return
    print(f"데이터: {len(df)}행")

    combos = list(product(LOOKBACK_LIST, ADX_LIST, VOL_MULT_LIST, TP_LIST, SL_LIST))
    print(f"총 조합: {len(combos)}개\n")

    results: list[dict] = []
    for lb, adx_t, vm, tp, sl in combos:
        r = backtest(df, lb, adx_t, vm, tp, sl)
        results.append({
            "lookback": lb, "adx": adx_t, "vol_mult": vm,
            "tp": tp, "sl": sl, **r
        })

    results.sort(key=lambda x: (x["sharpe"] if not np.isnan(x["sharpe"]) else -99), reverse=True)

    print("=== Top 15 (Sharpe 기준) ===")
    print(f"{'lookback':>8} {'adx':>5} {'vol':>5} {'TP':>5} {'SL':>5} | {'Sharpe':>7} {'WR':>6} {'avg%':>7} {'trades':>7}")
    print("-" * 75)
    for r in results[:15]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(f"{r['lookback']:>8} {r['adx']:>5.0f} {r['vol_mult']:>5.1f} {r['tp']:>5.2f} {r['sl']:>5.2f} | "
              f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret']*100:>+6.2f}% {r['trades']:>7}")

    best = results[0]
    print(f"\n★ 최적: lookback={best['lookback']} adx={best['adx']} vol={best['vol_mult']} "
          f"TP={best['tp']} SL={best['sl']}")
    print(f"  Sharpe={best['sharpe']:+.3f}  WR={best['wr']:.1%}  avg={best['avg_ret']*100:+.2f}%  "
          f"trades={best['trades']}")
    print(f"\n현재 daemon.toml: lookback=20 adx=20.0 vol=1.5 TP=0.08 SL=0.03")


if __name__ == "__main__":
    main()
