"""
ETH momentum + VPIN_fixed 콤보 백테스트 (사이클 70)

- 버그 수정: compute_vpin에서 분모를 high-low로 교정
- 베이스: 사이클 69 확정 파라미터 (lb=12, adx=20, vol_mult=2.5, TP=0.10, SL=0.02)
- 가설: VPIN < threshold (저독성 구간)에서만 진입 → WR 개선
- 탐색: vpin_thresh × direction (SAFE=low_tox / CONFIRM=high_imbal) × bucket_count
- 기간: 2022-01-01 ~ 2026-04-03 (4h)
"""
from __future__ import annotations

import math
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

START = "2022-01-01"
END   = "2026-04-03"
FEE   = 0.0005
SYMBOL = "KRW-ETH"

# 사이클 69 확정 파라미터 (고정)
LOOKBACK   = 12
ADX_THRESH = 20.0
VOL_MULT   = 2.5
TP_BASE    = 0.10
SL_BASE    = 0.02
RSI_PERIOD = 14
RSI_OB     = 75.0
MAX_HOLD   = 48
ENTRY_THR  = 0.005

# 그리드 탐색 파라미터
VPIN_THRESH_LIST = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
BUCKET_LIST      = [12, 20, 30]
DIRECTION_LIST   = ["safe", "confirm"]  # safe=VPIN<thresh, confirm=VPIN>thresh
TP_LIST          = [0.08, 0.10, 0.12]
SL_LIST          = [0.02, 0.03]


# ── 지표 함수 ──────────────────────────────────────────────────────────────────

def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
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
    with np.errstate(invalid="ignore", divide="ignore"):
        rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr   = np.maximum(highs[1:] - lows[1:],
           np.maximum(np.abs(highs[1:] - closes[:-1]),
                      np.abs(lows[1:]  - closes[:-1])))
    dm_p = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
                    np.maximum(highs[1:] - highs[:-1], 0.0), 0.0)
    dm_m = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
                    np.maximum(lows[:-1] - lows[1:], 0.0), 0.0)
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period-1] = tr[:period].sum()
    dip_s[period-1] = dm_p[:period].sum()
    dim_s[period-1] = dm_m[:period].sum()
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


def compute_vpin_fixed(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    opens: np.ndarray,
    volumes: np.ndarray,
    bucket_count: int = 20,
) -> np.ndarray:
    """VPIN via Bulk Volume Classification — 수정판 (분모=high-low).

    BVC 방법: 각 캔들의 가격 움직임을 [−1, 1] 범위로 정규화 후 정규분포 CDF로
    매수 비중 산출. |매수량 − 매도량|의 합산 / 총 거래량.
    """
    n = len(closes)
    result = np.full(n, np.nan)

    # 벡터화된 z-score (close - open) / (high - low)
    price_range = highs - lows
    with np.errstate(invalid="ignore", divide="ignore"):
        z_scores = np.where(price_range > 0, (closes - opens) / price_range, 0.0)

    # 정규분포 CDF 근사: 0.5*(1 + erf(z/sqrt(2))) → tanh 근사 사용
    # math.erf 대신 벡터 처리를 위해 tanh 기반 근사: CDF(z) ≈ 0.5 + 0.5*tanh(0.7978*z)
    SQRT2 = math.sqrt(2.0)
    buy_frac = 0.5 * (1.0 + np.tanh(z_scores * 0.7978))  # 정규 CDF 근사

    buy_vol  = volumes * buy_frac
    sell_vol = volumes * (1.0 - buy_frac)
    imbal    = np.abs(buy_vol - sell_vol)

    # 롤링 윈도우 VPIN
    imbal_cumsum = np.concatenate([[0.0], np.cumsum(imbal)])
    vol_cumsum   = np.concatenate([[0.0], np.cumsum(volumes)])

    for i in range(bucket_count, n):
        total_vol = vol_cumsum[i] - vol_cumsum[i - bucket_count]
        if total_vol > 0:
            result[i] = (imbal_cumsum[i] - imbal_cumsum[i - bucket_count]) / total_vol

    return result


# ── 백테스트 ───────────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    vpin_thresh: float,
    direction: str,
    bucket: int,
    tp: float,
    sl: float,
) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    o  = df["open"].values
    v  = df["volume"].values
    n  = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0

    rsi_arr  = compute_rsi(c, RSI_PERIOD)
    adx_arr  = compute_adx(h, lo, c, 14)
    vpin_arr = compute_vpin_fixed(h, lo, c, o, v, bucket)

    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    # VPIN 필터 방향
    if direction == "safe":
        # 저독성: VPIN < threshold (순매도 압력 낮음 = 안전 진입)
        vpin_ok_fn = lambda idx: vpin_arr[idx] < vpin_thresh
    else:
        # 모멘텀 확인: VPIN > threshold (거래량 불균형 클 때 강한 추세)
        vpin_ok_fn = lambda idx: vpin_arr[idx] > vpin_thresh

    returns: list[float] = []
    warmup = max(bucket, LOOKBACK, RSI_PERIOD + 1) + 28
    i = warmup
    while i < n - 1:
        if np.isnan(vpin_arr[i]):
            i += 1
            continue
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THR
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OB
            and not np.isnan(adx_arr[i]) and adx_arr[i] > ADX_THRESH
            and vol_ok[i]
            and vpin_ok_fn(i)
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

    if len(returns) < 5:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": len(returns)}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


# ── 베이스라인 (VPIN 없음) ────────────────────────────────────────────────────

def backtest_baseline(df: pd.DataFrame, tp: float, sl: float) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    v  = df["volume"].values
    n  = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0

    rsi_arr = compute_rsi(c, RSI_PERIOD)
    adx_arr = compute_adx(h, lo, c, 14)

    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = max(LOOKBACK, RSI_PERIOD + 1) + 28
    i = warmup
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THR
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OB
            and not np.isnan(adx_arr[i]) and adx_arr[i] > ADX_THRESH
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

    if len(returns) < 5:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": len(returns)}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


# ── VPIN 분포 디버그 ───────────────────────────────────────────────────────────

def debug_vpin(df: pd.DataFrame, bucket: int = 20) -> None:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    o  = df["open"].values
    v  = df["volume"].values

    vpin_fixed = compute_vpin_fixed(h, lo, c, o, v, bucket)
    valid = vpin_fixed[~np.isnan(vpin_fixed)]
    print(f"\n[VPIN 진단] bucket={bucket}")
    print(f"  범위: [{valid.min():.4f}, {valid.max():.4f}]")
    print(f"  평균: {valid.mean():.4f}  중앙값: {np.median(valid):.4f}")
    print(f"  <0.30: {(valid < 0.30).mean():.1%}  <0.40: {(valid < 0.40).mean():.1%}  "
          f"<0.50: {(valid < 0.50).mean():.1%}  >0.60: {(valid > 0.60).mean():.1%}")


def main() -> None:
    print("=== ETH momentum + VPIN_fixed 콤보 백테스트 (사이클 70) ===")
    print(f"심볼: {SYMBOL}  기간: {START} ~ {END}  캔들: 4h")
    print(f"베이스 파라미터: lb={LOOKBACK} adx={ADX_THRESH} vol×{VOL_MULT}")

    df = load_historical(SYMBOL, "240m", START, END)
    if df.empty:
        print("ERROR: 데이터 없음")
        return
    print(f"데이터: {len(df)}행 로드\n")

    # VPIN 분포 확인 (버그 수정 검증)
    debug_vpin(df, bucket=20)

    # 베이스라인 (VPIN 없음)
    print("\n=== 베이스라인 (VPIN 필터 없음) ===")
    for tp, sl in product(TP_LIST, SL_LIST):
        r = backtest_baseline(df, tp, sl)
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(f"  TP={tp:.2f} SL={sl:.2f} → Sharpe={sh}  WR={r['wr']:.1%}  "
              f"avg={r['avg_ret']*100:+.2f}%  N={r['trades']}")

    # 그리드 탐색
    combos = list(product(VPIN_THRESH_LIST, DIRECTION_LIST, BUCKET_LIST, TP_LIST, SL_LIST))
    print(f"\n파라미터 조합: {len(combos)}개\n")

    all_results: list[dict] = []
    for vt, direction, bucket, tp, sl in combos:
        r = backtest(df, vt, direction, bucket, tp, sl)
        all_results.append({
            "vpin_thresh": vt,
            "direction": direction,
            "bucket": bucket,
            "tp": tp,
            "sl": sl,
            **r,
        })

    # 정렬 (trades≥10 필터)
    valid = [r for r in all_results if not np.isnan(r["sharpe"]) and r["trades"] >= 10]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print("\n=== Top 20 (trades≥10, Sharpe 기준) ===")
    hdr = f"{'direction':<8} {'vpin':>5} {'bkt':>4} {'TP':>5} {'SL':>5} | {'Sharpe':>7} {'WR':>6} {'avg%':>7} {'N':>5}"
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        print(
            f"{r['direction']:<8} {r['vpin_thresh']:>5.2f} {r['bucket']:>4} "
            f"{r['tp']:>5.2f} {r['sl']:>5.2f} | "
            f"{r['sharpe']:+7.3f} {r['wr']:>5.1%} {r['avg_ret']*100:>+6.2f}% {r['trades']:>5}"
        )

    # direction별 평균
    print("\n=== direction별 평균 Sharpe (trades≥10) ===")
    for d in DIRECTION_LIST:
        subset = [r["sharpe"] for r in valid if r["direction"] == d]
        if subset:
            print(f"  {d}: avg_sharpe={np.mean(subset):+.3f}  n={len(subset)}")

    # VPIN 임계값별 효과 (safe 방향)
    print("\n=== vpin_thresh별 평균 Sharpe (safe 방향, trades≥10) ===")
    for vt in VPIN_THRESH_LIST:
        subset = [r["sharpe"] for r in valid if r["vpin_thresh"] == vt and r["direction"] == "safe"]
        if subset:
            print(f"  VPIN<{vt:.2f}: avg={np.mean(subset):+.3f}  n={len(subset)}")

    print("\n=== vpin_thresh별 평균 Sharpe (confirm 방향, trades≥10) ===")
    for vt in VPIN_THRESH_LIST:
        subset = [r["sharpe"] for r in valid if r["vpin_thresh"] == vt and r["direction"] == "confirm"]
        if subset:
            print(f"  VPIN>{vt:.2f}: avg={np.mean(subset):+.3f}  n={len(subset)}")

    if valid:
        best = valid[0]
        print(f"\n★ 최적 (trades≥10): direction={best['direction']}  "
              f"vpin_thresh={best['vpin_thresh']}  bucket={best['bucket']}  "
              f"TP={best['tp']}  SL={best['sl']}")
        print(f"  Sharpe={best['sharpe']:+.3f}  WR={best['wr']:.1%}  "
              f"avg={best['avg_ret']*100:+.2f}%  trades={best['trades']}")

        # 베이스라인 대비 개선 여부 요약
        base_r = backtest_baseline(df, best["tp"], best["sl"])
        if not np.isnan(base_r["sharpe"]):
            delta = best["sharpe"] - base_r["sharpe"]
            print(f"\n베이스라인 (TP={best['tp']} SL={best['sl']}) Sharpe={base_r['sharpe']:+.3f}")
            print(f"VPIN 필터 추가 후 Δ Sharpe={delta:+.3f}  ({'+개선' if delta > 0 else '-악화'})")


if __name__ == "__main__":
    main()
