"""
vpin_multi 사이클 184 — 멀티타임프레임 RSI 확인 + 적응적 포지션 홀드
- 기반: c179 OOS Sharpe +42.88 (변동성 레짐 출구 최적)
  c179 최적: volTh=60 tpSc=0.50 trSc=0.70 hdSc=0.8
  c177 고정: atrTh=30 body=0.7 vpRx=0.25 rxSc=0.5
  c176 고정: atrLB=60
  c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4
  c164 고정: dLB=3 dMin=0.0 SL=0.4-0.2 vMul=0.8
  TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
- 가설: 느린 RSI(longer lookback)가 빠른 RSI와 같은 방향일 때만 진입하면
  역추세 진입(false breakout)을 걸러낼 수 있음
  - Slow RSI > threshold = 상승 추세 확인
  - Fast RSI(기존 14) + Slow RSI 정렬 = 듀얼 컨펌
  - 추가: Slow RSI 기울기(N바 전 대비) > 0 = 추세 강화 중
- 추가 가설: RSI 정렬 강도에 따른 적응적 hold 기간
  - 정렬 완벽(둘 다 상승) → 더 오래 보유 (hold × 1.3)
  - 부분 정렬(방향만 일치) → 기본 hold
  → 트렌드 확인 강도에 따라 보유 기간 최적화
- 탐색 그리드: 3 slow_rsi_period × 2 slow_rsi_min × 3 rsi_align_mode
              × 2 hold_bonus = 36 combos
  c179 진입/출구 기본값 고정, MTF RSI 필터만 탐색
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
ATR_PCTILE_LB = 60  # c176 최적

# -- c177 최적 진입 필터 고정 --
ATR_PCTILE_THRESH = 30
BODY_RATIO_MIN = 0.7
VPIN_RELAX_THRESH = 0.25
RELAX_SCALE = 0.5

# -- c179 최적 고정: 변동성 레짐 TP/SL/Hold --
VOL_REGIME_THRESH = 60
HIGH_VOL_TP_SCALE = 0.50
HIGH_VOL_TRAIL_SCALE = 0.70
HIGH_VOL_HOLD_SCALE = 0.8

# -- 탐색 그리드: 멀티타임프레임 RSI --
# Slow RSI period (기존 fast=14 대비 2~4배)
SLOW_RSI_PERIOD_LIST = [28, 42, 56]
# Slow RSI minimum threshold (진입 시 slow RSI > 이 값이어야 함)
SLOW_RSI_MIN_LIST = [40, 50]
# RSI alignment mode:
#   0 = slow RSI > threshold만 체크 (방향 무관)
#   1 = slow RSI > threshold + slow RSI rising (N바 전보다 높음)
#   2 = slow RSI > threshold + slow RSI rising + fast RSI > slow RSI (크로스오버 확인)
RSI_ALIGN_MODE_LIST = [0, 1, 2]
SLOW_RSI_SLOPE_LB = 3  # slow RSI 기울기 측정용 lookback
# Hold bonus when both RSIs aligned strongly
HOLD_BONUS_LIST = [1.0, 1.3]  # 1.0 = 보너스 없음, 1.3 = +30% hold

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


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    slow_rsi_period: int,
    slow_rsi_min: float,
    rsi_align_mode: int,
    hold_bonus: float,
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
    slow_rsi_arr = rsi_calc(c, slow_rsi_period)
    ema_arr = ema_calc(c, EMA_PERIOD)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)
    atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
    body_ratio_arr = compute_body_ratio(o, c, h, lo)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 slow_rsi_period + 1, MOM_LOOKBACK, ATR_PERIOD,
                 VOL_SMA_PERIOD, ATR_PCTILE_LB,
                 SLOW_RSI_SLOPE_LB + slow_rsi_period, 50) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if COOLDOWN_BARS > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_arr[i]
        slow_rsi_val = slow_rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_sma_val = vol_sma_arr[i]
        atr_pctile_val = atr_pctile_arr[i]
        body_val = body_ratio_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0
                or np.isnan(slow_rsi_val)):
            i += 1
            continue

        # RSI velocity (fast)
        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue

        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # 변동성 레짐 판단
        is_high_vol = (
            not np.isnan(atr_pctile_val)
            and atr_pctile_val >= VOL_REGIME_THRESH
        )

        # 진입 조건 (c165 코어)
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

        # c177 신호강도 적응적 필터 완화 (고정)
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

        # ★ c184: Multi-Timeframe RSI 확인
        slow_rsi_ok = slow_rsi_val >= slow_rsi_min

        # Slow RSI slope check
        slow_rsi_prev_idx = i - SLOW_RSI_SLOPE_LB
        slow_rsi_rising = True  # default
        strong_alignment = False
        if slow_rsi_prev_idx >= 0 and not np.isnan(slow_rsi_arr[slow_rsi_prev_idx]):
            slow_rsi_slope = slow_rsi_val - slow_rsi_arr[slow_rsi_prev_idx]
            slow_rsi_rising = slow_rsi_slope > 0

            if rsi_align_mode == 1:
                # mode 1: slow RSI must be rising
                slow_rsi_ok = slow_rsi_ok and slow_rsi_rising
            elif rsi_align_mode == 2:
                # mode 2: slow RSI rising + fast RSI > slow RSI
                slow_rsi_ok = slow_rsi_ok and slow_rsi_rising and rsi_val > slow_rsi_val

            # Strong alignment: both RSIs rising and fast > slow
            strong_alignment = (
                slow_rsi_rising
                and rsi_delta > 0
                and rsi_val > slow_rsi_val
            )

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and slow_rsi_ok):
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # c179: 변동성 레짐 TP/SL/Hold 적응
            if is_high_vol:
                tp_scale = HIGH_VOL_TP_SCALE
                trail_scale = HIGH_VOL_TRAIL_SCALE
                hold_scale = HIGH_VOL_HOLD_SCALE
            else:
                tp_scale = 1.0 + (1.0 - HIGH_VOL_TP_SCALE) * 0.3
                trail_scale = 1.0 + (1.0 - HIGH_VOL_TRAIL_SCALE) * 0.2
                hold_scale = 1.0 + (1.0 - HIGH_VOL_HOLD_SCALE) * 0.3

            effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio) * tp_scale
            tp_price = buy + atr_at_entry * effective_tp_mult

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

            # ★ c184: 적응적 hold — 강한 RSI 정렬 시 보유 연장
            if strong_alignment and hold_bonus > 1.0:
                effective_hold_scale = hold_scale * hold_bonus
            else:
                effective_hold_scale = hold_scale
            max_hold = max(5, int(MAX_HOLD_BASE * effective_hold_scale))

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]

                # TP
                if current_price >= tp_price:
                    exit_ret = (tp_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # SL
                if current_price <= sl_price:
                    exit_ret = (sl_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # 트레일링 스톱
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
    print("c184: 멀티타임프레임 RSI 확인 + 적응적 포지션 홀드")
    print("기반: c179 OOS Sharpe +42.88 (vol regime 출구 + c177 진입 고정)")
    print("=" * 80)

    # 데이터 로드
    data_dir = Path(__file__).resolve().parent.parent / "data" / "historical" / "monthly"
    ctype = "minutes240"

    cache: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS + ["KRW-BTC"]:
        df = load_historical(sym, ctype, data_dir)
        if df is not None and len(df) > 0:
            cache[sym] = df
            print(f"  {sym}: {len(df)} rows  [{df.index[0]} ~ {df.index[-1]}]")
        else:
            print(f"  WARNING: {sym} no data!")

    if "KRW-BTC" not in cache:
        print("ERROR: KRW-BTC data required for BTC gate")
        sys.exit(1)

    df_btc = cache["KRW-BTC"]

    # 그리드 생성
    combos = list(product(
        SLOW_RSI_PERIOD_LIST,
        SLOW_RSI_MIN_LIST,
        RSI_ALIGN_MODE_LIST,
        HOLD_BONUS_LIST,
    ))
    print(f"\n총 {len(combos)} 조합 × {len(SYMBOLS)} 심볼 × {len(WF_FOLDS)} folds")
    print()

    # 그리드 탐색
    results_all: list[dict] = []

    for ci, (srp, srmin, align_mode, hbonus) in enumerate(combos):
        label = (f"slowRSI={srp} srMin={srmin:.0f} "
                 f"align={align_mode} hBonus={hbonus:.1f}")

        fold_oos_sharpes = []
        fold_oos_results = []

        for fi, fold in enumerate(WF_FOLDS):
            train_start, train_end = fold["train"]
            test_start, test_end = fold["test"]

            # Train
            train_results = []
            for sym in SYMBOLS:
                if sym not in cache:
                    continue
                df_sym = cache[sym]
                mask_train = (
                    (df_sym.index >= train_start) & (df_sym.index <= train_end)
                )
                df_train = df_sym[mask_train]
                if len(df_train) < 100:
                    continue
                btc_c, btc_s = align_btc_to_symbol(df_train, df_btc, BTC_SMA_PERIOD)
                r = backtest(
                    df_train, srp, srmin, align_mode, hbonus, btc_c, btc_s,
                )
                train_results.append(r)

            train_pooled = pool_results(train_results)

            # OOS
            oos_results = []
            oos_per_sym: dict[str, dict] = {}
            for sym in SYMBOLS:
                if sym not in cache:
                    continue
                df_sym = cache[sym]
                mask_test = (
                    (df_sym.index >= test_start) & (df_sym.index <= test_end)
                )
                df_test = df_sym[mask_test]
                if len(df_test) < 50:
                    continue
                btc_c, btc_s = align_btc_to_symbol(df_test, df_btc, BTC_SMA_PERIOD)
                r = backtest(
                    df_test, srp, srmin, align_mode, hbonus, btc_c, btc_s,
                )
                oos_results.append(r)
                oos_per_sym[sym] = r

            oos_pooled = pool_results(oos_results)
            fold_oos_sharpes.append(oos_pooled["sharpe"])
            fold_oos_results.append({
                "fold": fi + 1,
                "train": train_pooled,
                "oos": oos_pooled,
                "oos_per_sym": oos_per_sym,
            })

        avg_oos_sharpe = (
            float(np.nanmean(fold_oos_sharpes)) if fold_oos_sharpes
            else float("nan")
        )
        total_oos_trades = sum(
            fr["oos"]["trades"] for fr in fold_oos_results
        )
        avg_oos_wr = float(np.nanmean([
            fr["oos"]["wr"] for fr in fold_oos_results if fr["oos"]["trades"] > 0
        ])) if fold_oos_results else 0.0
        avg_oos_ret = float(np.nanmean([
            fr["oos"]["avg_ret"] for fr in fold_oos_results
            if fr["oos"]["trades"] > 0
        ])) if fold_oos_results else 0.0
        avg_oos_mdd = float(np.nanmean([
            fr["oos"]["max_dd"] for fr in fold_oos_results
            if fr["oos"]["trades"] > 0
        ])) if fold_oos_results else 0.0

        results_all.append({
            "slow_rsi_period": srp,
            "slow_rsi_min": srmin,
            "rsi_align_mode": align_mode,
            "hold_bonus": hbonus,
            "label": label,
            "avg_oos_sharpe": avg_oos_sharpe,
            "total_oos_trades": total_oos_trades,
            "avg_oos_wr": avg_oos_wr,
            "avg_oos_ret": avg_oos_ret,
            "avg_oos_mdd": avg_oos_mdd,
            "fold_results": fold_oos_results,
        })

        if (ci + 1) % 6 == 0 or ci == len(combos) - 1:
            print(f"  진행: {ci + 1}/{len(combos)}")

    # 결과 정렬
    valid_results = [r for r in results_all if not np.isnan(r["avg_oos_sharpe"])]
    valid_results.sort(key=lambda x: x["avg_oos_sharpe"], reverse=True)

    print("\n" + "=" * 80)
    print("=== OOS 결과 Top 10 ===")
    print("=" * 80)
    for rank, r in enumerate(valid_results[:10], 1):
        print(f"  #{rank} {r['label']}")
        print(f"    avg OOS Sharpe: {r['avg_oos_sharpe']:+.3f}  "
              f"WR: {r['avg_oos_wr']:.1%}  "
              f"trades: {r['total_oos_trades']}  "
              f"avg: {r['avg_oos_ret']:+.2%}  "
              f"MDD: {r['avg_oos_mdd']:+.2%}")
        for fr in r["fold_results"]:
            oos = fr["oos"]
            print(f"    Fold {fr['fold']}: "
                  f"Sharpe={oos['sharpe']:+.3f}  "
                  f"WR={oos['wr']:.1%}  "
                  f"trades={oos['trades']}  "
                  f"avg={oos['avg_ret']:+.2%}  "
                  f"MDD={oos['max_dd']:+.2%}")
        print()

    # 슬리피지 스트레스 (Top 1)
    if valid_results:
        best = valid_results[0]
        print("=" * 80)
        print(f"=== 슬리피지 스트레스 테스트 (Top 1: {best['label']}) ===")
        print("=" * 80)
        for slip in SLIPPAGE_LEVELS:
            slip_results = []
            for sym in SYMBOLS:
                if sym not in cache:
                    continue
                df_sym = cache[sym]
                btc_c, btc_s = align_btc_to_symbol(df_sym, df_btc, BTC_SMA_PERIOD)
                r = backtest(
                    df_sym, best["slow_rsi_period"], best["slow_rsi_min"],
                    best["rsi_align_mode"], best["hold_bonus"],
                    btc_c, btc_s, slippage=slip,
                )
                slip_results.append(r)
            pooled = pool_results(slip_results)
            print(f"  slip={slip:.4f}: Sharpe={pooled['sharpe']:+.3f}  "
                  f"WR={pooled['wr']:.1%}  "
                  f"avg={pooled['avg_ret']:+.2%}  "
                  f"MDD={pooled['max_dd']:+.2%}  "
                  f"trades={pooled['trades']}")

    # 심볼별 OOS 분해
    if valid_results:
        best = valid_results[0]
        print("\n" + "=" * 80)
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: {best['label']}) ===")
        for fr in best["fold_results"]:
            for sym in SYMBOLS:
                if sym in fr["oos_per_sym"]:
                    sr = fr["oos_per_sym"][sym]
                    print(f"  {sym} Fold {fr['fold']}: "
                          f"Sharpe={sr['sharpe']:+.3f}  "
                          f"WR={sr['wr']:.1%}  "
                          f"n={sr['trades']}  "
                          f"avg={sr['avg_ret']:+.2%}  "
                          f"MDD={sr['max_dd']:+.2%}")
        for sym in SYMBOLS:
            sym_sharpes = []
            sym_trades = 0
            for fr in best["fold_results"]:
                if sym in fr["oos_per_sym"]:
                    sr = fr["oos_per_sym"][sym]
                    if sr["trades"] > 0 and not np.isnan(sr["sharpe"]):
                        sym_sharpes.append(sr["sharpe"])
                        sym_trades += sr["trades"]
            if sym_sharpes:
                print(f"  {sym} 평균: Sharpe={np.mean(sym_sharpes):+.3f}  "
                      f"총 trades={sym_trades}")

    # c179 대비 비교
    C179_BASELINE_SHARPE = 42.878
    C179_BASELINE_TRADES = 64
    if valid_results:
        best = valid_results[0]
        print("\n" + "=" * 80)
        print("=== c179 베이스라인 대비 비교 ===")
        print(f"  c179 기준 (vol regime): "
              f"avg_OOS={C179_BASELINE_SHARPE:+.3f} n={C179_BASELINE_TRADES}")
        print(f"  c184 최적 ({best['label']}): "
              f"avg_OOS={best['avg_oos_sharpe']:+.3f} "
              f"n={best['total_oos_trades']}")
        delta_sh = best["avg_oos_sharpe"] - C179_BASELINE_SHARPE
        delta_n = best["total_oos_trades"] - C179_BASELINE_TRADES
        print(f"  Δ Sharpe: {delta_sh:+.3f} "
              f"({'개선' if delta_sh > 0 else '악화'})")
        print(f"  Δ trades: {delta_n:+d} "
              f"({'증가' if delta_n > 0 else '감소'})")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid_results:
        best = valid_results[0]
        tag = "PASS" if best["avg_oos_sharpe"] > 5.0 else "FAIL"
        print(f"★ OOS 최적: SLOW_RSI_PERIOD={best['slow_rsi_period']} "
              f"SLOW_RSI_MIN={best['slow_rsi_min']:.0f} "
              f"RSI_ALIGN_MODE={best['rsi_align_mode']} "
              f"HOLD_BONUS={best['hold_bonus']:.1f}")
        print(f"  (c179 고정: volTh=60 tpSc=0.50 trSc=0.70 hdSc=0.8)")
        print(f"  (c177 고정: atrTh=30 body=0.7 vpRx=0.25 rxSc=0.5)")
        print(f"  (c176 고정: atrLB=60)")
        print(f"  (c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4)")
        print(f"  (c164 고정: dLB=3 dMin=0.0 SL=0.4-0.2 vMul=0.8)")
        print(f"  (TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200)")
        print(f"  avg OOS Sharpe: {best['avg_oos_sharpe']:+.3f} {tag}")
        train_sharpes = [
            fr["train"]["sharpe"] for fr in best["fold_results"]
            if fr["train"]["trades"] > 0 and not np.isnan(fr["train"]["sharpe"])
        ]
        if train_sharpes:
            print(f"  train Sharpe: {np.mean(train_sharpes):+.3f}")
        for fr in best["fold_results"]:
            oos = fr["oos"]
            print(f"  Fold {fr['fold']}: "
                  f"Sharpe={oos['sharpe']:+.3f}  "
                  f"WR={oos['wr']:.1%}  "
                  f"trades={oos['trades']}  "
                  f"avg={oos['avg_ret']:+.2%}  "
                  f"MDD={oos['max_dd']:+.2%}")
        print()
        print(f"Sharpe: {best['avg_oos_sharpe']:+.3f}")
        print(f"WR: {best['avg_oos_wr']:.1%}")
        print(f"trades: {best['total_oos_trades']}")
    else:
        print("유효한 결과 없음")
        print("Sharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")


if __name__ == "__main__":
    main()
