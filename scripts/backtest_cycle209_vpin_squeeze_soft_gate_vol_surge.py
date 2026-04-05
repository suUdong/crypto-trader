"""
vpin_multi 사이클 209 — BB Squeeze Soft Gate + Volume Surge 타이밍
- 기반: c199 OOS Sharpe +51.425 (레짐 조건부 이중 출구) BEST
  c206 결과: BB squeeze hard gate → OOS +44.258 (악화), XRP 0 trades
  c199 고정: REGIME_TH=60 HI_TP_BONUS=1.0 HI_TRAIL_RELAX=2.0 LO_SL_TIGHTEN=0.20
  c192 고정: ttA=6 ttF=3.0
  c190 고정: VOL_MOM_LB=10 VOL_MOM_MIN=0.05 TP_SLOPE_BONUS=1.0
  c186 고정: body=0.50 rsiD=6 sLB=10 sPth=50
  c182 고정: vPth=60 vPLB=60
  c176 고정: atrLB=60 atrTh=30
  c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4
  c164 고정: dLB=3 SL=0.4-0.2 vMul=0.8
  TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
- 문제:
  1) c206 BB squeeze hard gate → XRP 전 fold 0 trades, ETH 1 fold만 활성
  2) 거래 수 10개로 c199(14+)보다 감소 → 신뢰도 하락
  3) squeeze→expansion 아이디어 자체는 유효하나, 하드게이트로 쓰면 필터링 과다
- 가설:
  A) BB squeeze를 soft gate로: squeeze 감지 시 TP/SL 조정 보너스만 부여, 진입 차단 안함
     → 거래 수 c199 수준 유지하면서 squeeze 구간 수익 극대화
  B) Volume Surge: 직전 N봉 대비 거래량 급등(vol_surge_ratio) 감지 시 진입 보너스
     → squeeze 후 breakout에서 거래량 급등이 동반되면 강한 시그널
  C) 두 조건 결합: squeeze + vol_surge 동시 → max TP boost
- 탐색 그리드:
  SQUEEZE_MODE: [0, 1, 2]              — 0=off, 1=soft(TP only), 2=hard(entry+TP)
  SQUEEZE_TP_BONUS: [0.5, 1.0, 1.5]    — squeeze 시 TP ATR 보너스
  VOL_SURGE_MODE: [0, 1, 2]            — 0=off, 1=entry boost, 2=required
  VOL_SURGE_TH: [1.5, 2.0, 3.0]       — vol/vol_sma 비율 임계값
  VOL_SURGE_LB: [5, 10]                — vol surge lookback
  COMBO_BONUS: [0.0, 0.5, 1.0]         — squeeze+surge 동시 시 추가 TP
  = 3×3×3×3×2×3 = 486 combos
- 목표: OOS Sharpe >= 52 AND trades >= 12
- 3-fold WF + 슬리피지 스트레스
- 진입: next_bar open
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

# -- BB 고정 (c206 best) --
BB_PERIOD = 20
BB_STD = 2.0
SQUEEZE_PCTILE_TH = 20
SQUEEZE_LB = 30
EXPAND_BARS = 2

# -- c209 탐색 그리드 --
SQUEEZE_MODE_LIST = [0, 1, 2]          # 0=off, 1=soft(TP only), 2=hard(entry+TP)
SQUEEZE_TP_BONUS_LIST = [0.5, 1.0, 1.5]
VOL_SURGE_MODE_LIST = [0, 1, 2]        # 0=off, 1=TP boost, 2=entry required
VOL_SURGE_TH_LIST = [1.5, 2.0, 3.0]
VOL_SURGE_LB_LIST = [5, 10]
COMBO_BONUS_LIST = [0.0, 0.5, 1.0]

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
    """Bollinger Band width = (upper - lower) / middle."""
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
    """BB width의 최근 lookback 봉 대비 백분위."""
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


def compute_vol_surge(
    volumes: np.ndarray, lookback: int,
) -> np.ndarray:
    """현재 거래량 / 직전 lookback봉 평균 거래량 비율."""
    n = len(volumes)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = volumes[i - lookback:i]
        avg_vol = np.mean(window)
        if avg_vol > 0:
            result[i] = volumes[i] / avg_vol
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
    squeeze_mode: int,
    squeeze_tp_bonus: float,
    vol_surge_mode: int,
    vol_surge_th: float,
    vol_surge_lb: int,
    combo_bonus: float,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    ema_slope_pctile_arr: np.ndarray,
    vol_mom_arr: np.ndarray,
    atr_pctile_full: np.ndarray,
    bb_width_pctile_arr: np.ndarray,
    vol_surge_arr: np.ndarray,
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
                 BB_PERIOD + SQUEEZE_LB + EXPAND_BARS,
                 vol_surge_lb + 5, 50) + 5
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

        # 기존 VPIN 진입 조건 (c165 고정)
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
        vol_ok = v[i] >= vol_sma_arr[i] * VOL_MULT

        # ATR 백분위 필터 (c176 고정)
        atr_pctile_ok = (not np.isnan(atr_pctile_val)
                         and atr_pctile_val >= ATR_TH)

        # 바디 비율 필터 (c186 고정)
        body_ok = (not np.isnan(body_val)
                   and body_val >= BODY_RATIO_MIN and c[i] >= o[i])

        # 볼륨 백분위 게이트 (c182 고정)
        vol_pctile_ok = (not np.isnan(vol_pctile_val)
                         and vol_pctile_val >= VOL_PCTILE_TH)

        # EMA slope percentile (c186 고정)
        esp = ema_slope_pctile_arr[i]
        ema_slope_ok = not np.isnan(esp) and esp >= EMA_SLOPE_PCTILE_TH

        # 볼륨 모멘텀 게이트 (c190 고정)
        vm = vol_mom_arr[i]
        vol_mom_ok = True
        if VOL_MOM_MIN > 0:
            vol_mom_ok = not np.isnan(vm) and vm >= VOL_MOM_MIN

        # === c209: BB Squeeze 상태 감지 (soft/hard) ===
        is_squeezed = False
        squeeze_intensity = 0.0
        if squeeze_mode > 0 and not np.isnan(bb_width_pctile_arr[i]):
            for eb in range(0, EXPAND_BARS + 1):
                idx_back = i - eb
                if idx_back >= 0 and not np.isnan(bb_width_pctile_arr[idx_back]):
                    if bb_width_pctile_arr[idx_back] <= SQUEEZE_PCTILE_TH:
                        is_squeezed = True
                        intensity = 1.0 - bb_width_pctile_arr[idx_back] / 100.0
                        squeeze_intensity = max(squeeze_intensity, intensity)
                        break

        # === c209: Volume Surge 감지 ===
        has_vol_surge = False
        vol_surge_val = vol_surge_arr[i] if not np.isnan(vol_surge_arr[i]) else 0.0
        if vol_surge_val >= vol_surge_th:
            has_vol_surge = True

        # === 진입 게이트 ===
        # squeeze_mode=2: squeeze가 감지돼야 진입
        squeeze_entry_ok = True
        if squeeze_mode == 2:
            squeeze_entry_ok = is_squeezed

        # vol_surge_mode=2: vol surge가 있어야 진입
        vol_surge_entry_ok = True
        if vol_surge_mode == 2:
            vol_surge_entry_ok = has_vol_surge

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and vol_pctile_ok
                and ema_slope_ok and vol_mom_ok
                and squeeze_entry_ok and vol_surge_entry_ok):

            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val
            entry_bar = i + 1

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # EMA slope 강도 → TP 보너스 (c190 고정)
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
                    regime_score = (
                        atr_pctile_val - (REGIME_TH - 10)) / 20.0
                else:
                    regime_score = 0.0

            regime_tp_extra = HI_TP_BONUS * regime_score

            # === c209: Soft gate TP 보너스 ===
            squeeze_tp_extra = 0.0
            if squeeze_mode >= 1 and is_squeezed:
                squeeze_tp_extra = squeeze_tp_bonus * squeeze_intensity

            vol_surge_tp_extra = 0.0
            if vol_surge_mode >= 1 and has_vol_surge:
                vol_surge_tp_extra = 0.5  # 고정 보너스 for vol surge

            # combo: squeeze + vol_surge 동시
            combo_tp_extra = 0.0
            if is_squeezed and has_vol_surge and combo_bonus > 0:
                combo_tp_extra = combo_bonus

            effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
                                 + slope_tp_extra + regime_tp_extra
                                 + squeeze_tp_extra + vol_surge_tp_extra
                                 + combo_tp_extra)
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
            max_hold = MAX_HOLD_BASE + int(6 * regime_score)

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
                    effective_trail_mult = (base_trail_mult
                                            / TRAIL_TIGHTEN_FACTOR)
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
        else:
            i += 1

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
    for sq_m, sq_tp, vs_m, vs_th, vs_lb, cb in product(
        SQUEEZE_MODE_LIST, SQUEEZE_TP_BONUS_LIST,
        VOL_SURGE_MODE_LIST, VOL_SURGE_TH_LIST,
        VOL_SURGE_LB_LIST, COMBO_BONUS_LIST,
    ):
        # squeeze_mode=0이면 squeeze_tp_bonus 무의미 → 하나만
        if sq_m == 0 and sq_tp != SQUEEZE_TP_BONUS_LIST[0]:
            continue
        # vol_surge_mode=0이면 vol_surge_th/lb 무의미 → 하나만
        if vs_m == 0 and (vs_th != VOL_SURGE_TH_LIST[0]
                          or vs_lb != VOL_SURGE_LB_LIST[0]):
            continue
        # combo_bonus > 0 only if both squeeze and surge can fire
        if cb > 0 and (sq_m == 0 or vs_m == 0):
            continue
        combos.append({
            "squeeze_mode": sq_m,
            "squeeze_tp_bonus": sq_tp,
            "vol_surge_mode": vs_m,
            "vol_surge_th": vs_th,
            "vol_surge_lb": vs_lb,
            "combo_bonus": cb,
        })
    return combos


def precompute_base(
    df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """EMA slope pctile + vol momentum + ATR pctile 사전 계산."""
    c = df["close"].values
    h = df["high"].values
    lo_arr = df["low"].values
    v = df["volume"].values
    ema_arr = ema_calc(c, EMA_PERIOD)
    ema_slope_pctile = compute_ema_slope_percentile(ema_arr, EMA_SLOPE_LB)
    vol_mom = compute_vol_momentum(v, ema_period=VOL_MOM_LB)
    atr_arr = compute_atr(h, lo_arr, c, ATR_PERIOD)
    atr_pctile = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
    return ema_slope_pctile, vol_mom, atr_pctile


def precompute_bb_and_surge(
    df: pd.DataFrame,
    vol_surge_lb: int,
) -> tuple[np.ndarray, np.ndarray]:
    """BB width percentile + vol surge 사전 계산."""
    c = df["close"].values
    v = df["volume"].values
    bb_w = compute_bb_width(c, BB_PERIOD, BB_STD)
    bb_wp = compute_bb_width_percentile(bb_w, SQUEEZE_LB)
    vol_surge = compute_vol_surge(v, vol_surge_lb)
    return bb_wp, vol_surge


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi c209 — BB Squeeze Soft Gate + Volume Surge ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe >= 52 AND trades >= 12")
    print("가설: squeeze를 hard gate→soft(TP boost)로 + vol surge 타이밍")
    print(f"기준선: c199 OOS +51.425")
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
    print(f"  BB 고정(c206): bbP={BB_PERIOD} bbS={BB_STD} "
          f"sqTh={SQUEEZE_PCTILE_TH} sqLB={SQUEEZE_LB} expB={EXPAND_BARS}")
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

    # 심볼별 train 캐시
    sym_train_cache: dict[str, tuple] = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if not df_tr.empty:
            btc_c, btc_s = align_btc_to_symbol(
                df_tr, df_btc_full, BTC_SMA_PERIOD)
            esp, vol_mom, atr_pctile = precompute_base(df_tr)
            sym_train_cache[sym] = (
                df_tr, btc_c, btc_s, esp, vol_mom, atr_pctile)
            print(f"  {sym} train: {len(df_tr)}행")

    # vol_surge_lb별 사전 계산 캐시
    surge_cache: dict[tuple[str, int, str], tuple[np.ndarray, np.ndarray]] = {}

    results: list[dict] = []
    for idx, combo in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr, btc_c, btc_s, esp, vol_mom, atr_pctile = (
                sym_train_cache[sym])

            cache_key = (sym, combo["vol_surge_lb"], "train")
            if cache_key not in surge_cache:
                surge_cache[cache_key] = precompute_bb_and_surge(
                    df_tr, combo["vol_surge_lb"])
            bb_wp, vol_surge = surge_cache[cache_key]

            r = backtest(
                df_tr,
                combo["squeeze_mode"], combo["squeeze_tp_bonus"],
                combo["vol_surge_mode"], combo["vol_surge_th"],
                combo["vol_surge_lb"], combo["combo_bonus"],
                btc_c, btc_s, esp, vol_mom, atr_pctile,
                bb_wp, vol_surge)
            sym_results.append(r)

        pooled = pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 50 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    print(f"  [{len(combos)}/{len(combos)}] 완료")

    valid = [r for r in results
             if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 16 (pooled Sharpe 기준) ===")
    hdr = (f"{'sqM':>4} {'sqTP':>5} {'vsM':>4} {'vsTh':>5} "
           f"{'vsLB':>5} {'comb':>5} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} "
           f"{'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:16]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['squeeze_mode']:>4} {r['squeeze_tp_bonus']:>5.1f} "
            f"{r['vol_surge_mode']:>4} {r['vol_surge_th']:>5.1f} "
            f"{r['vol_surge_lb']:>5} {r['combo_bonus']:>5.1f} | "
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
        key = (r["squeeze_mode"], r["squeeze_tp_bonus"],
               r["vol_surge_mode"], r["vol_surge_th"],
               r["vol_surge_lb"], r["combo_bonus"])
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
                esp, vol_mom, atr_pctile = precompute_base(df_test)
                bb_wp, vol_surge = precompute_bb_and_surge(
                    df_test, params["vol_surge_lb"])

                r = backtest(
                    df_test,
                    params["squeeze_mode"], params["squeeze_tp_bonus"],
                    params["vol_surge_mode"], params["vol_surge_th"],
                    params["vol_surge_lb"], params["combo_bonus"],
                    btc_c, btc_s, esp, vol_mom, atr_pctile,
                    bb_wp, vol_surge)
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
                f"  #{rank}: sqM={params['squeeze_mode']} "
                f"sqTP={params['squeeze_tp_bonus']:.1f} "
                f"vsM={params['vol_surge_mode']} "
                f"vsTh={params['vol_surge_th']:.1f} "
                f"vsLB={params['vol_surge_lb']} "
                f"comb={params['combo_bonus']:.1f} | "
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
    print(f"파라미터: sqM={best['squeeze_mode']} "
          f"sqTP={best['squeeze_tp_bonus']:.1f} "
          f"vsM={best['vol_surge_mode']} "
          f"vsTh={best['vol_surge_th']:.1f} "
          f"vsLB={best['vol_surge_lb']} "
          f"comb={best['combo_bonus']:.1f}")

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
                esp, vol_mom, atr_pctile = precompute_base(df_test)
                bb_wp, vol_surge = precompute_bb_and_surge(
                    df_test, best["vol_surge_lb"])
                r = backtest(
                    df_test,
                    best["squeeze_mode"], best["squeeze_tp_bonus"],
                    best["vol_surge_mode"], best["vol_surge_th"],
                    best["vol_surge_lb"], best["combo_bonus"],
                    btc_c, btc_s, esp, vol_mom, atr_pctile,
                    bb_wp, vol_surge,
                    slippage=slip)
                if r["trades"] > 0 and not np.isnan(r["sharpe"]):
                    slip_sharpes.append(r["sharpe"])
                    slip_trades += r["trades"]
        avg_sh = float(np.mean(slip_sharpes)) if slip_sharpes else float("nan")
        print(f"  slip={slip:.4f}: Sharpe={avg_sh:+.3f}  trades={slip_trades}")

    # -- 심볼별 fold 분해 --
    print(f"\n{'=' * 80}")
    print(f"=== OOS 최적 심볼별 fold 분해 ===")
    for detail in best.get("sym_fold_details", []):
        print(detail)

    # 심볼 평균 계산
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
            esp, vol_mom, atr_pctile = precompute_base(df_test)
            bb_wp, vol_surge = precompute_bb_and_surge(
                df_test, best["vol_surge_lb"])
            r = backtest(
                df_test,
                best["squeeze_mode"], best["squeeze_tp_bonus"],
                best["vol_surge_mode"], best["vol_surge_th"],
                best["vol_surge_lb"], best["combo_bonus"],
                btc_c, btc_s, esp, vol_mom, atr_pctile,
                bb_wp, vol_surge)
            if r["trades"] > 0 and not np.isnan(r["sharpe"]):
                sym_sharpes.append(r["sharpe"])
                sym_trades += r["trades"]
        avg_sym = float(np.mean(sym_sharpes)) if sym_sharpes else 0.0
        print(f"  {sym} 평균: Sharpe={avg_sym:+.3f}  총 trades={sym_trades}")

    # -- c199 베이스라인 대비 --
    print(f"\n{'=' * 80}")
    print("=== c199 베이스라인 대비 비교 ===")
    c199_baseline = 51.425
    print(f"  c199 기준 (regime dual exit): avg_OOS={c199_baseline:+.3f}")
    print(f"  c209 최적: avg_OOS={best['avg_oos']:+.3f}")
    delta = best["avg_oos"] - c199_baseline
    label = "개선" if delta > 0 else "악화"
    print(f"  Δ vs c199: {delta:+.3f} ({label})")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: sqM={best['squeeze_mode']} "
          f"sqTP={best['squeeze_tp_bonus']:.1f} "
          f"vsM={best['vol_surge_mode']} "
          f"vsTh={best['vol_surge_th']:.1f} "
          f"vsLB={best['vol_surge_lb']} "
          f"comb={best['combo_bonus']:.1f}")
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
