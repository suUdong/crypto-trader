"""
vpin_multi 사이클 199 — 레짐 조건부 이중 출구 (고변동 vs 저변동 분리)
- 기반: c192 OOS Sharpe +47.314 (time_decay_trail + ATR TP scale) 최고
  c192 고정: ttA=6, ttF=3.0, aTPS=0.5
  c190 고정: VOL_MOM_LB=10, VOL_MOM_MIN=0.05, TP_SLOPE_BONUS=1.0
  c186 고정: body=0.50 rsiD=6 sLB=10 sPth=50
  c182 고정: vPth=60 vPLB=60
  c176 고정: atrLB=60 atrTh=30
  c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4
  c164 고정: dLB=3 SL=0.4-0.2 vMul=0.8
  TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
- 문제:
  1) c192의 TP/Trail 파라미터가 단일 세트 → 고변동성 추세에서 조기 이탈, 저변동성에서 TP 미달
  2) c192 ATR TP scale이 TP만 조정 → Trail/SL/Hold도 레짐별 분리 필요
  3) c194에서 3단계 트레일이 발동 안 됨 → 레짐 전환점에서의 exit이 핵심
- 가설:
  A) ATR pctile >= REGIME_TH → 고변동성 레짐: TP 확대 + Trail 완화 + Hold 연장
     → 추세 지속 시 더 큰 수익 확보
  B) ATR pctile < REGIME_TH → 저변동성 레짐: TP 축소 + Trail 강화 + SL 축소
     → 빠른 수익 확정 + 손실 최소화
  C) 레짐 경계에서 선형 보간 → 급격한 전환 방지
- 탐색 그리드:
  REGIME_TH: [40, 50, 60]              — 고/저변동 경계 ATR 백분위
  HI_TP_BONUS: [1.0, 2.0, 3.0]        — 고변동 TP 추가 ATR 배수
  HI_TRAIL_RELAX: [1.0, 1.5, 2.0]     — 고변동 Trail 배수 확대 (×factor)
  LO_SL_TIGHTEN: [0.0, 0.1, 0.2]      — 저변동 SL 축소 ATR 배수
  = 3×3×3×3 = 81 combos
- 목표: OOS Sharpe >= 40 AND trades >= 18
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

# -- c199 탐색 그리드 --
REGIME_TH_LIST = [40, 50, 60]
HI_TP_BONUS_LIST = [1.0, 2.0, 3.0]
HI_TRAIL_RELAX_LIST = [1.0, 1.5, 2.0]
LO_SL_TIGHTEN_LIST = [0.0, 0.1, 0.2]

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
    atr = np.full(n, np.nan)
    if n < period:
        return atr
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


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
    regime_th: float,
    hi_tp_bonus: float,
    hi_trail_relax: float,
    lo_sl_tighten: float,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    ema_slope_pctile_arr: np.ndarray,
    vol_mom_arr: np.ndarray,
    atr_pctile_full: np.ndarray,
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
                 EMA_SLOPE_LB + 60, VOL_MOM_LB + 10, 50) + 5
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

        # 진입 조건: c165 고정
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
        vol_ok = v[i] >= vol_sma_val * VOL_MULT

        # ATR 백분위 필터 (c176 고정)
        atr_pctile_ok = True
        if np.isnan(atr_pctile_val):
            atr_pctile_ok = False
        else:
            atr_pctile_ok = atr_pctile_val >= ATR_TH

        # 바디 비율 필터 (c186 고정)
        body_ok = True
        if BODY_RATIO_MIN > 0:
            if np.isnan(body_val):
                body_ok = False
            else:
                body_ok = body_val >= BODY_RATIO_MIN and c[i] >= o[i]

        # 볼륨 백분위 게이트 (c182 고정)
        vol_pctile_ok = True
        if np.isnan(vol_pctile_val):
            vol_pctile_ok = False
        else:
            vol_pctile_ok = vol_pctile_val >= VOL_PCTILE_TH

        # EMA slope percentile (c186 고정)
        esp = ema_slope_pctile_arr[i]
        ema_slope_ok = True
        if np.isnan(esp):
            ema_slope_ok = False
        else:
            ema_slope_ok = esp >= EMA_SLOPE_PCTILE_TH

        # 볼륨 모멘텀 게이트 (c190 고정)
        vm = vol_mom_arr[i]
        vol_mom_ok = True
        if VOL_MOM_MIN > 0:
            if np.isnan(vm):
                vol_mom_ok = False
            else:
                vol_mom_ok = vm >= VOL_MOM_MIN

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and vol_pctile_ok
                and ema_slope_ok and vol_mom_ok):

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

            # === 신규 c199: 레짐 조건부 이중 출구 ===
            # ATR pctile 기반 레짐 판별 (진입 시점)
            regime_score = 0.0  # 0=저변동, 1=고변동
            if not np.isnan(atr_pctile_val):
                if atr_pctile_val >= regime_th + 10:
                    regime_score = 1.0
                elif atr_pctile_val >= regime_th - 10:
                    # 경계 구간: 선형 보간
                    regime_score = (atr_pctile_val - (regime_th - 10)) / 20.0
                else:
                    regime_score = 0.0

            # 고변동 레짐: TP 확대
            regime_tp_extra = hi_tp_bonus * regime_score

            effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
                                 + slope_tp_extra + regime_tp_extra)
            tp_price = buy + atr_at_entry * effective_tp_mult

            # 저변동 레짐: SL 축소
            sl_tighten = lo_sl_tighten * (1.0 - regime_score)
            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio - sl_tighten
            effective_sl_mult = max(0.15, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            # 기본 trail 파라미터 + 고변동 완화
            base_trail_mult = TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            trail_relax_factor = 1.0 + (hi_trail_relax - 1.0) * regime_score
            base_trail_mult *= trail_relax_factor

            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR

            # 고변동 레짐: Hold 연장 (최대 +6바)
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
                    effective_trail_mult = base_trail_mult / TRAIL_TIGHTEN_FACTOR
                else:
                    effective_trail_mult = base_trail_mult

                trail_dist = atr_at_entry * effective_trail_mult

                unrealized = peak_price - buy
                if unrealized >= min_profit_dist:
                    if peak_price - current_price >= trail_dist:
                        exit_ret = (current_price / buy - 1) - FEE - slippage
                        i = j
                        break

            if exit_ret is None:
                hold_end = min(i + max_hold, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)

            if exit_ret < 0:
                consecutive_losses += 1
                if consecutive_losses >= COOLDOWN_LOSSES and COOLDOWN_BARS > 0:
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
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
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
    for rth, hi_tp, hi_tr, lo_sl in product(
        REGIME_TH_LIST, HI_TP_BONUS_LIST,
        HI_TRAIL_RELAX_LIST, LO_SL_TIGHTEN_LIST,
    ):
        combos.append({
            "regime_th": rth,
            "hi_tp_bonus": hi_tp,
            "hi_trail_relax": hi_tr,
            "lo_sl_tighten": lo_sl,
        })
    return combos


def precompute_indicators(
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


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 199 — 레짐 조건부 이중 출구 ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe >= 40 AND trades >= 18")
    print("가설 A: 고변동 레짐 → TP 확대 + Trail 완화 + Hold 연장 (추세 라이딩)")
    print("가설 B: 저변동 레짐 → SL 축소 (빠른 손절 + 자본 보존)")
    print("가설 C: 레짐 경계 선형 보간 → 급격한 전환 방지")
    print(f"기준선: c192 OOS +47.314")
    print(f"c192 고정: ttA={TRAIL_TIGHTEN_AFTER} ttF={TRAIL_TIGHTEN_FACTOR}")
    print(f"c190 고정: vMomLB={VOL_MOM_LB} vMomMin={VOL_MOM_MIN} "
          f"tpBonus={TP_SLOPE_BONUS}")
    print(f"c186 고정: body={BODY_RATIO_MIN} rsiD={RSI_DELTA_MIN} "
          f"sLB={EMA_SLOPE_LB} sPth={EMA_SLOPE_PCTILE_TH}")
    print(f"c182 고정: vPth={VOL_PCTILE_TH} vPLB={VOL_PCTILE_LB}")
    print(f"c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH}")
    print(f"c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE} "
          f"CD={COOLDOWN_BARS}")
    print(f"  dLB={RSI_DELTA_LB} SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT}")
    print(f"  TP={TP_BASE_ATR}+{TP_BONUS_ATR} Trail={TRAIL_BASE_ATR}+"
          f"{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD}")
    print("=" * 80)

    # -- BTC 데이터 --
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
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
            btc_c, btc_s = align_btc_to_symbol(df_tr, df_btc_full, BTC_SMA_PERIOD)
            esp, vol_mom, atr_pctile = precompute_indicators(df_tr)
            sym_train_cache[sym] = (df_tr, btc_c, btc_s, esp, vol_mom, atr_pctile)
            print(f"  {sym} train: {len(df_tr)}행")

    results: list[dict] = []
    for idx, combo in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr, btc_c, btc_s, esp, vol_mom, atr_pctile = (
                sym_train_cache[sym])
            r = backtest(df_tr, combo["regime_th"], combo["hi_tp_bonus"],
                         combo["hi_trail_relax"], combo["lo_sl_tighten"],
                         btc_c, btc_s, esp, vol_mom, atr_pctile)
            sym_results.append(r)

        pooled = pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 27 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    valid = [r for r in results if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 16 (pooled Sharpe 기준) ===")
    hdr = (f"{'rTh':>4} {'hiTP':>5} {'hiTr':>5} {'loSL':>5} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} "
           f"{'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:16]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['regime_th']:>4} {r['hi_tp_bonus']:>5.1f} "
            f"{r['hi_trail_relax']:>5.1f} {r['lo_sl_tighten']:>5.2f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

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
        key = (r["regime_th"], r["hi_tp_bonus"],
               r["hi_trail_relax"], r["lo_sl_tighten"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 12:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(unique_top)} 고유) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        rth = params["regime_th"]
        hi_tp = params["hi_tp_bonus"]
        hi_tr = params["hi_trail_relax"]
        lo_sl = params["lo_sl_tighten"]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []

        for fold_i, fold in enumerate(WF_FOLDS):
            sym_fold_results = []
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                esp, vol_mom, atr_pctile = precompute_indicators(df_test)
                r = backtest(df_test, rth, hi_tp, hi_tr, lo_sl,
                             btc_c, btc_s, esp, vol_mom, atr_pctile)
                sym_fold_results.append(r)

            pooled = pool_results(sym_fold_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(pooled["trades"])
            fold_details.append(pooled)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            total_oos_n = sum(oos_trades)
            all_pass = all(s >= 3.0 for s in oos_sharpes) and avg_oos >= 5.0
            print(f"  #{rank}: rTh={rth} hiTP={hi_tp:.1f} "
                  f"hiTr={hi_tr:.1f} loSL={lo_sl:.2f} | "
                  f"train={params['sharpe']:+.3f} -> avg_OOS={avg_oos:+.3f} "
                  f"min_OOS={min_oos:+.3f} n={total_oos_n} "
                  f"{'PASS' if all_pass else 'FAIL'}")
            wf_results.append({
                **params,
                "train_sharpe": params["sharpe"],
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "total_oos_trades": total_oos_n,
                "all_pass": all_pass,
                "fold_details": fold_details,
            })

    if not wf_results:
        print("\nWF 검증 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 3: 슬리피지 스트레스 (OOS Top 3) --
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                       reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS Top 3, 전 심볼 풀링) ===")

    for rank, params in enumerate(wf_top3, 1):
        rth = params["regime_th"]
        hi_tp = params["hi_tp_bonus"]
        hi_tr = params["hi_trail_relax"]
        lo_sl = params["lo_sl_tighten"]
        print(f"\n--- #{rank}: rTh={rth} hiTP={hi_tp:.1f} "
              f"hiTr={hi_tr:.1f} loSL={lo_sl:.2f} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            sym_results = []
            for sym in sym_data_ok:
                df_full = load_historical(sym, "240m", "2022-01-01", "2026-12-31")
                if df_full.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_full, df_btc_full, BTC_SMA_PERIOD)
                esp, vol_mom, atr_pctile = precompute_indicators(df_full)
                r = backtest(df_full, rth, hi_tp, hi_tr, lo_sl,
                             btc_c, btc_s, esp, vol_mom, atr_pctile,
                             slippage=slip)
                sym_results.append(r)
            pooled = pool_results(sym_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {pooled['wr']:>5.1%} "
                  f"{pooled['avg_ret'] * 100:>+6.2f}% "
                  f"{pooled['max_dd'] * 100:>+6.2f}% "
                  f"{pooled['mcl']:>4} {pooled['trades']:>5}")

    # -- 심볼별 성능 분해 (Top 1) --
    best = wf_sorted[0]
    rth = best["regime_th"]
    hi_tp = best["hi_tp_bonus"]
    hi_tr = best["hi_trail_relax"]
    lo_sl = best["lo_sl_tighten"]

    print(f"\n{'=' * 80}")
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: rTh={rth} "
          f"hiTP={hi_tp:.1f} hiTr={hi_tr:.1f} loSL={lo_sl:.2f}) ===")
    for sym in sym_data_ok:
        sym_oos_sharpes = []
        sym_oos_trades = 0
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(sym, "240m",
                                      fold["test"][0], fold["test"][1])
            if df_test.empty:
                continue
            btc_c, btc_s = align_btc_to_symbol(
                df_test, df_btc_full, BTC_SMA_PERIOD)
            esp, vol_mom, atr_pctile = precompute_indicators(df_test)
            r = backtest(df_test, rth, hi_tp, hi_tr, lo_sl,
                         btc_c, btc_s, esp, vol_mom, atr_pctile)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            sym_oos_sharpes.append(sh)
            sym_oos_trades += r["trades"]
            print(f"  {sym} Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  "
                  f"MDD={r['max_dd'] * 100:+.2f}%")
        if sym_oos_sharpes:
            avg_sh = float(np.mean(sym_oos_sharpes))
            print(f"  {sym} 평균: Sharpe={avg_sh:+.3f}  "
                  f"총 trades={sym_oos_trades}")
        print()

    # -- c192 대비 비교 --
    print(f"{'=' * 80}")
    print("=== c192 베이스라인 대비 비교 ===")
    print(f"  c192 최적 (ttA=6 ttF=3.0 aTPS=0.5): "
          f"avg_OOS=+47.314 n=~20")
    print(f"  c199 최적 (rTh={best['regime_th']} "
          f"hiTP={best['hi_tp_bonus']:.1f} "
          f"hiTr={best['hi_trail_relax']:.1f} "
          f"loSL={best['lo_sl_tighten']:.2f}): "
          f"avg_OOS={best['avg_oos_sharpe']:+.3f} "
          f"n={best['total_oos_trades']}")
    delta_sh = best["avg_oos_sharpe"] - 47.314
    delta_n = best["total_oos_trades"] - 20
    print(f"  Δ Sharpe: {delta_sh:+.3f} "
          f"({'개선' if delta_sh > 0 else '악화' if delta_sh < 0 else '동일'})")
    print(f"  Δ trades: {delta_n:+d} "
          f"({'증가' if delta_n > 0 else '감소' if delta_n < 0 else '동일'})")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: REGIME_TH={best['regime_th']} "
          f"HI_TP_BONUS={best['hi_tp_bonus']:.1f} "
          f"HI_TRAIL_RELAX={best['hi_trail_relax']:.1f} "
          f"LO_SL_TIGHTEN={best['lo_sl_tighten']:.2f}")
    print(f"  (c192 고정: ttA={TRAIL_TIGHTEN_AFTER} ttF={TRAIL_TIGHTEN_FACTOR})")
    print(f"  (c190 고정: vMomLB={VOL_MOM_LB} vMomMin={VOL_MOM_MIN} "
          f"tpBonus={TP_SLOPE_BONUS})")
    print(f"  (c186 고정: body={BODY_RATIO_MIN} rsiD={RSI_DELTA_MIN} "
          f"sLB={EMA_SLOPE_LB} sPth={EMA_SLOPE_PCTILE_TH})")
    print(f"  (c182 고정: vPth={VOL_PCTILE_TH} vPLB={VOL_PCTILE_LB})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH})")
    print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE} "
          f"CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} "
          f"BTC_SMA={BTC_SMA_PERIOD})")
    oos_avg = best["avg_oos_sharpe"]
    total_n = best["total_oos_trades"]
    status = "PASS" if best["all_pass"] else "FAIL"
    print(f"  avg OOS Sharpe: {oos_avg:+.3f} {status}")
    print(f"  train Sharpe: {best['train_sharpe']:+.3f}")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={best['oos_trades'][fi]}  "
              f"avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))

    print(f"\nSharpe: {oos_avg:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
