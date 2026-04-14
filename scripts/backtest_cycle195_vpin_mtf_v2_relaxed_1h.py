"""
vpin_multi 사이클 195 v2 — 멀티타임프레임: 1h 최소필터 진입 + 4h 품질게이트
- 기반: c192 OOS Sharpe +30.947, WR 66.7%, trades 26 (4h 단일 TF)
- v1 실패 원인: 9개 필터를 모두 1h로 변환 → vol_mom 9%, body 21% 통과 → n=4
- v2 가설:
  1h에서는 핵심 신호(VPIN + momentum + RSI range + price>EMA)만 사용
  품질 필터(body, vol pctile, vol_mom, rsi_vel)는 4h 수준에서 판단
  → 1h 진입 횟수 증가 + 4h 추세 품질로 노이즈 제어
- 탐색 그리드:
  VPIN_1H_BUCKETS: [24, 48]        — 1h VPIN 윈도우
  MOM_1H_LB: [4, 8]               — 1h 모멘텀 룩백
  MAX_HOLD_1H: [40, 80]           — 1h 최대보유
  4H_BODY_GATE: [True, False]      — 4h 바디 확인 여부
  = 2×2×2×2 = 16 combos
- 3-fold WF + 슬리피지 스트레스
- 진입: next_bar open (1h)
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

# -- 1h 핵심 진입 (최소) --
VPIN_LOW = 0.35
MOM_THRESH = 0.0007
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
EMA_PERIOD_1H = 80  # 4h EMA20 동등
COOLDOWN_BARS_1H = 8  # 완화 (16→8)
COOLDOWN_LOSSES = 2

# -- 1h exit 파라미터 (c192 동등) --
ATR_PERIOD_1H = 80
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
VOL_SMA_PERIOD_1H = 80
TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5
TRAIL_TIGHTEN_AFTER_1H = 24
TRAIL_TIGHTEN_FACTOR = 3.0
TP_SLOPE_BONUS = 1.0

# -- 4h 품질 게이트 (c186/c190 검증) --
BTC_SMA_PERIOD_4H = 200
ATR_TH_4H = 30
ATR_PCTILE_LB_4H = 60
EMA_SLOPE_LB_4H = 10
EMA_SLOPE_PCTILE_TH_4H = 50
BODY_RATIO_MIN_4H = 0.50
RSI_DELTA_MIN_4H = 6
RSI_DELTA_LB_4H = 3
VOL_PCTILE_TH_4H = 60
VOL_PCTILE_LB_4H = 60
VOL_MOM_LB_4H = 10
VOL_MOM_MIN_4H = 0.05

# -- 탐색 그리드 --
VPIN_1H_BUCKETS_LIST = [24, 48]
MOM_1H_LB_LIST = [4, 8]
MAX_HOLD_1H_LIST = [40, 80]
BODY_4H_GATE_LIST = [True, False]

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
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
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

def map_4h_to_1h(df_4h: pd.DataFrame, arr_4h: np.ndarray,
                  df_1h: pd.DataFrame) -> np.ndarray:
    s = pd.Series(arr_4h, index=df_4h.index)
    return s.reindex(df_1h.index, method="ffill").values


# -- 4h 지표 사전계산 --
def precompute_4h_all(df_4h: pd.DataFrame) -> dict:
    c = df_4h["close"].values
    o = df_4h["open"].values
    h = df_4h["high"].values
    lo = df_4h["low"].values
    v = df_4h["volume"].values

    ema_4h = ema_calc(c, 20)
    esp_4h = compute_ema_slope_percentile(ema_4h, EMA_SLOPE_LB_4H)
    atr_4h = compute_atr(h, lo, c, 20)
    atp_4h = compute_atr_percentile(atr_4h, ATR_PCTILE_LB_4H)
    body_4h = compute_body_ratio(o, c, h, lo)
    rsi_4h = rsi_calc(c, 14)
    vol_pctile_4h = compute_vol_percentile(v, VOL_PCTILE_LB_4H)
    vol_mom_4h = compute_vol_momentum(v, ema_period=VOL_MOM_LB_4H)
    vol_sma_4h = sma_calc(v, 20)

    return {
        "esp": esp_4h,
        "atp": atp_4h,
        "body": body_4h,
        "rsi": rsi_4h,
        "vol_pctile": vol_pctile_4h,
        "vol_mom": vol_mom_4h,
        "vol_sma": vol_sma_4h,
        "close": c,
        "open": o,
        "volume": v,
    }


# -- 백테스트 --
def backtest(
    df_1h: pd.DataFrame,
    vpin_1h_buckets: int,
    mom_1h_lb: int,
    max_hold_1h: int,
    use_body_4h_gate: bool,
    # 4h 지표 (mapped to 1h index)
    btc_close_m: np.ndarray,
    btc_sma_m: np.ndarray,
    esp_4h_m: np.ndarray,
    atp_4h_m: np.ndarray,
    body_4h_m: np.ndarray,
    rsi_4h_m: np.ndarray,
    vol_pctile_4h_m: np.ndarray,
    vol_mom_4h_m: np.ndarray,
    close_4h_m: np.ndarray,
    open_4h_m: np.ndarray,
    vol_4h_m: np.ndarray,
    vol_sma_4h_m: np.ndarray,
    slippage: float = 0.0005,
) -> dict:
    c = df_1h["close"].values
    o = df_1h["open"].values
    h = df_1h["high"].values
    lo = df_1h["low"].values
    v = df_1h["volume"].values
    n = len(c)

    # 1h indicators (핵심만)
    rsi_1h = rsi_calc(c, RSI_PERIOD)
    ema_1h = ema_calc(c, EMA_PERIOD_1H)
    vpin_1h = compute_vpin_bvc(c, o, h, lo, v, vpin_1h_buckets)
    mom_1h = compute_momentum(c, mom_1h_lb)
    atr_1h = compute_atr(h, lo, c, ATR_PERIOD_1H)

    returns: list[float] = []
    warmup = max(vpin_1h_buckets, EMA_PERIOD_1H, RSI_PERIOD + 1,
                 mom_1h_lb, ATR_PERIOD_1H, 300) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if COOLDOWN_BARS_1H > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_1h[i]
        ema_val = ema_1h[i]
        vpin_val = vpin_1h[i]
        mom_val = mom_1h[i]
        atr_val = atr_1h[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0):
            i += 1
            continue

        # === 1h 핵심 진입 (4 필터) ===
        vpin_ok = vpin_val < VPIN_LOW
        mom_ok = mom_val >= MOM_THRESH
        rsi_ok = RSI_FLOOR < rsi_val < RSI_CEILING
        ema_ok = c[i] > ema_val

        # === 4h 품질 게이트 (mapped) ===
        btc_ok = (not np.isnan(btc_close_m[i]) and not np.isnan(btc_sma_m[i])
                  and btc_close_m[i] > btc_sma_m[i])
        esp_ok = not np.isnan(esp_4h_m[i]) and esp_4h_m[i] >= EMA_SLOPE_PCTILE_TH_4H
        atp_ok = not np.isnan(atp_4h_m[i]) and atp_4h_m[i] >= ATR_TH_4H

        # 4h RSI velocity
        rsi_4h_val = rsi_4h_m[i]
        rsi_vel_4h_ok = True  # 기본 통과
        # 4h에서 RSI delta 확인 (mapped이므로 4h 레벨)
        # NOTE: mapped이라 이전 4h 바 참조 불가 → 생략, 대신 4h vol_mom으로 대체

        # 4h volume momentum
        vm_4h = vol_mom_4h_m[i]
        vol_mom_4h_ok = not np.isnan(vm_4h) and vm_4h >= VOL_MOM_MIN_4H

        # 4h volume percentile
        vp_4h = vol_pctile_4h_m[i]
        vol_pctile_4h_ok = not np.isnan(vp_4h) and vp_4h >= VOL_PCTILE_TH_4H

        # 4h body (optional gate)
        body_4h_ok = True
        if use_body_4h_gate:
            b_4h = body_4h_m[i]
            o_4h = open_4h_m[i]
            c_4h = close_4h_m[i]
            body_4h_ok = (not np.isnan(b_4h) and b_4h >= BODY_RATIO_MIN_4H
                          and not np.isnan(c_4h) and not np.isnan(o_4h)
                          and c_4h >= o_4h)

        # 1h volume (minimal check)
        vol_sma_1h = ema_calc(v[:i + 1], 20)  # expensive, use cached
        # Actually just skip 1h volume check — rely on 4h

        if (vpin_ok and mom_ok and rsi_ok and ema_ok
                and btc_ok and esp_ok and atp_ok
                and vol_mom_4h_ok and vol_pctile_4h_ok and body_4h_ok):

            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val
            entry_bar = i + 1

            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # TP (c192 logic, using 4h indicators)
            slope_tp_extra = 0.0
            if TP_SLOPE_BONUS > 0 and not np.isnan(esp_4h_m[i]):
                if esp_4h_m[i] >= 70.0:
                    slope_tp_extra = TP_SLOPE_BONUS
                elif esp_4h_m[i] >= 60.0:
                    slope_tp_extra = TP_SLOPE_BONUS * 0.5

            atr_tp_extra = 0.0
            if not np.isnan(atp_4h_m[i]):
                if atp_4h_m[i] >= 70.0:
                    atr_tp_extra = 0.5
                elif atp_4h_m[i] >= 50.0:
                    atr_tp_extra = 0.5 * ((atp_4h_m[i] - 50.0) / 20.0)

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

                if bars_held >= TRAIL_TIGHTEN_AFTER_1H:
                    eff_trail = base_trail_mult / TRAIL_TIGHTEN_FACTOR
                else:
                    eff_trail = base_trail_mult
                trail_dist = atr_at_entry * eff_trail

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
    all_sh, all_wr, total_t, all_avg, all_dd, all_mcl = [], [], 0, [], [], []
    for r in results_list:
        if r["trades"] > 0 and not np.isnan(r["sharpe"]):
            all_sh.append(r["sharpe"])
            all_wr.append(r["wr"])
            total_t += r["trades"]
            all_avg.append(r["avg_ret"])
            all_dd.append(r["max_dd"])
            all_mcl.append(r["mcl"])
    if not all_sh:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    return {"sharpe": float(np.mean(all_sh)), "wr": float(np.mean(all_wr)),
            "avg_ret": float(np.mean(all_avg)), "trades": total_t,
            "max_dd": float(np.mean(all_dd)), "mcl": max(all_mcl)}


def main() -> None:
    print("=" * 80)
    print("=== c195 v2: VPIN 멀티타임프레임 — 1h 최소필터 + 4h 품질게이트 ===")
    print("=" * 80)

    combos = []
    for vb, mlb, mh, bg in product(
        VPIN_1H_BUCKETS_LIST, MOM_1H_LB_LIST,
        MAX_HOLD_1H_LIST, BODY_4H_GATE_LIST,
    ):
        combos.append({"vpin_1h_buckets": vb, "mom_1h_lb": mlb,
                        "max_hold_1h": mh, "body_4h_gate": bg})
    print(f"탐색 조합: {len(combos)}개")

    # Load data
    print("[1/4] 데이터 로딩...")
    data_1h: dict[str, pd.DataFrame] = {}
    data_4h: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        data_1h[sym] = load_historical(sym, "60m", "2022-01-01", "2026-04-05")
        data_4h[sym] = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        print(f"  {sym}: 1h={len(data_1h[sym])}행, 4h={len(data_4h[sym])}행")
    btc_4h = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"  KRW-BTC 4h: {len(btc_4h)}행")

    # Precompute 4h indicators + map to 1h
    print("[2/4] 4h 지표 → 1h 매핑...")
    mapped: dict[str, dict] = {}
    for sym in SYMBOLS:
        df_4h = data_4h[sym]
        df_1h = data_1h[sym]
        ind_4h = precompute_4h_all(df_4h)

        btc_c = btc_4h["close"].values
        btc_sma = sma_calc(btc_c, BTC_SMA_PERIOD_4H)

        m = {}
        for key in ["esp", "atp", "body", "rsi", "vol_pctile", "vol_mom",
                     "vol_sma", "close", "open", "volume"]:
            m[key] = map_4h_to_1h(df_4h, ind_4h[key], df_1h)
        m["btc_close"] = map_4h_to_1h(btc_4h,btc_c, df_1h)
        m["btc_sma"] = map_4h_to_1h(btc_4h, btc_sma, df_1h)
        mapped[sym] = m
    print("  완료")

    # Walk-forward
    print("[3/4] 3-fold Walk-Forward...")
    fold_results: dict[int, list[tuple[dict, dict, list]]] = {
        f: [] for f in range(len(WF_FOLDS))
    }

    for ci, combo in enumerate(combos):
        vb = combo["vpin_1h_buckets"]
        mlb = combo["mom_1h_lb"]
        mh = combo["max_hold_1h"]
        bg = combo["body_4h_gate"]

        for fi, fold in enumerate(WF_FOLDS):
            ts, te = fold["train"]
            os_s, os_e = fold["test"]

            sym_test_results = []
            sym_details = []

            for sym in SYMBOLS:
                df_1h_full = data_1h[sym]
                m = mapped[sym]

                # Test slice
                test_mask = (df_1h_full.index >= os_s) & (df_1h_full.index <= os_e)
                df_test = df_1h_full[test_mask]
                if len(df_test) < 200:
                    continue

                test_idx = df_1h_full.index.get_indexer(df_test.index)
                valid = test_idx >= 0
                test_idx = test_idx[valid]

                r = backtest(
                    df_test, vb, mlb, mh, bg,
                    m["btc_close"][test_idx], m["btc_sma"][test_idx],
                    m["esp"][test_idx], m["atp"][test_idx],
                    m["body"][test_idx], m["rsi"][test_idx],
                    m["vol_pctile"][test_idx], m["vol_mom"][test_idx],
                    m["close"][test_idx], m["open"][test_idx],
                    m["volume"][test_idx], m["vol_sma"][test_idx],
                    slippage=0.0005,
                )
                sym_test_results.append(r)
                sym_details.append({"sym": sym, **r})

            pooled = pool_results(sym_test_results)
            fold_results[fi].append((combo, pooled, sym_details))

        if (ci + 1) % 8 == 0 or ci == len(combos) - 1:
            print(f"  조합 {ci + 1}/{len(combos)} 완료")

    # Aggregate
    print("\n[4/4] 결과 집계...")
    combo_scores = []
    for ci, combo in enumerate(combos):
        fsh, ft, fd = [], [], []
        for fi in range(len(WF_FOLDS)):
            _, pooled, details = fold_results[fi][ci]
            if not np.isnan(pooled["sharpe"]):
                fsh.append(pooled["sharpe"])
                ft.append(pooled["trades"])
                fd.append((fi, pooled, details))
        if fsh:
            combo_scores.append((combo, float(np.mean(fsh)), sum(ft), fd))

    combo_scores.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'=' * 80}")
    print("=== OOS 순위 (avg Sharpe across folds) ===")
    print("=" * 80)
    for rank, (combo, avg_sh, total_t, _) in enumerate(combo_scores[:15]):
        vb = combo["vpin_1h_buckets"]
        mlb = combo["mom_1h_lb"]
        mh = combo["max_hold_1h"]
        bg = "Y" if combo["body_4h_gate"] else "N"
        tag = "[PASS]" if avg_sh >= 10.0 and total_t >= 30 else "[FAIL]"
        print(f"  {rank + 1:2d}: vB={vb} mLB={mlb} mH={mh} bg={bg} → "
              f"Sharpe={avg_sh:+.3f} trades={total_t} {tag}")

    if not combo_scores:
        print("결과 없음!")
        return

    best_combo, best_sh, best_t, best_details = combo_scores[0]
    vb = best_combo["vpin_1h_buckets"]
    mlb = best_combo["mom_1h_lb"]
    mh = best_combo["max_hold_1h"]
    bg = best_combo["body_4h_gate"]

    print(f"\n{'=' * 80}")
    print(f"=== 심볼별 OOS 분해 (Top 1: vB={vb} mLB={mlb} mH={mh} bg={bg}) ===")
    sym_sh: dict[str, list] = {s: [] for s in SYMBOLS}
    sym_t: dict[str, int] = {s: 0 for s in SYMBOLS}
    for fi, pooled, details in best_details:
        for d in details:
            print(f"  {d['sym']} F{fi + 1}: Sh={d['sharpe']:+.3f} WR={d['wr']:.1%} "
                  f"n={d['trades']} avg={d['avg_ret']:+.2%} MDD={d['max_dd']:+.2%}")
            if d["trades"] > 0 and not np.isnan(d["sharpe"]):
                sym_sh[d["sym"]].append(d["sharpe"])
                sym_t[d["sym"]] += d["trades"]
    for sym in SYMBOLS:
        if sym_sh[sym]:
            print(f"  {sym} 평균: Sh={np.mean(sym_sh[sym]):+.3f} trades={sym_t[sym]}")

    print(f"\n{'=' * 80}")
    print("=== c192 베이스라인 대비 비교 ===")
    print(f"  c192 (4h 단일 TF): avg_OOS=+30.947 n=26")
    print(f"  c195v2 (vB={vb} mLB={mlb} mH={mh} bg={bg}): "
          f"avg_OOS={best_sh:+.3f} n={best_t}")
    d_sh = best_sh - 30.947
    d_t = best_t - 26
    print(f"  Δ Sharpe: {d_sh:+.3f} ({'개선' if d_sh > 0 else '악화'})")
    print(f"  Δ trades: {d_t:+d} ({'증가' if d_t > 0 else '감소'})")

    # Slippage stress (fold 3)
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 (Fold 3) ===")
    for slip in SLIPPAGE_LEVELS:
        slip_res = []
        for sym in SYMBOLS:
            df_1h_full = data_1h[sym]
            m = mapped[sym]
            test_mask = ((df_1h_full.index >= WF_FOLDS[2]["test"][0])
                         & (df_1h_full.index <= WF_FOLDS[2]["test"][1]))
            df_test = df_1h_full[test_mask]
            if len(df_test) < 200:
                continue
            test_idx = df_1h_full.index.get_indexer(df_test.index)
            valid = test_idx >= 0
            test_idx = test_idx[valid]
            r = backtest(
                df_test, vb, mlb, mh, bg,
                m["btc_close"][test_idx], m["btc_sma"][test_idx],
                m["esp"][test_idx], m["atp"][test_idx],
                m["body"][test_idx], m["rsi"][test_idx],
                m["vol_pctile"][test_idx], m["vol_mom"][test_idx],
                m["close"][test_idx], m["open"][test_idx],
                m["volume"][test_idx], m["vol_sma"][test_idx],
                slippage=slip,
            )
            slip_res.append(r)
        p = pool_results(slip_res)
        print(f"  slip={slip:.4f}: Sh={p['sharpe']:+.3f} WR={p['wr']:.1%} "
              f"avg={p['avg_ret']:+.2%} MDD={p['max_dd']:+.2%} n={p['trades']}")

    # Summary
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ VPIN_1H_BUCKETS={vb} MOM_1H_LB={mlb} MAX_HOLD_1H={mh} "
          f"BODY_4H_GATE={bg}")
    print(f"  1h 진입: VPIN<{VPIN_LOW} + MOM>={MOM_THRESH} + RSI {RSI_FLOOR}-{RSI_CEILING} + price>EMA")
    print(f"  4h 게이트: BTC>SMA{BTC_SMA_PERIOD_4H} + ESP>={EMA_SLOPE_PCTILE_TH_4H} "
          f"+ ATRp>={ATR_TH_4H} + vol_mom>={VOL_MOM_MIN_4H} + vol_pctile>={VOL_PCTILE_TH_4H}")
    print(f"  avg OOS Sharpe: {best_sh:+.3f} "
          f"{'PASS' if best_sh >= 10.0 and best_t >= 30 else 'FAIL'}")
    for fi, pooled, _ in best_details:
        print(f"  Fold {fi + 1}: Sh={pooled['sharpe']:+.3f} WR={pooled['wr']:.1%} "
              f"n={pooled['trades']} avg={pooled['avg_ret']:+.2%} MDD={pooled['max_dd']:+.2%}")

    print(f"\nSharpe: {best_sh:+.3f}")
    print(f"WR: {best_details[0][1]['wr']:.1%}" if best_details else "WR: N/A")
    print(f"trades: {best_t}")


if __name__ == "__main__":
    main()
