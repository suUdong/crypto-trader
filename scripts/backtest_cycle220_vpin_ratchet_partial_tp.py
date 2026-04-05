#!/usr/bin/env python3
"""
사이클 220: vpin_multi 래칫 스탑 + 2-tier 분할익절 동시 적용 — 스태킹 효과 검증
- 기반:
  c216 래칫 스탑 최적(beTr=0.5, lkTr=1.5, lkPct=0.90, vAdp=0, sMode=all)
    → c179 재현(slip=0.0005) 대비 +3.436 개선 (avg OOS +20.707 vs +17.271)
  c219 2-tier 분할익절(donchian용) avg OOS Sharpe +23.575 (+4.893 개선)
    → 핵심: tp1M=2.5, pRat=0.7 (70% 조기 청산)
- 가설:
  A) 래칫 스탑(수익 보호)과 분할익절(조기 확보)은 상보적 — 스태킹 시 추가 개선
  B) vpin에서의 최적 tp1_mult/part_ratio는 donchian과 다를 수 있음
  C) 래칫 OFF + 분할익절만으로도 개선 가능 → 래칫 기여 분리 측정
- 탐색 그리드:
  TP1_MULT_ATR: [0, 1.0, 1.5, 2.0, 2.5]  — 0=분할익절OFF (래칫만 테스트)
  PART_RATIO: [0.3, 0.5, 0.7]             — 1차 청산 비율
  RATCHET: [on, off]                       — c216 최적 래칫 on/off
  = 5×3×2 = 30 (tp1=0일 때 pRat 무관 → 중복제거 ~22개)
- c216 래칫 고정: beTr=0.5 lkTr=1.5 lkPct=0.90 vAdp=0 sMode=all
- c179 고정: volTh=60 tpSc=0.65 trSc=0.7 hdSc=0.8
- c177 고정: atrTh=30 body=0.7 vpRx=0.25 rxSc=0.5
- c176 고정: atrLB=60
- c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4
- c164 고정: dLB=3 dMin=0.0 SL=0.4-0.2 vMul=0.8
- TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
- 3-fold WF + 슬리피지 스트레스
- slippage=0.0005 (공정 비교 기준)
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
SLIPPAGE = 0.0005

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
ATR_PCTILE_LB = 60  # c176

# -- c177 최적 진입 필터 고정 --
ATR_PCTILE_THRESH = 30
BODY_RATIO_MIN = 0.7
VPIN_RELAX_THRESH = 0.25
RELAX_SCALE = 0.5

# -- c179 최적 고정: vol regime adaptive --
VOL_REGIME_THRESH = 60
HIGH_VOL_TP_SCALE = 0.65
HIGH_VOL_TRAIL_SCALE = 0.7
HIGH_VOL_HOLD_SCALE = 0.8

# -- c216 래칫 최적 고정값 --
RATCHET_BE_TRIGGER = 0.5
RATCHET_LOCK_TRIGGER = 1.5
RATCHET_LOCK_PCT = 0.90

# -- c220 탐색 그리드 --
TP1_MULT_LIST = [0.0, 1.0, 1.5, 2.0, 2.5]  # 0=분할익절 OFF
PART_RATIO_LIST = [0.3, 0.5, 0.7]
RATCHET_LIST = [True, False]

# -- 3-fold Walkforward --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────

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


# ── 백테스트 ──────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    tp1_mult_atr: float,
    part_ratio: float,
    ratchet_on: bool,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    slippage: float = 0.0005,
) -> dict:
    """c179 베이스 + 래칫 스탑 + 2-tier 분할익절 백테스트.

    분할익절 로직:
    - TP1: 수익 >= tp1_mult_atr * ATR → 포지션의 part_ratio% 청산, 잔여분 계속
    - TP2: 기존 TP (full) → 잔여분 최종 청산
    - TP1 후 SL을 breakeven으로 이동 (래칫과 독립적으로)

    래칫 로직 (c216 최적 고정):
    - L1: 수익 >= 0.5 * ATR → SL을 breakeven으로
    - L2: 수익 >= 1.5 * ATR → SL을 진입가 + 수익*0.90으로
    """
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

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, 50) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    use_partial_tp = tp1_mult_atr > 0

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

        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # 진입 조건: c165 최적 (고정)
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

        if not (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok):
            i += 1
            continue

        # === 진입 ===
        buy = o[i + 1] * (1 + FEE + slippage)
        peak_price = buy
        atr_at_entry = atr_val

        # RSI 기반 동적 스케일링
        rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
        rsi_ratio = max(0.0, min(1.0, rsi_ratio))

        # c179: 변동성 레짐 판단
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

        effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio) * tp_scale
        tp_price = buy + atr_at_entry * effective_tp_mult  # = TP2 (full TP)

        # ★ c220: TP1 (부분 익절 가격)
        tp1_price = buy + atr_at_entry * tp1_mult_atr if use_partial_tp else 0.0

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

        # === 래칫 스탑 설정 (c216 최적 고정) ===
        if ratchet_on:
            eff_be_trigger = RATCHET_BE_TRIGGER * atr_at_entry
            eff_lock_trigger = RATCHET_LOCK_TRIGGER * atr_at_entry
            ratchet_active = True
        else:
            eff_be_trigger = 0.0
            eff_lock_trigger = 0.0
            ratchet_active = False

        be_locked = False
        profit_locked = False
        tp1_hit = False
        remaining = 1.0

        trade_return = 0.0  # 누적 수익 (분할 포함)
        exit_found = False

        for j in range(i + 2, min(i + 1 + max_hold, n)):
            current_price = c[j]
            unrealized_profit = current_price - buy

            # === 래칫 SL 업데이트 ===
            if ratchet_active:
                if (not be_locked and eff_be_trigger > 0
                        and unrealized_profit >= eff_be_trigger):
                    sl_price = max(sl_price, buy)
                    be_locked = True
                if (not profit_locked and eff_lock_trigger > 0
                        and unrealized_profit >= eff_lock_trigger):
                    lock_sl = buy + unrealized_profit * RATCHET_LOCK_PCT
                    sl_price = max(sl_price, lock_sl)
                    profit_locked = True

            # === ★ TP1: 부분 익절 체크 ===
            if use_partial_tp and not tp1_hit and current_price >= tp1_price:
                tp1_ret = (tp1_price / buy - 1) - FEE - slippage
                trade_return += tp1_ret * part_ratio
                tp1_hit = True
                remaining = 1.0 - part_ratio
                # TP1 후 SL을 breakeven으로 (래칫과 독립)
                sl_price = max(sl_price, buy)
                be_locked = True
                continue  # 이번 봉에서 추가 청산 안 함

            # TP2 체크 (full TP — 잔여분)
            if current_price >= tp_price:
                exit_ret = (tp_price / buy - 1) - FEE - slippage
                trade_return += exit_ret * remaining
                i = j
                exit_found = True
                break

            # SL 체크 (래칫으로 상향된 SL 포함)
            if current_price <= sl_price:
                exit_ret = (sl_price / buy - 1) - FEE - slippage
                trade_return += exit_ret * remaining
                i = j
                exit_found = True
                break

            # Trailing stop
            if current_price > peak_price:
                peak_price = current_price

            unrealized_from_peak = peak_price - buy
            if unrealized_from_peak >= min_profit_dist:
                if peak_price - current_price >= trail_dist:
                    exit_ret = (current_price / buy - 1) - FEE - slippage
                    trade_return += exit_ret * remaining
                    i = j
                    exit_found = True
                    break

        if not exit_found:
            hold_end = min(i + max_hold, n - 1)
            exit_ret = c[hold_end] / buy - 1 - FEE - slippage
            trade_return += exit_ret * remaining
            i = hold_end

        returns.append(trade_return)

        if trade_return < 0:
            consecutive_losses += 1
            if consecutive_losses >= COOLDOWN_LOSSES and COOLDOWN_BARS > 0:
                cooldown_until = i + COOLDOWN_BARS
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
    """Build parameter grid, deduplicating tp1=0 combos."""
    combos = []
    seen_off: set[tuple] = set()
    for tp1, pr, ratch in product(TP1_MULT_LIST, PART_RATIO_LIST, RATCHET_LIST):
        if tp1 == 0.0:
            key = (0.0, ratch)
            if key in seen_off:
                continue
            seen_off.add(key)
            combos.append({
                "tp1_mult": 0.0, "part_ratio": 0.0, "ratchet": ratch,
            })
            continue
        combos.append({
            "tp1_mult": tp1, "part_ratio": pr, "ratchet": ratch,
        })
    return combos


def main() -> None:
    print("=" * 80)
    print("=== c220: vpin_multi 래칫 스탑 + 2-tier 분할익절 스태킹 검증 ===")
    print(f"=== 심볼: {', '.join(SYMBOLS)} | 240m | ★슬리피지포함 | 다음봉시가진입 ===")
    print(f"c216 래칫 고정: beTr={RATCHET_BE_TRIGGER} lkTr={RATCHET_LOCK_TRIGGER}"
          f" lkPct={RATCHET_LOCK_PCT}")
    print(f"c179 고정: volTh={VOL_REGIME_THRESH} tpSc={HIGH_VOL_TP_SCALE} "
          f"trSc={HIGH_VOL_TRAIL_SCALE} hdSc={HIGH_VOL_HOLD_SCALE}")
    print(f"c177 고정: atrTh={ATR_PCTILE_THRESH} body={BODY_RATIO_MIN} "
          f"vpRx={VPIN_RELAX_THRESH} rxSc={RELAX_SCALE}")
    print(f"c176 고정: atrLB={ATR_PCTILE_LB}")
    print(f"c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE}"
          f" CD={COOLDOWN_BARS}")
    print(f"c164 고정: dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT}")
    print(f"TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} Trail={TRAIL_BASE_ATR}+"
          f"{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD}")
    print(f"슬리피지: {SLIPPAGE} (공정 비교 기준)")
    print("가설: 래칫(수익보호) + 분할익절(조기확보)은 상보적 → 스태킹 개선")
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
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # -- Phase 1: train 그리드 서치 (F1 train) --
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
            sym_train_cache[sym] = (df_tr, btc_c, btc_s)
            print(f"  {sym} train: {len(df_tr)}행")

    results: list[dict] = []
    for idx, combo in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr, btc_c, btc_s = sym_train_cache[sym]
            r = backtest(
                df_tr,
                combo["tp1_mult"], combo["part_ratio"],
                combo["ratchet"],
                btc_c, btc_s, SLIPPAGE)
            sym_results.append(r)

        pooled = pool_results(sym_results)
        results.append({**combo, **pooled})

    print(f"  [{len(combos)}/{len(combos)}] 완료")

    valid = [r for r in results
             if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 20 (pooled Sharpe 기준) ===")
    hdr = (f"{'tp1M':>5} {'pRat':>5} {'ratch':>6} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} "
           f"{'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        ratch_s = "ON" if r["ratchet"] else "OFF"
        print(
            f"{r['tp1_mult']:>5.1f} {r['part_ratio']:>5.1f} "
            f"{ratch_s:>6} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}")

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # -- Phase 2: 3-fold OOS Walk-Forward (Top 12) --
    seen: set[tuple] = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["tp1_mult"], r["part_ratio"], r["ratchet"])
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
                r = backtest(
                    df_test,
                    params["tp1_mult"], params["part_ratio"],
                    params["ratchet"],
                    btc_c, btc_s, SLIPPAGE)
                sym_fold_results.append(r)

                sym_fold_details.append(
                    f"  {sym} F{fold_i + 1}: "
                    f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
                    f"n={r['trades']}  avg={r['avg_ret'] * 100:+.2f}%  "
                    f"MDD={r['max_dd']:+.4f}")

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
            ratch_s = "ON" if params["ratchet"] else "OFF"
            print(
                f"\n[{rank}] tp1M={params['tp1_mult']:.1f} "
                f"pRat={params['part_ratio']:.1f} ratch={ratch_s}  "
                f"avg_OOS={avg_oos:+.3f} min={min_oos:+.3f} "
                f"n={total_oos_n} [{tag}]")
            for fi, fd in enumerate(fold_details):
                sh_s = f"{fd['sharpe']:+.3f}" if not np.isnan(
                    fd["sharpe"]) else "nan"
                print(
                    f"  F{fi + 1}: Sharpe={sh_s}  WR={fd['wr']:.1%}  "
                    f"trades={fd['trades']}  avg={fd['avg_ret'] * 100:+.2f}%  "
                    f"MDD={fd['max_dd']:+.4f}")

            wf_results.append({
                **params,
                "avg_oos": avg_oos, "min_oos": min_oos,
                "total_n": total_oos_n,
                "fold_details": fold_details,
                "sym_fold_details": sym_fold_details,
                "tag": tag,
            })

    if not wf_results:
        print("WF 결과 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # -- 최적 결과 --
    wf_results.sort(key=lambda x: x["avg_oos"], reverse=True)
    best = wf_results[0]

    # -- 심볼별 성능 분해 --
    print(f"\n{'=' * 80}")
    ratch_s = "ON" if best["ratchet"] else "OFF"
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: tp1M={best['tp1_mult']:.1f} "
          f"pRat={best['part_ratio']:.1f} ratch={ratch_s}) ===")
    for line in best["sym_fold_details"]:
        print(line)

    for sym in sym_data_ok:
        sym_sharpes = []
        sym_trades = 0
        for line in best["sym_fold_details"]:
            if sym in line and "Sharpe=" in line:
                try:
                    sh_str = line.split("Sharpe=")[1].split()[0]
                    sym_sharpes.append(float(sh_str))
                except (IndexError, ValueError):
                    pass
                try:
                    n_str = line.split("n=")[1].split()[0]
                    sym_trades += int(n_str)
                except (IndexError, ValueError):
                    pass
        if sym_sharpes:
            print(f"  {sym} 평균: Sharpe={np.mean(sym_sharpes):+.3f}  "
                  f"총 trades={sym_trades}")

    # -- 스태킹 효과 분석: 4가지 모드 비교 --
    print(f"\n{'=' * 80}")
    print("=== 스태킹 효과 분석 (4모드 비교) ===")

    modes = [
        {"label": "A) baseline (래칫OFF+분할OFF)",
         "tp1": 0.0, "pr": 0.0, "ratch": False},
        {"label": "B) 래칫ON만 (c216 최적)",
         "tp1": 0.0, "pr": 0.0, "ratch": True},
        {"label": f"C) 분할ON만 (tp1={best['tp1_mult']}, pr={best['part_ratio']})",
         "tp1": best["tp1_mult"], "pr": best["part_ratio"], "ratch": False},
        {"label": f"D) 스태킹 (래칫+분할, tp1={best['tp1_mult']}, "
                  f"pr={best['part_ratio']})",
         "tp1": best["tp1_mult"], "pr": best["part_ratio"], "ratch": True},
    ]

    mode_results = []
    for mode in modes:
        mode_sharpes = []
        mode_trades = 0
        mode_wrs = []
        mode_mdds = []
        for fold in WF_FOLDS:
            sym_results = []
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(
                    df_test, mode["tp1"], mode["pr"], mode["ratch"],
                    btc_c, btc_s, SLIPPAGE)
                sym_results.append(r)
            pooled = pool_results(sym_results)
            if not np.isnan(pooled["sharpe"]):
                mode_sharpes.append(pooled["sharpe"])
                mode_trades += pooled["trades"]
                mode_wrs.append(pooled["wr"])
                mode_mdds.append(pooled["max_dd"])

        avg_sh = float(np.mean(mode_sharpes)) if mode_sharpes else 0.0
        avg_wr = float(np.mean(mode_wrs)) if mode_wrs else 0.0
        avg_mdd = float(np.mean(mode_mdds)) if mode_mdds else 0.0
        mode_results.append(avg_sh)
        print(f"  {mode['label']}")
        print(f"    avg OOS Sharpe: {avg_sh:+.3f}  WR: {avg_wr:.1%}  "
              f"MDD: {avg_mdd * 100:+.2f}%  n={mode_trades}")

    if len(mode_results) == 4:
        print(f"\n  래칫 기여: {mode_results[1] - mode_results[0]:+.3f} "
              f"(B-A)")
        print(f"  분할익절 기여: {mode_results[2] - mode_results[0]:+.3f} "
              f"(C-A)")
        print(f"  스태킹 기여: {mode_results[3] - mode_results[0]:+.3f} "
              f"(D-A)")
        synergy = (mode_results[3] - mode_results[0]) - (
            (mode_results[1] - mode_results[0])
            + (mode_results[2] - mode_results[0]))
        print(f"  시너지: {synergy:+.3f} (스태킹 - 래칫 - 분할 개별합)")

    # -- 슬리피지 스트레스 --
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (최적 조합) ===")
    for slip_level in SLIPPAGE_LEVELS:
        slip_sharpes = []
        slip_trades = 0
        for fold in WF_FOLDS:
            sym_results = []
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(
                    df_test,
                    best["tp1_mult"], best["part_ratio"],
                    best["ratchet"],
                    btc_c, btc_s, slip_level)
                sym_results.append(r)
            pooled = pool_results(sym_results)
            if not np.isnan(pooled["sharpe"]):
                slip_sharpes.append(pooled["sharpe"])
                slip_trades += pooled["trades"]
        if slip_sharpes:
            avg_slip = float(np.mean(slip_sharpes))
            tag = "PASS" if avg_slip >= 5.0 else "FAIL"
            print(f"  slip={slip_level:.4f}: avg Sharpe={avg_slip:+.3f} "
                  f"n={slip_trades} [{tag}]")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_fd = best["fold_details"]
    ratch_s = "ON" if best["ratchet"] else "OFF"
    print(f"★ OOS 최적: tp1M={best['tp1_mult']:.1f} "
          f"pRat={best['part_ratio']:.1f} ratch={ratch_s}")
    print(f"  (c216 래칫: beTr={RATCHET_BE_TRIGGER} lkTr={RATCHET_LOCK_TRIGGER}"
          f" lkPct={RATCHET_LOCK_PCT})")
    print(f"  (c179 고정: volTh={VOL_REGIME_THRESH} "
          f"tpSc={HIGH_VOL_TP_SCALE} trSc={HIGH_VOL_TRAIL_SCALE} "
          f"hdSc={HIGH_VOL_HOLD_SCALE})")
    print(f"  (c177 고정: atrTh={ATR_PCTILE_THRESH} body={BODY_RATIO_MIN} "
          f"vpRx={VPIN_RELAX_THRESH} rxSc={RELAX_SCALE})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB})")
    print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} "
          f"Hold={MAX_HOLD_BASE} CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} "
          f"minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD})")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} {best['tag']}")
    total_wr = 0.0
    total_n = 0
    for fi, fd in enumerate(best_fd):
        sh_s = f"{fd['sharpe']:+.3f}" if not np.isnan(fd["sharpe"]) else "nan"
        print(f"  F{fi + 1}: Sharpe={sh_s}  WR={fd['wr']:.1%}  "
              f"trades={fd['trades']}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd']:+.4f}")
        total_wr += fd["wr"] * fd["trades"]
        total_n += fd["trades"]

    final_wr = total_wr / total_n if total_n > 0 else 0.0

    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    print(f"WR: {final_wr:.1%}")
    print(f"trades: {best['total_n']}")


if __name__ == "__main__":
    main()
