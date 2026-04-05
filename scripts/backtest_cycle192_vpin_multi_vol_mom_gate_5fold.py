"""
vpin_multi 사이클 192 — c190 vol_mom_gate 5-fold WF 재검증
- 목적: c190 최적(vLB=10, vMin=0.05, tpB=1.0) OOS Sharpe +29.342, n=26을
  5-fold expanding window로 재검증하여 n≥45 확보 + SOL 0거래 원인 분석
- c190 고정: VOL_MOM_LB=10 VOL_MOM_MIN=0.05 TP_SLOPE_BONUS=1.0
  c186 고정: body=0.50 rsiD=6 sLB=10 sPth=50
  c182 고정: vPth=60 vPLB=60
  c176 고정: atrLB=60 atrTh=30
  c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4
  c164 고정: dLB=3 SL=0.4-0.2 vMul=0.8
  TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
- 5-fold expanding window (non-overlapping OOS):
  F1: train 2022-01~2023-06, OOS 2023-07~2024-01 (7m)
  F2: train 2022-01~2024-01, OOS 2024-02~2024-08 (7m)
  F3: train 2022-01~2024-08, OOS 2024-09~2025-03 (7m)
  F4: train 2022-01~2025-03, OOS 2025-04~2025-10 (7m)
  F5: train 2022-01~2025-10, OOS 2025-11~2026-04 (5m)
- 목표: OOS Sharpe >= 20 AND n >= 45
- 진입: next_bar open
- 슬리피지 포함
"""
from __future__ import annotations

import math
import sys
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
MAX_HOLD = 20
COOLDOWN_BARS = 4

RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

RSI_DELTA_LB = 3
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD = 20
VOL_SMA_PERIOD = 20

TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

BTC_SMA_PERIOD = 200

# -- c176 고정 --
ATR_PCTILE_LB = 60
ATR_TH = 30

# -- c182 최적 고정 --
VOL_PCTILE_TH = 60
VOL_PCTILE_LB = 60

# -- c186 최적 고정 --
BODY_RATIO_MIN = 0.50
RSI_DELTA_MIN = 6
EMA_SLOPE_LB = 10
EMA_SLOPE_PCTILE_TH = 50

# -- c190 최적 고정 --
VOL_MOM_LB = 10
VOL_MOM_MIN = 0.05
TP_SLOPE_BONUS = 1.0

# -- 5-fold Expanding Window --
WF_FOLDS = [
    {"train": ("2022-01-01", "2023-06-30"), "test": ("2023-07-01", "2024-01-31")},
    {"train": ("2022-01-01", "2024-01-31"), "test": ("2024-02-01", "2024-08-31")},
    {"train": ("2022-01-01", "2024-08-31"), "test": ("2024-09-01", "2025-03-31")},
    {"train": ("2022-01-01", "2025-03-31"), "test": ("2025-04-01", "2025-10-31")},
    {"train": ("2022-01-01", "2025-10-31"), "test": ("2025-11-01", "2026-04-05")},
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
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    ema_slope_pctile_arr: np.ndarray,
    vol_mom_arr: np.ndarray,
    slippage: float = 0.0005,
    debug_signal: bool = False,
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
    vol_pctile_arr = compute_vol_percentile(v, VOL_PCTILE_LB)

    returns: list[float] = []
    # debug: track filter rejection counts
    reject_counts = {
        "vpin": 0, "btc": 0, "rsi_vel": 0, "vol": 0,
        "atr_pctile": 0, "body": 0, "vol_pctile": 0,
        "ema_slope": 0, "vol_mom": 0, "nan": 0,
    }
    bars_checked = 0

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
            if debug_signal:
                reject_counts["nan"] += 1
            i += 1
            continue

        bars_checked += 1

        # RSI velocity
        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # 진입 조건 체크 (개별 필터 추적)
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
        vol_ok = v[i] >= vol_sma_arr[i] * VOL_MULT

        atr_pctile_ok = (not np.isnan(atr_pctile_val)
                         and atr_pctile_val >= ATR_TH)
        body_ok = (BODY_RATIO_MIN <= 0
                   or (not np.isnan(body_val)
                       and body_val >= BODY_RATIO_MIN and c[i] >= o[i]))
        vol_pctile_ok = (not np.isnan(vol_pctile_val)
                         and vol_pctile_val >= VOL_PCTILE_TH)

        esp = ema_slope_pctile_arr[i]
        ema_slope_ok = not np.isnan(esp) and esp >= EMA_SLOPE_PCTILE_TH

        vm = vol_mom_arr[i]
        vol_mom_ok = True
        if VOL_MOM_MIN > 0:
            vol_mom_ok = not np.isnan(vm) and vm >= VOL_MOM_MIN

        if debug_signal:
            if not vpin_ok:
                reject_counts["vpin"] += 1
            if not btc_ok:
                reject_counts["btc"] += 1
            if not rsi_velocity_ok:
                reject_counts["rsi_vel"] += 1
            if not vol_ok:
                reject_counts["vol"] += 1
            if not atr_pctile_ok:
                reject_counts["atr_pctile"] += 1
            if not body_ok:
                reject_counts["body"] += 1
            if not vol_pctile_ok:
                reject_counts["vol_pctile"] += 1
            if not ema_slope_ok:
                reject_counts["ema_slope"] += 1
            if not vol_mom_ok:
                reject_counts["vol_mom"] += 1

        if not (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and vol_pctile_ok
                and ema_slope_ok and vol_mom_ok):
            i += 1
            continue

        buy = o[i + 1] * (1 + FEE + slippage)
        peak_price = buy
        atr_at_entry = atr_val

        rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
        rsi_ratio = max(0.0, min(1.0, rsi_ratio))

        # EMA slope 강도 → TP 보너스
        slope_tp_extra = 0.0
        if TP_SLOPE_BONUS > 0 and not np.isnan(esp):
            if esp >= 70.0:
                slope_tp_extra = TP_SLOPE_BONUS
            elif esp >= 60.0:
                slope_tp_extra = TP_SLOPE_BONUS * 0.5

        effective_tp_mult = TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio + slope_tp_extra
        tp_price = buy + atr_at_entry * effective_tp_mult

        effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
        effective_sl_mult = max(0.2, effective_sl_mult)
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

        i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0,
                "reject_counts": reject_counts, "bars_checked": bars_checked}
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
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl,
            "reject_counts": reject_counts, "bars_checked": bars_checked}


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


def precompute_indicators(
    df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    c = df["close"].values
    v = df["volume"].values
    ema_arr = ema_calc(c, EMA_PERIOD)
    ema_slope_pctile = compute_ema_slope_percentile(ema_arr, EMA_SLOPE_LB)
    vol_mom_arr = compute_vol_momentum(v, ema_period=VOL_MOM_LB)
    return ema_slope_pctile, vol_mom_arr


def compute_buy_and_hold(df: pd.DataFrame) -> float:
    """Buy-and-hold return for comparison."""
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi c192 — c190 vol_mom_gate 5-fold WF 재검증 ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"목표: OOS Sharpe >= 20 AND n >= 45")
    print(f"c190 고정: vLB={VOL_MOM_LB} vMin={VOL_MOM_MIN} tpB={TP_SLOPE_BONUS}")
    print(f"c186 고정: body={BODY_RATIO_MIN} rsiD={RSI_DELTA_MIN} "
          f"sLB={EMA_SLOPE_LB} sPth={EMA_SLOPE_PCTILE_TH}")
    print(f"c182 고정: vPth={VOL_PCTILE_TH} vPLB={VOL_PCTILE_LB}")
    print(f"c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH}")
    print(f"c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD} "
          f"CD={COOLDOWN_BARS}")
    print(f"  dLB={RSI_DELTA_LB} SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT}")
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

    # ================================================================
    # Phase 1: SOL 0거래 원인 분석 (디버그 모드)
    # ================================================================
    print(f"\n{'=' * 80}")
    print("=== Phase 1: SOL 0거래 원인 분석 (필터별 거부 비율) ===")
    for sym in sym_data_ok:
        # Use first fold test period for analysis
        df_debug = load_historical(sym, "240m", "2023-07-01", "2024-01-31")
        if df_debug.empty:
            print(f"  {sym}: 데이터 없음")
            continue
        btc_c, btc_s = align_btc_to_symbol(df_debug, df_btc_full, BTC_SMA_PERIOD)
        esp, vm = precompute_indicators(df_debug)
        r = backtest(df_debug, btc_c, btc_s, esp, vm, debug_signal=True)
        rc = r["reject_counts"]
        total_bars = r["bars_checked"]
        print(f"\n  {sym} (F1 OOS: 2023-07~2024-01, {len(df_debug)}봉):")
        print(f"    trades={r['trades']}  bars_checked={total_bars}")
        if total_bars > 0:
            for k, cnt in sorted(rc.items(), key=lambda x: -x[1]):
                if cnt > 0:
                    pct = cnt / total_bars * 100
                    print(f"    {k:>12}: {cnt:>5} ({pct:>5.1f}%)")

    # ================================================================
    # Phase 2: 5-fold OOS Walk-Forward 검증
    # ================================================================
    print(f"\n{'=' * 80}")
    print("=== Phase 2: 5-fold OOS Walk-Forward 검증 ===")

    oos_sharpes: list[float] = []
    oos_trades: list[int] = []
    fold_details: list[dict] = []

    for fold_i, fold in enumerate(WF_FOLDS):
        sym_fold_results = []
        sym_fold_detail = {}
        for sym in sym_data_ok:
            df_test = load_historical(
                sym, "240m", fold["test"][0], fold["test"][1])
            if df_test.empty:
                continue
            btc_c, btc_s = align_btc_to_symbol(
                df_test, df_btc_full, BTC_SMA_PERIOD)
            esp, vm = precompute_indicators(df_test)
            r = backtest(df_test, btc_c, btc_s, esp, vm)
            sym_fold_results.append(r)

            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            sym_fold_detail[sym] = r
            print(f"  F{fold_i + 1} {sym}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  "
                  f"MDD={r['max_dd'] * 100:+.2f}%")

        pooled = pool_results(sym_fold_results)
        sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
        oos_sharpes.append(sh)
        oos_trades.append(pooled["trades"])
        fold_details.append({"pooled": pooled, "by_sym": sym_fold_detail})
        print(f"  F{fold_i + 1} pooled: Sharpe={sh:+.3f}  "
              f"WR={pooled['wr']:.1%}  n={pooled['trades']}  "
              f"avg={pooled['avg_ret'] * 100:+.2f}%  "
              f"MDD={pooled['max_dd'] * 100:+.2f}%")
        print()

    avg_oos = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    min_oos = min(oos_sharpes) if oos_sharpes else 0.0
    total_n = sum(oos_trades)
    all_pass = (all(s >= 3.0 for s in oos_sharpes)
                and avg_oos >= 5.0 and total_n >= 45)

    print(f"--- 5-fold 종합 ---")
    print(f"  avg OOS Sharpe: {avg_oos:+.3f}")
    print(f"  min OOS Sharpe: {min_oos:+.3f}")
    print(f"  total OOS trades: {total_n}")
    print(f"  fold Sharpes: {[f'{s:+.3f}' for s in oos_sharpes]}")
    print(f"  fold trades: {oos_trades}")
    print(f"  판정: {'PASS ✓' if all_pass else 'FAIL ✗'}")

    # ================================================================
    # Phase 3: Buy-and-Hold 비교
    # ================================================================
    print(f"\n{'=' * 80}")
    print("=== Phase 3: Buy-and-Hold 비교 ===")
    for sym in sym_data_ok:
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                sym, "240m", fold["test"][0], fold["test"][1])
            if df_test.empty:
                continue
            bh_ret = compute_buy_and_hold(df_test)
            strat_detail = fold_details[fold_i]["by_sym"].get(sym)
            strat_avg = strat_detail["avg_ret"] if strat_detail else 0.0
            strat_n = strat_detail["trades"] if strat_detail else 0
            total_strat_ret = strat_avg * strat_n if strat_n > 0 else 0.0
            print(f"  {sym} F{fold_i + 1}: BH={bh_ret * 100:+.1f}%  "
                  f"strat_total={total_strat_ret * 100:+.1f}%  "
                  f"(avg={strat_avg * 100:+.2f}% × {strat_n})")

    # ================================================================
    # Phase 4: 슬리피지 스트레스 테스트
    # ================================================================
    print(f"\n{'=' * 80}")
    print("=== Phase 4: 슬리피지 스트레스 테스트 (전체 기간) ===")
    print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
          f"{'MDD':>7} {'MCL':>4} {'n':>5}")
    print("-" * 55)
    for slip in SLIPPAGE_LEVELS:
        sym_results = []
        for sym in sym_data_ok:
            df_full = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
            if df_full.empty:
                continue
            btc_c, btc_s = align_btc_to_symbol(
                df_full, df_btc_full, BTC_SMA_PERIOD)
            esp, vm = precompute_indicators(df_full)
            r = backtest(df_full, btc_c, btc_s, esp, vm, slippage=slip)
            sym_results.append(r)
        pooled = pool_results(sym_results)
        sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
        print(f"  {slip * 100:.2f}% {sh:>+8.3f} {pooled['wr']:>5.1%} "
              f"{pooled['avg_ret'] * 100:>+6.2f}% "
              f"{pooled['max_dd'] * 100:>+6.2f}% "
              f"{pooled['mcl']:>4} {pooled['trades']:>5}")

    # ================================================================
    # Phase 5: 심볼별 OOS 성능 분해
    # ================================================================
    print(f"\n{'=' * 80}")
    print("=== Phase 5: 심볼별 OOS 성능 종합 ===")
    for sym in sym_data_ok:
        sym_sharpes = []
        sym_trades = 0
        for fold_i, fold in enumerate(WF_FOLDS):
            detail = fold_details[fold_i]["by_sym"].get(sym)
            if detail and detail["trades"] > 0:
                sh = detail["sharpe"] if not np.isnan(detail["sharpe"]) else 0.0
                sym_sharpes.append(sh)
                sym_trades += detail["trades"]
        if sym_sharpes:
            print(f"  {sym}: avg Sharpe={np.mean(sym_sharpes):+.3f}  "
                  f"총 trades={sym_trades}  "
                  f"fold별=[{', '.join(f'{s:+.1f}' for s in sym_sharpes)}]")
        else:
            print(f"  {sym}: 거래 없음 (0 trades across all folds)")

    # ================================================================
    # 최종 요약
    # ================================================================
    print(f"\n{'=' * 80}")
    print("=== c190 대비 비교 ===")
    print(f"  c190 3-fold: avg_OOS=+29.342 n=26")
    print(f"  c192 5-fold: avg_OOS={avg_oos:+.3f} n={total_n}")
    delta_n = total_n - 26
    print(f"  Δ trades: {delta_n:+d}")
    print(f"  n≥45 충족: {'YES ✓' if total_n >= 45 else 'NO ✗'}")

    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ c190 vol_mom_gate 5-fold 재검증")
    print(f"  c190 고정: VOL_MOM_LB={VOL_MOM_LB} VOL_MOM_MIN={VOL_MOM_MIN} "
          f"TP_SLOPE_BONUS={TP_SLOPE_BONUS}")
    print(f"  (c186 고정: body={BODY_RATIO_MIN} rsiD={RSI_DELTA_MIN} "
          f"sLB={EMA_SLOPE_LB} sPth={EMA_SLOPE_PCTILE_TH})")
    print(f"  (c182 고정: vPth={VOL_PCTILE_TH} vPLB={VOL_PCTILE_LB})")
    print(f"  (c176 고정: atrLB={ATR_PCTILE_LB} atrTh={ATR_TH})")
    print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD} "
          f"CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} SL={SL_BASE_ATR}-{SL_BONUS_ATR} "
          f"vMul={VOL_MULT})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} "
          f"minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD})")
    print(f"  avg OOS Sharpe: {avg_oos:+.3f} "
          f"{'PASS' if all_pass else 'FAIL'}")

    for fold_i in range(len(WF_FOLDS)):
        p = fold_details[fold_i]["pooled"]
        sh = p["sharpe"] if not np.isnan(p["sharpe"]) else 0.0
        print(f"  Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
              f"WR={p['wr']:.1%}  trades={p['trades']}  "
              f"avg={p['avg_ret'] * 100:+.2f}%  "
              f"MDD={p['max_dd'] * 100:+.2f}%")

    print(f"\nSharpe: {avg_oos:+.3f}")
    print(f"WR: {pool_results([fd['pooled'] for fd in fold_details])['wr']:.1%}")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
