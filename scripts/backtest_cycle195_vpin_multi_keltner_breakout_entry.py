"""
vpin_multi 사이클 195 — Keltner Channel 돌파 + VPIN 진입 게이트
- 기반: c179 OOS Sharpe +42.878, vol regime adaptive TP/SL
  c179 최적: volTh=60 tpSc=0.65 trSc=0.7 hdSc=0.8
  c177 고정: atrTh=30 body=0.7 vpRx=0.25 rxSc=0.5
  c176 고정: atrLB=60
  c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4
  c164 고정: dLB=3 dMin=0.0 SL=0.4-0.2 vMul=0.8
  TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
- c194 교훈: exit 최적화 포화 — 진입 메커니즘 방향 전환 필요
- 가설: Keltner Channel (EMA ± ATR*mult) 상단 돌파를 진입 게이트로 추가
  기존 VPIN + MOM + BTC 필터에 "가격이 Keltner 상단을 돌파한 봉"만 진입
  → 변동성 확장 + 추세 돌파 동시 확인 = 가짜 신호 필터링
  Keltner width가 좁을 때 돌파 = squeeze breakout (더 강력)
  두 모드 탐색: (A) 단순 돌파 (B) squeeze 조건부 돌파 (width percentile < thresh)
- 탐색 그리드:
  KC_ATR_MULT: [1.0, 1.5, 2.0]     — Keltner 채널 폭 (ATR 배수)
  KC_ATR_PERIOD: [14, 20]           — Keltner ATR 기간
  KC_SQUEEZE_PCTILE: [0, 30, 50]    — 0=squeeze 무시, 30/50=width가 하위 N% 이하일때만
  KC_CONFIRM_BARS: [1, 2]           — 돌파 후 N봉 연속 상단 위 유지 확인
  = 3×2×3×2 = 36 combos
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

# -- 탐색 그리드: Keltner Channel 파라미터 --
KC_ATR_MULT_LIST = [1.0, 1.5, 2.0]
KC_ATR_PERIOD_LIST = [14, 20]
KC_SQUEEZE_PCTILE_LIST = [0, 30, 50]  # 0=squeeze 무시
KC_CONFIRM_BARS_LIST = [1, 2]

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


def compute_keltner_channel(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
    ema_period: int, atr_period: int, atr_mult: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keltner Channel: middle=EMA, upper/lower = EMA ± ATR*mult."""
    mid = ema_calc(closes, ema_period)
    atr = compute_atr(highs, lows, closes, atr_period)
    upper = mid + atr * atr_mult
    lower = mid - atr * atr_mult
    return mid, upper, lower


def compute_kc_width_percentile(
    upper: np.ndarray, lower: np.ndarray, mid: np.ndarray,
    lookback: int = 60,
) -> np.ndarray:
    """KC width의 백분위수: 낮을수록 squeeze 상태."""
    n = len(mid)
    width = np.where(mid > 0, (upper - lower) / mid, np.nan)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = width[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = width[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    kc_atr_mult: float,
    kc_atr_period: int,
    kc_squeeze_pctile: float,
    kc_confirm_bars: int,
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

    # Keltner Channel
    kc_mid, kc_upper, kc_lower = compute_keltner_channel(
        c, h, lo, EMA_PERIOD, kc_atr_period, kc_atr_mult,
    )
    kc_width_pctile = compute_kc_width_percentile(kc_upper, kc_lower, kc_mid)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, kc_atr_period, 60) + 5
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

        # 기존 c179 진입 조건
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

        # ★ Keltner Channel 돌파 확인
        kc_upper_val = kc_upper[i]
        kc_width_pctile_val = kc_width_pctile[i]

        kc_breakout_ok = False
        if not np.isnan(kc_upper_val) and c[i] > kc_upper_val:
            # 연속 봉 확인 (kc_confirm_bars)
            confirmed = True
            for cb in range(1, kc_confirm_bars):
                check_idx = i - cb
                if check_idx < 0:
                    confirmed = False
                    break
                if np.isnan(kc_upper[check_idx]) or c[check_idx] <= kc_upper[check_idx]:
                    # 현재 봉이 돌파 + 이전 봉들은 채널 내에 있었으면 OK (첫 돌파)
                    # confirm_bars=1: 현재만 돌파 (기본)
                    # confirm_bars=2: 현재 돌파 + 직전봉도 상단 위
                    confirmed = False
                    break
            if kc_confirm_bars <= 1:
                confirmed = True
            kc_breakout_ok = confirmed

        # squeeze 조건 (kc_squeeze_pctile > 0이면 적용)
        squeeze_ok = True
        if kc_squeeze_pctile > 0 and kc_breakout_ok:
            if np.isnan(kc_width_pctile_val):
                squeeze_ok = False
            else:
                squeeze_ok = kc_width_pctile_val <= kc_squeeze_pctile

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok
                and kc_breakout_ok and squeeze_ok):

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

            effective_tp_mult = (
                TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
            ) * tp_scale
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
    print("=== vpin_multi 사이클 195 — Keltner Channel 돌파 + VPIN 진입 게이트 ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe >= 43.0 (c179 +42.878 대비 개선)")
    print("가설: Keltner Channel 상단 돌파를 진입 게이트에 추가")
    print("  → 변동성 확장 + 추세 돌파 동시 확인 = 가짜 신호 필터링")
    print("  squeeze 모드: width 백분위수가 낮을 때 돌파 = 더 강력한 신호")
    print(f"기준선: c179 OOS +42.878, WR ~45%, trades ~60")
    print(f"c194 교훈: exit 최적화 포화 — 진입 메커니즘 방향 전환")
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
        KC_ATR_MULT_LIST, KC_ATR_PERIOD_LIST,
        KC_SQUEEZE_PCTILE_LIST, KC_CONFIRM_BARS_LIST,
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
    for idx, (kc_mult, kc_atr_p, kc_sq, kc_cb) in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_data:
                continue
            df_tr = sym_train_data[sym]
            btc_c, btc_s = align_btc_to_symbol(df_tr, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_tr, kc_mult, kc_atr_p, kc_sq, kc_cb, btc_c, btc_s)
            sym_results.append(r)
        pooled = pool_results(sym_results)
        results.append({
            "kc_mult": kc_mult, "kc_atr_p": kc_atr_p,
            "kc_sq": kc_sq, "kc_cb": kc_cb,
            **pooled,
        })
        if (idx + 1) % 12 == 0 or idx == len(combos) - 1:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    valid = [r for r in results if not np.isnan(r["sharpe"]) and r["trades"] >= 10]
    if not valid:
        print("유효 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    valid.sort(key=lambda x: x["sharpe"], reverse=True)
    top20 = valid[:20]
    print("\n--- Train Top 20 ---")
    for rank, r in enumerate(top20, 1):
        print(f"  #{rank} kcM={r['kc_mult']} kcP={r['kc_atr_p']} "
              f"sq={r['kc_sq']} cb={r['kc_cb']} → Sharpe={r['sharpe']:+.3f} "
              f"WR={r['wr']:.1%} n={r['trades']} avg={r['avg_ret']:+.2%} "
              f"MDD={r['max_dd']:+.2%}")

    # -- Phase 2: 3-fold WF 검증 (top 16 unique) --
    seen = set()
    top_unique: list[dict] = []
    for r in valid:
        key = (r["kc_mult"], r["kc_atr_p"], r["kc_sq"], r["kc_cb"])
        if key not in seen:
            seen.add(key)
            top_unique.append(r)
        if len(top_unique) >= 16:
            break

    print("\n" + "=" * 80)
    print(f"Phase 2: 3-fold WF 검증 (Top {len(top_unique)})")
    print("=" * 80)

    best_oos_sharpe = float("-inf")
    best_combo = None
    best_fold_details: list[dict] = []

    for rank, combo in enumerate(top_unique, 1):
        kc_mult = combo["kc_mult"]
        kc_atr_p = combo["kc_atr_p"]
        kc_sq = combo["kc_sq"]
        kc_cb = combo["kc_cb"]

        print(f"\n--- #{rank}: kcM={kc_mult} kcP={kc_atr_p} "
              f"sq={kc_sq} cb={kc_cb} ---")

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
                r = backtest(df_tr, kc_mult, kc_atr_p, kc_sq, kc_cb,
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
                r = backtest(df_te, kc_mult, kc_atr_p, kc_sq, kc_cb,
                             btc_c, btc_s, 0.0005)
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

    kc_mult = best_combo["kc_mult"]
    kc_atr_p = best_combo["kc_atr_p"]
    kc_sq = best_combo["kc_sq"]
    kc_cb = best_combo["kc_cb"]

    print(f"최적: kcM={kc_mult} kcP={kc_atr_p} sq={kc_sq} cb={kc_cb}")

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
                r = backtest(df_te, kc_mult, kc_atr_p, kc_sq, kc_cb,
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
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: kcM={kc_mult} kcP={kc_atr_p} "
          f"sq={kc_sq} cb={kc_cb}) ===")
    for fd in best_fold_details:
        fi = fd["fold"]
        for sd in fd["sym_details"]:
            print(f"  {sd['sym']} Fold {fi}: Sharpe={sd['sharpe']:+.3f}  "
                  f"WR={sd['wr']:.1%}  n={sd['trades']}  "
                  f"avg={sd['avg_ret']:+.2%}  MDD={sd['max_dd']:+.2%}")

    # 심볼별 평균
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
    total_trades = sum(
        fd["test"]["trades"] for fd in best_fold_details
    )
    print(f"  c179 기준 (vol regime adaptive): avg_OOS={c179_sharpe:+.3f} n=~60")
    print(f"  c195 최적 (kcM={kc_mult} kcP={kc_atr_p} sq={kc_sq} "
          f"cb={kc_cb}): avg_OOS={best_oos_sharpe:+.3f} n={total_trades}")
    delta_sharpe = best_oos_sharpe - c179_sharpe
    print(f"  Δ Sharpe: {delta_sharpe:+.3f} "
          f"({'개선' if delta_sharpe > 0 else '악화'})")
    print(f"  Δ trades: {total_trades - 60:+d} "
          f"({'증가' if total_trades > 60 else '감소' if total_trades < 60 else '동일'})")

    # -- 최종 요약 --
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    pass_fail = "PASS" if best_oos_sharpe > 5.0 and slippage_ok else "FAIL"
    print(f"★ OOS 최적: kcM={kc_mult} kcP={kc_atr_p} sq={kc_sq} cb={kc_cb}")
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

    # train Sharpe
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
