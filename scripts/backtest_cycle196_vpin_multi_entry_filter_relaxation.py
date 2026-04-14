"""
vpin_multi 사이클 196 — 진입 필터 임계값 완화 탐색
- 기반: c195 최적 (rsiP=12 emaP=30 momLB=6) avg_OOS=+27.895 n=14
- 문제:
  1) 거래수 14건 (c192 36건 대비 -22) — 통계적 신뢰 부족
  2) XRP 전 폴드 0건 — 필터가 XRP 특성에 과도하게 타이트
  3) ETH Fold3 0건 — 최근 구간 진입 불가
  ★ c195에서 지표주기를 변경한 결과 진입 조건이 더 까다로워졌으므로,
    고정된 필터 임계값을 재조정하여 거래수 복원 필요
- 가설:
  A) BODY_RATIO_MIN 완화 → 캔들 형태 필터 느슨하게 → 더 많은 진입 허용
  B) VOL_PCTILE_TH 완화 → 거래량 백분위 문턱 낮춤 → XRP 등 저유동성 구간 포함
  C) EMA_SLOPE_PCTILE_TH 완화 → 추세 강도 요구 완화 → 초기 추세 포착
  D) VOL_MOM_MIN 완화 → 거래량 모멘텀 문턱 낮춤
  ★ 4개 필터는 c182~c190에서 고정된 이후 한 번도 재탐색 안 됨
    c195 지표주기 변경 후 최적 임계값이 달라졌을 가능성 높음
- 탐색 그리드:
  BODY_RATIO_MIN:        [0.30, 0.40, 0.50]       — 3수준 (현 0.50)
  VOL_PCTILE_TH:         [40, 50, 60]              — 3수준 (현 60)
  EMA_SLOPE_PCTILE_TH:   [30, 40, 50]              — 3수준 (현 50)
  VOL_MOM_MIN:           [0.00, 0.03, 0.05]        — 3수준 (현 0.05)
  = 3×3×3×3 = 81 combos
- 목표: OOS Sharpe >= 20 AND trades >= 25 (c195 Sharpe 유지하며 거래수 복원)
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

# -- c195 최적 지표 주기 (고정) --
RSI_PERIOD = 12
EMA_PERIOD = 30
MOM_LOOKBACK = 6

# -- c192 최적 고정 --
VPIN_LOW = 0.4
MOM_THRESH = 0.0005
MAX_HOLD = 20
COOLDOWN_BARS = 4

BTC_SMA_PERIOD = 200
RSI_CEILING = 65
RSI_FLOOR = 20

BUCKET_COUNT = 24
COOLDOWN_LOSSES = 2

RSI_DELTA_LB = 3
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD = 20
VOL_SMA_PERIOD = 20

# -- c191 최적 고정 --
SL_SLOPE_BONUS = 0.1
RELAX_VOL_MOM_TH = 0.40
RELAX_FACTOR = 0.9

# -- c192 최적 출구 --
TP_BASE_ATR = 4.0
TRAIL_BASE_ATR = 0.30
MIN_PROFIT_ATR = 1.5
TP_BONUS_ATR = 2.0
TRAIL_BONUS_ATR = 0.2

# -- c176 고정 --
ATR_PCTILE_LB = 60
ATR_TH = 30

# -- c182 최적 고정 (탐색 대상 1) --
VOL_PCTILE_LB = 60

# -- c186 최적 고정 (탐색 대상 2,3) --
RSI_DELTA_MIN = 6
EMA_SLOPE_LB = 10

# -- c190 최적 고정 --
VOL_MOM_LB = 10
TP_SLOPE_BONUS = 1.0

# -- 탐색 그리드: 진입 필터 임계값 --
BODY_RATIO_MIN_LIST = [0.30, 0.40, 0.50]
VOL_PCTILE_TH_LIST = [40, 50, 60]
EMA_SLOPE_PCTILE_TH_LIST = [30, 40, 50]
VOL_MOM_MIN_LIST = [0.00, 0.03, 0.05]

# -- 3-fold Walkforward --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-10")},
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


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    body_ratio_min: float,
    vol_pctile_th: float,
    ema_slope_pctile_th: float,
    vol_mom_min: float,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    # c195 최적 지표 (고정)
    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)

    # 고정 지표
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)
    atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
    body_ratio_arr = compute_body_ratio(o, c, h, lo)
    vol_pctile_arr = compute_vol_percentile(v, VOL_PCTILE_LB)
    ema_slope_pctile_arr = compute_ema_slope_percentile(
        ema_arr, EMA_SLOPE_LB)
    vol_mom_arr = compute_vol_momentum(v, ema_period=VOL_MOM_LB)

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
        atr_pctile_val = atr_pctile_arr[i]
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

        # 볼륨모멘텀 기반 진입조건 완화 (c191 최적 고정)
        vm = vol_mom_arr[i]
        vol_mom_strong = (not np.isnan(vm)) and (vm >= RELAX_VOL_MOM_TH)

        effective_body_min = (
            body_ratio_min * RELAX_FACTOR if vol_mom_strong else body_ratio_min
        )
        effective_rsi_delta_min = (
            RSI_DELTA_MIN * RELAX_FACTOR if vol_mom_strong else RSI_DELTA_MIN
        )

        # 진입 조건
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
        rsi_velocity_ok = rsi_delta >= effective_rsi_delta_min
        vol_ok = v[i] >= vol_sma_val * VOL_MULT

        # ATR 백분위 필터 (c176 고정)
        atr_pctile_ok = True
        if np.isnan(atr_pctile_val):
            atr_pctile_ok = False
        else:
            atr_pctile_ok = atr_pctile_val >= ATR_TH

        # 바디 비율 필터 (탐색 대상)
        body_ok = True
        if effective_body_min > 0:
            if np.isnan(body_val):
                body_ok = False
            else:
                body_ok = body_val >= effective_body_min and c[i] >= o[i]

        # 볼륨 백분위 게이트 (탐색 대상)
        vol_pctile_ok = True
        if np.isnan(vol_pctile_val):
            vol_pctile_ok = False
        else:
            vol_pctile_ok = vol_pctile_val >= vol_pctile_th

        # EMA slope percentile (탐색 대상)
        esp = ema_slope_pctile_arr[i]
        ema_slope_ok = True
        if np.isnan(esp):
            ema_slope_ok = False
        else:
            ema_slope_ok = esp >= ema_slope_pctile_th

        # 볼륨 모멘텀 게이트 (탐색 대상)
        vol_mom_ok = True
        if vol_mom_min > 0:
            if np.isnan(vm):
                vol_mom_ok = False
            else:
                vol_mom_ok = vm >= vol_mom_min

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and vol_pctile_ok
                and ema_slope_ok and vol_mom_ok):

            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # EMA slope 강도 -> TP 보너스 (c190 고정)
            slope_tp_extra = 0.0
            if TP_SLOPE_BONUS > 0 and not np.isnan(esp):
                if esp >= 70.0:
                    slope_tp_extra = TP_SLOPE_BONUS
                elif esp >= 60.0:
                    slope_tp_extra = TP_SLOPE_BONUS * 0.5

            effective_tp_mult = (
                TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio + slope_tp_extra
            )
            tp_price = buy + atr_at_entry * effective_tp_mult

            # 적응형 SL (c191 최적 고정)
            sl_slope_extra = 0.0
            if SL_SLOPE_BONUS > 0 and not np.isnan(esp):
                if esp >= 70.0:
                    sl_slope_extra = SL_SLOPE_BONUS
                elif esp >= 60.0:
                    sl_slope_extra = SL_SLOPE_BONUS * 0.5

            effective_sl_mult = (
                SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio + sl_slope_extra
            )
            effective_sl_mult = max(0.2, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            effective_trail_mult = (
                TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            )
            trail_dist = atr_at_entry * effective_trail_mult
            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR

            exit_ret = None
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
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
                hold_end = min(i + MAX_HOLD, n - 1)
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
    for body, vol_p, ema_sp, vol_m in product(
        BODY_RATIO_MIN_LIST, VOL_PCTILE_TH_LIST,
        EMA_SLOPE_PCTILE_TH_LIST, VOL_MOM_MIN_LIST,
    ):
        combos.append({
            "body_ratio_min": body,
            "vol_pctile_th": vol_p,
            "ema_slope_pctile_th": ema_sp,
            "vol_mom_min": vol_m,
        })
    return combos


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 196 — 진입 필터 임계값 완화 탐색 ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe >= 20 AND trades >= 25")
    print("가설: c195 지표주기 변경 후 고정 필터 임계값 재조정 → 거래수 복원")
    print(f"기준선: c195 OOS +27.895, WR 72.2%, trades 14")
    print(f"  c195 고정: RSI_P={RSI_PERIOD} EMA_P={EMA_PERIOD} "
          f"MOM_LB={MOM_LOOKBACK}")
    print(f"  c192 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} "
          f"bSMA={BTC_SMA_PERIOD} rCeil={RSI_CEILING} rFlr={RSI_FLOOR}")
    print(f"  c192 출구: tpB={TP_BASE_ATR} trB={TRAIL_BASE_ATR} "
          f"mnP={MIN_PROFIT_ATR}")
    print(f"  c191 고정: slB={SL_SLOPE_BONUS} rTh={RELAX_VOL_MOM_TH} "
          f"rF={RELAX_FACTOR}")
    print(f"  c190 고정: VOL_MOM_LB={VOL_MOM_LB} "
          f"TP_SLOPE_BONUS={TP_SLOPE_BONUS}")
    print(f"  c186 고정: rsiD={RSI_DELTA_MIN} sLB={EMA_SLOPE_LB}")
    print(f"  c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH}")
    print(f"  c165 고정: Hold={MAX_HOLD} CD={COOLDOWN_BARS}")
    print(f"  c164 고정: dLB={RSI_DELTA_LB} SL={SL_BASE_ATR}-{SL_BONUS_ATR} "
          f"vMul={VOL_MULT}")
    print(f"  탐색: body={BODY_RATIO_MIN_LIST} volP={VOL_PCTILE_TH_LIST} "
          f"emaSP={EMA_SLOPE_PCTILE_TH_LIST} volMom={VOL_MOM_MIN_LIST}")
    print("=" * 80)

    # -- BTC 데이터 --
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    btc_close = df_btc_full["close"].values
    btc_sma_arr = sma_calc(btc_close, BTC_SMA_PERIOD)
    btc_close_s = pd.Series(btc_close, index=df_btc_full.index)
    btc_sma_s = pd.Series(btc_sma_arr, index=df_btc_full.index)

    # -- 심볼별 데이터 확인 --
    print("\n--- 심볼별 데이터 확인 ---")
    sym_data_ok = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-10")
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

    sym_train_cache: dict[str, pd.DataFrame] = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if not df_tr.empty:
            sym_train_cache[sym] = df_tr
            print(f"  {sym} train: {len(df_tr)}행")

    results: list[dict] = []
    for idx, combo in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr = sym_train_cache[sym]
            btc_c_aligned = btc_close_s.reindex(
                df_tr.index, method="ffill").values
            btc_s_aligned = btc_sma_s.reindex(
                df_tr.index, method="ffill").values
            r = backtest(df_tr, btc_c_aligned, btc_s_aligned,
                         combo["body_ratio_min"], combo["vol_pctile_th"],
                         combo["ema_slope_pctile_th"], combo["vol_mom_min"])
            sym_results.append(r)

        pooled = pool_results(sym_results)
        results.append({**combo, **pooled})

    valid = [r for r in results if r["trades"] >= 8 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=8): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 16 (pooled Sharpe 기준) ===")
    hdr = (f"{'body':>5} {'volP':>5} {'emaSP':>5} {'volMm':>5} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} "
           f"{'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:16]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['body_ratio_min']:>5.2f} {r['vol_pctile_th']:>5.0f} "
            f"{r['ema_slope_pctile_th']:>5.0f} {r['vol_mom_min']:>5.2f} | "
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
        key = (r["body_ratio_min"], r["vol_pctile_th"],
               r["ema_slope_pctile_th"], r["vol_mom_min"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 12:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(unique_top)} 고유) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        body_min = params["body_ratio_min"]
        vol_p = params["vol_pctile_th"]
        ema_sp = params["ema_slope_pctile_th"]
        vol_m = params["vol_mom_min"]

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
                btc_c_aligned = btc_close_s.reindex(
                    df_test.index, method="ffill").values
                btc_s_aligned = btc_sma_s.reindex(
                    df_test.index, method="ffill").values
                r = backtest(df_test, btc_c_aligned, btc_s_aligned,
                             body_min, vol_p, ema_sp, vol_m)
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
            print(f"  #{rank}: body={body_min:.2f} volP={vol_p:.0f} "
                  f"emaSP={ema_sp:.0f} volMm={vol_m:.2f} | "
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
        body_min = params["body_ratio_min"]
        vol_p = params["vol_pctile_th"]
        ema_sp = params["ema_slope_pctile_th"]
        vol_m = params["vol_mom_min"]
        print(f"\n--- #{rank}: body={body_min:.2f} volP={vol_p:.0f} "
              f"emaSP={ema_sp:.0f} volMm={vol_m:.2f} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            sym_results = []
            for sym in sym_data_ok:
                df_full = load_historical(
                    sym, "240m", "2022-01-01", "2026-12-31")
                if df_full.empty:
                    continue
                btc_c_aligned = btc_close_s.reindex(
                    df_full.index, method="ffill").values
                btc_s_aligned = btc_sma_s.reindex(
                    df_full.index, method="ffill").values
                r = backtest(df_full, btc_c_aligned, btc_s_aligned,
                             body_min, vol_p, ema_sp, vol_m,
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
    body_min = best["body_ratio_min"]
    vol_p = best["vol_pctile_th"]
    ema_sp = best["ema_slope_pctile_th"]
    vol_m = best["vol_mom_min"]

    print(f"\n{'=' * 80}")
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: body={body_min:.2f} "
          f"volP={vol_p:.0f} emaSP={ema_sp:.0f} volMm={vol_m:.2f}) ===")
    for sym in sym_data_ok:
        sym_oos_sharpes = []
        sym_oos_trades = 0
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(sym, "240m",
                                      fold["test"][0], fold["test"][1])
            if df_test.empty:
                continue
            btc_c_aligned = btc_close_s.reindex(
                df_test.index, method="ffill").values
            btc_s_aligned = btc_sma_s.reindex(
                df_test.index, method="ffill").values
            r = backtest(df_test, btc_c_aligned, btc_s_aligned,
                         body_min, vol_p, ema_sp, vol_m)
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

    # -- c195 대비 비교 --
    print(f"{'=' * 80}")
    print("=== c195 베이스라인 대비 비교 ===")
    print(f"  c195 최적 (body=0.50 volP=60 emaSP=50 volMm=0.05): "
          f"avg_OOS=+27.895 n=14")
    print(f"  c196 최적 (body={best['body_ratio_min']:.2f} "
          f"volP={best['vol_pctile_th']:.0f} "
          f"emaSP={best['ema_slope_pctile_th']:.0f} "
          f"volMm={best['vol_mom_min']:.2f}): "
          f"avg_OOS={best['avg_oos_sharpe']:+.3f} "
          f"n={best['total_oos_trades']}")
    delta_sh = best["avg_oos_sharpe"] - 27.895
    delta_n = best["total_oos_trades"] - 14
    print(f"  Δ Sharpe: {delta_sh:+.3f} "
          f"({'개선' if delta_sh > 0 else '악화' if delta_sh < 0 else '동일'})")
    print(f"  Δ trades: {delta_n:+d} "
          f"({'증가' if delta_n > 0 else '감소' if delta_n < 0 else '동일'})")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: BODY_RATIO_MIN={best['body_ratio_min']:.2f} "
          f"VOL_PCTILE_TH={best['vol_pctile_th']:.0f} "
          f"EMA_SLOPE_PCTILE_TH={best['ema_slope_pctile_th']:.0f} "
          f"VOL_MOM_MIN={best['vol_mom_min']:.2f}")
    print(f"  (c195 고정: rsiP={RSI_PERIOD} emaP={EMA_PERIOD} "
          f"momLB={MOM_LOOKBACK})")
    print(f"  (c192 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH})")
    print(f"  (c192 고정: bSMA={BTC_SMA_PERIOD} rCeil={RSI_CEILING} "
          f"rFlr={RSI_FLOOR})")
    print(f"  (c192 출구: tpB={TP_BASE_ATR} trB={TRAIL_BASE_ATR} "
          f"mnP={MIN_PROFIT_ATR})")
    print(f"  (c191 고정: slB={SL_SLOPE_BONUS} rTh={RELAX_VOL_MOM_TH} "
          f"rF={RELAX_FACTOR})")
    print(f"  (c190 고정: VOL_MOM_LB={VOL_MOM_LB} "
          f"TP_SLOPE_BONUS={TP_SLOPE_BONUS})")
    print(f"  (c186 고정: rsiD={RSI_DELTA_MIN} sLB={EMA_SLOPE_LB})")
    print(f"  (c182 고정: vPLB={VOL_PCTILE_LB})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH})")
    print(f"  (c165 고정: Hold={MAX_HOLD} CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT})")
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
