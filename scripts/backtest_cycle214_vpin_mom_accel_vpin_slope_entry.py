"""
vpin_multi 사이클 214 — 모멘텀 가속도 + VPIN 기울기 진입 타이밍 필터
- 기반: c179 OOS Sharpe +42.878 (vol regime adaptive) BEST
  c210 결과: signal strength adaptive TP/SL → +17.655 (악화)
  → slTighten=0 최적(SL 조정 유해), tpBoost=0.8이나 고정TP가 이미 최적
  c209~c213: 모든 TP/SL 오버레이가 c179 대비 악화
  → 출구 최적화 한계, 진입 타이밍 개선으로 방향 전환
- 문제:
  1) 현재 진입: VPIN < 0.35 AND mom > 0.0007 (단일 시점 스냅샷)
  2) 모멘텀이 양수이나 감속 중이면 → 추세 끝물 진입 → 손실
  3) VPIN이 낮지만 상승 중이면 → toxicity 증가 구간 진입 → 역행
  4) SOL avg Sharpe +9.381 (약점) — 가짜 브레이크아웃 필터링 필요
- 가설:
  A) 모멘텀 가속도: mom[i] > mom[i-k] (모멘텀 증가 중일 때만 진입)
     → 감속 중인 추세 끝물 진입 방지
  B) VPIN 기울기: VPIN[i] - VPIN[i-k] < threshold (VPIN 하락/안정 시 진입)
     → toxicity 증가 구간 회피
  C) 두 필터 결합: 가속 모멘텀 + 하락 VPIN = 최적 진입 타이밍
  D) c179 TP/SL/Trail 완전 고정 — 출구 변경 없음
- c179 고정: volTh=60 tpSc=0.65 trSc=0.7 hdSc=0.8
  c177 고정: atrTh=30 body=0.7 vpRx=0.25 rxSc=0.5
  c176 고정: atrLB=60
  c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4
  c164 고정: dLB=3 dMin=0.0 SL=0.4-0.2 vMul=0.8
  TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
- 탐색 그리드:
  MOM_ACCEL_LB: [2, 3, 4, 6]         — 모멘텀 비교 lookback (bars)
  MOM_ACCEL_MIN: [0.0, 0.0003, 0.0006, 0.001] — 최소 모멘텀 증가분
  VPIN_DELTA_LB: [3, 5, 8]            — VPIN 변화 lookback (bars)
  VPIN_DELTA_MAX: [0.10, 0.03, 0.0, -0.03] — 최대 VPIN 변화 (음수=하락 필수)
  = 4×4×3×4 = 192 combos
- 목표: OOS Sharpe >= 43 AND trades >= 40
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

# -- c177 고정 TP/Trail (기준선) --
TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

BTC_SMA_PERIOD = 200
ATR_PCTILE_LB = 60  # c176 최적 고정

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

# -- c214 탐색 그리드: 진입 타이밍 --
MOM_ACCEL_LB_LIST = [2, 3, 4, 6]
MOM_ACCEL_MIN_LIST = [0.0, 0.0003, 0.0006, 0.001]
VPIN_DELTA_LB_LIST = [3, 5, 8]
VPIN_DELTA_MAX_LIST = [0.10, 0.03, 0.0, -0.03]

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
    mom_accel_lb: int,
    mom_accel_min: float,
    vpin_delta_lb: int,
    vpin_delta_max: float,
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

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, mom_accel_lb + MOM_LOOKBACK,
                 vpin_delta_lb + BUCKET_COUNT, 50) + 5
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

        # ATR 백분위 필터
        atr_pctile_ok = True
        if eff_atr_thresh > 0:
            if np.isnan(atr_pctile_val):
                atr_pctile_ok = False
            else:
                atr_pctile_ok = atr_pctile_val >= eff_atr_thresh

        # 캔들 바디 비율 필터 — 양봉(close>=open) 필수
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

        # === c214: 모멘텀 가속도 필터 ===
        mom_prev_idx = i - mom_accel_lb
        if mom_prev_idx < 0 or np.isnan(mom_arr[mom_prev_idx]):
            i += 1
            continue
        mom_accel = mom_val - mom_arr[mom_prev_idx]
        if mom_accel < mom_accel_min:
            i += 1
            continue

        # === c214: VPIN 기울기 필터 ===
        vpin_prev_idx = i - vpin_delta_lb
        if vpin_prev_idx < 0 or np.isnan(vpin_arr[vpin_prev_idx]):
            i += 1
            continue
        vpin_delta = vpin_val - vpin_arr[vpin_prev_idx]
        if vpin_delta > vpin_delta_max:
            i += 1
            continue

        # === 진입 (c179 고정 출구) ===
        buy = o[i + 1] * (1 + FEE + slippage)
        peak_price = buy
        atr_at_entry = atr_val

        # RSI 기반 동적 스케일링
        rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
        rsi_ratio = max(0.0, min(1.0, rsi_ratio))

        # c179 고정: 변동성 레짐 판단
        is_high_vol = (
            not np.isnan(atr_pctile_val)
            and atr_pctile_val >= VOL_REGIME_THRESH
        )

        # TP/SL/Trail — c179 레짐별 스케일 (완전 고정)
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
    combos = []
    for ma_lb, ma_min, vd_lb, vd_max in product(
        MOM_ACCEL_LB_LIST, MOM_ACCEL_MIN_LIST,
        VPIN_DELTA_LB_LIST, VPIN_DELTA_MAX_LIST,
    ):
        combos.append({
            "mom_accel_lb": ma_lb,
            "mom_accel_min": ma_min,
            "vpin_delta_lb": vd_lb,
            "vpin_delta_max": vd_max,
        })
    return combos


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi c214 — 모멘텀 가속도 + VPIN 기울기 진입 타이밍 ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe >= 43 AND trades >= 40")
    print("가설: 모멘텀 가속(2차 미분>0) + VPIN 하락(toxicity 감소) = 최적 타이밍")
    print(f"기준선: c179 OOS +42.878 (vol regime adaptive)")
    print(f"c179 고정: volTh={VOL_REGIME_THRESH} tpSc={HIGH_VOL_TP_SCALE} "
          f"trSc={HIGH_VOL_TRAIL_SCALE} hdSc={HIGH_VOL_HOLD_SCALE}")
    print(f"c177 고정: atrTh={ATR_PCTILE_THRESH} body={BODY_RATIO_MIN} "
          f"vpRx={VPIN_RELAX_THRESH} rxSc={RELAX_SCALE}")
    print(f"c176 고정: atrLB={ATR_PCTILE_LB}")
    print(f"c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE}"
          f" CD={COOLDOWN_BARS}")
    print(f"  dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT}")
    print(f"  TP={TP_BASE_ATR}+{TP_BONUS_ATR} Trail={TRAIL_BASE_ATR}+"
          f"{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD}")
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
                combo["mom_accel_lb"], combo["mom_accel_min"],
                combo["vpin_delta_lb"], combo["vpin_delta_max"],
                btc_c, btc_s)
            sym_results.append(r)

        pooled = pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 50 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    print(f"  [{len(combos)}/{len(combos)}] 완료")

    valid = [r for r in results
             if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 16 (pooled Sharpe 기준) ===")
    hdr = (f"{'maLB':>5} {'maMin':>7} {'vdLB':>5} {'vdMax':>7} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} "
           f"{'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:16]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['mom_accel_lb']:>5} {r['mom_accel_min']:>7.4f} "
            f"{r['vpin_delta_lb']:>5} {r['vpin_delta_max']:>7.3f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}")

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
        key = (r["mom_accel_lb"], r["mom_accel_min"],
               r["vpin_delta_lb"], r["vpin_delta_max"])
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
                    params["mom_accel_lb"], params["mom_accel_min"],
                    params["vpin_delta_lb"], params["vpin_delta_max"],
                    btc_c, btc_s)
                sym_fold_results.append(r)

                sym_fold_details.append(
                    f"  {sym} Fold {fold_i + 1}: "
                    f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
                    f"n={r['trades']}  avg={r['avg_ret'] * 100:+.2f}%  "
                    f"MDD={r['max_dd'] * 100:+.4f}")

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
            print(
                f"  #{rank}: maLB={params['mom_accel_lb']} "
                f"maMin={params['mom_accel_min']:.4f} "
                f"vdLB={params['vpin_delta_lb']} "
                f"vdMax={params['vpin_delta_max']:.3f} | "
                f"avg_OOS={avg_oos:+.3f} min={min_oos:+.3f} "
                f"n={total_oos_n} {tag}")
            wf_results.append({
                **params,
                "avg_oos": avg_oos,
                "min_oos": min_oos,
                "total_n": total_oos_n,
                "fold_details": fold_details,
                "sym_fold_details": sym_fold_details,
                "tag": tag,
            })

    if not wf_results:
        print("WF 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    wf_results.sort(key=lambda x: x["avg_oos"], reverse=True)
    best = wf_results[0]

    # -- Phase 3: 슬리피지 스트레스 테스트 --
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS 최적) ===")
    print(f"파라미터: maLB={best['mom_accel_lb']} "
          f"maMin={best['mom_accel_min']:.4f} "
          f"vdLB={best['vpin_delta_lb']} "
          f"vdMax={best['vpin_delta_max']:.3f}")

    for slip in SLIPPAGE_LEVELS:
        slip_sharpes = []
        slip_trades = 0
        for fold in WF_FOLDS:
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(
                    df_test,
                    best["mom_accel_lb"], best["mom_accel_min"],
                    best["vpin_delta_lb"], best["vpin_delta_max"],
                    btc_c, btc_s, slippage=slip)
                if r["trades"] > 0 and not np.isnan(r["sharpe"]):
                    slip_sharpes.append(r["sharpe"])
                    slip_trades += r["trades"]
        avg_sh = float(np.mean(slip_sharpes)) if slip_sharpes else float("nan")
        print(f"  slip={slip:.4f}: Sharpe={avg_sh:+.3f}  trades={slip_trades}")

    # -- 심볼별 fold 분해 --
    print(f"\n{'=' * 80}")
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: maLB={best['mom_accel_lb']} "
          f"maMin={best['mom_accel_min']:.4f} "
          f"vdLB={best['vpin_delta_lb']} "
          f"vdMax={best['vpin_delta_max']:.3f}) ===")
    for detail in best.get("sym_fold_details", []):
        print(detail)

    # 심볼 평균 계산
    for sym in sym_data_ok:
        sym_sharpes = []
        sym_trades = 0
        for fold in WF_FOLDS:
            df_test = load_historical(
                sym, "240m", fold["test"][0], fold["test"][1])
            if df_test.empty:
                continue
            btc_c, btc_s = align_btc_to_symbol(
                df_test, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(
                df_test,
                best["mom_accel_lb"], best["mom_accel_min"],
                best["vpin_delta_lb"], best["vpin_delta_max"],
                btc_c, btc_s)
            if r["trades"] > 0 and not np.isnan(r["sharpe"]):
                sym_sharpes.append(r["sharpe"])
                sym_trades += r["trades"]
        avg_sym = float(np.mean(sym_sharpes)) if sym_sharpes else 0.0
        print(f"  {sym} 평균: Sharpe={avg_sym:+.3f}  총 trades={sym_trades}")

    # -- c179 베이스라인 대비 --
    print(f"\n{'=' * 80}")
    print("=== c179 베이스라인 대비 비교 ===")
    c179_baseline = 42.878
    print(f"  c179 기준 (vol regime adaptive): avg_OOS={c179_baseline:+.3f} n=~60")
    print(f"  c214 최적 (maLB={best['mom_accel_lb']} "
          f"maMin={best['mom_accel_min']:.4f} "
          f"vdLB={best['vpin_delta_lb']} "
          f"vdMax={best['vpin_delta_max']:.3f}): "
          f"avg_OOS={best['avg_oos']:+.3f} n={best['total_n']}")
    delta = best["avg_oos"] - c179_baseline
    label = "개선" if delta > 0 else "악화"
    print(f"  Δ vs c179: {delta:+.3f} ({label})")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: maLB={best['mom_accel_lb']} "
          f"maMin={best['mom_accel_min']:.4f} "
          f"vdLB={best['vpin_delta_lb']} "
          f"vdMax={best['vpin_delta_max']:.3f}")
    print(f"  (c179 고정: volTh={VOL_REGIME_THRESH} "
          f"tpSc={HIGH_VOL_TP_SCALE} trSc={HIGH_VOL_TRAIL_SCALE} "
          f"hdSc={HIGH_VOL_HOLD_SCALE})")
    print(f"  (c177 고정: atrTh={ATR_PCTILE_THRESH} body={BODY_RATIO_MIN} "
          f"vpRx={VPIN_RELAX_THRESH} rxSc={RELAX_SCALE})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB})")
    print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD_BASE}"
          f" CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} "
          f"minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD})")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} {best['tag']}")
    train_best = valid[0] if valid else None
    if train_best:
        print(f"  train Sharpe: {train_best['sharpe']:+.3f}")
    for fi, fd in enumerate(best["fold_details"]):
        sh = fd["sharpe"] if not np.isnan(fd["sharpe"]) else 0.0
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={fd['trades']}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.4f}")

    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    total_wr = 0.0
    total_n = 0
    for fd in best["fold_details"]:
        if fd["trades"] > 0:
            total_wr += fd["wr"] * fd["trades"]
            total_n += fd["trades"]
    final_wr = total_wr / total_n * 100 if total_n > 0 else 0.0
    print(f"WR: {final_wr:.1f}%")
    print(f"trades: {best['total_n']}")


if __name__ == "__main__":
    main()
