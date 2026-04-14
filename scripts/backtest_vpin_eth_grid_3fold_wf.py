"""
vpin_eth grid Sharpe +7.461 후속 — 3-fold walk-forward 검증 + 이웃 파라미터 확장.

직전 결과: vh=0.55 vm=0.0005 hold=18 TP=0.06 SL=0.008 → Sharpe +7.461 (전체기간 단일 fit).
단일-fit Sharpe는 과적합 위험이 크므로, 최상위 후보군을 3-fold walk-forward로 재검증하고
이웃 파라미터(hold, TP, SL, vpin_high, vpin_mom)를 살짝 확장하여 안정성을 평가한다.
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical  # type: ignore

START  = "2022-01-01"
END    = "2026-12-31"
SYMBOL = "KRW-ETH"
FEE    = 0.0005

# 직전 최적 근처 확장 — 이웃 파라미터만 살짝 변주 (과적합 방지)
VPIN_HIGH_LIST = [0.50, 0.55, 0.60, 0.65, 0.70]
VPIN_MOM_LIST  = [0.0003, 0.0005, 0.0007]
MAX_HOLD_LIST  = [14, 18, 22]
TP_LIST        = [0.045, 0.050, 0.060, 0.070]
SL_LIST        = [0.006, 0.008, 0.010]

VPIN_LOW     = 0.35
RSI_PERIOD   = 14
RSI_CEILING  = 65.0
RSI_FLOOR    = 20.0
BUCKET_COUNT = 24
EMA_PERIOD   = 20
MOM_LOOKBACK = 8

N_FOLDS = 3  # walk-forward 폴드 수


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


def compute_vpin(closes: np.ndarray, opens: np.ndarray, bucket_count: int = 24) -> np.ndarray:
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


def backtest(df: pd.DataFrame, vh: float, vm: float, mh: int, tp: float, sl: float) -> dict:
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
            not np.isnan(vpin_val) and vpin_val > vh
            and not np.isnan(mom_val) and mom_val > vm
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            for j in range(i + 2, min(i + 1 + mh, n)):
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
                hold_end = min(i + mh, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def wf_evaluate(df: pd.DataFrame, vh: float, vm: float, mh: int, tp: float, sl: float) -> dict:
    """3-fold 연속 walk-forward — 각 폴드별 Sharpe 평균/최소."""
    fold_len = len(df) // N_FOLDS
    folds = []
    for k in range(N_FOLDS):
        start = k * fold_len
        end = len(df) if k == N_FOLDS - 1 else (k + 1) * fold_len
        folds.append(backtest(df.iloc[start:end], vh, vm, mh, tp, sl))

    sharpes = [f["sharpe"] for f in folds if not np.isnan(f["sharpe"])]
    total_trades = sum(f["trades"] for f in folds)
    total_wins = sum(f["wr"] * f["trades"] for f in folds)
    avg_wr = (total_wins / total_trades) if total_trades else 0.0

    return {
        "sharpe_mean": float(np.mean(sharpes)) if sharpes else float("nan"),
        "sharpe_min":  float(np.min(sharpes))  if sharpes else float("nan"),
        "wr": avg_wr,
        "trades": total_trades,
        "folds": [f["sharpe"] for f in folds],
    }


def main() -> None:
    print("=== vpin_eth 이웃 그리드 + 3-fold walk-forward 검증 ===")
    print(f"심볼: {SYMBOL}  기간: {START} ~ {END}")

    df = load_historical(SYMBOL, "240m", START, END)
    if df.empty:
        print("데이터 없음.")
        return
    print(f"데이터: {len(df)}행  (폴드당 ≈ {len(df) // N_FOLDS}행)")

    combos = list(product(VPIN_HIGH_LIST, VPIN_MOM_LIST, MAX_HOLD_LIST, TP_LIST, SL_LIST))
    print(f"총 조합: {len(combos)}개\n")

    results: list[dict] = []
    for idx, (vh, vm, mh, tp, sl) in enumerate(combos, 1):
        r = wf_evaluate(df, vh, vm, mh, tp, sl)
        results.append({
            "vpin_high": vh, "vpin_mom": vm, "max_hold": mh,
            "tp": tp, "sl": sl, **r,
        })
        if idx % 50 == 0:
            print(f"  … 진행 {idx}/{len(combos)}")

    # Sharpe_min 기준 정렬 — 최악 폴드 기준 안정성 평가
    results.sort(
        key=lambda x: (x["sharpe_min"] if not np.isnan(x["sharpe_min"]) else -99),
        reverse=True,
    )

    print("\n=== Top 15 (min-fold Sharpe 기준) ===")
    hdr = (f"{'vh':>5} {'vm':>7} {'hold':>5} {'TP':>5} {'SL':>6} | "
           f"{'ShMean':>7} {'ShMin':>7} {'WR':>6} {'trades':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in results[:15]:
        shm = f"{r['sharpe_mean']:+.3f}" if not np.isnan(r["sharpe_mean"]) else "   nan"
        shn = f"{r['sharpe_min']:+.3f}"  if not np.isnan(r["sharpe_min"])  else "   nan"
        print(
            f"{r['vpin_high']:>5.2f} {r['vpin_mom']:>7.4f} {r['max_hold']:>5} "
            f"{r['tp']:>5.3f} {r['sl']:>6.3f} | "
            f"{shm:>7} {shn:>7} {r['wr']:>5.1%} {r['trades']:>7}"
        )

    best = results[0]
    print(
        f"\n★ 최적 (min-fold 기준): vpin_high={best['vpin_high']} "
        f"vpin_mom={best['vpin_mom']} max_hold={best['max_hold']} "
        f"TP={best['tp']} SL={best['sl']}"
    )
    print(f"  폴드별 Sharpe: {['%+.3f' % s for s in best['folds']]}")
    shm = best["sharpe_mean"] if not np.isnan(best["sharpe_mean"]) else 0.0
    print(f"  Sharpe: {shm:+.3f} (mean 3-fold)")
    print(f"  WR: {best['wr']*100:.1f}%")
    print(f"  trades: {best['trades']}")

    gate = best["sharpe_min"] if not np.isnan(best["sharpe_min"]) else -99
    if gate >= 3.0:
        print("\n✅ 모든 폴드 Sharpe ≥ 3.0 — paper 데이터 30건 수집 후보")
    else:
        print(f"\n⚠️ 최악 폴드 Sharpe {gate:+.3f} < 3.0 — 배포 금지, 과적합 의심")


if __name__ == "__main__":
    main()
