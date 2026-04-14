"""
vpin_multi 사이클 220 — Momentum Persistence + Symbol-Adaptive Hold + Regime Cooldown
- 기반: c199 OOS Sharpe +51.425 (regime dual exit) — 현재 BEST
  c217 OOS +37.362 (score ablation) — c199 미달, score 기반 접근 한계 확인
- 문제:
  1) 모멘텀 point-in-time 체크 → 노이즈 진입 허용
  2) 모든 심볼 동일 hold 기간 → SOL(추세형)은 길게, XRP(회귀형)은 짧게 해야
  3) 약한 레짐에서 연패 후 cooldown 동일 → 레짐 약할 때 더 긴 대기 필요
  4) 강한 모멘텀 진입 시 TP 여유 부족 → 추가 TP 보너스 가능
- 가설:
  A) 모멘텀 N바 연속 확인 → 노이즈 진입 제거, 승률 개선
  B) SOL hold 확대 → fat tail 포착 극대화
  C) XRP hold 축소 → 빠른 회전, MDD 감소
  D) 레짐 약할 때 cooldown 확대 → 연패 구간 회피
  E) 강한 모멘텀 → TP 보너스 → 이익 극대화
- 탐색 그리드:
  MOM_PERSIST: [1, 2, 3]          — 최근 N바 중 모멘텀>0 필수
  REGIME_CD_MULT: [1.0, 2.0]      — 약 레짐 cooldown 배수
  SOL_HOLD_MULT: [1.0, 1.3]       — SOL hold 배수
  XRP_HOLD_MULT: [0.7, 1.0]       — XRP hold 배수
  MOM_TP_BONUS: [0.0, 0.5, 1.0]   — 강모멘텀 TP 보너스
  = 3×2×2×2×3 = 72 combos
- 목표: avg OOS Sharpe >= 52 AND trades >= 12
- 3-fold WF + 슬리피지 스트레스
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
VPIN_LOW = 0.35
MOM_THRESH = 0.0007
MAX_HOLD_BASE = 20
COOLDOWN_BARS = 4

RSI_PERIOD = 14
RSI_CEILING = 65.0
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

# -- BB 고정 (c206) --
BB_PERIOD = 20
BB_STD = 2.0
SQUEEZE_PCTILE_TH = 20
SQUEEZE_LB = 30
EXPAND_BARS = 2

# -- c220 탐색 그리드 --
MOM_PERSIST_LIST = [1, 2, 3]        # 최근 N바 연속 모멘텀>0
REGIME_CD_MULT_LIST = [1.0, 2.0]    # 약 레짐 cooldown 배수
SOL_HOLD_MULT_LIST = [1.0, 1.3]     # SOL hold 배수
XRP_HOLD_MULT_LIST = [0.7, 1.0]     # XRP hold 배수
MOM_TP_BONUS_LIST = [0.0, 0.5, 1.0] # 강모멘텀 TP 보너스

# 모멘텀 강도 문턱값 (상위 25% → "강한 모멘텀")
MOM_STRONG_PCTILE = 75

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
    """모멘텀 백분위: 현재 모멘텀이 lookback 윈도우 내 어느 수준인지."""
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
    mom_persist: int,
    regime_cd_mult: float,
    sym_hold_mult: float,
    mom_tp_bonus: float,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    ema_slope_pctile_arr: np.ndarray,
    vol_mom_arr: np.ndarray,
    atr_pctile_full: np.ndarray,
    bb_width_pctile_arr: np.ndarray,
    mom_pctile_arr: np.ndarray,
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

        # 기존 binary gates (c165~c190 고정)
        vpin_ok = (
            vpin_val < VPIN_LOW
            and mom_val >= MOM_THRESH
            and RSI_FLOOR < rsi_val < RSI_CEILING
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

        # === c220 핵심 A: 모멘텀 지속성 확인 ===
        # 최근 mom_persist 바 연속 모멘텀 > MOM_THRESH
        mom_persist_ok = True
        if mom_persist > 1:
            for back in range(1, mom_persist):
                idx_back = i - back
                if idx_back < MOM_LOOKBACK:
                    mom_persist_ok = False
                    break
                m_back = mom_arr[idx_back]
                if np.isnan(m_back) or m_back < MOM_THRESH:
                    mom_persist_ok = False
                    break

        if not mom_persist_ok:
            i += 1
            continue

        # === 진입 ===
        buy = o[i + 1] * (1 + FEE + slippage)
        peak_price = buy
        atr_at_entry = atr_val
        entry_bar = i + 1

        # RSI 기반 동적 스케일링 (기존)
        rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
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

        # === c220 핵심 E: 강모멘텀 TP 보너스 ===
        mom_tp_extra = 0.0
        if mom_tp_bonus > 0:
            mom_pctile_val = mom_pctile_arr[i]
            if not np.isnan(mom_pctile_val) and mom_pctile_val >= MOM_STRONG_PCTILE:
                # 모멘텀 상위 25%: 비례 보너스
                mom_strength = (mom_pctile_val - MOM_STRONG_PCTILE) / (
                    100.0 - MOM_STRONG_PCTILE + 1e-9)
                mom_tp_extra = mom_tp_bonus * mom_strength

        effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
                             + slope_tp_extra + regime_tp_extra + mom_tp_extra)
        tp_price = buy + atr_at_entry * effective_tp_mult

        sl_tighten = LO_SL_TIGHTEN * (1.0 - regime_score)
        effective_sl_mult = (SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
                             - sl_tighten)
        effective_sl_mult = max(0.15, effective_sl_mult)
        sl_price = buy - atr_at_entry * effective_sl_mult

        base_trail_mult = (TRAIL_BASE_ATR
                           + TRAIL_BONUS_ATR * (1.0 - rsi_ratio))
        trail_relax_factor = 1.0 + (HI_TRAIL_RELAX - 1.0) * regime_score
        base_trail_mult *= trail_relax_factor

        min_profit_dist = atr_at_entry * MIN_PROFIT_ATR

        # === c220 핵심 B/C: 심볼별 적응형 hold ===
        max_hold = int((MAX_HOLD_BASE + int(6 * regime_score)) * sym_hold_mult)
        max_hold = max(5, max_hold)  # 최소 5바

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

            # 시간감쇠 트레일 (c192 고정)
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
                # === c220 핵심 D: 레짐 조건부 cooldown ===
                effective_cd = COOLDOWN_BARS
                if regime_score < 0.5:
                    effective_cd = int(COOLDOWN_BARS * regime_cd_mult)
                cooldown_until = i + effective_cd
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


def build_combos() -> list[dict]:
    combos = []
    for mp, rcd, shS, shX, mtb in product(
        MOM_PERSIST_LIST, REGIME_CD_MULT_LIST,
        SOL_HOLD_MULT_LIST, XRP_HOLD_MULT_LIST,
        MOM_TP_BONUS_LIST,
    ):
        combos.append({
            "mom_persist": mp,
            "regime_cd_mult": rcd,
            "sol_hold_mult": shS,
            "xrp_hold_mult": shX,
            "mom_tp_bonus": mtb,
        })
    return combos


def get_sym_hold_mult(symbol: str, combo: dict) -> float:
    if symbol == "KRW-SOL":
        return combo["sol_hold_mult"]
    elif symbol == "KRW-XRP":
        return combo["xrp_hold_mult"]
    return 1.0  # ETH 기본


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
    print("=== vpin_multi c220 — Mom Persist + Sym Hold + Regime CD ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe >= 52 AND trades >= 12")
    print("가설: 모멘텀 지속성→노이즈 제거 + 심볼별 hold→SOL 극대화 + 레짐CD")
    print(f"기준선: c199 OOS +51.425 (BEST) / c217 OOS +37.362")
    print(f"c199 고정: rTh={REGIME_TH} hiTP={HI_TP_BONUS} "
          f"hiTr={HI_TRAIL_RELAX} loSL={LO_SL_TIGHTEN}")
    print(f"c192 고정: ttA={TRAIL_TIGHTEN_AFTER} ttF={TRAIL_TIGHTEN_FACTOR}")
    print(f"c190 고정: vMomLB={VOL_MOM_LB} vMomMin={VOL_MOM_MIN} "
          f"tpBonus={TP_SLOPE_BONUS}")
    print(f"c186 고정: body={BODY_RATIO_MIN} rsiD={RSI_DELTA_MIN} "
          f"sLB={EMA_SLOPE_LB} sPth={EMA_SLOPE_PCTILE_TH}")
    print(f"c182 고정: vPth={VOL_PCTILE_TH} vPLB={VOL_PCTILE_LB}")
    print(f"c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH}")
    print(f"c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE}"
          f" CD={COOLDOWN_BARS}")
    print(f"  dLB={RSI_DELTA_LB} SL={SL_BASE_ATR}-{SL_BONUS_ATR} "
          f"vMul={VOL_MULT}")
    print(f"  TP={TP_BASE_ATR}+{TP_BONUS_ATR} Trail={TRAIL_BASE_ATR}+"
          f"{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD}")
    print(f"  BB 고정: bbP={BB_PERIOD} bbS={BB_STD} "
          f"sqTh={SQUEEZE_PCTILE_TH} sqLB={SQUEEZE_LB} expB={EXPAND_BARS}")
    print(f"탐색: momP={MOM_PERSIST_LIST} rCD={REGIME_CD_MULT_LIST} "
          f"solH={SOL_HOLD_MULT_LIST} xrpH={XRP_HOLD_MULT_LIST} "
          f"mTP={MOM_TP_BONUS_LIST}")
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

            r = backtest(
                df_tr, sym,
                combo["mom_persist"], combo["regime_cd_mult"],
                get_sym_hold_mult(sym, combo),
                combo["mom_tp_bonus"],
                btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp, mom_pctile)
            sym_results.append(r)

        pooled = pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 30 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    print(f"  [{len(combos)}/{len(combos)}] 완료")

    valid = [r for r in results
             if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")

    print(f"\n=== Train Top 16 (pooled Sharpe 기준) ===")
    hdr = (f"{'mP':>3} {'rCD':>4} {'sH':>4} {'xH':>4} {'mTP':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} "
           f"{'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:16]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['mom_persist']:>3} {r['regime_cd_mult']:>4.1f} "
            f"{r['sol_hold_mult']:>4.1f} {r['xrp_hold_mult']:>4.1f} "
            f"{r['mom_tp_bonus']:>4.1f} | "
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
        key = (r["mom_persist"], r["regime_cd_mult"],
               r["sol_hold_mult"], r["xrp_hold_mult"],
               r["mom_tp_bonus"])
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

                r = backtest(
                    df_test, sym,
                    params["mom_persist"], params["regime_cd_mult"],
                    get_sym_hold_mult(sym, params),
                    params["mom_tp_bonus"],
                    btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp,
                    mom_pctile)
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
                f"  #{rank}: mP={params['mom_persist']} "
                f"rCD={params['regime_cd_mult']:.1f} "
                f"sH={params['sol_hold_mult']:.1f} "
                f"xH={params['xrp_hold_mult']:.1f} "
                f"mTP={params['mom_tp_bonus']:.1f} | "
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
    print(f"파라미터: mP={best['mom_persist']} rCD={best['regime_cd_mult']:.1f} "
          f"sH={best['sol_hold_mult']:.1f} xH={best['xrp_hold_mult']:.1f} "
          f"mTP={best['mom_tp_bonus']:.1f}")

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
                r = backtest(
                    df_test, sym,
                    best["mom_persist"], best["regime_cd_mult"],
                    get_sym_hold_mult(sym, best),
                    best["mom_tp_bonus"],
                    btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp,
                    mom_pctile, slippage=slip)
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
            r = backtest(
                df_test, sym,
                best["mom_persist"], best["regime_cd_mult"],
                get_sym_hold_mult(sym, best),
                best["mom_tp_bonus"],
                btc_c, btc_s, esp, vol_mom, atr_pctile, bb_wp, mom_pctile)
            if r["trades"] > 0 and not np.isnan(r["sharpe"]):
                sym_sharpes.append(r["sharpe"])
                sym_trades += r["trades"]
        avg_sym = float(np.mean(sym_sharpes)) if sym_sharpes else 0.0
        print(f"  {sym} 평균: Sharpe={avg_sym:+.3f}  총 trades={sym_trades}")

    # -- c199 베이스라인 대비 --
    print(f"\n{'=' * 80}")
    print("=== c199 베이스라인 대비 비교 ===")
    c199_baseline = 51.425
    c217_baseline = 37.362
    print(f"  c199 기준 (regime dual exit): avg_OOS={c199_baseline:+.3f}")
    print(f"  c217 기준 (score ablation): avg_OOS={c217_baseline:+.3f}")
    print(f"  c220 최적: avg_OOS={best['avg_oos']:+.3f}")
    delta199 = best["avg_oos"] - c199_baseline
    delta217 = best["avg_oos"] - c217_baseline
    label199 = "개선" if delta199 > 0 else "악화"
    label217 = "개선" if delta217 > 0 else "악화"
    print(f"  Δ vs c199: {delta199:+.3f} ({label199})")
    print(f"  Δ vs c217: {delta217:+.3f} ({label217})")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: mP={best['mom_persist']} "
          f"rCD={best['regime_cd_mult']:.1f} "
          f"sH={best['sol_hold_mult']:.1f} "
          f"xH={best['xrp_hold_mult']:.1f} "
          f"mTP={best['mom_tp_bonus']:.1f}")
    print(f"  (c199 고정: rTh={REGIME_TH} hiTP={HI_TP_BONUS} "
          f"hiTr={HI_TRAIL_RELAX} loSL={LO_SL_TIGHTEN})")
    print(f"  (c192 고정: ttA={TRAIL_TIGHTEN_AFTER} ttF={TRAIL_TIGHTEN_FACTOR})")
    print(f"  (c190 고정: vMomLB={VOL_MOM_LB} vMomMin={VOL_MOM_MIN} "
          f"tpBonus={TP_SLOPE_BONUS})")
    print(f"  (c186 고정: body={BODY_RATIO_MIN} rsiD={RSI_DELTA_MIN} "
          f"sLB={EMA_SLOPE_LB} sPth={EMA_SLOPE_PCTILE_TH})")
    print(f"  (c182 고정: vPth={VOL_PCTILE_TH} vPLB={VOL_PCTILE_LB})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH})")
    print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE}"
          f" CD={COOLDOWN_BARS})")
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
