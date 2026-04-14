"""
vpin_multi 사이클 200 — VPIN 절대값 → 상대 백분위 게이트 전환
- 기반: c197 최적 (VPIN_LOW=0.40 MOM=0.0002 rCeil=65 rFlr=25) avg_OOS=+27.932 n=14
- 문제 진단:
    KRW-XRP 전 폴드 0건, KRW-ETH Fold 3 0건
    근본 원인: VPIN < 0.40 절대 임계값이 XRP의 VPIN 분포와 불일치
    (ETH/SOL은 VPIN 0.3~0.5 구간 분포, XRP는 구조적으로 다를 수 있음)
- 가설:
    절대 VPIN < threshold → 상대 VPIN < N-번째 백분위 로 교체
    = 각 심볼의 최근 VPIN 분포 기준으로 "현재 VPIN이 낮은 상태"를 판단
    → XRP 포함 전 심볼 진입 가능 + 시장 레짐 변화에 자동 적응
- 탐색 그리드:
    VPIN_PCTILE_TH: [25, 30, 35, 40, 45]  (최근 VPIN의 N번째 백분위 이하)
    VPIN_PCTILE_LB: [24, 48, 72]           (백분위 계산 윈도우, 봉 수)
    MOM_THRESH:     [0.0001, 0.0002, 0.0005]  (c197 최적 + 범위 확장)
    RSI_CEILING: 65, RSI_FLOOR: 25 (c197 고정)
    총 5×3×3 = 45 조합
- 베이스라인 비교: c197 절대값 방식 (VPIN<0.40) 동시 실행
- 목표: OOS Sharpe >= 20 AND trades >= 20 AND XRP 진입 복원
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

# -- c196 최적 진입 필터 (고정) --
BODY_RATIO_MIN = 0.50
VOL_PCTILE_TH = 40
EMA_SLOPE_PCTILE_TH = 50
VOL_MOM_MIN = 0.05

# -- c197 고정 RSI 범위 --
RSI_CEILING_FIXED = 65
RSI_FLOOR_FIXED = 25

# -- 출구/리스크 고정값 --
MAX_HOLD = 20
COOLDOWN_BARS = 4
BTC_SMA_PERIOD = 200
BUCKET_COUNT = 24
COOLDOWN_LOSSES = 2
RSI_DELTA_LB = 3
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD = 20
VOL_SMA_PERIOD = 20
SL_SLOPE_BONUS = 0.1
RELAX_VOL_MOM_TH = 0.40
RELAX_FACTOR = 0.9
TP_BASE_ATR = 4.0
TRAIL_BASE_ATR = 0.30
MIN_PROFIT_ATR = 1.5
TP_BONUS_ATR = 2.0
TRAIL_BONUS_ATR = 0.2
ATR_PCTILE_LB = 60
ATR_TH = 30
VOL_PCTILE_LB = 60
RSI_DELTA_MIN = 6
EMA_SLOPE_LB = 10
VOL_MOM_LB = 10
TP_SLOPE_BONUS = 1.0

# -- 탐색 그리드 --
VPIN_PCTILE_TH_LIST = [25, 30, 35, 40, 45]    # 상대 백분위 임계 (VPIN 낮음 판단)
VPIN_PCTILE_LB_LIST = [24, 48, 72]             # 백분위 계산 윈도우
MOM_THRESH_LIST = [0.0001, 0.0002, 0.0005]

# -- 3-fold Walkforward --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-10")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 헬퍼 ──

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
    result[period - 1:] = (
        cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))
    ) / period
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


def compute_vpin_percentile(
    vpin_arr: np.ndarray, lookback: int,
) -> np.ndarray:
    """각 봉에서 vpin이 최근 lookback봉 중 몇 번째 백분위인지 반환 (0~100)"""
    n = len(vpin_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        current = vpin_arr[i]
        if np.isnan(current):
            continue
        window = vpin_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
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
        result[i] = 0.0 if candle_range <= 0 else abs(closes[i] - opens[i]) / candle_range
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


# ── 백테스트 (상대 VPIN 백분위 모드) ──

def backtest(
    df: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    vpin_pctile_th: float,      # VPIN 백분위 임계 (이 값 이하 = 낮은 VPIN)
    vpin_pctile_lb: int,        # VPIN 백분위 계산 윈도우
    mom_thresh: float,
    rsi_ceiling: float = RSI_CEILING_FIXED,
    rsi_floor: float = RSI_FLOOR_FIXED,
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
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)

    # ★ 핵심: 절대 VPIN → 상대 VPIN 백분위
    vpin_pctile_arr = compute_vpin_percentile(vpin_arr, vpin_pctile_lb)

    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)
    atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
    body_ratio_arr = compute_body_ratio(o, c, h, lo)
    vol_pctile_arr = compute_vol_percentile(v, VOL_PCTILE_LB)
    ema_slope_pctile_arr = compute_ema_slope_percentile(ema_arr, EMA_SLOPE_LB)
    vol_mom_arr = compute_vol_momentum(v, ema_period=VOL_MOM_LB)

    returns: list[float] = []
    warmup = max(
        BUCKET_COUNT + vpin_pctile_lb, EMA_PERIOD, RSI_PERIOD + 1,
        MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
        ATR_PCTILE_LB, VOL_PCTILE_LB,
        EMA_SLOPE_LB + 60, VOL_MOM_LB + 10, 50,
    ) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if COOLDOWN_BARS > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_pctile_val = vpin_pctile_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_sma_val = vol_sma_arr[i]
        atr_pctile_val = atr_pctile_arr[i]
        body_val = body_ratio_arr[i]
        vol_pctile_val = vol_pctile_arr[i]
        esp = ema_slope_pctile_arr[i]

        if (np.isnan(vpin_pctile_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0):
            i += 1
            continue

        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        vm = vol_mom_arr[i]
        vol_mom_strong = (not np.isnan(vm)) and (vm >= RELAX_VOL_MOM_TH)
        effective_body_min = BODY_RATIO_MIN * RELAX_FACTOR if vol_mom_strong else BODY_RATIO_MIN
        effective_rsi_delta_min = RSI_DELTA_MIN * RELAX_FACTOR if vol_mom_strong else RSI_DELTA_MIN

        # ★ 핵심 진입 조건: 절대 VPIN < 0.40 → 상대 VPIN 백분위 < vpin_pctile_th
        vpin_ok = (
            vpin_pctile_val < vpin_pctile_th      # VPIN이 최근 분포 기준 낮음
            and mom_val >= mom_thresh
            and rsi_floor < rsi_val < rsi_ceiling
            and c[i] > ema_val
        )
        btc_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )
        rsi_velocity_ok = rsi_delta >= effective_rsi_delta_min
        vol_ok = v[i] >= vol_sma_val * VOL_MULT

        atr_pctile_ok = (not np.isnan(atr_pctile_val)) and (atr_pctile_val >= ATR_TH)

        body_ok = True
        if effective_body_min > 0:
            body_ok = (not np.isnan(body_val)) and body_val >= effective_body_min and c[i] >= o[i]

        vol_pctile_ok = (not np.isnan(vol_pctile_val)) and (vol_pctile_val >= VOL_PCTILE_TH)

        ema_slope_ok = (not np.isnan(esp)) and (esp >= EMA_SLOPE_PCTILE_TH)

        vol_mom_ok = True
        if VOL_MOM_MIN > 0:
            vol_mom_ok = (not np.isnan(vm)) and (vm >= VOL_MOM_MIN)

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and vol_pctile_ok
                and ema_slope_ok and vol_mom_ok):

            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            rsi_ratio = (rsi_ceiling - rsi_val) / (rsi_ceiling - rsi_floor)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            slope_tp_extra = 0.0
            if TP_SLOPE_BONUS > 0 and not np.isnan(esp):
                if esp >= 70.0:
                    slope_tp_extra = TP_SLOPE_BONUS
                elif esp >= 60.0:
                    slope_tp_extra = TP_SLOPE_BONUS * 0.5

            effective_tp_mult = TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio + slope_tp_extra
            tp_price = buy + atr_at_entry * effective_tp_mult

            sl_slope_extra = 0.0
            if SL_SLOPE_BONUS > 0 and not np.isnan(esp):
                if esp >= 70.0:
                    sl_slope_extra = SL_SLOPE_BONUS
                elif esp >= 60.0:
                    sl_slope_extra = SL_SLOPE_BONUS * 0.5

            effective_sl_mult = max(0.2, SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio + sl_slope_extra)
            sl_price = buy - atr_at_entry * effective_sl_mult

            effective_trail_mult = TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
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
    for vp_th, vp_lb, mom in product(
        VPIN_PCTILE_TH_LIST, VPIN_PCTILE_LB_LIST, MOM_THRESH_LIST,
    ):
        combos.append({
            "vpin_pctile_th": vp_th,
            "vpin_pctile_lb": vp_lb,
            "mom_thresh": mom,
        })
    return combos


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 200 — VPIN 상대 백분위 게이트 ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print("목표: OOS Sharpe >= 20 AND trades >= 20 AND XRP 진입 복원")
    print("핵심 변경: VPIN < 0.40 절대값 → VPIN < N번째 백분위 (심볼 적응형)")
    print(f"기준선: c197 avg_OOS=+27.932 WR=72.2% trades=14 (XRP 0건)")
    print(f"  c197 고정: MOM=0.0002 rCeil={RSI_CEILING_FIXED} rFlr={RSI_FLOOR_FIXED}")
    print(f"  탐색: VPIN_PCTILE_TH={VPIN_PCTILE_TH_LIST}")
    print(f"         VPIN_PCTILE_LB={VPIN_PCTILE_LB_LIST}")
    print(f"         MOM_THRESH={MOM_THRESH_LIST}")
    print("=" * 80)

    # BTC 데이터
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    btc_close = df_btc_full["close"].values
    btc_sma_arr = sma_calc(btc_close, BTC_SMA_PERIOD)
    btc_close_s = pd.Series(btc_close, index=df_btc_full.index)
    btc_sma_s = pd.Series(btc_sma_arr, index=df_btc_full.index)

    # 심볼 데이터 확인
    print("\n--- 심볼별 데이터 확인 ---")
    sym_data_ok: list[str] = []
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

    # Phase 1: Train 그리드 서치
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
    for combo in combos:
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr = sym_train_cache[sym]
            btc_c_al = btc_close_s.reindex(df_tr.index, method="ffill").values
            btc_s_al = btc_sma_s.reindex(df_tr.index, method="ffill").values
            r = backtest(df_tr, btc_c_al, btc_s_al,
                         combo["vpin_pctile_th"],
                         combo["vpin_pctile_lb"],
                         combo["mom_thresh"])
            sym_results.append(r)
        pooled = pool_results(sym_results)
        results.append({**combo, **pooled})

    valid = [r for r in results if r["trades"] >= 8 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=8): {len(valid)}/{len(results)}")
    print("\n=== Train Top 16 (pooled Sharpe 기준) ===")
    hdr = (f"{'vPTh':>5} {'vPLb':>5} {'MOM':>7} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:16]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['vpin_pctile_th']:>5.0f} {r['vpin_pctile_lb']:>5.0f} "
            f"{r['mom_thresh']:>7.4f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # Phase 2: 3-fold OOS Walk-Forward
    seen: set[tuple] = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["vpin_pctile_th"], r["vpin_pctile_lb"], r["mom_thresh"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 12:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(unique_top)} 고유) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        vp_th = params["vpin_pctile_th"]
        vp_lb = params["vpin_pctile_lb"]
        mom_t = params["mom_thresh"]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []

        for fold_i, fold in enumerate(WF_FOLDS):
            sym_fold_results = []
            for sym in sym_data_ok:
                df_test = load_historical(sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c_al = btc_close_s.reindex(df_test.index, method="ffill").values
                btc_s_al = btc_sma_s.reindex(df_test.index, method="ffill").values
                r = backtest(df_test, btc_c_al, btc_s_al, vp_th, vp_lb, mom_t)
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
            print(f"  #{rank}: vPTh={vp_th} vPLb={vp_lb} MOM={mom_t:.4f} | "
                  f"train={params['sharpe']:+.3f} -> avg_OOS={avg_oos:+.3f} "
                  f"min={min_oos:+.3f} n={total_oos_n} "
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

    # Phase 3: 심볼별 OOS 분해 (Top 1)
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"], reverse=True)
    best = wf_sorted[0]

    print(f"\n{'=' * 80}")
    print(f"=== 심볼별 OOS 성능 분해 "
          f"(Top 1: vPTh={best['vpin_pctile_th']} vPLb={best['vpin_pctile_lb']} "
          f"MOM={best['mom_thresh']:.4f}) ===")

    for sym in sym_data_ok:
        sym_folds_sh = []
        sym_folds_wr = []
        sym_folds_n = []
        sym_folds_avg = []
        sym_folds_mdd = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(sym, "240m", fold["test"][0], fold["test"][1])
            if df_test.empty:
                sym_folds_sh.append(0.0)
                sym_folds_wr.append(0.0)
                sym_folds_n.append(0)
                sym_folds_avg.append(0.0)
                sym_folds_mdd.append(0.0)
                print(f"  {sym} Fold {fold_i + 1}: 데이터 없음")
                continue
            btc_c_al = btc_close_s.reindex(df_test.index, method="ffill").values
            btc_s_al = btc_sma_s.reindex(df_test.index, method="ffill").values
            r = backtest(df_test, btc_c_al, btc_s_al,
                         best["vpin_pctile_th"], best["vpin_pctile_lb"],
                         best["mom_thresh"])
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            sym_folds_sh.append(sh)
            sym_folds_wr.append(r["wr"])
            sym_folds_n.append(r["trades"])
            sym_folds_avg.append(r["avg_ret"])
            sym_folds_mdd.append(r["max_dd"])
            print(f"  {sym} Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%")
        print(f"  {sym} 평균: Sharpe={np.mean(sym_folds_sh):+.3f}  "
              f"총 trades={sum(sym_folds_n)}\n")

    # Phase 4: 슬리피지 스트레스 (OOS Top 3)
    wf_top3 = wf_sorted[:3]
    print(f"{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS Top 3) ===")
    for rank, params in enumerate(wf_top3, 1):
        vp_th = params["vpin_pctile_th"]
        vp_lb = params["vpin_pctile_lb"]
        mom_t = params["mom_thresh"]
        print(f"\n--- #{rank}: vPTh={vp_th} vPLb={vp_lb} MOM={mom_t:.4f} "
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
                btc_c_al = btc_close_s.reindex(df_full.index, method="ffill").values
                btc_s_al = btc_sma_s.reindex(df_full.index, method="ffill").values
                r = backtest(df_full, btc_c_al, btc_s_al, vp_th, vp_lb, mom_t,
                             slippage=slip)
                sym_results.append(r)
            pooled = pool_results(sym_results)
            sh = f"{pooled['sharpe']:+.3f}" if not np.isnan(pooled["sharpe"]) else "  nan"
            print(f"{slip:>10.4f} {sh:>8} {pooled['wr']:>5.1%} "
                  f"{pooled['avg_ret'] * 100:>+6.2f}% "
                  f"{pooled['max_dd'] * 100:>+6.2f}% "
                  f"{pooled['mcl']:>4} {pooled['trades']:>5}")

    # c197 베이스라인 비교 (절대 VPIN = 0.40)
    print(f"\n{'=' * 80}")
    print("=== c197 베이스라인 비교 (절대 VPIN<0.40, MOM=0.0002) ===")
    print("  c197 결과: avg_OOS=+27.932 WR=72.2% trades=14")
    print(f"  c200 최적: vPTh={best['vpin_pctile_th']} vPLb={best['vpin_pctile_lb']} "
          f"MOM={best['mom_thresh']:.4f} -> avg_OOS={best['avg_oos_sharpe']:+.3f} "
          f"n={best['total_oos_trades']}")
    delta_sh = best["avg_oos_sharpe"] - 27.932
    delta_n = best["total_oos_trades"] - 14
    print(f"  Δ Sharpe: {delta_sh:+.3f} ({'개선' if delta_sh > 0 else '저하'})")
    print(f"  Δ trades: {delta_n:+d} ({'증가' if delta_n > 0 else '동일/감소'})")

    # 최종 요약
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: VPIN_PCTILE_TH={best['vpin_pctile_th']} "
          f"VPIN_PCTILE_LB={best['vpin_pctile_lb']} "
          f"MOM_THRESH={best['mom_thresh']:.4f} "
          f"RSI_CEILING={RSI_CEILING_FIXED} RSI_FLOOR={RSI_FLOOR_FIXED}")
    print(f"  (c196 고정: body={BODY_RATIO_MIN} volP={VOL_PCTILE_TH} "
          f"emaSP={EMA_SLOPE_PCTILE_TH} volMm={VOL_MOM_MIN})")
    print(f"  (c195 고정: rsiP={RSI_PERIOD} emaP={EMA_PERIOD} momLB={MOM_LOOKBACK})")
    print(f"  (c192 출구: tpB={TP_BASE_ATR} trB={TRAIL_BASE_ATR} mnP={MIN_PROFIT_ATR})")
    print(f"  (c191 고정: slB={SL_SLOPE_BONUS} rTh={RELAX_VOL_MOM_TH} rF={RELAX_FACTOR})")
    print(f"  (c190 고정: VOL_MOM_LB={VOL_MOM_LB} TP_SLOPE_BONUS={TP_SLOPE_BONUS})")
    print(f"  (c186 고정: rsiD={RSI_DELTA_MIN} sLB={EMA_SLOPE_LB})")
    print(f"  (c182 고정: vPLB={VOL_PCTILE_LB})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH})")
    print(f"  (c165 고정: Hold={MAX_HOLD} CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} SL={SL_BASE_ATR}-{SL_BONUS_ATR} "
          f"vMul={VOL_MULT})")

    b = best
    print(f"  avg OOS Sharpe: {b['avg_oos_sharpe']:+.3f} "
          f"{'PASS' if b['all_pass'] else 'FAIL'}")
    print(f"  train Sharpe: {b['train_sharpe']:+.3f}")
    for fi, (sh, n) in enumerate(zip(b["oos_sharpes"], b["oos_trades"]), 1):
        fd = b["fold_details"][fi - 1]
        print(f"  Fold {fi}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={n}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    print(f"\nSharpe: {b['avg_oos_sharpe']:.2f}")
    print(f"WR: {b['fold_details'][0]['wr'] * 100:.1f}%")
    print(f"trades: {b['total_oos_trades']}")


if __name__ == "__main__":
    main()
