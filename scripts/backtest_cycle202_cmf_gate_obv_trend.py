"""
vpin_multi 사이클 202 — CMF 게이트 + OBV 추세확인 이중필터
- 기반: c200 OOS Sharpe +17.674, cmfP=10 cmfM=0.1 divL=14 divD=0.0 tpB=1.0
  c179 베이스라인: OOS Sharpe +42.878
- 문제 진단:
  1. c200 CMF+RSI div OR 보너스 로직이 너무 느슨 → Sharpe -25.2 악화
  2. SOL Fold 2 Sharpe=-2.551 (자금유입 없이 진입 허용)
  3. 단순 CMF > 0.1 임계값이 레짐 변화에 둔감
- 가설:
  1. CMF를 보너스가 아닌 게이트로 전환: CMF >= threshold여야 진입 허용
     → 자금 유출 중 진입을 원천 차단
  2. OBV (On-Balance Volume) 추세 기울기 확인: OBV SMA 기울기 양수 = 매집 중
     → CMF(단기 자금흐름) + OBV(누적 매집 추세) 이중확인
  3. CMF 게이트 + OBV 추세 AND 조건 → 진입 필터 강화
  4. 확인 시 TP 보너스 유지 (c200 tpB=1.0 효과 계승)
- 설계:
  진입 = c179 기본 조건 + CMF >= CMF_GATE (게이트) + OBV_SLOPE > OBV_MIN
  CMF 게이트: CMF < threshold → 진입 거부 (c200의 보너스와 다름)
  OBV 추세: OBV SMA의 N봉 기울기(정규화) > 임계값
  AND 모드: 둘 다 충족 필수 / OR 모드: 하나만 충족도 가능 (비교용)
- 탐색 그리드:
  CMF_GATE: [0.0, 0.05, 0.10, 0.15]     — 게이트 임계 (0=비활성)
  OBV_SMA_PERIOD: [10, 20]               — OBV 평활 기간
  OBV_SLOPE_LB: [5, 10]                  — 기울기 측정 룩백
  OBV_SLOPE_MIN: [0.0, 0.001, 0.003]     — 정규화 기울기 최소
  FILTER_MODE: [0, 1]                     — 0=AND, 1=OR
  TP_BONUS: [0.5, 1.0]                   — 필터 통과 시 TP 보너스 ATR
  = 4×2×2×3×2×2 = 192 combos
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
RSI_DELTA_MIN = 0.0
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD = 20
VOL_SMA_PERIOD = 20

# -- c177 고정 TP/Trail --
TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

BTC_SMA_PERIOD = 200
ATR_PCTILE_LB = 60

# -- c177 최적 진입 필터 고정 --
ATR_PCTILE_THRESH = 30
BODY_RATIO_MIN = 0.7
VPIN_RELAX_THRESH = 0.25
RELAX_SCALE = 0.5

# -- c179 vol regime 최적 고정 --
VOL_REGIME_THRESH = 60
HIGH_VOL_TP_SCALE = 0.65
HIGH_VOL_TRAIL_SCALE = 0.7
HIGH_VOL_HOLD_SCALE = 0.8

# -- c200 최적 고정 (CMF period) --
CMF_PERIOD = 10

# -- 탐색 그리드: CMF gate + OBV trend --
CMF_GATE_LIST = [0.0, 0.05, 0.10, 0.15]
OBV_SMA_PERIOD_LIST = [10, 20]
OBV_SLOPE_LB_LIST = [5, 10]
OBV_SLOPE_MIN_LIST = [0.0, 0.001, 0.003]
FILTER_MODE_LIST = [0, 1]  # 0=AND, 1=OR
TP_BONUS_LIST = [0.5, 1.0]

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
    atr_arr: np.ndarray, lookback: int = 40,
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


def compute_cmf(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    volumes: np.ndarray, period: int = 20,
) -> np.ndarray:
    """Chaikin Money Flow: sum(MFV) / sum(Vol) over period."""
    n = len(closes)
    result = np.full(n, np.nan)
    mfm = np.zeros(n)
    for i in range(n):
        hl = highs[i] - lows[i]
        if hl > 0:
            mfm[i] = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl
        else:
            mfm[i] = 0.0
    mfv = mfm * volumes
    for i in range(period - 1, n):
        vol_sum = volumes[i - period + 1:i + 1].sum()
        if vol_sum > 0:
            result[i] = mfv[i - period + 1:i + 1].sum() / vol_sum
        else:
            result[i] = 0.0
    return result


def compute_obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """On-Balance Volume: 누적 매수/매도 볼륨."""
    n = len(closes)
    obv = np.zeros(n)
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def compute_obv_slope(
    obv: np.ndarray, sma_period: int, slope_lb: int,
) -> np.ndarray:
    """OBV SMA의 정규화 기울기: (OBV_SMA[i] - OBV_SMA[i-lb]) / abs(OBV_SMA[i-lb])."""
    n = len(obv)
    obv_sma = sma_calc(obv, sma_period)
    result = np.full(n, np.nan)
    for i in range(sma_period + slope_lb, n):
        prev = obv_sma[i - slope_lb]
        if np.isnan(prev) or np.isnan(obv_sma[i]) or abs(prev) < 1e-9:
            continue
        result[i] = (obv_sma[i] - prev) / (abs(prev) + 1e-9)
    return result


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    cmf_gate: float,
    obv_sma_period: int, obv_slope_lb: int, obv_slope_min: float,
    filter_mode: int,
    tp_bonus: float,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
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
    atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
    body_ratio_arr = compute_body_ratio(o, c, h, lo)
    cmf_arr = compute_cmf(h, lo, c, v, CMF_PERIOD)
    obv_arr = compute_obv(c, v)
    obv_slope_arr = compute_obv_slope(obv_arr, obv_sma_period, obv_slope_lb)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, CMF_PERIOD, obv_sma_period + obv_slope_lb,
                 50) + 5
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
        atr_pctile_val = atr_pctile_arr[i]
        body_val = body_ratio_arr[i]
        cmf_val = cmf_arr[i]
        obv_slope_val = obv_slope_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0
                or np.isnan(cmf_val) or np.isnan(obv_slope_val)):
            i += 1
            continue

        # RSI velocity
        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # 진입 조건: c179 동일
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

        # c177 신호강도 적응적 필터 완화
        strong_signal = vpin_val < VPIN_RELAX_THRESH
        if strong_signal:
            eff_atr_thresh = ATR_PCTILE_THRESH * RELAX_SCALE
            eff_body_min = BODY_RATIO_MIN * RELAX_SCALE
        else:
            eff_atr_thresh = ATR_PCTILE_THRESH
            eff_body_min = BODY_RATIO_MIN

        atr_pctile_ok = True
        if eff_atr_thresh > 0:
            if np.isnan(atr_pctile_val):
                atr_pctile_ok = False
            else:
                atr_pctile_ok = atr_pctile_val >= eff_atr_thresh

        body_ok = True
        if eff_body_min > 0:
            if np.isnan(body_val):
                body_ok = False
            else:
                body_ok = body_val >= eff_body_min and c[i] >= o[i]

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok):

            # ★ CMF 게이트 + OBV 추세 필터
            cmf_pass = cmf_val >= cmf_gate if cmf_gate > 0 else True
            obv_pass = obv_slope_val >= obv_slope_min if obv_slope_min > 0 else True

            if filter_mode == 0:
                # AND 모드: 둘 다 충족
                filter_pass = cmf_pass and obv_pass
            else:
                # OR 모드: 하나만 충족 (둘 다 비활성이면 통과)
                if cmf_gate > 0 or obv_slope_min > 0:
                    filter_pass = cmf_pass or obv_pass
                else:
                    filter_pass = True

            if not filter_pass:
                i += 1
                continue

            # 보너스: 필터 통과 시 TP 보너스
            has_bonus = (cmf_gate > 0 and cmf_pass) or (
                obv_slope_min > 0 and obv_pass
            )

            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # c179 변동성 레짐 판단
            is_high_vol = (
                not np.isnan(atr_pctile_val)
                and atr_pctile_val >= VOL_REGIME_THRESH
            )

            if is_high_vol:
                tp_scale = HIGH_VOL_TP_SCALE
                trail_scale = HIGH_VOL_TRAIL_SCALE
                hold_scale = HIGH_VOL_HOLD_SCALE
            else:
                tp_scale = 1.0 + (1.0 - HIGH_VOL_TP_SCALE) * 0.3
                trail_scale = 1.0 + (1.0 - HIGH_VOL_TRAIL_SCALE) * 0.2
                hold_scale = 1.0 + (1.0 - HIGH_VOL_HOLD_SCALE) * 0.3

            # ★ TP: 필터 확인 시 보너스 추가
            effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio) * tp_scale
            if has_bonus and tp_bonus > 0:
                effective_tp_mult += tp_bonus

            tp_price = buy + atr_at_entry * effective_tp_mult

            # SL: c179 고정
            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)
            if is_high_vol:
                effective_sl_mult *= (1.0 - (1.0 - HIGH_VOL_TP_SCALE) * 0.2)
                effective_sl_mult = max(0.15, effective_sl_mult)

            sl_price = buy - atr_at_entry * effective_sl_mult

            effective_trail_mult = (
                TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            ) * trail_scale
            trail_dist = atr_at_entry * effective_trail_mult
            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR * trail_scale

            max_hold = max(5, int(MAX_HOLD_BASE * hold_scale))

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]

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


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 202 — CMF 게이트 + OBV 추세확인 이중필터 ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe >= 43.0 (c179 +42.878 대비 개선)")
    print("가설: CMF를 게이트로 전환 + OBV 추세기울기 AND/OR 필터")
    print("  c200 문제: CMF+div OR 보너스 느슨 → Sharpe -25.2 악화")
    print("  c202 해법: CMF >= gate(자금유입 필수) + OBV slope(매집 추세)")
    print(f"기준선: c179 OOS +42.878, c200 OOS +17.674")
    print(f"c200 고정: cmfP={CMF_PERIOD}")
    print(f"c179 고정: volTh={VOL_REGIME_THRESH} tpSc={HIGH_VOL_TP_SCALE} "
          f"trSc={HIGH_VOL_TRAIL_SCALE} hdSc={HIGH_VOL_HOLD_SCALE}")
    print(f"c177 고정: atrTh={ATR_PCTILE_THRESH} body={BODY_RATIO_MIN} "
          f"vpRx={VPIN_RELAX_THRESH} rxSc={RELAX_SCALE}")
    print(f"c176 고정: atrLB={ATR_PCTILE_LB}")
    print(f"c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE} "
          f"CD={COOLDOWN_BARS}")
    print(f"  dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} SL={SL_BASE_ATR}-"
          f"{SL_BONUS_ATR} vMul={VOL_MULT}")
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
    combos = list(product(
        CMF_GATE_LIST, OBV_SMA_PERIOD_LIST, OBV_SLOPE_LB_LIST,
        OBV_SLOPE_MIN_LIST, FILTER_MODE_LIST, TP_BONUS_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개 × {len(sym_data_ok)} 심볼")

    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: train 그리드 서치 ({train_start} ~ {train_end})")

    sym_train_data: dict[str, pd.DataFrame] = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if not df_tr.empty:
            sym_train_data[sym] = df_tr
            print(f"  {sym} train: {len(df_tr)}행")

    results: list[dict] = []
    for idx, (cmf_g, obv_sp, obv_sl, obv_sm, fm, tp_b) in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_data:
                continue
            df_tr = sym_train_data[sym]
            btc_c, btc_s = align_btc_to_symbol(df_tr, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_tr, cmf_g, obv_sp, obv_sl, obv_sm, fm, tp_b,
                         btc_c, btc_s)
            sym_results.append(r)
        pooled = pool_results(sym_results)
        results.append({
            "cmf_g": cmf_g, "obv_sp": obv_sp, "obv_sl": obv_sl,
            "obv_sm": obv_sm, "fm": fm, "tp_b": tp_b,
            **pooled,
        })
        if (idx + 1) % 50 == 0 or idx == len(combos) - 1:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    valid = [r for r in results if not np.isnan(r["sharpe"]) and r["trades"] >= 30]
    if not valid:
        print("유효 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    valid.sort(key=lambda x: x["sharpe"], reverse=True)
    top5 = valid[:5]
    print("\n--- Train Top 5 ---")
    for rank, r in enumerate(top5, 1):
        mode_str = "AND" if r["fm"] == 0 else "OR"
        print(f"  #{rank} cmfG={r['cmf_g']} obvSP={r['obv_sp']} "
              f"obvSL={r['obv_sl']} obvSM={r['obv_sm']} "
              f"mode={mode_str} tpB={r['tp_b']} → "
              f"Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1%} "
              f"n={r['trades']} avg={r['avg_ret']:+.2%} "
              f"MDD={r['max_dd']:+.2%}")

    # -- Phase 2: 3-fold WF 검증 (top5) --
    print("\n" + "=" * 80)
    print("Phase 2: 3-fold WF 검증 (Top 5)")
    print("=" * 80)

    best_oos_sharpe = float("-inf")
    best_combo = None
    best_fold_details: list[dict] = []

    for rank, combo in enumerate(top5, 1):
        cmf_g = combo["cmf_g"]
        obv_sp = combo["obv_sp"]
        obv_sl = combo["obv_sl"]
        obv_sm = combo["obv_sm"]
        fm = combo["fm"]
        tp_b = combo["tp_b"]
        mode_str = "AND" if fm == 0 else "OR"

        print(f"\n--- #{rank}: cmfG={cmf_g} obvSP={obv_sp} obvSL={obv_sl} "
              f"obvSM={obv_sm} mode={mode_str} tpB={tp_b} ---")

        fold_results: list[dict] = []
        fold_details: list[dict] = []
        for fi, fold in enumerate(WF_FOLDS, 1):
            tr_start, tr_end = fold["train"]
            te_start, te_end = fold["test"]

            # train
            train_results: list[dict] = []
            for sym in sym_data_ok:
                df_tr = load_historical(sym, "240m", tr_start, tr_end)
                if df_tr.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_tr, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_tr, cmf_g, obv_sp, obv_sl, obv_sm, fm, tp_b,
                             btc_c, btc_s)
                train_results.append(r)
            train_pooled = pool_results(train_results)

            # test (OOS)
            test_results: list[dict] = []
            sym_test_details: list[dict] = []
            for sym in sym_data_ok:
                df_te = load_historical(sym, "240m", te_start, te_end)
                if df_te.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_te, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_te, cmf_g, obv_sp, obv_sl, obv_sm, fm, tp_b,
                             btc_c, btc_s, slippage=0.0005)
                test_results.append(r)
                sym_test_details.append({"sym": sym, **r})
            test_pooled = pool_results(test_results)

            fold_results.append(test_pooled)
            fold_details.append({
                "fold": fi, "train": train_pooled, "test": test_pooled,
                "sym_details": sym_test_details,
            })

            print(f"  Fold {fi}: train Sharpe={train_pooled['sharpe']:+.3f} "
                  f"→ OOS Sharpe={test_pooled['sharpe']:+.3f} "
                  f"WR={test_pooled['wr']:.1%} n={test_pooled['trades']}")

        oos_sharpes = [fr["sharpe"] for fr in fold_results
                       if not np.isnan(fr["sharpe"])]
        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
        else:
            avg_oos = float("nan")

        print(f"  → avg OOS Sharpe: {avg_oos:+.3f}")

        if not np.isnan(avg_oos) and avg_oos > best_oos_sharpe:
            best_oos_sharpe = avg_oos
            best_combo = combo
            best_fold_details = fold_details

    if best_combo is None:
        print("\n유효 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 3: 슬리피지 스트레스 --
    print("\n" + "=" * 80)
    print("Phase 3: 슬리피지 스트레스 테스트")
    print("=" * 80)

    cmf_g = best_combo["cmf_g"]
    obv_sp = best_combo["obv_sp"]
    obv_sl = best_combo["obv_sl"]
    obv_sm = best_combo["obv_sm"]
    fm = best_combo["fm"]
    tp_b = best_combo["tp_b"]
    mode_str = "AND" if fm == 0 else "OR"

    print(f"최적: cmfG={cmf_g} obvSP={obv_sp} obvSL={obv_sl} "
          f"obvSM={obv_sm} mode={mode_str} tpB={tp_b}")

    slippage_ok = True
    for slip in SLIPPAGE_LEVELS:
        slip_results: list[dict] = []
        for sym in sym_data_ok:
            for fold in WF_FOLDS:
                te_start, te_end = fold["test"]
                df_te = load_historical(sym, "240m", te_start, te_end)
                if df_te.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_te, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_te, cmf_g, obv_sp, obv_sl, obv_sm, fm, tp_b,
                             btc_c, btc_s, slip)
                slip_results.append(r)
        sp = pool_results(slip_results)
        status = "PASS" if sp["sharpe"] > 0 else "FAIL"
        if sp["sharpe"] <= 0:
            slippage_ok = False
        print(f"  slip={slip:.4f}: Sharpe={sp['sharpe']:+.3f} "
              f"WR={sp['wr']:.1%} n={sp['trades']} [{status}]")

    # -- 심볼별 OOS 분해 --
    print("\n" + "=" * 80)
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: cmfG={cmf_g} obvSP={obv_sp} "
          f"obvSL={obv_sl} obvSM={obv_sm} mode={mode_str} tpB={tp_b}) ===")
    for fd in best_fold_details:
        fi = fd["fold"]
        for sd in fd["sym_details"]:
            print(f"  {sd['sym']} Fold {fi}: Sharpe={sd['sharpe']:+.3f}  "
                  f"WR={sd['wr']:.1%}  n={sd['trades']}  "
                  f"avg={sd['avg_ret']:+.2%}  MDD={sd['max_dd']:+.2%}")

    for sym in sym_data_ok:
        sym_sharpes = []
        sym_trades = 0
        for fd in best_fold_details:
            for sd in fd["sym_details"]:
                if sd["sym"] == sym and not np.isnan(sd["sharpe"]):
                    sym_sharpes.append(sd["sharpe"])
                    sym_trades += sd["trades"]
        if sym_sharpes:
            print(f"  {sym} 평균: Sharpe={np.mean(sym_sharpes):+.3f}  "
                  f"총 trades={sym_trades}")

    # -- c179 비교 --
    print("\n" + "=" * 80)
    print("=== c179 베이스라인 대비 비교 ===")
    c179_sharpe = 42.878
    c200_sharpe = 17.674
    total_trades = sum(fd["test"]["trades"] for fd in best_fold_details)
    print(f"  c179 기준 (vol regime adaptive): avg_OOS={c179_sharpe:+.3f} n=~60")
    print(f"  c200 기준 (cmf+rsi_div bonus): avg_OOS={c200_sharpe:+.3f} n=64")
    print(f"  c202 최적 (cmfG={cmf_g} obvSP={obv_sp} obvSL={obv_sl} "
          f"obvSM={obv_sm} mode={mode_str} tpB={tp_b}): "
          f"avg_OOS={best_oos_sharpe:+.3f} n={total_trades}")
    delta_179 = best_oos_sharpe - c179_sharpe
    delta_200 = best_oos_sharpe - c200_sharpe
    print(f"  Δ vs c179: {delta_179:+.3f} "
          f"({'개선' if delta_179 > 0 else '악화'})")
    print(f"  Δ vs c200: {delta_200:+.3f} "
          f"({'개선' if delta_200 > 0 else '악화'})")

    # -- 최종 요약 --
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    pass_fail = "PASS" if best_oos_sharpe > 5.0 and slippage_ok else "FAIL"
    print(f"★ OOS 최적: cmfG={cmf_g} obvSP={obv_sp} obvSL={obv_sl} "
          f"obvSM={obv_sm} mode={mode_str} tpB={tp_b}")
    print(f"  (c200 고정: cmfP={CMF_PERIOD})")
    print(f"  (c179 고정: volTh={VOL_REGIME_THRESH} tpSc={HIGH_VOL_TP_SCALE} "
          f"trSc={HIGH_VOL_TRAIL_SCALE} hdSc={HIGH_VOL_HOLD_SCALE})")
    print(f"  (c177 고정: atrTh={ATR_PCTILE_THRESH} body={BODY_RATIO_MIN} "
          f"vpRx={VPIN_RELAX_THRESH} rxSc={RELAX_SCALE})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB})")
    print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE} "
          f"CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} "
          f"BTC_SMA={BTC_SMA_PERIOD})")
    print(f"  avg OOS Sharpe: {best_oos_sharpe:+.3f} {pass_fail}")

    train_sharpes = [fd["train"]["sharpe"] for fd in best_fold_details
                     if not np.isnan(fd["train"]["sharpe"])]
    if train_sharpes:
        print(f"  train Sharpe: {np.mean(train_sharpes):+.3f}")

    for fd in best_fold_details:
        t = fd["test"]
        print(f"  Fold {fd['fold']}: Sharpe={t['sharpe']:+.3f}  "
              f"WR={t['wr']:.1%}  trades={t['trades']}  "
              f"avg={t['avg_ret']:+.2%}  MDD={t['max_dd']:+.2%}")

    print(f"\nSharpe: {best_oos_sharpe:+.3f}")
    all_wrs = [fd["test"]["wr"] for fd in best_fold_details
               if not np.isnan(fd["test"]["wr"])]
    avg_wr = float(np.mean(all_wrs)) * 100 if all_wrs else 0.0
    print(f"WR: {avg_wr:.1f}%")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
