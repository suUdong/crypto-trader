"""
사이클 187: VPIN vs BB_squeeze_independent 신호 상관관계 분석
- 목적: 두 전략의 진입 시점 겹침 비율(Jaccard similarity) 산출
  → 겹침 < 20%이면 비상관 확인 → 포트폴리오 분산 효과 입증
- 기간: 2024-06-01 ~ 2026-04-05 (ETH 240m)
- VPIN 파라미터: daemon.toml 현재값 (vpin_low=0.45, momentum=0.01, rsi=30~70, ema=20, adx>0)
- BB_squeeze 파라미터: c182 최적 (sqTh=40, sqLB=15, upR=0.97, adx=25, bb=20/2.0, ema=20)
- 공통: BTC > SMA(200) gate
- 출력: 각 전략 신호 수, 겹침 수, Jaccard, 시간적 근접도(±2봉 완화)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
TIMEFRAME = "240m"
ANALYSIS_START = "2024-06-01"
ANALYSIS_END = "2026-04-05"

# ---- VPIN parameters (daemon.toml vpin_eth_wallet) ----
VPIN_BUCKET_COUNT = 20
VPIN_LOW_TH = 0.45
VPIN_HIGH_TH = 0.7
VPIN_MOMENTUM_TH = 0.01
VPIN_RSI_FLOOR = 30.0
VPIN_RSI_CEILING = 70.0
VPIN_EMA_PERIOD = 20

# ---- BB Squeeze parameters (c182 optimal) ----
BB_PERIOD = 20
BB_STD = 2.0
BW_PCTILE_LB = 120
SQUEEZE_PCTILE_TH = 40.0
SQUEEZE_LB = 15
UPPER_RATIO = 0.97
ADX_TH = 25.0
EMA_PERIOD = 20
EXPANSION_LB = 4
BTC_SMA_PERIOD = 200


# ======================= indicators =======================

def ema_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def sma_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    cumsum = np.cumsum(series)
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate(
        ([0.0], cumsum[:-period]))) / period
    return result


def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    rsi_arr = np.full(n, np.nan)
    if n < period + 1:
        return rsi_arr
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    if avg_loss == 0:
        rsi_arr[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_arr[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_arr[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_arr[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return rsi_arr


def compute_momentum(closes: np.ndarray, lookback: int = 12) -> np.ndarray:
    n = len(closes)
    mom = np.full(n, np.nan)
    for i in range(lookback, n):
        if closes[i - lookback] > 0:
            mom[i] = (closes[i] - closes[i - lookback]) / closes[i - lookback]
    return mom


def compute_vpin(
    opens: np.ndarray, closes: np.ndarray, volumes: np.ndarray,
    bucket_count: int = 20,
) -> np.ndarray:
    """Bulk Volume Classification VPIN."""
    import math
    n = len(closes)
    vpin_arr = np.full(n, np.nan)
    if n < bucket_count + 1:
        return vpin_arr
    for i in range(bucket_count, n):
        buy_vol = 0.0
        sell_vol = 0.0
        for j in range(i - bucket_count, i):
            price_change = closes[j] - opens[j]
            mid_price = (opens[j] + closes[j]) / 2.0
            if mid_price <= 0 or volumes[j] <= 0:
                continue
            z = price_change / (mid_price * 0.01 + 1e-12)
            # Approximate CDF using error function
            buy_pct = 0.5 * (1.0 + math.erf(z / math.sqrt(2)))
            buy_vol += volumes[j] * buy_pct
            sell_vol += volumes[j] * (1.0 - buy_pct)
        total = buy_vol + sell_vol
        if total > 0:
            vpin_arr[i] = abs(buy_vol - sell_vol) / total
        else:
            vpin_arr[i] = 0.5
    return vpin_arr


def compute_adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
) -> np.ndarray:
    n = len(closes)
    adx = np.full(n, np.nan)
    if n < period * 2 + 1:
        return adx
    tr = np.full(n, 0.0)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    plus_dm = np.full(n, 0.0)
    minus_dm = np.full(n, 0.0)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        if up > dn and up > 0:
            plus_dm[i] = up
        if dn > up and dn > 0:
            minus_dm[i] = dn
    atr_s = np.full(n, np.nan)
    plus_dm_s = np.full(n, np.nan)
    minus_dm_s = np.full(n, np.nan)
    atr_s[period] = np.sum(tr[1:period + 1])
    plus_dm_s[period] = np.sum(plus_dm[1:period + 1])
    minus_dm_s[period] = np.sum(minus_dm[1:period + 1])
    for i in range(period + 1, n):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        plus_dm_s[i] = plus_dm_s[i - 1] - plus_dm_s[i - 1] / period + plus_dm[i]
        minus_dm_s[i] = minus_dm_s[i - 1] - minus_dm_s[i - 1] / period + minus_dm[i]
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if np.isnan(atr_s[i]) or atr_s[i] <= 0:
            continue
        plus_di = 100.0 * plus_dm_s[i] / atr_s[i]
        minus_di = 100.0 * minus_dm_s[i] / atr_s[i]
        di_sum = plus_di + minus_di
        if di_sum > 0:
            dx[i] = 100.0 * abs(plus_di - minus_di) / di_sum
    start_idx = period * 2
    if start_idx >= n:
        return adx
    dx_window = []
    for i in range(period, start_idx + 1):
        if not np.isnan(dx[i]):
            dx_window.append(dx[i])
    if len(dx_window) < period:
        return adx
    adx[start_idx] = np.mean(dx_window[-period:])
    for i in range(start_idx + 1, n):
        if np.isnan(dx[i]) or np.isnan(adx[i - 1]):
            adx[i] = adx[i - 1] if not np.isnan(adx[i - 1]) else np.nan
            continue
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def compute_bb(
    closes: np.ndarray, period: int = 20, num_std: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(closes)
    middle = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    bw = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        middle[i] = m
        upper[i] = m + num_std * s
        lower[i] = m - num_std * s
        if m > 0:
            bw[i] = (upper[i] - lower[i]) / m * 100.0
        else:
            bw[i] = 0.0
    return middle, upper, lower, bw


def compute_bw_percentile(bw_arr: np.ndarray, lookback: int = 120) -> np.ndarray:
    n = len(bw_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = bw_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = bw_arr[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


# ======================= signal generators =======================

def generate_vpin_signals(
    df: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
) -> np.ndarray:
    """Return boolean array: True where VPIN strategy would enter."""
    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)
    v = df["volume"].values.astype(float)
    h = df["high"].values.astype(float)
    lo = df["low"].values.astype(float)
    n = len(c)

    signals = np.zeros(n, dtype=bool)

    vpin_arr = compute_vpin(o, c, v, VPIN_BUCKET_COUNT)
    rsi_arr = compute_rsi(c, 14)
    mom_arr = compute_momentum(c, 12)
    ema_arr = ema_calc(c, VPIN_EMA_PERIOD)
    adx_arr = compute_adx(h, lo, c, 14)

    warmup = max(BTC_SMA_PERIOD, VPIN_BUCKET_COUNT + 1, 30)

    for i in range(warmup, n):
        # BTC gate
        if (np.isnan(btc_close_aligned[i]) or np.isnan(btc_sma_aligned[i])
                or btc_close_aligned[i] <= btc_sma_aligned[i]):
            continue

        vpin_val = vpin_arr[i]
        rsi_val = rsi_arr[i]
        mom_val = mom_arr[i]
        ema_val = ema_arr[i]
        adx_val = adx_arr[i]

        if np.isnan(vpin_val) or np.isnan(rsi_val) or np.isnan(mom_val):
            continue
        if np.isnan(ema_val):
            continue

        # VPIN high toxicity block
        if vpin_val >= VPIN_HIGH_TH:
            continue

        # EMA trend filter
        ema_up = c[i] > ema_val
        if i >= 3:
            ema_rising = ema_arr[i] > ema_arr[i - 3]
        else:
            ema_rising = True
        if not (ema_up and ema_rising):
            continue

        # VPIN low zone entry
        if vpin_val <= VPIN_LOW_TH:
            if mom_val >= VPIN_MOMENTUM_TH and VPIN_RSI_FLOOR <= rsi_val <= VPIN_RSI_CEILING:
                signals[i] = True
                continue

        # Moderate VPIN zone (strong momentum)
        mid_th = (VPIN_LOW_TH + VPIN_HIGH_TH) / 2
        if vpin_val <= mid_th:
            if mom_val >= VPIN_MOMENTUM_TH * 2 and VPIN_RSI_FLOOR <= rsi_val <= VPIN_RSI_CEILING:
                signals[i] = True

    return signals


def generate_bb_squeeze_signals(
    df: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
) -> np.ndarray:
    """Return boolean array: True where BB Squeeze strategy would enter."""
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    lo = df["low"].values.astype(float)
    n = len(c)

    signals = np.zeros(n, dtype=bool)

    ema_arr = ema_calc(c, EMA_PERIOD)
    adx_arr = compute_adx(h, lo, c, 14)
    _mid, bb_upper, _lower, bb_bw = compute_bb(c, BB_PERIOD, BB_STD)
    bw_pctile_arr = compute_bw_percentile(bb_bw, BW_PCTILE_LB)

    warmup = max(BW_PCTILE_LB, BTC_SMA_PERIOD, 30) + 5

    for i in range(warmup, n):
        # BTC gate
        if (np.isnan(btc_close_aligned[i]) or np.isnan(btc_sma_aligned[i])
                or btc_close_aligned[i] <= btc_sma_aligned[i]):
            continue

        ema_val = ema_arr[i]
        adx_val = adx_arr[i]
        bw_pctile_val = bw_pctile_arr[i]
        bb_upper_val = bb_upper[i]
        bb_bw_val = bb_bw[i]

        if np.isnan(ema_val) or np.isnan(adx_val):
            continue

        # Momentum: close > EMA
        if c[i] <= ema_val:
            continue

        # ADX >= threshold
        if adx_val < ADX_TH:
            continue

        if (np.isnan(bw_pctile_val) or np.isnan(bb_bw_val)
                or np.isnan(bb_upper_val)):
            continue

        # Squeeze history
        had_squeeze = False
        search_start = max(0, i - SQUEEZE_LB)
        search_end = max(0, i - EXPANSION_LB + 1)
        for k in range(search_start, search_end):
            if not np.isnan(bw_pctile_arr[k]) and bw_pctile_arr[k] < SQUEEZE_PCTILE_TH:
                had_squeeze = True
                break
        if not had_squeeze:
            continue

        # Bandwidth expanding
        if i - EXPANSION_LB < 0:
            continue
        prev_bw = bb_bw[i - EXPANSION_LB]
        if np.isnan(prev_bw) or prev_bw <= 0 or bb_bw_val <= prev_bw:
            continue

        # Upper band breakout
        if c[i] < bb_upper_val * UPPER_RATIO:
            continue

        signals[i] = True

    return signals


# ======================= analysis =======================

def jaccard(a: np.ndarray, b: np.ndarray) -> float:
    intersection = np.sum(a & b)
    union = np.sum(a | b)
    if union == 0:
        return 0.0
    return float(intersection) / float(union)


def jaccard_relaxed(a: np.ndarray, b: np.ndarray, window: int = 2) -> float:
    """Relaxed Jaccard: a signal in A 'matches' B if B fires within ±window bars."""
    n = len(a)
    a_matched = np.zeros(n, dtype=bool)
    b_matched = np.zeros(n, dtype=bool)

    a_indices = np.where(a)[0]
    b_indices = np.where(b)[0]

    for ai in a_indices:
        for bi in b_indices:
            if abs(int(ai) - int(bi)) <= window:
                a_matched[ai] = True
                b_matched[bi] = True

    matched_count = int(np.sum(a_matched) + np.sum(b_matched)) // 2
    total = len(a_indices) + len(b_indices) - matched_count
    if total == 0:
        return 0.0
    return float(matched_count) / float(total)


def main() -> None:
    print("=" * 80)
    print("=== 사이클 187: VPIN vs BB_squeeze_independent 신호 상관관계 분석 ===")
    print(f"심볼: {SYMBOL} | 기간: {ANALYSIS_START} ~ {ANALYSIS_END}")
    print(f"VPIN params: low={VPIN_LOW_TH} high={VPIN_HIGH_TH} mom={VPIN_MOMENTUM_TH}")
    print(f"BB params: sqTh={SQUEEZE_PCTILE_TH} sqLB={SQUEEZE_LB} "
          f"upR={UPPER_RATIO} adx={ADX_TH}")
    print("=" * 80)

    # Load data — use wider range for warmup
    df_eth = load_historical(SYMBOL, TIMEFRAME, "2021-01-01", ANALYSIS_END)
    df_btc = load_historical("KRW-BTC", TIMEFRAME, "2021-01-01", ANALYSIS_END)

    if df_eth.empty or df_btc.empty:
        print("데이터 없음")
        return

    print(f"\n  ETH: {len(df_eth)}행 | BTC: {len(df_btc)}행")

    # Align BTC
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, BTC_SMA_PERIOD)
    btc_c_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_c_aligned = btc_c_s.reindex(df_eth.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_eth.index, method="ffill").values

    # Generate signals on full data
    vpin_signals_full = generate_vpin_signals(df_eth, btc_c_aligned, btc_sma_aligned)
    bb_signals_full = generate_bb_squeeze_signals(df_eth, btc_c_aligned, btc_sma_aligned)

    # Trim to analysis window
    mask = (df_eth.index >= ANALYSIS_START) & (df_eth.index <= ANALYSIS_END)
    vpin_signals = vpin_signals_full[mask]
    bb_signals = bb_signals_full[mask]
    dates = df_eth.index[mask]

    n_vpin = int(np.sum(vpin_signals))
    n_bb = int(np.sum(bb_signals))
    n_both = int(np.sum(vpin_signals & bb_signals))

    print(f"\n--- 분석 기간 내 신호 수 ---")
    print(f"  VPIN 진입 신호: {n_vpin}건")
    print(f"  BB_squeeze 진입 신호: {n_bb}건")
    print(f"  동일 봉 겹침: {n_both}건")

    # Jaccard exact
    j_exact = jaccard(vpin_signals, bb_signals)
    print(f"\n--- Jaccard Similarity ---")
    print(f"  Exact (동일 봉):  {j_exact:.4f} ({j_exact * 100:.1f}%)")

    # Jaccard relaxed (±1, ±2, ±3 bars)
    for w in [1, 2, 3]:
        j_rel = jaccard_relaxed(vpin_signals, bb_signals, window=w)
        print(f"  Relaxed (±{w}봉):   {j_rel:.4f} ({j_rel * 100:.1f}%)")

    # Monthly breakdown
    print(f"\n--- 월별 신호 분포 ---")
    print(f"{'월':>10} | {'VPIN':>5} | {'BB_sq':>5} | {'겹침':>4} | {'Jaccard':>8}")
    print("-" * 45)

    months = pd.to_datetime(dates).to_period("M").unique()
    for month in months:
        m_mask = pd.to_datetime(dates).to_period("M") == month
        v_m = int(np.sum(vpin_signals[m_mask]))
        b_m = int(np.sum(bb_signals[m_mask]))
        both_m = int(np.sum(vpin_signals[m_mask] & bb_signals[m_mask]))
        union_m = v_m + b_m - both_m
        j_m = both_m / union_m if union_m > 0 else 0.0
        print(f"  {str(month):>8} | {v_m:>5} | {b_m:>5} | {both_m:>4} | {j_m:>7.1%}")

    # Temporal distance analysis
    vpin_idx = np.where(vpin_signals)[0]
    bb_idx = np.where(bb_signals)[0]

    if len(vpin_idx) > 0 and len(bb_idx) > 0:
        min_dists = []
        for vi in vpin_idx:
            dists = np.abs(bb_idx.astype(int) - int(vi))
            min_dists.append(int(dists.min()))
        min_dists_arr = np.array(min_dists)
        print(f"\n--- VPIN→BB_squeeze 최소 거리 통계 (봉 단위) ---")
        print(f"  평균: {min_dists_arr.mean():.1f}봉")
        print(f"  중앙값: {np.median(min_dists_arr):.1f}봉")
        print(f"  최소: {min_dists_arr.min()}봉 | 최대: {min_dists_arr.max()}봉")
        print(f"  ≤2봉 이내: {np.sum(min_dists_arr <= 2)}건 ({np.sum(min_dists_arr <= 2) / len(min_dists_arr) * 100:.1f}%)")
        print(f"  ≤5봉 이내: {np.sum(min_dists_arr <= 5)}건 ({np.sum(min_dists_arr <= 5) / len(min_dists_arr) * 100:.1f}%)")

    # Verdict
    print(f"\n{'=' * 80}")
    print(f"=== 최종 판정 ===")
    j_relaxed_2 = jaccard_relaxed(vpin_signals, bb_signals, window=2)
    if j_relaxed_2 < 0.20:
        print(f"  ✅ Jaccard(±2봉) = {j_relaxed_2:.1%} < 20% → 비상관 확인")
        print(f"  → 포트폴리오 분산 효과 유효, 동시 배포 권고")
    else:
        print(f"  ⚠️ Jaccard(±2봉) = {j_relaxed_2:.1%} ≥ 20% → 상관관계 존재")
        print(f"  → 포지션 사이즈 조정 또는 진입 시차 두기 필요")

    # Summary for ralph loop
    print(f"\nSharpe: 0")
    print(f"WR: 0.0%")
    print(f"trades: 0")
    print(f"\n[CORRELATION ANALYSIS] VPIN n={n_vpin}, BB n={n_bb}, "
          f"overlap={n_both}, Jaccard_exact={j_exact:.4f}, "
          f"Jaccard_2bar={j_relaxed_2:.4f}")


if __name__ == "__main__":
    main()
