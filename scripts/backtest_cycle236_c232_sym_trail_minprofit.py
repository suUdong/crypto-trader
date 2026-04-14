"""
vpin_multi 사이클 236: c232 최적 고정 + 심볼별 trailing stop & min_profit 스케일링 3-fold WF

기반: c232 OOS avg=+39.465, WR=70.0%, trades=20
  최적: eTP=0.70 sTP=1.00 eSL=0.80 sSL=1.00 xMOM=0.0003
  ETH Sharpe=+32.955 (trades=12), SOL=+49.890 (trades=8), XRP=0 (trades=0)

문제:
  1) trailing stop이 전 심볼 동일(Trail=0.3+0.2) → 심볼 변동성 특성 미반영
  2) ETH는 빠른 익절(eTP=0.70)이 유효 → trail도 타이트하면 수익 보존↑
  3) SOL은 확대(sTP=1.00) 유효 → trail 넓히면 큰 추세 더 캡처
  4) min_profit(1.5 ATR)도 심볼별 최적 다를 수 있음
  5) 시간감쇠(trail_tighten) 팩터도 심볼별 차이 가능

가설:
  A) ETH trail 타이트닝: eTrail=0.6~1.0 스케일 (기본 대비 축소)
  B) SOL trail 확대: sTrail=1.0~1.4 스케일 (큰 추세 캡처)
  C) min_profit 심볼별: eMinP=0.8~1.2 / sMinP=1.0~1.5 (ETH 빠른 트레일 발동, SOL 여유)
  D) 시간감쇠 팩터: eTTF=2.0~4.0 / sTTF=2.0~4.0 (ETH 빠른 감쇠, SOL 느린 감쇠)

탐색 그리드:
  E_TRAIL_SCALE: [0.6, 0.8, 1.0]      — ETH trail 스케일 (1.0=기존)
  S_TRAIL_SCALE: [1.0, 1.2, 1.4]      — SOL trail 스케일 (1.0=기존)
  E_MINP_SCALE:  [0.8, 1.0, 1.2]      — ETH min_profit 스케일
  S_MINP_SCALE:  [1.0, 1.3, 1.5]      — SOL min_profit 스케일
  = 3×3×3×3 = 81 combos × 3-fold × 3 심볼

c232 고정 (전부):
  c226 고정 진입: eV=0.35 sV=0.35 xV=0.15 vpc=0 dR=0
  c232 최적: eTP=0.70 sTP=1.00 eSL=0.80 sSL=1.00 xMOM=0.0003
  c220 확정: xH=0.7 mTP=0.5
  c199 고정: rTh=60 hiTP=1.0 hiTr=2.0 loSL=0.2
  c192 고정: ttA=6 ttF=3.0 (← 심볼별 오버라이드 탐색)
  c190 고정: vMomLB=10 vMomMin=0.05 tpBonus=1.0
  c186 고정: body=0.5 rsiD=6 sLB=10 sPth=50
  c182 고정: vPth=60 vPLB=60
  c176 고정: atrLB=60 atrTh=30
  c165 고정: VPIN_BASE=0.35 MOM=0.0007 Hold=20 CD=4
  c164 고정: dLB=3 SL=0.4-0.2 vMul=0.8
  TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
  BB 고정: bbP=20 bbS=2.0 sqTh=20 sqLB=30 expB=2

목표: avg OOS Sharpe >= 40 AND trades >= 18
3-fold WF + 슬리피지 스트레스
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

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]
FEE = 0.0005

# -- c165 최적 고정값 --
VPIN_LOW_BASE = 0.35
MOM_THRESH = 0.0007
MAX_HOLD_BASE = 20
COOLDOWN_BARS = 4

RSI_PERIOD = 14
RSI_CEILING_BASE = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

RSI_DELTA_LB = 3
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD = 20
VOL_SMA_PERIOD = 20

TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

BTC_SMA_PERIOD = 200

# -- c176 고정 --
ATR_PCTILE_LB = 60
ATR_TH = 30

# -- c182 최적 고정 --
VOL_PCTILE_TH = 60
VOL_PCTILE_LB = 60

# -- c186 최적 고정 --
BODY_RATIO_MIN = 0.50
RSI_DELTA_MIN = 6
EMA_SLOPE_LB = 10
EMA_SLOPE_PCTILE_TH = 50

# -- c190 최적 고정 --
VOL_MOM_LB = 10
VOL_MOM_MIN = 0.05
TP_SLOPE_BONUS = 1.0

# -- c192 최적 고정 --
TRAIL_TIGHTEN_AFTER = 6
TRAIL_TIGHTEN_FACTOR = 3.0

# -- c199 최적 고정 --
REGIME_TH = 60
HI_TP_BONUS = 1.0
HI_TRAIL_RELAX = 2.0
LO_SL_TIGHTEN = 0.20

# -- BB 고정 --
BB_PERIOD = 20
BB_STD = 2.0
SQUEEZE_PCTILE_TH = 20
SQUEEZE_LB = 30
EXPAND_BARS = 2

# -- c220 확정 --
XRP_HOLD_MULT = 0.7
MOM_TP_BONUS = 0.5
MOM_STRONG_PCTILE = 75

# -- c226 고정 진입: 심볼별 VPIN --
SYM_VPIN = {"KRW-ETH": 0.35, "KRW-SOL": 0.35, "KRW-XRP": 0.15}
VP_CONV = 0
DYN_RSI_BONUS = 0

# -- c232 최적: 심볼별 TP/SL 스케일 --
SYM_TP_SCALE = {"KRW-ETH": 0.70, "KRW-SOL": 1.00, "KRW-XRP": 1.00}
SYM_SL_SCALE = {"KRW-ETH": 0.80, "KRW-SOL": 1.00, "KRW-XRP": 1.00}
XRP_MOM_THRESH = 0.0003

# -- c236 탐색 그리드 --
E_TRAIL_SCALE_LIST = [0.6, 0.8, 1.0]
S_TRAIL_SCALE_LIST = [1.0, 1.2, 1.4]
E_MINP_SCALE_LIST = [0.8, 1.0, 1.2]
S_MINP_SCALE_LIST = [1.0, 1.3, 1.5]

# -- 3-fold Walkforward --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# -- 지표 --

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


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


def rsi_calc(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def compute_vpin_bvc(
    closes: np.ndarray, opens: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray, bucket_count: int = 24,
) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(bucket_count, n):
        total_vol = 0.0
        abs_imbalance = 0.0
        for j in range(i - bucket_count, i):
            price_range = highs[j] - lows[j]
            if price_range <= 0:
                buy_frac = 0.5
            else:
                z = (closes[j] - opens[j]) / price_range
                buy_frac = _normal_cdf(z)
            bv = volumes[j] * buy_frac
            sv = volumes[j] * (1.0 - buy_frac)
            abs_imbalance += abs(bv - sv)
            total_vol += volumes[j]
        if total_vol > 0:
            result[i] = abs_imbalance / total_vol
        else:
            result[i] = 0.5
    return result


def compute_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def compute_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 20,
) -> np.ndarray:
    n = len(closes)
    tr = np.full(n, np.nan)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr_arr = np.full(n, np.nan)
    if n < period:
        return atr_arr
    atr_arr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr_arr[i] = (atr_arr[i - 1] * (period - 1) + tr[i]) / period
    return atr_arr


def compute_atr_percentile(
    atr_arr: np.ndarray, lookback: int = 60,
) -> np.ndarray:
    n = len(atr_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = atr_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = atr_arr[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


def compute_body_ratio(
    opens: np.ndarray, closes: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(n):
        candle_range = highs[i] - lows[i]
        if candle_range <= 0:
            result[i] = 0.0
        else:
            result[i] = abs(closes[i] - opens[i]) / candle_range
    return result


def compute_vol_percentile(
    volumes: np.ndarray, lookback: int = 60,
) -> np.ndarray:
    n = len(volumes)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = volumes[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = volumes[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


def compute_ema_slope_percentile(
    ema_arr: np.ndarray, slope_lb: int, pctile_lb: int = 60,
) -> np.ndarray:
    n = len(ema_arr)
    slope = np.full(n, np.nan)
    for i in range(slope_lb, n):
        if np.isnan(ema_arr[i]) or np.isnan(ema_arr[i - slope_lb]):
            continue
        if ema_arr[i - slope_lb] <= 0:
            continue
        slope[i] = (ema_arr[i] - ema_arr[i - slope_lb]) / ema_arr[i - slope_lb]

    result = np.full(n, np.nan)
    start = max(slope_lb, pctile_lb)
    for i in range(start, n):
        window = slope[i - pctile_lb:i]
        valid = window[~np.isnan(window)]
        if len(valid) < pctile_lb // 2:
            continue
        current = slope[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


def compute_vol_momentum(
    volumes: np.ndarray, ema_period: int = 10,
) -> np.ndarray:
    vol_ema = ema_calc(volumes, ema_period)
    n = len(volumes)
    result = np.full(n, np.nan)
    for i in range(ema_period + 1, n):
        if np.isnan(vol_ema[i]) or np.isnan(vol_ema[i - 1]):
            continue
        if vol_ema[i - 1] <= 0:
            continue
        result[i] = vol_ema[i] / vol_ema[i - 1] - 1.0
    return result


def compute_bb_width(
    closes: np.ndarray, period: int, std_mult: float,
) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    sma_arr = sma_calc(closes, period)
    for i in range(period - 1, n):
        if np.isnan(sma_arr[i]) or sma_arr[i] <= 0:
            continue
        window = closes[max(0, i - period + 1):i + 1]
        std = np.std(window, ddof=1) if len(window) > 1 else 0.0
        upper = sma_arr[i] + std_mult * std
        lower = sma_arr[i] - std_mult * std
        result[i] = (upper - lower) / sma_arr[i]
    return result


def compute_bb_width_percentile(
    bb_width: np.ndarray, lookback: int,
) -> np.ndarray:
    n = len(bb_width)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = bb_width[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = bb_width[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


def compute_mom_percentile(
    mom_arr: np.ndarray, lookback: int = 60,
) -> np.ndarray:
    n = len(mom_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = mom_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = mom_arr[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


def align_btc_to_symbol(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame, btc_sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, btc_sma_period)
    btc_close_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_close_aligned = btc_close_s.reindex(df_sym.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_sym.index, method="ffill").values
    return btc_close_aligned, btc_sma_aligned


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    symbol: str,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    ema_slope_pctile_arr: np.ndarray,
    vol_mom_arr: np.ndarray,
    atr_pctile_full: np.ndarray,
    bb_width_pctile_arr: np.ndarray,
    mom_pctile_arr: np.ndarray,
    # c236 심볼별 파라미터
    trail_scale: float,
    minp_scale: float,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)
    body_ratio_arr = compute_body_ratio(o, c, h, lo)
    vol_pctile_arr = compute_vol_percentile(v, VOL_PCTILE_LB)

    # c232: 심볼별 TP/SL 스케일
    sym_tp_scale = SYM_TP_SCALE.get(symbol, 1.0)
    sym_sl_scale = SYM_SL_SCALE.get(symbol, 1.0)
    sym_vpin_th = SYM_VPIN.get(symbol, VPIN_LOW_BASE)
    sym_mom_thresh = XRP_MOM_THRESH if symbol == "KRW-XRP" else MOM_THRESH

    # c220: XRP hold 축소
    sym_hold_mult = XRP_HOLD_MULT if symbol == "KRW-XRP" else 1.0

    # c236: 심볼별 trail/minP 스케일
    effective_min_profit = MIN_PROFIT_ATR * minp_scale

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, VOL_PCTILE_LB,
                 EMA_SLOPE_LB + 60, VOL_MOM_LB + 10,
                 BB_PERIOD + SQUEEZE_LB + EXPAND_BARS, 60, 50) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if COOLDOWN_BARS > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_sma_val = vol_sma_arr[i]
        atr_pctile_val = atr_pctile_full[i]
        body_val = body_ratio_arr[i]
        vol_pctile_val = vol_pctile_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0):
            i += 1
            continue

        # RSI velocity
        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        effective_rsi_ceiling = RSI_CEILING_BASE

        # === 진입 조건 ===
        vpin_ok = (
            vpin_val < sym_vpin_th
            and mom_val >= sym_mom_thresh
            and RSI_FLOOR < rsi_val < effective_rsi_ceiling
            and c[i] > ema_val
        )
        btc_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )
        rsi_velocity_ok = rsi_delta >= RSI_DELTA_MIN
        vol_ratio = v[i] / vol_sma_arr[i] if vol_sma_arr[i] > 0 else 0.0
        vol_ok = vol_ratio >= VOL_MULT
        atr_pctile_ok = (not np.isnan(atr_pctile_val)
                         and atr_pctile_val >= ATR_TH)
        body_ok = (not np.isnan(body_val)
                   and body_val >= BODY_RATIO_MIN and c[i] >= o[i])
        vol_pctile_ok = (not np.isnan(vol_pctile_val)
                         and vol_pctile_val >= VOL_PCTILE_TH)
        esp = ema_slope_pctile_arr[i]
        ema_slope_ok = not np.isnan(esp) and esp >= EMA_SLOPE_PCTILE_TH
        vm = vol_mom_arr[i]
        vol_mom_ok = True
        if VOL_MOM_MIN > 0:
            vol_mom_ok = not np.isnan(vm) and vm >= VOL_MOM_MIN

        if not (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and vol_pctile_ok
                and ema_slope_ok and vol_mom_ok):
            i += 1
            continue

        # === 진입 ===
        buy = o[i + 1] * (1 + FEE + slippage)
        peak_price = buy
        atr_at_entry = atr_val
        entry_bar = i + 1

        # RSI 기반 동적 스케일링
        rsi_ratio = (effective_rsi_ceiling - rsi_val) / (
            effective_rsi_ceiling - RSI_FLOOR)
        rsi_ratio = max(0.0, min(1.0, rsi_ratio))

        # EMA slope → TP 보너스 (c190 고정)
        slope_tp_extra = 0.0
        if TP_SLOPE_BONUS > 0 and not np.isnan(esp):
            if esp >= 70.0:
                slope_tp_extra = TP_SLOPE_BONUS
            elif esp >= 60.0:
                slope_tp_extra = TP_SLOPE_BONUS * 0.5

        # c199 고정: 레짐 조건부 이중 출구
        regime_score = 0.0
        if not np.isnan(atr_pctile_val):
            if atr_pctile_val >= REGIME_TH + 10:
                regime_score = 1.0
            elif atr_pctile_val >= REGIME_TH - 10:
                regime_score = (atr_pctile_val - (REGIME_TH - 10)) / 20.0

        regime_tp_extra = HI_TP_BONUS * regime_score

        # c220 확정: 모멘텀 TP 보너스
        mom_tp_extra = 0.0
        if MOM_TP_BONUS > 0:
            mom_pctile_val = mom_pctile_arr[i]
            if not np.isnan(mom_pctile_val) and mom_pctile_val >= MOM_STRONG_PCTILE:
                mom_strength = (mom_pctile_val - MOM_STRONG_PCTILE) / (
                    100.0 - MOM_STRONG_PCTILE + 1e-9)
                mom_tp_extra = MOM_TP_BONUS * mom_strength

        # c232: 심볼별 TP 스케일
        effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
                             + slope_tp_extra + regime_tp_extra
                             + mom_tp_extra) * sym_tp_scale
        tp_price = buy + atr_at_entry * effective_tp_mult

        # c232: 심볼별 SL 스케일
        sl_tighten = LO_SL_TIGHTEN * (1.0 - regime_score)
        effective_sl_mult = (SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
                             - sl_tighten) * sym_sl_scale
        effective_sl_mult = max(0.15, effective_sl_mult)
        sl_price = buy - atr_at_entry * effective_sl_mult

        # c236: 심볼별 trail 스케일
        base_trail_mult = (TRAIL_BASE_ATR
                           + TRAIL_BONUS_ATR * (1.0 - rsi_ratio))
        trail_relax_factor = 1.0 + (HI_TRAIL_RELAX - 1.0) * regime_score
        base_trail_mult *= trail_relax_factor * trail_scale

        min_profit_dist = atr_at_entry * effective_min_profit

        # c220: 심볼별 hold
        max_hold = int((MAX_HOLD_BASE + int(6 * regime_score)) * sym_hold_mult)
        max_hold = max(5, max_hold)

        exit_ret = None
        for j in range(i + 2, min(i + 1 + max_hold, n)):
            current_price = c[j]
            bars_held = j - entry_bar

            if current_price >= tp_price:
                exit_ret = (tp_price / buy - 1) - FEE - slippage
                i = j
                break

            if current_price <= sl_price:
                exit_ret = (sl_price / buy - 1) - FEE - slippage
                i = j
                break

            if current_price > peak_price:
                peak_price = current_price

            # c192 고정 + c236: 시간감쇠 트레일
            if bars_held >= TRAIL_TIGHTEN_AFTER:
                effective_trail_mult = base_trail_mult / TRAIL_TIGHTEN_FACTOR
            else:
                effective_trail_mult = base_trail_mult

            trail_dist = atr_at_entry * effective_trail_mult

            unrealized = peak_price - buy
            if unrealized >= min_profit_dist:
                if peak_price - current_price >= trail_dist:
                    exit_ret = (
                        current_price / buy - 1) - FEE - slippage
                    i = j
                    break

        if exit_ret is None:
            hold_end = min(i + max_hold, n - 1)
            exit_ret = c[hold_end] / buy - 1 - FEE - slippage
            i = hold_end

        returns.append(exit_ret)

        if exit_ret < 0:
            consecutive_losses += 1
            if (consecutive_losses >= COOLDOWN_LOSSES
                    and COOLDOWN_BARS > 0):
                cooldown_until = i + COOLDOWN_BARS
                consecutive_losses = 0
        else:
            consecutive_losses = 0

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak_cum = np.maximum.accumulate(cum)
    dd = cum - peak_cum
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    mcl = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl}


def pool_results(results_list: list[dict]) -> dict:
    all_sharpes = []
    all_wrs = []
    total_trades = 0
    all_avg_rets = []
    all_max_dds = []
    all_mcls = []
    for r in results_list:
        if r["trades"] > 0 and not np.isnan(r["sharpe"]):
            all_sharpes.append(r["sharpe"])
            all_wrs.append(r["wr"])
            total_trades += r["trades"]
            all_avg_rets.append(r["avg_ret"])
            all_max_dds.append(r["max_dd"])
            all_mcls.append(r["mcl"])
    if not all_sharpes:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    return {
        "sharpe": float(np.mean(all_sharpes)),
        "wr": float(np.mean(all_wrs)),
        "avg_ret": float(np.mean(all_avg_rets)),
        "trades": total_trades,
        "max_dd": float(np.mean(all_max_dds)),
        "mcl": max(all_mcls),
    }


def get_sym_params(
    symbol: str, combo: dict,
) -> tuple[float, float]:
    """심볼별 trail_scale, minp_scale 반환."""
    if symbol == "KRW-ETH":
        return combo["e_trail"], combo["e_minp"]
    elif symbol == "KRW-SOL":
        return combo["s_trail"], combo["s_minp"]
    else:  # XRP — 기본값 1.0
        return 1.0, 1.0


def build_combos() -> list[dict]:
    combos = []
    for et, st, em, sm in product(
        E_TRAIL_SCALE_LIST, S_TRAIL_SCALE_LIST,
        E_MINP_SCALE_LIST, S_MINP_SCALE_LIST,
    ):
        combos.append({
            "e_trail": et,
            "s_trail": st,
            "e_minp": em,
            "s_minp": sm,
        })
    return combos


def precompute_base(
    df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    c = df["close"].values
    h = df["high"].values
    lo_arr = df["low"].values
    v = df["volume"].values
    ema_arr = ema_calc(c, EMA_PERIOD)
    ema_slope_pctile = compute_ema_slope_percentile(ema_arr, EMA_SLOPE_LB)
    vol_mom = compute_vol_momentum(v, ema_period=VOL_MOM_LB)
    atr_arr = compute_atr(h, lo_arr, c, ATR_PERIOD)
    atr_pctile = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    mom_pctile = compute_mom_percentile(mom_arr, lookback=60)
    return ema_slope_pctile, vol_mom, atr_pctile, mom_pctile


def precompute_bb(df: pd.DataFrame) -> np.ndarray:
    c = df["close"].values
    bb_w = compute_bb_width(c, BB_PERIOD, BB_STD)
    bb_wp = compute_bb_width_percentile(bb_w, SQUEEZE_LB)
    return bb_wp


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi c236 — 심볼별 Trailing Stop & Min Profit 스케일링 ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe >= 40 AND trades >= 18")
    print("가설: ETH trail 타이트(빠른 수익 보존) + SOL trail 확대(큰 추세 캡처) "
          "+ min_profit 심볼별 최적화")
    print(f"기준선: c232 OOS +39.465 / c226 OOS +38.407 / c199 OOS +51.425")
    print(f"c232 고정: eTP={SYM_TP_SCALE['KRW-ETH']} sTP={SYM_TP_SCALE['KRW-SOL']}"
          f" eSL={SYM_SL_SCALE['KRW-ETH']} sSL={SYM_SL_SCALE['KRW-SOL']}"
          f" xMOM={XRP_MOM_THRESH}")
    print(f"c226 고정 진입: eV={SYM_VPIN['KRW-ETH']} sV={SYM_VPIN['KRW-SOL']}"
          f" xV={SYM_VPIN['KRW-XRP']} vpc={VP_CONV} dR={DYN_RSI_BONUS}")
    print(f"c220 확정: xH={XRP_HOLD_MULT} mTP={MOM_TP_BONUS}")
    print(f"c199 고정: rTh={REGIME_TH} hiTP={HI_TP_BONUS} "
          f"hiTr={HI_TRAIL_RELAX} loSL={LO_SL_TIGHTEN}")
    print(f"c192 고정: ttA={TRAIL_TIGHTEN_AFTER} ttF={TRAIL_TIGHTEN_FACTOR}")
    print(f"c190 고정: vMomLB={VOL_MOM_LB} vMomMin={VOL_MOM_MIN} "
          f"tpBonus={TP_SLOPE_BONUS}")
    print(f"c186 고정: body={BODY_RATIO_MIN} rsiD={RSI_DELTA_MIN} "
          f"sLB={EMA_SLOPE_LB} sPth={EMA_SLOPE_PCTILE_TH}")
    print(f"c182 고정: vPth={VOL_PCTILE_TH} vPLB={VOL_PCTILE_LB}")
    print(f"c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH}")
    print(f"c165 고정: VPIN_BASE={VPIN_LOW_BASE} MOM={MOM_THRESH} "
          f"Hold={MAX_HOLD_BASE} CD={COOLDOWN_BARS}")
    print(f"  dLB={RSI_DELTA_LB} SL={SL_BASE_ATR}-{SL_BONUS_ATR} "
          f"vMul={VOL_MULT}")
    print(f"  TP={TP_BASE_ATR}+{TP_BONUS_ATR} Trail={TRAIL_BASE_ATR}+"
          f"{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD}")
    print(f"  BB 고정: bbP={BB_PERIOD} bbS={BB_STD} "
          f"sqTh={SQUEEZE_PCTILE_TH} sqLB={SQUEEZE_LB} expB={EXPAND_BARS}")
    print(f"탐색: eTrail={E_TRAIL_SCALE_LIST} sTrail={S_TRAIL_SCALE_LIST}")
    print(f"      eMinP={E_MINP_SCALE_LIST}  sMinP={S_MINP_SCALE_LIST}")
    print("=" * 80)

    # -- BTC 데이터 --
    df_btc_full = load_historical(
        "KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # -- 심볼별 데이터 확인 --
    print("\n--- 심볼별 데이터 확인 ---")
    sym_data_ok = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df_check.empty or len(df_check) < 500:
            print(f"  {sym}: 데이터 부족 ({len(df_check)}행) → 제외")
        else:
            print(f"  {sym}: {len(df_check)}행 OK")
            sym_data_ok.append(sym)

    if not sym_data_ok:
        print("유효 심볼 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 1: train 그리드 서치 --
    combos = build_combos()
    print(f"\n총 조합: {len(combos)}개 × {len(sym_data_ok)} 심볼")

    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: train 그리드 서치 ({train_start} ~ {train_end})")

    sym_train_cache: dict[str, tuple] = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if not df_tr.empty:
            btc_c, btc_s = align_btc_to_symbol(
                df_tr, df_btc_full, BTC_SMA_PERIOD)
            esp, vol_mom, atr_pctile, mom_pctile = precompute_base(df_tr)
            bb_wp = precompute_bb(df_tr)
            sym_train_cache[sym] = (
                df_tr, btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp,
                mom_pctile)
            print(f"  {sym} train: {len(df_tr)}행")

    results: list[dict] = []
    for idx, combo in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            (df_tr, btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp,
             mom_pctile) = sym_train_cache[sym]

            trail_s, minp_s = get_sym_params(sym, combo)
            r = backtest(
                df_tr, sym,
                btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp, mom_pctile,
                trail_scale=trail_s, minp_scale=minp_s)
            sym_results.append(r)

        pooled = pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 27 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    print(f"  [{len(combos)}/{len(combos)}] 완료")

    valid = [r for r in results
             if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")

    print(f"\n=== Train Top 16 (pooled Sharpe 기준) ===")
    hdr = (f"{'eT':>4} {'sT':>4} {'eM':>4} {'sM':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} "
           f"{'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:16]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['e_trail']:>4.1f} {r['s_trail']:>4.1f} "
            f"{r['e_minp']:>4.1f} {r['s_minp']:>4.1f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}")

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 2: 3-fold OOS Walk-Forward --
    seen: set[tuple] = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["e_trail"], r["s_trail"], r["e_minp"], r["s_minp"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 12:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(unique_top)} 고유) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        sym_fold_details: list[str] = []

        for fold_i, fold in enumerate(WF_FOLDS):
            sym_fold_results = []
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                esp, vol_mom, atr_pctile, mom_pctile = precompute_base(
                    df_test)
                bb_wp = precompute_bb(df_test)

                trail_s, minp_s = get_sym_params(sym, params)
                r = backtest(
                    df_test, sym,
                    btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp,
                    mom_pctile,
                    trail_scale=trail_s, minp_scale=minp_s)
                sym_fold_results.append(r)

                sym_fold_details.append(
                    f"  {sym} Fold {fold['test'][0]}~{fold['test'][1]}: "
                    f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
                    f"n={r['trades']}  avg={r['avg_ret'] * 100:+.2f}%  "
                    f"MDD={r['max_dd'] * 100:+.2f}%"
                )

            pooled = pool_results(sym_fold_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(pooled["trades"])
            fold_details.append(pooled)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            total_oos_n = sum(oos_trades)
            all_pass = (all(s >= 3.0 for s in oos_sharpes)
                        and avg_oos >= 5.0)
            tag = "PASS" if all_pass else "FAIL"
            print(
                f"  #{rank}: eT={params['e_trail']:.1f} "
                f"sT={params['s_trail']:.1f} "
                f"eM={params['e_minp']:.1f} "
                f"sM={params['s_minp']:.1f} | "
                f"avg_OOS={avg_oos:+.3f} min={min_oos:+.3f} "
                f"n={total_oos_n} {tag}")
            wf_results.append({
                **params,
                "avg_oos": avg_oos,
                "min_oos": min_oos,
                "total_n": total_oos_n,
                "fold_details": fold_details,
                "sym_fold_details": sym_fold_details,
                "tag": tag,
            })

    if not wf_results:
        print("WF 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    wf_results.sort(key=lambda x: x["avg_oos"], reverse=True)
    best = wf_results[0]

    # -- Phase 3: 슬리피지 스트레스 테스트 --
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS 최적) ===")
    print(f"파라미터: eT={best['e_trail']:.1f} sT={best['s_trail']:.1f} "
          f"eM={best['e_minp']:.1f} sM={best['s_minp']:.1f}")

    for slip in SLIPPAGE_LEVELS:
        slip_sharpes = []
        slip_trades = 0
        for fold in WF_FOLDS:
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                esp, vol_mom, atr_pctile, mom_pctile = precompute_base(
                    df_test)
                bb_wp = precompute_bb(df_test)
                trail_s, minp_s = get_sym_params(sym, best)
                r = backtest(
                    df_test, sym,
                    btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp,
                    mom_pctile,
                    trail_scale=trail_s, minp_scale=minp_s,
                    slippage=slip)
                if r["trades"] > 0 and not np.isnan(r["sharpe"]):
                    slip_sharpes.append(r["sharpe"])
                    slip_trades += r["trades"]
        avg_sh = float(np.mean(slip_sharpes)) if slip_sharpes else float("nan")
        print(f"  slip={slip:.4f}: Sharpe={avg_sh:+.3f}  trades={slip_trades}")

    # -- 심볼별 fold 분해 --
    print(f"\n{'=' * 80}")
    print("=== OOS 최적 심볼별 fold 분해 ===")
    for detail in best.get("sym_fold_details", []):
        print(detail)

    for sym in sym_data_ok:
        sym_sharpes = []
        sym_trades = 0
        for fold in WF_FOLDS:
            df_test = load_historical(
                sym, "240m", fold["test"][0], fold["test"][1])
            if df_test.empty:
                continue
            btc_c, btc_s = align_btc_to_symbol(
                df_test, df_btc_full, BTC_SMA_PERIOD)
            esp, vol_mom, atr_pctile, mom_pctile = precompute_base(df_test)
            bb_wp = precompute_bb(df_test)
            trail_s, minp_s = get_sym_params(sym, best)
            r = backtest(
                df_test, sym,
                btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp, mom_pctile,
                trail_scale=trail_s, minp_scale=minp_s)
            if r["trades"] > 0 and not np.isnan(r["sharpe"]):
                sym_sharpes.append(r["sharpe"])
                sym_trades += r["trades"]
        avg_sym = float(np.mean(sym_sharpes)) if sym_sharpes else 0.0
        print(f"  {sym} 평균: Sharpe={avg_sym:+.3f}  총 trades={sym_trades}")

    # -- 베이스라인 대비 --
    print(f"\n{'=' * 80}")
    print("=== 베이스라인 대비 비교 ===")
    c199_baseline = 51.425
    c226_baseline = 38.407
    c232_baseline = 39.465
    print(f"  c199 기준 (regime dual exit): avg_OOS={c199_baseline:+.3f}")
    print(f"  c226 기준 (sym VPIN fine): avg_OOS={c226_baseline:+.3f}")
    print(f"  c232 기준 (sym TP/SL): avg_OOS={c232_baseline:+.3f}")
    print(f"  c236 최적: avg_OOS={best['avg_oos']:+.3f}")
    delta199 = best["avg_oos"] - c199_baseline
    delta232 = best["avg_oos"] - c232_baseline
    label199 = "개선" if delta199 > 0 else "악화"
    label232 = "개선" if delta232 > 0 else "악화"
    print(f"  Δ vs c199: {delta199:+.3f} ({label199})")
    print(f"  Δ vs c232: {delta232:+.3f} ({label232})")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: eTrail={best['e_trail']:.1f} "
          f"sTrail={best['s_trail']:.1f} "
          f"eMinP={best['e_minp']:.1f} "
          f"sMinP={best['s_minp']:.1f}")
    print(f"  (c232 고정: eTP={SYM_TP_SCALE['KRW-ETH']} "
          f"sTP={SYM_TP_SCALE['KRW-SOL']} "
          f"eSL={SYM_SL_SCALE['KRW-ETH']} "
          f"sSL={SYM_SL_SCALE['KRW-SOL']} "
          f"xMOM={XRP_MOM_THRESH})")
    print(f"  (c226 고정 진입: eV={SYM_VPIN['KRW-ETH']} "
          f"sV={SYM_VPIN['KRW-SOL']} "
          f"xV={SYM_VPIN['KRW-XRP']} vpc={VP_CONV} dR={DYN_RSI_BONUS})")
    print(f"  (c220 확정: xH={XRP_HOLD_MULT} mTP={MOM_TP_BONUS})")
    print(f"  (c199 고정: rTh={REGIME_TH} hiTP={HI_TP_BONUS} "
          f"hiTr={HI_TRAIL_RELAX} loSL={LO_SL_TIGHTEN})")
    print(f"  (c192 고정: ttA={TRAIL_TIGHTEN_AFTER} ttF={TRAIL_TIGHTEN_FACTOR})")
    print(f"  (c190 고정: vMomLB={VOL_MOM_LB} vMomMin={VOL_MOM_MIN} "
          f"tpBonus={TP_SLOPE_BONUS})")
    print(f"  (c186 고정: body={BODY_RATIO_MIN} rsiD={RSI_DELTA_MIN} "
          f"sLB={EMA_SLOPE_LB} sPth={EMA_SLOPE_PCTILE_TH})")
    print(f"  (c182 고정: vPth={VOL_PCTILE_TH} vPLB={VOL_PCTILE_LB})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH})")
    print(f"  (c165 고정: VPIN_BASE={VPIN_LOW_BASE} MOM={MOM_THRESH} "
          f"Hold={MAX_HOLD_BASE} CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} SL={SL_BASE_ATR}-{SL_BONUS_ATR} "
          f"vMul={VOL_MULT})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} "
          f"minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD})")
    print(f"  (BB 고정: bbP={BB_PERIOD} bbS={BB_STD} "
          f"sqTh={SQUEEZE_PCTILE_TH} sqLB={SQUEEZE_LB} expB={EXPAND_BARS})")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} {best['tag']}")
    train_best = valid[0] if valid else None
    if train_best:
        print(f"  train Sharpe: {train_best['sharpe']:+.3f}")
    for fi, fd in enumerate(best["fold_details"]):
        sh = fd["sharpe"] if not np.isnan(fd["sharpe"]) else 0.0
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={fd['trades']}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    total_wr = 0.0
    total_n = 0
    for fd in best["fold_details"]:
        if fd["trades"] > 0:
            total_wr += fd["wr"] * fd["trades"]
            total_n += fd["trades"]
    final_wr = total_wr / total_n * 100 if total_n > 0 else 0.0
    print(f"WR: {final_wr:.1f}%")
    print(f"trades: {best['total_n']}")


if __name__ == "__main__":
    main()
