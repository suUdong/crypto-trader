"""
momentum_sui 슬라이딩 윈도우 다중 OOS 검증 (사이클 77)
- 배경: 사이클 67에서 KRW-SUI Sharpe +5.28 (lb=20, TP=12%, SL=3%, WR=29.3%, T=58) 단일구간
  → 슬라이딩 OOS 검증 미수행, 안정성 미확인
- SUI 데이터: 2023-05 ~ 2026-04 (약 2.9년)
- SOL/ETH 수렴 파라미터(lb=12, adx=25) SUI 적용 가능성 검증
- 3개 슬라이딩 윈도우:
  W1: IS=2023-05~2023-12 / OOS=2024-01~2024-12
  W2: IS=2023-05~2024-12 / OOS=2025-01~2025-12
  W3: IS=2023-05~2025-12 / OOS=2026-01~2026-04
- 검증 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-SUI"
FEE    = 0.0005

WINDOWS = [
    {"name": "W1", "is_start": "2023-05-01", "is_end": "2023-12-31", "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2023-05-01", "is_end": "2024-12-31", "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"name": "W3", "is_start": "2023-05-01", "is_end": "2025-12-31", "oos_start": "2026-01-01", "oos_end": "2026-04-03"},
]

# 후보 파라미터
CANDIDATES = [
    {"lookback": 12, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "C1 (lb=12 adx=25) ★SOL/ETH 수렴"},
    {"lookback": 20, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "C0 (lb=20 adx=25) 기준"},
    {"lookback": 12, "adx": 20.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "C2 (lb=12 adx=20) 필터완화"},
    {"lookback": 12, "adx": 25.0, "vol_mult": 2.0, "tp": 0.15, "sl": 0.05, "label": "C3 (lb=12 adx=25 TP15/SL5) 고베타"},
    {"lookback": 20, "adx": 20.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.03, "label": "C4 (lb=20 adx=20 SL3) 사이클67근사"},
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
    print("momentum_sui 슬라이딩 윈도우 다중 OOS 검증 (사이클 77)")
    print("목적: 사이클 67 단일구간 Sharpe +5.28 → 슬라이딩 안정성 검증")
    print("=" * 80)

    print("\n데이터 로드 중...")
    data_cache: dict[str, pd.DataFrame] = {}
    for w in WINDOWS:
        df_is = load_historical(SYMBOL, "240m", w["is_start"], w["is_end"])
        df_oos = load_historical(SYMBOL, "240m", w["oos_start"], w["oos_end"])
        data_cache[f"{w['name']}_is"]  = df_is
        data_cache[f"{w['name']}_oos"] = df_oos
        print(f"  {w['name']}: IS={len(df_is)}행 ({w['is_start']}~{w['is_end']}), OOS={len(df_oos)}행 ({w['oos_start']}~{w['oos_end']})")

    print()
    OOS_SHARPE_MIN = 3.0
    OOS_WR_MIN     = 0.45
    OOS_TRADES_MIN = 6

    for cand in CANDIDATES:
        lb, adx_t, vm, tp, sl = cand["lookback"], cand["adx"], cand["vol_mult"], cand["tp"], cand["sl"]
        label = cand["label"]
        print(f"\n{'='*70}")
        print(f"파라미터: {label}")
        print(f"lb={lb} adx={adx_t:.0f} vol={vm} TP={tp:.0%} SL={sl:.0%}")
        print(f"{'윈도우':<38} | {'IS Sharpe':>10} {'IS WR':>7} {'IS T':>5} | {'OOS Sharpe':>10} {'OOS WR':>7} {'OOS T':>5} | {'판정':>6}")
        print("-" * 90)

        window_results = []
        for w in WINDOWS:
            df_is  = data_cache[f"{w['name']}_is"]
            df_oos = data_cache[f"{w['name']}_oos"]

            is_r  = backtest(df_is,  lb, adx_t, vm, tp, sl)
            oos_r = backtest(df_oos, lb, adx_t, vm, tp, sl)

            oos_ok = (
                not np.isnan(oos_r["sharpe"])
                and oos_r["sharpe"] > OOS_SHARPE_MIN
                and oos_r["wr"] > OOS_WR_MIN
                and oos_r["trades"] >= OOS_TRADES_MIN
            )
            verdict = "✅" if oos_ok else "❌"
            window_results.append(oos_ok)

            is_sh  = f"{is_r['sharpe']:+.3f}"  if not np.isnan(is_r['sharpe'])  else "   nan"
            oos_sh = f"{oos_r['sharpe']:+.3f}" if not np.isnan(oos_r['sharpe']) else "   nan"
            oos_wr = f"{oos_r['wr']:.1%}"

            wname = f"{w['name']}({w['oos_start'][:7]}~{w['oos_end'][:7]})"
            print(
                f"{wname:<38} | "
                f"{is_sh:>10} {is_r['wr']:>6.1%} {is_r['trades']:>5} | "
                f"{oos_sh:>10} {oos_wr:>7} {oos_r['trades']:>5} | {verdict:>6}"
            )

        pass_count = sum(window_results)
        print(f"\n  → 통과 {pass_count}/{len(WINDOWS)} 윈도우 | ", end="")
        if pass_count == len(WINDOWS):
            print("★★★ 전 구간 통과 — daemon 후보 확정 가능")
        elif pass_count >= 2:
            print("◆◆ 2/3 통과 — 조건부 daemon 후보")
        else:
            print("✗ 불안정 — daemon 반영 보류")

    print("\n" + "=" * 80)
    print(f"검증 기준: OOS Sharpe > {OOS_SHARPE_MIN} && WR > {OOS_WR_MIN:.0%} && trades >= {OOS_TRADES_MIN}")
    print("=" * 80)


if __name__ == "__main__":
    main()
