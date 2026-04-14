"""
vpin_eth 5-fold WF Sharpe +8.071 후속 — ATR 변동성 레짐 필터 추가.

직전 최적: vh=0.50 vm=0.0005 hold=14 TP=0.06 SL=0.006 BTC_lb=OFF → Sharpe +8.071, WR 27.7%, 513 trades.
관찰: WR 27.7% 로 낮음 — TP 도달 전 만기 청산 비중이 크다는 뜻.
다음 단계:
  1) hold/TP/SL 격자를 직전 최적 근방으로 좁혀서 미세 탐색
  2) ATR% 기반 변동성 레짐 필터 추가 (저변동 구간 진입 차단 → TP 도달률 개선 가설)
  3) 5-fold WF 로 강건성 유지 확인, 거래수 200↓ 떨어지면 탈락 (과최적화 방지)
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

VPIN_HIGH = 0.50
VPIN_MOM  = 0.0005

# 직전 최적 (14 / 0.06 / 0.006) 근방 미세 격자
MAX_HOLD_LIST = [12, 14, 16]
TP_LIST       = [0.055, 0.060, 0.065, 0.070]
SL_LIST       = [0.005, 0.006, 0.007]

# ATR% 레짐 필터: 진입 시점 ATR/close 가 하한 이상이어야 허용 (저변동 구간 배제)
# None = 필터 OFF (baseline)
ATR_MIN_LIST: list[float | None] = [None, 0.010, 0.015, 0.020]
ATR_PERIOD   = 14

VPIN_LOW     = 0.35
RSI_PERIOD   = 14
RSI_CEILING  = 65.0
RSI_FLOOR    = 20.0
BUCKET_COUNT = 24
EMA_PERIOD   = 20
MOM_LOOKBACK = 8
N_FOLDS      = 5


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


def compute_mom(closes: np.ndarray, lookback: int) -> np.ndarray:
    out = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        out[i] = closes[i] / closes[i - lookback] - 1
    return out


def compute_atr_pct(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14
) -> np.ndarray:
    n = len(close)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr / (close + 1e-9)


def backtest(
    df: pd.DataFrame,
    vh: float, vm: float, mh: int, tp: float, sl: float,
    atr_min: float | None,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values if "high" in df.columns else c
    low = df["low"].values if "low" in df.columns else c
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr  = compute_mom(c, MOM_LOOKBACK)
    atr_arr  = compute_atr_pct(h, low, c, ATR_PERIOD)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK, ATR_PERIOD) + 5
    i = warmup
    while i < n - 1:
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]
        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]
        atr_val  = atr_arr[i]

        entry_ok = (
            not np.isnan(vpin_val) and vpin_val > vh
            and not np.isnan(mom_val) and mom_val > vm
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        if entry_ok and atr_min is not None:
            if np.isnan(atr_val) or atr_val < atr_min:
                entry_ok = False

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
        return {"sharpe": float("nan"), "wr": 0.0, "trades": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "trades": len(arr)}


def wf_eval(
    df: pd.DataFrame,
    vh: float, vm: float, mh: int, tp: float, sl: float,
    atr_min: float | None,
) -> dict:
    fold_len = len(df) // N_FOLDS
    folds = []
    for k in range(N_FOLDS):
        s = k * fold_len
        e = len(df) if k == N_FOLDS - 1 else (k + 1) * fold_len
        folds.append(backtest(df.iloc[s:e], vh, vm, mh, tp, sl, atr_min))

    sharpes = [f["sharpe"] for f in folds if not np.isnan(f["sharpe"])]
    total_trades = sum(f["trades"] for f in folds)
    total_wins   = sum(f["wr"] * f["trades"] for f in folds)
    avg_wr = (total_wins / total_trades) if total_trades else 0.0
    return {
        "sharpe_mean": float(np.mean(sharpes)) if sharpes else float("nan"),
        "sharpe_min":  float(np.min(sharpes))  if sharpes else float("nan"),
        "wr": avg_wr,
        "trades": total_trades,
        "folds": [f["sharpe"] for f in folds],
    }


def main() -> None:
    print("=== vpin_eth + ATR 변동성 레짐 필터 (5-fold WF) ===")
    print(f"심볼: {SYMBOL}  기간: {START} ~ {END}")

    df = load_historical(SYMBOL, "240m", START, END)
    if df.empty:
        print("데이터 없음.")
        return
    print(f"데이터: {len(df)}행")

    combos = list(product(MAX_HOLD_LIST, TP_LIST, SL_LIST, ATR_MIN_LIST))
    print(f"총 조합: {len(combos)}개\n")

    results: list[dict] = []
    for idx, (mh, tp, sl, atr_min) in enumerate(combos, 1):
        r = wf_eval(df, VPIN_HIGH, VPIN_MOM, mh, tp, sl, atr_min)
        results.append({"hold": mh, "tp": tp, "sl": sl, "atr_min": atr_min, **r})
        if idx % 10 == 0:
            print(f"  … 진행 {idx}/{len(combos)}")

    results.sort(
        key=lambda x: (x["sharpe_min"] if not np.isnan(x["sharpe_min"]) else -99),
        reverse=True,
    )

    print("\n=== Top 15 (min-fold Sharpe 기준) ===")
    hdr = (f"{'hold':>5} {'TP':>6} {'SL':>6} {'ATRmin':>7} | "
           f"{'ShMean':>7} {'ShMin':>7} {'WR':>6} {'trades':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in results[:15]:
        shm = f"{r['sharpe_mean']:+.3f}" if not np.isnan(r["sharpe_mean"]) else "   nan"
        shn = f"{r['sharpe_min']:+.3f}"  if not np.isnan(r["sharpe_min"])  else "   nan"
        atr_str = "OFF" if r["atr_min"] is None else f"{r['atr_min']:.3f}"
        print(
            f"{r['hold']:>5} {r['tp']:>6.3f} {r['sl']:>6.3f} {atr_str:>7} | "
            f"{shm:>7} {shn:>7} {r['wr']:>5.1%} {r['trades']:>7}"
        )

    best = results[0]
    atr_str = "OFF" if best["atr_min"] is None else f"{best['atr_min']:.3f}"
    print(
        f"\n★ 최적 (min-fold 기준): hold={best['hold']} TP={best['tp']} "
        f"SL={best['sl']} ATRmin={atr_str}"
    )
    print(f"  폴드별 Sharpe: {['%+.3f' % s for s in best['folds']]}")
    shm = best["sharpe_mean"] if not np.isnan(best["sharpe_mean"]) else 0.0
    print(f"  Sharpe: {shm:+.3f} (mean 5-fold)")
    print(f"  WR: {best['wr']*100:.1f}%")
    print(f"  trades: {best['trades']}")

    # ATR OFF baseline 비교
    baseline = next(
        (r for r in results if r["atr_min"] is None
         and r["hold"] == best["hold"] and r["tp"] == best["tp"] and r["sl"] == best["sl"]),
        None,
    )
    if baseline and best["atr_min"] is not None:
        d_sh = best["sharpe_min"] - baseline["sharpe_min"]
        d_wr = best["wr"] - baseline["wr"]
        print(
            f"\n📊 ATR 필터 효과: ShMin {baseline['sharpe_min']:+.3f} → "
            f"{best['sharpe_min']:+.3f} (Δ {d_sh:+.3f}), "
            f"WR {baseline['wr']*100:.1f}% → {best['wr']*100:.1f}% (Δ {d_wr*100:+.1f}pp), "
            f"trades {baseline['trades']} → {best['trades']}"
        )

    gate = best["sharpe_min"] if not np.isnan(best["sharpe_min"]) else -99
    if gate >= 3.0 and best["trades"] >= 200:
        print("\n✅ 모든 폴드 Sharpe ≥ 3.0 & 거래수 충분 — paper 데이터 30건 수집 후보")
    elif best["trades"] < 200:
        print(f"\n⚠️ 거래수 {best['trades']} < 200 — 필터가 너무 엄격, 과최적화 의심")
    else:
        print(f"\n⚠️ 최악 폴드 Sharpe {gate:+.3f} < 3.0 — 배포 금지")


if __name__ == "__main__":
    main()
