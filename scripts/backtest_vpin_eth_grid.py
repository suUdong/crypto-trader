"""
vpin_eth 4h 파라미터 그리드 탐색
- KRW-ETH 단일 심볼
- 기간: 2022~2026
- 그리드: vpin_high, vpin_momentum_threshold, max_hold, TP, SL
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

START  = "2022-01-01"
END    = "2026-12-31"
SYMBOL = "KRW-ETH"
FEE    = 0.0005  # 0.05% 수수료

# ── 그리드 ─────────────────────────────────────────────────────────────────────
VPIN_HIGH_LIST   = [0.55, 0.60, 0.65, 0.70]
VPIN_MOM_LIST    = [0.0001, 0.0003, 0.0005]
MAX_HOLD_LIST    = [18, 24, 30]
TP_LIST          = [0.03, 0.04, 0.05, 0.06]
SL_LIST          = [0.008, 0.012, 0.015]

# 고정값 (daemon.toml 현재값)
VPIN_LOW       = 0.35
RSI_PERIOD     = 14
RSI_CEILING    = 65.0
RSI_FLOOR      = 20.0
BUCKET_COUNT   = 24
EMA_PERIOD     = 20
ADX_THRESHOLD  = 15.0
MOM_LOOKBACK   = 8


# ── 지표 ──────────────────────────────────────────────────────────────────────

def ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i-1] * (1 - k)
    return result


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


def compute_vpin(closes: np.ndarray, opens: np.ndarray, volumes: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    """Simplified VPIN: |close-open|/range proxy, rolling bucket_count."""
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy  = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i-bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, volumes: np.ndarray,
                          lookback: int = 8) -> np.ndarray:
    """CVD momentum proxy: (close - close[-lookback]) * vol_mean."""
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        price_chg = closes[i] / closes[i - lookback] - 1
        vol_mean  = volumes[i-lookback:i].mean() + 1e-9
        mom[i]    = price_chg * vol_mean / vol_mean  # normalized to price change
    return mom


def backtest(
    df: pd.DataFrame,
    vpin_high: float,
    vpin_mom_thresh: float,
    max_hold: int,
    tp: float,
    sl: float,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    v = df["volume"].values
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, v, BUCKET_COUNT)
    mom_arr  = compute_vpin_momentum(c, v, MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK) + 5
    i = warmup
    while i < n - 1:
        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]

        entry_ok = (
            not np.isnan(vpin_val) and vpin_val > vpin_high
            and not np.isnan(mom_val) and mom_val > vpin_mom_thresh
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val  # 상승 추세
        )

        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            for j in range(i + 2, min(i + 1 + max_hold, n)):
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
                hold_end = min(i + max_hold, n - 1)
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
    print(f"=== vpin_eth 4h 그리드 탐색 ===")
    print(f"심볼: {SYMBOL}  기간: {START} ~ {END}")

    df = load_historical(SYMBOL, "240m", START, END)
    if df.empty:
        print("데이터 없음.")
        return
    print(f"데이터: {len(df)}행")

    combos = list(product(VPIN_HIGH_LIST, VPIN_MOM_LIST, MAX_HOLD_LIST, TP_LIST, SL_LIST))
    print(f"총 조합: {len(combos)}개\n")

    results: list[dict] = []
    for vh, vm, mh, tp, sl in combos:
        r = backtest(df, vh, vm, mh, tp, sl)
        results.append({
            "vpin_high": vh, "vpin_mom": vm, "max_hold": mh,
            "tp": tp, "sl": sl, **r
        })

    results.sort(key=lambda x: (x["sharpe"] if not np.isnan(x["sharpe"]) else -99), reverse=True)

    print("=== Top 15 (Sharpe 기준) ===")
    print(f"{'vh':>5} {'vm':>7} {'hold':>5} {'TP':>5} {'SL':>6} | {'Sharpe':>7} {'WR':>6} {'avg%':>7} {'trades':>7}")
    print("-" * 72)
    for r in results[:15]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(f"{r['vpin_high']:>5.2f} {r['vpin_mom']:>7.4f} {r['max_hold']:>5} {r['tp']:>5.3f} {r['sl']:>6.3f} | "
              f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret']*100:>+6.2f}% {r['trades']:>7}")

    best = results[0]
    print(f"\n★ 최적: vpin_high={best['vpin_high']} vpin_mom={best['vpin_mom']} "
          f"max_hold={best['max_hold']} TP={best['tp']} SL={best['sl']}")
    print(f"  Sharpe={best['sharpe']:+.3f}  WR={best['wr']:.1%}  avg={best['avg_ret']*100:+.2f}%  "
          f"trades={best['trades']}")
    print(f"\n현재 daemon.toml: vpin_high=0.65 vpin_mom=0.0003 max_hold=24 TP=0.04 SL=0.012")


if __name__ == "__main__":
    main()
