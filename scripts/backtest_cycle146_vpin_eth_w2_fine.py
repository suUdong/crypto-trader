"""
vpin_eth W2 fine-grid 재탐색 — Sharpe ≥ 5.0 목표
- W1 최적 근처 fine grid (vpin_high, vpin_mom, TP, SL)
- Walk-forward W2: train 70% / test 30% OOS 검증
- 사이클 146
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
FEE    = 0.0005

# ── W1 최적 근처 fine grid ────────────────────────────────────────────────────
VPIN_HIGH_LIST   = [0.58, 0.60, 0.62, 0.64, 0.66, 0.68]
VPIN_MOM_LIST    = [0.0001, 0.0002, 0.0003, 0.0004, 0.0005]
MAX_HOLD_LIST    = [20, 24, 28, 32]
TP_LIST          = [0.025, 0.030, 0.035, 0.040, 0.045]
SL_LIST          = [0.008, 0.010, 0.012, 0.015]

# 고정
VPIN_LOW       = 0.35
RSI_PERIOD     = 14
RSI_CEILING    = 65.0
RSI_FLOOR      = 20.0
BUCKET_COUNT   = 24
EMA_PERIOD     = 20
MOM_LOOKBACK   = 8

TRAIN_RATIO    = 0.70


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
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def compute_vpin(closes: np.ndarray, opens: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy  = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


# ── 백테스트 ──────────────────────────────────────────────────────────────────

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
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr  = compute_vpin_momentum(c, MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK) + 5
    i = warmup
    while i < n - 1:
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]
        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]

        entry_ok = (
            not np.isnan(vpin_val) and vpin_val > vpin_high
            and not np.isnan(mom_val) and mom_val > vpin_mom_thresh
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
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
        return {
            "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
            "trades": 0, "max_dd": 0.0,
        }
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    # max drawdown from cumulative returns
    cum = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = float(dd.min())
    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd,
    }


def main() -> None:
    print("=== vpin_eth W2 fine-grid 재탐색 (사이클 146) ===")
    print(f"심볼: {SYMBOL}  기간: {START} ~ {END}")

    df = load_historical(SYMBOL, "240m", START, END)
    if df.empty:
        print("데이터 없음.")
        return
    print(f"데이터: {len(df)}행")

    split = int(len(df) * TRAIN_RATIO)
    df_train = df.iloc[:split]
    df_test  = df.iloc[split:]
    print(f"Train: {len(df_train)}행 ({df_train.index[0]} ~ {df_train.index[-1]})")
    print(f"Test:  {len(df_test)}행 ({df_test.index[0]} ~ {df_test.index[-1]})")

    combos = list(product(
        VPIN_HIGH_LIST, VPIN_MOM_LIST, MAX_HOLD_LIST, TP_LIST, SL_LIST
    ))
    print(f"총 조합: {len(combos)}개\n")

    # ── Phase 1: Train set grid search ────────────────────────────────────────
    train_results: list[dict] = []
    for vh, vm, mh, tp, sl in combos:
        r = backtest(df_train, vh, vm, mh, tp, sl)
        train_results.append({
            "vpin_high": vh, "vpin_mom": vm, "max_hold": mh,
            "tp": tp, "sl": sl, **r,
        })

    train_results.sort(
        key=lambda x: (x["sharpe"] if not np.isnan(x["sharpe"]) else -99),
        reverse=True,
    )

    print("=== Train Top 10 (Sharpe 기준) ===")
    hdr = (f"{'vh':>5} {'vm':>7} {'hold':>5} {'TP':>5} {'SL':>6} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'trades':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in train_results[:10]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['vpin_high']:>5.2f} {r['vpin_mom']:>7.4f} {r['max_hold']:>5} "
            f"{r['tp']:>5.3f} {r['sl']:>6.3f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret']*100:>+6.2f}% "
            f"{r['max_dd']*100:>+6.1f}% {r['trades']:>7}"
        )

    # ── Phase 2: OOS validation on top 20 train combos ───────────────────────
    print("\n=== OOS (Walk-Forward W2) Top 20 후보 검증 ===")
    print(hdr)
    print("-" * len(hdr))

    oos_results: list[dict] = []
    for r_train in train_results[:20]:
        r_oos = backtest(
            df_test, r_train["vpin_high"], r_train["vpin_mom"],
            r_train["max_hold"], r_train["tp"], r_train["sl"],
        )
        entry = {
            "vpin_high": r_train["vpin_high"],
            "vpin_mom": r_train["vpin_mom"],
            "max_hold": r_train["max_hold"],
            "tp": r_train["tp"], "sl": r_train["sl"],
            "train_sharpe": r_train["sharpe"],
            **r_oos,
        }
        oos_results.append(entry)
        sh = f"{r_oos['sharpe']:+.3f}" if not np.isnan(r_oos["sharpe"]) else "  nan"
        print(
            f"{entry['vpin_high']:>5.2f} {entry['vpin_mom']:>7.4f} "
            f"{entry['max_hold']:>5} {entry['tp']:>5.3f} {entry['sl']:>6.3f} | "
            f"{sh:>7} {r_oos['wr']:>5.1%} {r_oos['avg_ret']*100:>+6.2f}% "
            f"{r_oos['max_dd']*100:>+6.1f}% {r_oos['trades']:>7}"
        )

    oos_results.sort(
        key=lambda x: (x["sharpe"] if not np.isnan(x["sharpe"]) else -99),
        reverse=True,
    )

    best = oos_results[0]
    print(f"\n★ OOS 최적: vpin_high={best['vpin_high']} vpin_mom={best['vpin_mom']} "
          f"max_hold={best['max_hold']} TP={best['tp']} SL={best['sl']}")
    sh_str = f"{best['sharpe']:+.3f}" if not np.isnan(best["sharpe"]) else "nan"
    print(f"  Sharpe: {sh_str}")
    print(f"  WR: {best['wr']:.1%}")
    print(f"  trades: {best['trades']}")
    print(f"  MDD: {best['max_dd']*100:+.1f}%")
    print(f"  train_sharpe: {best['train_sharpe']:+.3f}")

    gate = best["sharpe"] if not np.isnan(best["sharpe"]) else 0
    if gate >= 5.0:
        print("\n✅ OOS Sharpe ≥ 5.0 — daemon.toml 반영 후보")
    else:
        print(f"\n⚠️ OOS Sharpe {gate:+.3f} < 5.0 — 추가 탐색 필요")


if __name__ == "__main__":
    main()
