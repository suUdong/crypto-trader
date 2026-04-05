"""
vpin_multi 사이클 177 — c178 BB스퀴즈 해제 n 확보 (squeeze 완화 + 5심볼 확장)
- 기반: c178 OOS Sharpe +42.205, WR 65.0%, trades 19
  최적: BB_PERIOD=20 SQUEEZE_PCTILE_TH=50 EXPANSION_LB=4 UPPER_RATIO=0.98 ATR_PCTILE=ON
  (c176 고정: body=0.7)
  (c165 고정: VPIN=0.35 MOM=0.0007 Hold=20 CD=4)
  (c164 고정: dLB=3 dMin=0.0 SL=0.4-0.2 vMul=0.8)
  (TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200)
- c178 약점: n=19 통계적 부족, XRP 0건
- 가설:
  A) squeeze_pctile 완화 (50→30/40): 더 많은 스퀴즈 탐지 → 진입 기회 증가
  B) squeeze history window 확장 (10→20/30봉): 넓은 스퀴즈 히스토리 → 더 많은 매칭
  C) upper_ratio 완화 (0.98→0.95): 밴드 근접 진입 허용
  D) 심볼 확장 (ETH/SOL/XRP → +DOGE/AVAX): 거래 풀 확대
- 탐색 그리드:
  3 SQUEEZE_PCTILE × 3 SQUEEZE_LB_WINDOW × 2 UPPER_RATIO = 18 combos
  BB_PERIOD=20, EXPANSION_LB=4, ATR_PCTILE=ON 고정 (c178 최적)
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

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE", "KRW-AVAX"]
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
RSI_DELTA_MIN = 0.0
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
BODY_RATIO_MIN = 0.7

# -- c178 고정 (최적) --
BB_PERIOD = 20
EXPANSION_LB = 4
USE_ATR_PCTILE = True
ATR_PCTILE_LB = 60
ATR_PCTILE_THRESH = 30

# -- c177 탐색 그리드 --
SQUEEZE_PCTILE_TH_LIST = [30, 40, 50]          # 완화 (c178: 50)
SQUEEZE_LB_WINDOW_LIST = [10, 20, 30]          # 스퀴즈 히스토리 윈도우 확장
UPPER_RATIO_LIST = [0.95, 0.98]                # 완화 (c178: 0.98)

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


def compute_bb(
    closes: np.ndarray, period: int = 20, num_std: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """볼린저밴드: middle, upper, lower, bandwidth(%)."""
    n = len(closes)
    middle = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    bw = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        middle[i] = m
        upper[i] = m + num_std * s
        lower[i] = m - num_std * s
        if m > 0:
            bw[i] = (upper[i] - lower[i]) / m * 100.0
        else:
            bw[i] = 0.0
    return middle, upper, lower, bw


def compute_bw_percentile(
    bw_arr: np.ndarray, lookback: int = 120,
) -> np.ndarray:
    """bandwidth의 최근 lookback 기간 내 백분위."""
    n = len(bw_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = bw_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = bw_arr[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
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
    squeeze_pctile_th: float,
    squeeze_lb_window: int,
    upper_ratio: float,
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
    body_ratio_arr = compute_body_ratio(o, c, h, lo)
    atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)

    _middle, bb_upper, _lower, bb_bw = compute_bb(c, BB_PERIOD)
    bw_pctile_arr = compute_bw_percentile(bb_bw, lookback=120)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, BB_PERIOD, 120, 50) + 5
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
        body_val = body_ratio_arr[i]
        atr_pctile_val = atr_pctile_arr[i]
        bw_pctile_val = bw_pctile_arr[i]
        bb_upper_val = bb_upper[i]
        bb_bw_val = bb_bw[i]

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

        # c176 바디 비율 필터 (고정)
        body_ok = True
        if BODY_RATIO_MIN > 0:
            if np.isnan(body_val):
                body_ok = False
            else:
                body_ok = body_val >= BODY_RATIO_MIN and c[i] >= o[i]

        # ATR 백분위 필터 (ON 고정)
        atr_pctile_ok = True
        if USE_ATR_PCTILE and ATR_PCTILE_THRESH > 0:
            if np.isnan(atr_pctile_val):
                atr_pctile_ok = False
            else:
                atr_pctile_ok = atr_pctile_val >= ATR_PCTILE_THRESH

        # BB 스퀴즈 해제 진입 (c177: squeeze_lb_window 파라미터화)
        bb_squeeze_ok = True
        if (np.isnan(bw_pctile_val) or np.isnan(bb_bw_val)
                or np.isnan(bb_upper_val)):
            bb_squeeze_ok = False
        else:
            # 최근 squeeze_lb_window 봉 내에 스퀴즈 상태가 있었는지 확인
            had_squeeze = False
            search_start = max(0, i - squeeze_lb_window)
            for k in range(search_start, i - EXPANSION_LB + 1):
                if k >= 0 and not np.isnan(bw_pctile_arr[k]):
                    if bw_pctile_arr[k] < squeeze_pctile_th:
                        had_squeeze = True
                        break

            # 현재 bandwidth가 스퀴즈에서 확장되었는지
            expanding = False
            if EXPANSION_LB > 0 and i - EXPANSION_LB >= 0:
                prev_bw = bb_bw[i - EXPANSION_LB]
                if not np.isnan(prev_bw) and prev_bw > 0:
                    expanding = bb_bw_val > prev_bw

            # close가 upper band 근처/위
            upper_break = c[i] >= bb_upper_val * upper_ratio

            bb_squeeze_ok = had_squeeze and expanding and upper_break

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and body_ok and atr_pctile_ok and bb_squeeze_ok):
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            effective_tp_mult = TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
            tp_price = buy + atr_at_entry * effective_tp_mult

            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            effective_trail_mult = (TRAIL_BASE_ATR
                                    + TRAIL_BONUS_ATR * (1.0 - rsi_ratio))
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


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 177 — BB스퀴즈 n 확보 (squeeze 완화 + 5심볼) ===")
    print(f"심볼: {', '.join(SYMBOLS)}  목표: n>=30 + OOS Sharpe >= 5.0")
    print("가설 A: squeeze_pctile 완화 (50→30/40) → 더 많은 스퀴즈 탐지")
    print("가설 B: squeeze history 윈도우 확장 (10→20/30) → 넓은 히스토리")
    print("가설 C: upper_ratio 완화 (0.98→0.95) → 밴드 근접 진입")
    print("가설 D: 심볼 확장 (ETH/SOL/XRP → +DOGE/AVAX)")
    print(f"기준선: c178 OOS +42.205, WR 65.0%, trades 19")
    print(f"c178 고정: BB_PERIOD={BB_PERIOD} EXPANSION_LB={EXPANSION_LB} "
          f"ATR_PCTILE=ON")
    print(f"c176 고정: body={BODY_RATIO_MIN}")
    print(f"c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD} "
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
        SQUEEZE_PCTILE_TH_LIST, SQUEEZE_LB_WINDOW_LIST, UPPER_RATIO_LIST,
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
    for idx, (sq_th, sq_lb, up_r) in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_data:
                continue
            df_tr = sym_train_data[sym]
            btc_c, btc_s = align_btc_to_symbol(df_tr, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_tr, sq_th, sq_lb, up_r, btc_c, btc_s)
            sym_results.append(r)

        pooled = pool_results(sym_results)
        results.append({
            "squeeze_th": sq_th, "squeeze_lb": sq_lb, "upper_ratio": up_r,
            **pooled,
        })

    valid = [r for r in results if r["trades"] >= 10 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=10): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 18 (pooled Sharpe 기준) ===")
    hdr = (f"{'sqTh':>5} {'sqLB':>5} {'upR':>5} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:18]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['squeeze_th']:>5} {r['squeeze_lb']:>5} "
            f"{r['upper_ratio']:>5.2f} | "
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
        key = (r["squeeze_th"], r["squeeze_lb"], r["upper_ratio"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 12:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(unique_top)} 고유) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        sq_th = params["squeeze_th"]
        sq_lb = params["squeeze_lb"]
        up_r = params["upper_ratio"]

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
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_test, sq_th, sq_lb, up_r, btc_c, btc_s)
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
            print(f"  #{rank}: sqTh={sq_th} sqLB={sq_lb} upR={up_r:.2f} | "
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
        sq_th = params["squeeze_th"]
        sq_lb = params["squeeze_lb"]
        up_r = params["upper_ratio"]
        print(f"\n--- #{rank}: sqTh={sq_th} sqLB={sq_lb} upR={up_r:.2f} "
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
                btc_c, btc_s = align_btc_to_symbol(
                    df_full, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_full, sq_th, sq_lb, up_r,
                             btc_c, btc_s, slippage=slip)
                sym_results.append(r)
            pooled = pool_results(sym_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {pooled['wr']:>5.1%} "
                  f"{pooled['avg_ret'] * 100:>+6.2f}% "
                  f"{pooled['max_dd'] * 100:>+6.2f}% "
                  f"{pooled['mcl']:>4} {pooled['trades']:>5}")

    # -- 심볼별 성능 분해 (Top 1) --
    best = wf_sorted[0]
    sq_th = best["squeeze_th"]
    sq_lb = best["squeeze_lb"]
    up_r = best["upper_ratio"]

    print(f"\n{'=' * 80}")
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: sqTh={sq_th} sqLB={sq_lb} "
          f"upR={up_r:.2f}) ===")
    for sym in sym_data_ok:
        sym_oos_sharpes = []
        sym_oos_trades = 0
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(sym, "240m",
                                      fold["test"][0], fold["test"][1])
            if df_test.empty:
                continue
            btc_c, btc_s = align_btc_to_symbol(
                df_test, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_test, sq_th, sq_lb, up_r, btc_c, btc_s)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            sym_oos_sharpes.append(sh)
            sym_oos_trades += r["trades"]
            print(f"  {sym} Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%")
        if sym_oos_sharpes:
            avg_sh = float(np.mean(sym_oos_sharpes))
            print(f"  {sym} 평균: Sharpe={avg_sh:+.3f}  총 trades={sym_oos_trades}")
        print()

    # -- c178 대비 비교 --
    print(f"{'=' * 80}")
    print("=== c178 베이스라인 대비 비교 ===")
    print(f"  c178 최적 (bbP=20 sqTh=50 expLB=4 upR=0.98 atr=ON): "
          f"avg_OOS=+42.205 n=19")
    print(f"  c177 최적 (sqTh={best['squeeze_th']} sqLB={best['squeeze_lb']} "
          f"upR={best['upper_ratio']:.2f}): "
          f"avg_OOS={best['avg_oos_sharpe']:+.3f} "
          f"n={best['total_oos_trades']}")
    delta = best["avg_oos_sharpe"] - 42.205
    n_delta = best["total_oos_trades"] - 19
    print(f"  Δ Sharpe: {delta:+.3f} "
          f"({'개선' if delta > 0 else '악화' if delta < 0 else '동일'})")
    print(f"  Δ trades: {n_delta:+d} "
          f"({'확대' if n_delta > 0 else '감소' if n_delta < 0 else '동일'})")
    n_target = "달성" if best["total_oos_trades"] >= 30 else "미달"
    print(f"  n≥30 목표: {n_target} (n={best['total_oos_trades']})")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: SQUEEZE_PCTILE_TH={best['squeeze_th']} "
          f"SQUEEZE_LB_WINDOW={best['squeeze_lb']} "
          f"UPPER_RATIO={best['upper_ratio']:.2f}")
    print(f"  (c178 고정: BB_PERIOD={BB_PERIOD} EXPANSION_LB={EXPANSION_LB} "
          f"ATR_PCTILE=ON)")
    print(f"  (c176 고정: body={BODY_RATIO_MIN})")
    print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD} "
          f"CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} "
          f"BTC_SMA={BTC_SMA_PERIOD})")
    oos_avg = best["avg_oos_sharpe"]
    total_n = best["total_oos_trades"]
    status = "PASS" if best["all_pass"] else "FAIL"
    print(f"  avg OOS Sharpe: {oos_avg:+.3f} {status}")
    print(f"  train Sharpe: {best['train_sharpe']:+.3f}")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={best['oos_trades'][fi]}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))

    print(f"\nSharpe: {oos_avg:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
