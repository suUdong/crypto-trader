"""
사이클 212: c179 베이스 + 래칫 스탑 (breakeven lock + profit lock) 3-fold WF
- 기반: c179 OOS Sharpe +42.878 (vol regime adaptive) — 현 최적
- 실패 분석 (c200~c211):
  1. 진입필터 추가(CMF/OBV/RSI div/MACD) → 좋은 진입까지 차단 → 악화
  2. 시그널강도 TP/SL 스케일링 → 복잡성만 증가 → 악화
  3. 적응적 청산(모멘텀반전/시간감쇠/거래량) → fat-tail 파괴 → 악화
  4. 공통 원인: c179 진입+청산 로직 자체가 이미 높은 완성도
- 가설:
  래칫 스탑 — 진입/TP/Trail 100% 유지, SL만 단계적 상향
  Level 1: 수익이 BE_TRIGGER ATR 도달 → SL을 진입가(breakeven)로 이동
  Level 2: 수익이 LOCK_TRIGGER ATR 도달 → SL을 진입가 + LOCK_PCT * 수익으로 이동
  → 기존 trailing stop과 독립적으로 작동 (둘 중 높은 SL 적용)
  → fat-tail 수익은 유지하되, 큰 수익이 0 또는 손실로 반전하는 케이스 방지
  → c179의 문제: 큰 unrealized profit이 trail 못 잡고 SL까지 하락하는 구간 존재
- c179 100% 동일 진입 + c179 동일 TP/Trail
- 탐색 그리드:
  BE_TRIGGER: [0.0, 1.0, 1.5, 2.0]       — breakeven 이동 트리거 (ATR 배수, 0=OFF)
  LOCK_TRIGGER: [0.0, 2.0, 2.5, 3.0]     — profit lock 트리거 (ATR 배수, 0=OFF)
  LOCK_PCT: [0.3, 0.5, 0.7]              — lock할 수익 비율
  = 4×4×3 = 48조합 (가볍게 시작)
  + 슬리피지 스트레스 (0.0010 고정)
- 3-fold WF + 슬리피지포함 | 다음봉시가진입
- 목표: avg OOS Sharpe > 42.878 (c179 개선)
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
SLIPPAGE = 0.0010

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

# -- c212 탐색 그리드: 래칫 스탑 --
BE_TRIGGER_LIST = [0.0, 1.0, 1.5, 2.0]       # breakeven trigger (ATR 배수)
LOCK_TRIGGER_LIST = [0.0, 2.0, 2.5, 3.0]     # profit lock trigger (ATR 배수)
LOCK_PCT_LIST = [0.3, 0.5, 0.7]              # lock할 수익 비율
# 총 조합: 4×4×3 = 48

# -- 3-fold Walkforward --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]


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
    be_trigger: float,
    lock_trigger: float,
    lock_pct: float,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
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

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, 50) + 5
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

        # ★ 진입 조건: c179 100% 동일
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

            buy = o[i + 1] * (1 + FEE + SLIPPAGE)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링 (c179 동일)
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

            # TP (c179 동일)
            effective_tp_mult = (
                (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio) * tp_scale
            )
            tp_price = buy + atr_at_entry * effective_tp_mult

            # SL (c179 동일)
            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)
            if is_high_vol:
                effective_sl_mult *= (1.0 - (1.0 - HIGH_VOL_TP_SCALE) * 0.2)
                effective_sl_mult = max(0.15, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            # Trail (c179 동일)
            effective_trail_mult = (
                (TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio))
                * trail_scale
            )
            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR * trail_scale

            max_hold = max(5, int(MAX_HOLD_BASE * hold_scale))

            # ★ c212: 래칫 스탑 상태
            ratchet_sl = sl_price  # 현재 래칫 SL (초기값 = 기본 SL)
            be_triggered = False
            lock_triggered = False

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]

                # ★ c212: 래칫 스탑 업데이트
                unrealized_atr = (current_price - buy) / atr_at_entry

                # Level 1: Breakeven lock
                if (be_trigger > 0 and not be_triggered
                        and unrealized_atr >= be_trigger):
                    be_triggered = True
                    new_sl = buy * (1 + FEE)  # breakeven (수수료 포함)
                    if new_sl > ratchet_sl:
                        ratchet_sl = new_sl

                # Level 2: Profit lock
                if (lock_trigger > 0 and not lock_triggered
                        and unrealized_atr >= lock_trigger):
                    lock_triggered = True
                    profit = current_price - buy
                    new_sl = buy + profit * lock_pct
                    if new_sl > ratchet_sl:
                        ratchet_sl = new_sl

                # TP
                if current_price >= tp_price:
                    exit_ret = (tp_price / buy - 1) - FEE - SLIPPAGE
                    i = j
                    break

                # ★ SL: 래칫 SL 적용 (기본 SL보다 높을 수 있음)
                effective_sl = max(sl_price, ratchet_sl)
                if current_price <= effective_sl:
                    exit_ret = (effective_sl / buy - 1) - FEE - SLIPPAGE
                    i = j
                    break

                # Trailing (c179 동일)
                if current_price > peak_price:
                    peak_price = current_price

                unrealized = peak_price - buy
                if unrealized >= min_profit_dist:
                    if (peak_price - current_price
                            >= atr_at_entry * effective_trail_mult):
                        exit_ret = (
                            (current_price / buy - 1) - FEE - SLIPPAGE
                        )
                        i = j
                        break

            if exit_ret is None:
                hold_end = min(i + max_hold, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - SLIPPAGE
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
                "trades": 0, "max_dd": 0.0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd}


def pool_results(results_list: list[dict]) -> dict:
    all_sharpes = []
    all_wrs = []
    total_trades = 0
    all_avg_rets = []
    all_max_dds = []
    for r in results_list:
        if r["trades"] > 0 and not np.isnan(r["sharpe"]):
            all_sharpes.append(r["sharpe"])
            all_wrs.append(r["wr"])
            total_trades += r["trades"]
            all_avg_rets.append(r["avg_ret"])
            all_max_dds.append(r["max_dd"])
    if not all_sharpes:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0}
    return {
        "sharpe": float(np.mean(all_sharpes)),
        "wr": float(np.mean(all_wrs)),
        "avg_ret": float(np.mean(all_avg_rets)),
        "trades": total_trades,
        "max_dd": float(np.mean(all_max_dds)),
    }


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 212 — 래칫 스탑 (breakeven+profit lock) 3-fold WF ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe > 42.878 (c179 baseline)")
    print("가설: 진입/TP/Trail 100% 유지, SL만 래칫 상향")
    print("  L1: 수익 BE_TRIGGER ATR 도달 → SL을 breakeven으로 이동")
    print("  L2: 수익 LOCK_TRIGGER ATR 도달 → SL을 진입가+수익*LOCK_PCT로 이동")
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

    # -- 그리드 정의 --
    combos = list(product(
        BE_TRIGGER_LIST, LOCK_TRIGGER_LIST, LOCK_PCT_LIST,
    ))
    # be_trigger=0 이고 lock_trigger=0이면 lock_pct는 의미없음 → 중복 제거
    unique_combos = []
    seen = set()
    for be_t, lk_t, lk_p in combos:
        if be_t == 0.0 and lk_t == 0.0:
            key = (0.0, 0.0, 0.3)  # 하나만 남김
            if key not in seen:
                seen.add(key)
                unique_combos.append(key)
        elif lk_t == 0.0:
            key = (be_t, 0.0, 0.3)  # lock_pct 의미없음
            if key not in seen:
                seen.add(key)
                unique_combos.append(key)
        else:
            key = (be_t, lk_t, lk_p)
            if key not in seen:
                seen.add(key)
                unique_combos.append(key)
    combos = unique_combos
    print(f"\n총 조합: {len(combos)}개 × {len(sym_data_ok)} 심볼 × 3 folds")

    # -- 3-fold WF 전체 그리드 서치 --
    print("\n" + "=" * 80)
    print("3-fold Walk-Forward 그리드 서치")
    print("=" * 80)

    all_wf_results: list[dict] = []

    for ci, (be_t, lk_t, lk_p) in enumerate(combos):
        fold_sharpes = []
        fold_details = []
        total_n = 0

        for fi, fold in enumerate(WF_FOLDS, 1):
            te_start, te_end = fold["test"]

            sym_results = []
            for sym in sym_data_ok:
                df_te = load_historical(sym, "240m", te_start, te_end)
                if df_te.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_te, df_btc_full, BTC_SMA_PERIOD
                )
                r = backtest(df_te, be_t, lk_t, lk_p, btc_c, btc_s)
                sym_results.append(r)

            pooled = pool_results(sym_results)
            fold_sharpes.append(pooled["sharpe"] if not np.isnan(
                pooled["sharpe"]) else -999)
            fold_details.append({
                "name": f"F{fi}",
                "sharpe": pooled["sharpe"],
                "wr": pooled["wr"],
                "n": pooled["trades"],
                "avg": pooled["avg_ret"],
                "mdd": pooled["max_dd"],
            })
            total_n += pooled["trades"]

        avg_oos = float(np.mean(fold_sharpes))
        all_wf_results.append({
            "params": (be_t, lk_t, lk_p),
            "avg_sharpe": avg_oos,
            "total_n": total_n,
            "folds": fold_details,
        })

        if (ci + 1) % 10 == 0 or ci == len(combos) - 1:
            print(f"  진행: {ci + 1}/{len(combos)} 완료")

    # -- 결과 정리 --
    valid = [r for r in all_wf_results
             if r["total_n"] >= 30 and r["avg_sharpe"] > -900]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_wf_results)}")

    print("\n" + "=" * 80)
    print("=== Top 10 결과 ===")
    print("=" * 80)
    hdr = (f"{'beTr':>5} {'lkTr':>5} {'lkPct':>5} | "
           f"{'avgSh':>8} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:10]:
        p = r["params"]
        print(
            f"{p[0]:>5.1f} {p[1]:>5.1f} {p[2]:>5.1f} | "
            f"{r['avg_sharpe']:>+8.3f} {r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: beTrigger={p[0]:.1f} lockTrigger={p[1]:.1f} "
              f"lockPct={p[2]:.1f}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}")
        for f in r["folds"]:
            sh = f["sharpe"] if not np.isnan(f["sharpe"]) else 0.0
            print(f"  {f['name']}: Sharpe={sh:+.3f}  "
                  f"WR={f['wr']:.1%}  n={f['n']}  "
                  f"avg={f['avg']:+.2%}  MDD={f['mdd']:+.4f}")

    # Top 1 심볼별 분해
    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n" + "=" * 80)
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: beTr={bp[0]:.1f} "
              f"lkTr={bp[1]:.1f} lkPct={bp[2]:.1f}) ===")

        for sym in sym_data_ok:
            sym_sharpes_list = []
            sym_total_n = 0
            for fi, fold in enumerate(WF_FOLDS, 1):
                te_start, te_end = fold["test"]
                df_te = load_historical(sym, "240m", te_start, te_end)
                if df_te.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_te, df_btc_full, BTC_SMA_PERIOD
                )
                r = backtest(df_te, bp[0], bp[1], bp[2], btc_c, btc_s)
                sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
                print(f"  {sym} F{fi}: Sharpe={sh:+.3f}  "
                      f"WR={r['wr']:.1%}  n={r['trades']}  "
                      f"avg={r['avg_ret']:+.2%}  MDD={r['max_dd']:+.4f}")
                sym_sharpes_list.append(sh)
                sym_total_n += r["trades"]
            avg_sh = np.mean(sym_sharpes_list) if sym_sharpes_list else 0.0
            print(f"  {sym} 평균: Sharpe={avg_sh:+.3f}  총 trades={sym_total_n}")

    # c179 비교
    print("\n" + "=" * 80)
    print("=== c179 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        bp = b["params"]
        print(f"  c179 기준 (vol regime adaptive): avg_OOS=+42.878 n=~60")
        print(f"  c212 최적 (beTr={bp[0]:.1f} lkTr={bp[1]:.1f} "
              f"lkPct={bp[2]:.1f}): avg_OOS={b['avg_sharpe']:+.3f} "
              f"n={b['total_n']}")
        delta = b["avg_sharpe"] - 42.878
        print(f"  Δ Sharpe: {delta:+.3f} "
              f"({'개선' if delta > 0 else '악화'})")
        print(f"  Δ trades: {b['total_n'] - 60}")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        status = "PASS" if b["avg_sharpe"] > 0 and b["total_n"] >= 30 else "FAIL"
        print(f"★ OOS 최적: beTr={p[0]:.1f} lkTr={p[1]:.1f} lkPct={p[2]:.1f}")
        print(f"  (c179 고정: volTh={VOL_REGIME_THRESH} "
              f"tpSc={HIGH_VOL_TP_SCALE} trSc={HIGH_VOL_TRAIL_SCALE} "
              f"hdSc={HIGH_VOL_HOLD_SCALE})")
        print(f"  (c177 고정: atrTh={ATR_PCTILE_THRESH} "
              f"body={BODY_RATIO_MIN} vpRx={VPIN_RELAX_THRESH} "
              f"rxSc={RELAX_SCALE})")
        print(f"  (c176 고정: atrLB={ATR_PCTILE_LB})")
        print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} "
              f"Hold={MAX_HOLD_BASE} CD={COOLDOWN_BARS})")
        print(f"  (c164 고정: dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
              f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT})")
        print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
              f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} "
              f"minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD})")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        train_sharpe = b["avg_sharpe"]  # train 따로 안 돌림 (OOS만)
        for f in b["folds"]:
            sh = f["sharpe"] if not np.isnan(f["sharpe"]) else 0.0
            print(f"  {f['name']}: Sharpe={sh:+.3f}  "
                  f"WR={f['wr']:.1%}  trades={f['n']}  "
                  f"avg={f['avg']:+.2%}  MDD={f['mdd']:+.4f}")
        avg_wr = np.mean([f["wr"] for f in b["folds"]]) * 100
        print(f"\nSharpe: {b['avg_sharpe']:+.3f}")
        print(f"WR: {avg_wr:.1f}%")
        print(f"trades: {b['total_n']}")
    else:
        print("n>=30 조건 충족 조합 없음 — FAIL")
        print("\nSharpe: N/A")
        print("WR: N/A")
        print("trades: 0")


if __name__ == "__main__":
    main()
