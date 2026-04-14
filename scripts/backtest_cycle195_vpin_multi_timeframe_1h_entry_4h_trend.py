"""
vpin_multi 사이클 195 — 멀티타임프레임: 1h 진입 + 4h 추세확인
- 기반: c192 OOS Sharpe +30.947, WR 66.7%, trades 26 (4h 단일 TF)
  c194 exit 포화 확정, c193 Q-score entry gate 악화
- 문제:
  1) 4h 단일 TF → n=26 신호 희소 (통계적으로 불충분)
  2) 4h 진입은 4시간 단위 → 최적 진입점 놓침
  3) exit도 4h 해상도 → 4시간 내 급변에 대응 불가
- 가설:
  1h 캔들로 진입/exit 세분화 → n 증가 + 진입 타이밍 정밀화
  4h 추세 필터(EMA slope, ATR regime)로 노이즈 제거 → 승률 유지
  1h VPIN은 24h~96h 버켓으로 단기 유동성 불균형 감지
- 탐색 그리드:
  VPIN_1H_BUCKETS: [24, 48, 96] — 1h VPIN 버켓 수 (24h, 48h, 96h 윈도우)
  MOM_1H_LB: [4, 8, 16]        — 1h 모멘텀 룩백 (4h, 8h, 16h)
  MAX_HOLD_1H: [40, 60, 80]    — 1h 최대보유 (≈10~20 4h bars)
  = 3×3×3 = 27 combos
- 목표: OOS Sharpe >= 15 AND trades >= 40 (1h이므로 trades 증가 기대)
- 3-fold WF + 슬리피지 스트레스
- 진입: next_bar open (1h)
- 4h 지표(EMA slope pctile, ATR pctile, BTC SMA)는 최근 완료된 4h 바에서 가져옴
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

# -- c165 최적 고정값 (1h 적응) --
VPIN_LOW = 0.35
MOM_THRESH = 0.0007
COOLDOWN_BARS_1H = 16  # 4h기준 4 → 1h기준 16
COOLDOWN_LOSSES = 2

RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
EMA_PERIOD_1H = 80  # 4h EMA20 → 1h 80봉 동등
MOM_LOOKBACK_DEFAULT = 8  # 탐색 대상

# -- c164 고정 (1h 적응) --
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD_1H = 80  # 4h ATR20 → 1h 80
VOL_SMA_PERIOD_1H = 80

TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

BTC_SMA_PERIOD_4H = 200  # 4h BTC SMA (변경 없음)

# -- c176 고정 (4h에서 계산 후 매핑) --
ATR_TH_4H = 30
ATR_PCTILE_LB_4H = 60

# -- c182 고정 (1h 적응) --
VOL_PCTILE_TH = 60
VOL_PCTILE_LB_1H = 240  # 4h 60봉 → 1h 240

# -- c186 고정 --
BODY_RATIO_MIN = 0.50
RSI_DELTA_LB = 12  # 4h 3봉 → 1h 12봉
RSI_DELTA_MIN = 6

# -- 4h 추세 필터 (c186/c190에서 검증된 값) --
EMA_SLOPE_LB_4H = 10
EMA_SLOPE_PCTILE_TH_4H = 50

# -- c190 고정 (1h 적응) --
VOL_MOM_LB_1H = 40  # 4h 10봉 → 1h 40봉
VOL_MOM_MIN = 0.05

# -- c192 최적 고정 (1h 적응) --
TRAIL_TIGHTEN_AFTER_1H = 24  # 4h 6봉 → 1h 24봉
TRAIL_TIGHTEN_FACTOR = 3.0
TP_SLOPE_BONUS = 1.0

# -- c195 탐색 그리드 --
VPIN_1H_BUCKETS_LIST = [24, 48, 96]
MOM_1H_LB_LIST = [4, 8, 16]
MAX_HOLD_1H_LIST = [40, 60, 80]

# -- 3-fold Walkforward (1h 날짜 동일) --
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


def compute_atr_percentile(atr_arr: np.ndarray, lookback: int = 60) -> np.ndarray:
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


def compute_vol_percentile(volumes: np.ndarray, lookback: int = 60) -> np.ndarray:
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


def compute_vol_momentum(volumes: np.ndarray, ema_period: int = 10) -> np.ndarray:
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


def map_4h_to_1h(
    df_4h: pd.DataFrame, indicator_arr: np.ndarray, df_1h: pd.DataFrame,
) -> np.ndarray:
    """Map 4h indicator values to 1h index using forward-fill."""
    s = pd.Series(indicator_arr, index=df_4h.index)
    return s.reindex(df_1h.index, method="ffill").values


# -- 백테스트 --

def backtest(
    df_1h: pd.DataFrame,
    vpin_1h_buckets: int,
    mom_1h_lb: int,
    max_hold_1h: int,
    btc_close_4h_mapped: np.ndarray,
    btc_sma_4h_mapped: np.ndarray,
    ema_slope_4h_mapped: np.ndarray,
    atr_pctile_4h_mapped: np.ndarray,
    vol_mom_1h_arr: np.ndarray,
    slippage: float = 0.0005,
) -> dict:
    c = df_1h["close"].values
    o = df_1h["open"].values
    h = df_1h["high"].values
    lo = df_1h["low"].values
    v = df_1h["volume"].values
    n = len(c)

    # 1h indicators
    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD_1H)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, vpin_1h_buckets)
    mom_arr = compute_momentum(c, mom_1h_lb)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD_1H)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD_1H)
    body_ratio_arr = compute_body_ratio(o, c, h, lo)
    vol_pctile_arr = compute_vol_percentile(v, VOL_PCTILE_LB_1H)

    returns: list[float] = []
    warmup = max(vpin_1h_buckets, EMA_PERIOD_1H, RSI_PERIOD + 1,
                 mom_1h_lb, ATR_PERIOD_1H, VOL_SMA_PERIOD_1H,
                 VOL_PCTILE_LB_1H, VOL_MOM_LB_1H + 10, 300) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if COOLDOWN_BARS_1H > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_sma_val = vol_sma_arr[i]
        body_val = body_ratio_arr[i]
        vol_pctile_val = vol_pctile_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0):
            i += 1
            continue

        # RSI velocity (1h)
        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # === 1h 진입 필터 ===
        vpin_ok = (
            vpin_val < VPIN_LOW
            and mom_val >= MOM_THRESH
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )
        vol_ok = v[i] >= vol_sma_val * VOL_MULT
        rsi_velocity_ok = rsi_delta >= RSI_DELTA_MIN
        body_ok = body_val >= BODY_RATIO_MIN and c[i] >= o[i]
        vol_pctile_ok = (not np.isnan(vol_pctile_val)
                         and vol_pctile_val >= VOL_PCTILE_TH)

        # 볼륨 모멘텀 (1h 적응)
        vm = vol_mom_1h_arr[i]
        vol_mom_ok = not np.isnan(vm) and vm >= VOL_MOM_MIN

        # === 4h 추세확인 필터 (mapped to 1h index) ===
        btc_ok = (
            not np.isnan(btc_close_4h_mapped[i])
            and not np.isnan(btc_sma_4h_mapped[i])
            and btc_close_4h_mapped[i] > btc_sma_4h_mapped[i]
        )
        esp_4h = ema_slope_4h_mapped[i]
        ema_slope_4h_ok = not np.isnan(esp_4h) and esp_4h >= EMA_SLOPE_PCTILE_TH_4H

        atr_pctile_4h_val = atr_pctile_4h_mapped[i]
        atr_pctile_4h_ok = (not np.isnan(atr_pctile_4h_val)
                            and atr_pctile_4h_val >= ATR_TH_4H)

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and body_ok and vol_pctile_ok and vol_mom_ok
                and ema_slope_4h_ok and atr_pctile_4h_ok):

            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val
            entry_bar = i + 1

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # TP 계산 (c192 고정 로직, 4h EMA slope 사용)
            slope_tp_extra = 0.0
            if TP_SLOPE_BONUS > 0 and not np.isnan(esp_4h):
                if esp_4h >= 70.0:
                    slope_tp_extra = TP_SLOPE_BONUS
                elif esp_4h >= 60.0:
                    slope_tp_extra = TP_SLOPE_BONUS * 0.5

            # ATR 레짐 TP 스케일링 (c192, 4h ATR pctile 사용)
            atr_tp_extra = 0.0
            if not np.isnan(atr_pctile_4h_val):
                if atr_pctile_4h_val >= 70.0:
                    atr_tp_extra = 0.5
                elif atr_pctile_4h_val >= 50.0:
                    atr_tp_extra = 0.5 * ((atr_pctile_4h_val - 50.0) / 20.0)

            effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
                                 + slope_tp_extra + atr_tp_extra)
            tp_price = buy + atr_at_entry * effective_tp_mult

            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            base_trail_mult = TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold_1h, n)):
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

                # 시간감쇠 트레일 (c192, 1h 적응)
                if bars_held >= TRAIL_TIGHTEN_AFTER_1H:
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
                hold_end = min(i + max_hold_1h, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)

            if exit_ret < 0:
                consecutive_losses += 1
                if consecutive_losses >= COOLDOWN_LOSSES and COOLDOWN_BARS_1H > 0:
                    cooldown_until = i + COOLDOWN_BARS_1H
                    consecutive_losses = 0
            else:
                consecutive_losses = 0
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    # Sharpe: annualize with 1h bars (252*24 = 6048 trading hours/year)
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
    for vb, mlb, mh in product(
        VPIN_1H_BUCKETS_LIST,
        MOM_1H_LB_LIST,
        MAX_HOLD_1H_LIST,
    ):
        combos.append({
            "vpin_1h_buckets": vb,
            "mom_1h_lb": mlb,
            "max_hold_1h": mh,
        })
    return combos


def precompute_4h_indicators(
    df_4h: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    """4h EMA slope percentile + 4h ATR percentile 사전 계산."""
    c = df_4h["close"].values
    h = df_4h["high"].values
    lo = df_4h["low"].values
    ema_arr = ema_calc(c, 20)  # 4h EMA20
    ema_slope_pctile = compute_ema_slope_percentile(ema_arr, EMA_SLOPE_LB_4H)
    atr_arr = compute_atr(h, lo, c, 20)  # 4h ATR20
    atr_pctile = compute_atr_percentile(atr_arr, ATR_PCTILE_LB_4H)
    return ema_slope_pctile, atr_pctile


def main() -> None:
    print("=" * 80)
    print("=== c195: VPIN 멀티타임프레임 — 1h 진입 + 4h 추세확인 ===")
    print("=" * 80)

    combos = build_combos()
    print(f"탐색 조합: {len(combos)}개")
    print(f"심볼: {SYMBOLS}")
    print(f"VPIN_1H_BUCKETS: {VPIN_1H_BUCKETS_LIST}")
    print(f"MOM_1H_LB: {MOM_1H_LB_LIST}")
    print(f"MAX_HOLD_1H: {MAX_HOLD_1H_LIST}")
    print()

    # Load data
    print("[1/4] 데이터 로딩...")
    data_1h: dict[str, pd.DataFrame] = {}
    data_4h: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        data_1h[sym] = load_historical(sym, "60m", "2022-01-01", "2026-04-05")
        data_4h[sym] = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        print(f"  {sym}: 1h={len(data_1h[sym])}행, 4h={len(data_4h[sym])}행")

    # BTC 4h data
    btc_4h = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"  KRW-BTC 4h: {len(btc_4h)}행")

    # Precompute 4h indicators per symbol
    print("[2/4] 4h 지표 사전계산 + 1h 매핑...")
    indicators_4h: dict[str, dict] = {}
    for sym in SYMBOLS:
        df_4h = data_4h[sym]
        df_1h = data_1h[sym]
        esp_4h, atp_4h = precompute_4h_indicators(df_4h)

        # Map to 1h
        esp_4h_mapped = map_4h_to_1h(df_4h, esp_4h, df_1h)
        atp_4h_mapped = map_4h_to_1h(df_4h, atp_4h, df_1h)

        # BTC SMA on 4h, mapped to 1h
        btc_close_4h = btc_4h["close"].values
        btc_sma_4h = sma_calc(btc_close_4h, BTC_SMA_PERIOD_4H)
        btc_c_s = pd.Series(btc_close_4h, index=btc_4h.index)
        btc_s_s = pd.Series(btc_sma_4h, index=btc_4h.index)
        btc_close_mapped = btc_c_s.reindex(df_1h.index, method="ffill").values
        btc_sma_mapped = btc_s_s.reindex(df_1h.index, method="ffill").values

        # 1h vol momentum (pre-compute once)
        vol_mom_1h = compute_vol_momentum(
            df_1h["volume"].values, ema_period=VOL_MOM_LB_1H)

        indicators_4h[sym] = {
            "esp_4h_mapped": esp_4h_mapped,
            "atp_4h_mapped": atp_4h_mapped,
            "btc_close_mapped": btc_close_mapped,
            "btc_sma_mapped": btc_sma_mapped,
            "vol_mom_1h": vol_mom_1h,
        }
    print("  완료")

    # Walk-forward
    print("[3/4] 3-fold Walk-Forward 실행...")
    fold_results: dict[int, list[tuple[dict, dict, list[dict]]]] = {
        f: [] for f in range(len(WF_FOLDS))
    }

    for ci, combo in enumerate(combos):
        vb = combo["vpin_1h_buckets"]
        mlb = combo["mom_1h_lb"]
        mh = combo["max_hold_1h"]

        for fi, fold in enumerate(WF_FOLDS):
            train_start, train_end = fold["train"]
            test_start, test_end = fold["test"]

            sym_results_train = []
            sym_results_test = []
            sym_details_test = []

            for sym in SYMBOLS:
                df_1h_full = data_1h[sym]
                ind = indicators_4h[sym]

                # Slice for train
                train_mask = (
                    (df_1h_full.index >= train_start)
                    & (df_1h_full.index <= train_end)
                )
                df_train = df_1h_full[train_mask]
                if len(df_train) < 500:
                    continue

                # Get full-array index positions for indicator slicing
                train_idx = df_1h_full.index.get_indexer(df_train.index)
                valid_train = train_idx >= 0
                train_idx = train_idx[valid_train]

                r_train = backtest(
                    df_train, vb, mlb, mh,
                    ind["btc_close_mapped"][train_idx],
                    ind["btc_sma_mapped"][train_idx],
                    ind["esp_4h_mapped"][train_idx],
                    ind["atp_4h_mapped"][train_idx],
                    ind["vol_mom_1h"][train_idx],
                    slippage=0.0005,
                )
                sym_results_train.append(r_train)

                # Slice for test
                test_mask = (
                    (df_1h_full.index >= test_start)
                    & (df_1h_full.index <= test_end)
                )
                df_test = df_1h_full[test_mask]
                if len(df_test) < 200:
                    continue

                test_idx = df_1h_full.index.get_indexer(df_test.index)
                valid_test = test_idx >= 0
                test_idx = test_idx[valid_test]

                r_test = backtest(
                    df_test, vb, mlb, mh,
                    ind["btc_close_mapped"][test_idx],
                    ind["btc_sma_mapped"][test_idx],
                    ind["esp_4h_mapped"][test_idx],
                    ind["atp_4h_mapped"][test_idx],
                    ind["vol_mom_1h"][test_idx],
                    slippage=0.0005,
                )
                sym_results_test.append(r_test)
                sym_details_test.append({"sym": sym, **r_test})

            pooled_train = pool_results(sym_results_train)
            pooled_test = pool_results(sym_results_test)
            fold_results[fi].append((combo, pooled_test, sym_details_test))

        if (ci + 1) % 9 == 0 or ci == len(combos) - 1:
            print(f"  조합 {ci + 1}/{len(combos)} 완료")

    # Aggregate: avg OOS Sharpe across folds
    print("\n[4/4] 결과 집계...")
    combo_scores: list[tuple[dict, float, int, list]] = []

    for ci, combo in enumerate(combos):
        fold_sharpes = []
        fold_trades = []
        fold_details = []
        for fi in range(len(WF_FOLDS)):
            _, pooled_test, details = fold_results[fi][ci]
            if not np.isnan(pooled_test["sharpe"]):
                fold_sharpes.append(pooled_test["sharpe"])
                fold_trades.append(pooled_test["trades"])
                fold_details.append((fi, pooled_test, details))

        if fold_sharpes:
            avg_sh = float(np.mean(fold_sharpes))
            total_t = sum(fold_trades)
            combo_scores.append((combo, avg_sh, total_t, fold_details))

    combo_scores.sort(key=lambda x: x[1], reverse=True)

    print("\n" + "=" * 80)
    print("=== OOS 순위 (avg Sharpe across folds) ===")
    print("=" * 80)
    for rank, (combo, avg_sh, total_t, _) in enumerate(combo_scores[:10]):
        vb = combo["vpin_1h_buckets"]
        mlb = combo["mom_1h_lb"]
        mh = combo["max_hold_1h"]
        tag = "[PASS]" if avg_sh >= 15.0 and total_t >= 40 else "[FAIL]"
        print(f"  {rank + 1:2d}: vB={vb} mLB={mlb} mH={mh} → "
              f"Sharpe={avg_sh:+.3f} trades={total_t} {tag}")

    # Best combo details
    if combo_scores:
        best_combo, best_sh, best_t, best_details = combo_scores[0]
        vb = best_combo["vpin_1h_buckets"]
        mlb = best_combo["mom_1h_lb"]
        mh = best_combo["max_hold_1h"]

        print(f"\n{'=' * 80}")
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: vB={vb} mLB={mlb} mH={mh}) ===")
        for fi, pooled, details in best_details:
            for d in details:
                print(f"  {d['sym']} Fold {fi + 1}: "
                      f"Sharpe={d['sharpe']:+.3f}  WR={d['wr']:.1%}  "
                      f"n={d['trades']}  avg={d['avg_ret']:+.2%}  "
                      f"MDD={d['max_dd']:+.2%}")

        # Per-symbol averages
        sym_sharpes: dict[str, list[float]] = {s: [] for s in SYMBOLS}
        sym_trades: dict[str, int] = {s: 0 for s in SYMBOLS}
        for _, _, details in best_details:
            for d in details:
                if d["trades"] > 0 and not np.isnan(d["sharpe"]):
                    sym_sharpes[d["sym"]].append(d["sharpe"])
                    sym_trades[d["sym"]] += d["trades"]
        for sym in SYMBOLS:
            if sym_sharpes[sym]:
                avg = float(np.mean(sym_sharpes[sym]))
                print(f"  {sym} 평균: Sharpe={avg:+.3f}  총 trades={sym_trades[sym]}")

        # Compare with c192 baseline
        print(f"\n{'=' * 80}")
        print("=== c192 베이스라인 대비 비교 ===")
        print(f"  c192 최적 (4h 단일 TF): avg_OOS=+30.947 n=26")
        print(f"  c195 최적 (vB={vb} mLB={mlb} mH={mh}): "
              f"avg_OOS={best_sh:+.3f} n={best_t}")
        delta = best_sh - 30.947
        delta_t = best_t - 26
        print(f"  Δ Sharpe: {delta:+.3f} ({'개선' if delta > 0 else '악화'})")
        print(f"  Δ trades: {delta_t:+d} ({'증가' if delta_t > 0 else '감소'})")

        # Slippage stress test
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 ===")
        for slip in SLIPPAGE_LEVELS:
            slip_results = []
            for sym in SYMBOLS:
                df_1h_full = data_1h[sym]
                ind = indicators_4h[sym]

                # Use fold 3 test period (most recent)
                test_start = WF_FOLDS[2]["test"][0]
                test_end = WF_FOLDS[2]["test"][1]
                test_mask = (
                    (df_1h_full.index >= test_start)
                    & (df_1h_full.index <= test_end)
                )
                df_test = df_1h_full[test_mask]
                if len(df_test) < 200:
                    continue

                test_idx = df_1h_full.index.get_indexer(df_test.index)
                valid = test_idx >= 0
                test_idx = test_idx[valid]

                r = backtest(
                    df_test, vb, mlb, mh,
                    ind["btc_close_mapped"][test_idx],
                    ind["btc_sma_mapped"][test_idx],
                    ind["esp_4h_mapped"][test_idx],
                    ind["atp_4h_mapped"][test_idx],
                    ind["vol_mom_1h"][test_idx],
                    slippage=slip,
                )
                slip_results.append(r)
            pooled_slip = pool_results(slip_results)
            print(f"  slip={slip:.4f}: Sharpe={pooled_slip['sharpe']:+.3f}  "
                  f"WR={pooled_slip['wr']:.1%}  avg={pooled_slip['avg_ret']:+.2%}  "
                  f"MDD={pooled_slip['max_dd']:+.2%}  trades={pooled_slip['trades']}")

        # Final summary
        print(f"\n{'=' * 80}")
        print("=== 최종 요약 ===")
        print(f"★ OOS 최적: VPIN_1H_BUCKETS={vb} MOM_1H_LB={mlb} "
              f"MAX_HOLD_1H={mh}")
        print(f"  (1h 진입 + 4h 추세확인: EMA slope pctile>={EMA_SLOPE_PCTILE_TH_4H}, "
              f"ATR pctile>={ATR_TH_4H})")
        print(f"  (c192 고정: TRAIL_TIGHTEN_AFTER_1H={TRAIL_TIGHTEN_AFTER_1H} "
              f"TRAIL_TIGHTEN_FACTOR={TRAIL_TIGHTEN_FACTOR})")
        print(f"  (c190 고정: VOL_MOM_LB_1H={VOL_MOM_LB_1H} "
              f"VOL_MOM_MIN={VOL_MOM_MIN})")
        print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} CD={COOLDOWN_BARS_1H})")
        print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
              f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} "
              f"BTC_SMA_4H={BTC_SMA_PERIOD_4H})")
        print(f"  avg OOS Sharpe: {best_sh:+.3f} "
              f"{'PASS' if best_sh >= 15.0 and best_t >= 40 else 'FAIL'}")

        # Per-fold summary
        for fi, pooled, details in best_details:
            print(f"  Fold {fi + 1}: Sharpe={pooled['sharpe']:+.3f}  "
                  f"WR={pooled['wr']:.1%}  trades={pooled['trades']}  "
                  f"avg={pooled['avg_ret']:+.2%}  MDD={pooled['max_dd']:+.2%}")

    print(f"\nSharpe: {best_sh:+.3f}")
    print(f"WR: {combo_scores[0][3][0][1]['wr']:.1%}" if combo_scores else "WR: N/A")
    print(f"trades: {best_t}")


if __name__ == "__main__":
    main()
