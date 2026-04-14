"""
vpin_eth W2 파라미터 재탐색 — 사이클 146
- W1 최적 근처 fine-grid + 2-fold walkforward 검증
- 목표: Sharpe ≥ 5.0 달성 파라미터 탐색
- W1 best: vpin_high=0.65, vpin_mom=0.0003, max_hold=24, TP=0.04, SL=0.012
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

# ── W2 fine-grid (W1 최적 근처) ──────────────────────────────────────────────
VPIN_HIGH_LIST = [0.58, 0.60, 0.62, 0.65, 0.68, 0.70]
VPIN_MOM_LIST = [0.0001, 0.0002, 0.0003, 0.0004, 0.0005]
MAX_HOLD_LIST = [18, 21, 24, 28, 32]
TP_LIST = [0.03, 0.035, 0.04, 0.045, 0.05]
SL_LIST = [0.008, 0.010, 0.012, 0.015]

# 고정값
VPIN_LOW = 0.35
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8

# ── Walkforward 기간 ─────────────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-01")},
]


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


def compute_vpin(closes: np.ndarray, opens: np.ndarray, volumes: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, volumes: np.ndarray,
                          lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        price_chg = closes[i] / closes[i - lookback] - 1
        mom[i] = price_chg
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
    v = df["volume"].values
    n = len(c)

    rsi_arr = rsi(c, RSI_PERIOD)
    ema_arr = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, v, BUCKET_COUNT)
    mom_arr = compute_vpin_momentum(c, v, MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK) + 5
    i = warmup
    while i < n - 1:
        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]

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
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0,
                "max_dd": 0.0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    # max drawdown
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd}


def main() -> None:
    print("=== vpin_eth W2 fine-grid 재탐색 (사이클 146) ===")
    print(f"심볼: {SYMBOL}  목표: Sharpe ≥ 5.0")

    # ── Phase 1: 전체 기간 그리드 서치 ─────────────────────────────────────
    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_full.empty:
        print("데이터 없음.")
        return
    print(f"전체 데이터: {len(df_full)}행\n")

    combos = list(product(
        VPIN_HIGH_LIST, VPIN_MOM_LIST, MAX_HOLD_LIST, TP_LIST, SL_LIST,
    ))
    print(f"총 조합: {len(combos)}개")

    results: list[dict] = []
    for vh, vm, mh, tp, sl in combos:
        r = backtest(df_full, vh, vm, mh, tp, sl)
        results.append({
            "vpin_high": vh, "vpin_mom": vm, "max_hold": mh,
            "tp": tp, "sl": sl, **r,
        })

    results.sort(
        key=lambda x: (x["sharpe"] if not np.isnan(x["sharpe"]) else -99),
        reverse=True,
    )

    print("\n=== Top 20 (Sharpe 기준) ===")
    print(f"{'vh':>5} {'vm':>7} {'hold':>5} {'TP':>6} {'SL':>6} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'trades':>7}")
    print("-" * 80)
    for r in results[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['vpin_high']:>5.2f} {r['vpin_mom']:>7.4f} {r['max_hold']:>5} "
            f"{r['tp']:>6.3f} {r['sl']:>6.3f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['trades']:>7}"
        )

    best = results[0]
    print(f"\n★ 전체기간 최적: vpin_high={best['vpin_high']} vpin_mom={best['vpin_mom']} "
          f"max_hold={best['max_hold']} TP={best['tp']} SL={best['sl']}")
    print(f"  Sharpe: {best['sharpe']:+.3f}  WR: {best['wr']:.1%}  "
          f"avg={best['avg_ret'] * 100:+.2f}%  trades: {best['trades']}")

    # ── Phase 2: Walkforward 검증 (Top 5) ──────────────────────────────────
    top5 = results[:5]
    print("\n=== Walkforward 검증 (Top 5) ===")
    for rank, params in enumerate(top5, 1):
        vh = params["vpin_high"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        tp = params["tp"]
        sl = params["sl"]
        print(f"\n--- #{rank}: vh={vh} vm={vm} hold={mh} TP={tp} SL={sl} ---")

        oos_sharpes: list[float] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                print(f"  Fold {fold_i + 1} test: 데이터 없음")
                continue
            r = backtest(df_test, vh, vm, mh, tp, sl)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            print(f"  Fold {fold_i + 1} OOS: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  trades={r['trades']}")

        if oos_sharpes:
            avg_oos = np.mean(oos_sharpes)
            print(f"  평균 OOS Sharpe: {avg_oos:+.3f} "
                  f"{'✅ PASS' if avg_oos >= 5.0 else '❌ FAIL (<5.0)'}")

    # ── 최종 결과 (파이프라인 출력 형식) ────────────────────────────────────
    print(f"\nSharpe: {best['sharpe']:+.3f}")
    print(f"WR: {best['wr'] * 100:.1f}%")
    print(f"trades: {best['trades']}")


if __name__ == "__main__":
    main()
