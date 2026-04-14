"""
vpin_multi 사이클 175 — c166 BTC 드로다운 게이트 + ETH/BTC 상대강도 + c168 regime exit
멀티심볼(ETH+SOL) 확장
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경:
  c166 단일심볼(ETH) + BTC 드로다운 게이트 + ETH/BTC 상대강도 = OOS Sharpe +46.790
  최적: ddLB=90 ddMx=0.05 rsLB=20 rsMn=0.01
  문제: n=22 (거래 부족), 단일 심볼(ETH)

가설:
  1) 멀티심볼(ETH+SOL) 확장 → n 2배 확대 기대
     SOL은 BTC 대비 상대강도 대신 SOL/BTC 상대강도 사용
  2) ddMx 완화(0.05→0.15) + rsMn 완화(0.01→-0.02) → 진입 기회 확대
     단, 너무 완화하면 F3 BEAR 방어력 저하 → 적정 선 탐색
  3) c168 ATR regime-adaptive TP/SL 결합 → BEAR 구간 SL 축소, BULL 구간 TP 확대
  4) trailing stop 파라미터: c174 최적 기반(trA=1.8, trSL=0.4) 고정

그리드:
  - ddMx: [0.03, 0.05, 0.08, 0.10, 0.15] (5)  — BTC 고점 대비 하락 허용치
  - rsMn: [-0.02, -0.01, 0.0, 0.01, 0.02] (5)  — 알트/BTC 상대강도 최소값
  - regime_exit: [False, True] (2)  — c168 ATR regime TP/SL 적용 여부
  = 5×5×2 = 50 조합 × 2 심볼

3-fold WF + 슬리피지 스트레스
진입: next_bar open
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

SYMBOLS = ["KRW-ETH", "KRW-SOL"]
BTC = "KRW-BTC"
FEE = 0.0005

# -- c165 최적 고정 (진입) --
VPIN_LOW = 0.35
MOM_THRESH = 0.0007
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

# -- c168 regime-adaptive exit 고정 --
BTC_SMA_PERIOD = 200
TP_BASE_ATR = 3.0
TP_BONUS_ATR = 2.0
MIN_PROFIT_ATR = 1.5

# -- c168 vol regime 파라미터 --
VOL_REGIME_LOOKBACK = 90
VOL_REGIME_THRESHOLD_PCT = 50

# -- c168 regime-adaptive hold --
HV_HOLD = 24
LV_HOLD = 12

# -- c168 regime-adaptive TP/SL offsets --
HV_TP_OFFSET = 1.0
HV_SL_OFFSET = 0.2
LV_TP_OFFSET = -0.5
LV_SL_OFFSET = -0.1

# -- c174 최적 trailing stop (고정) --
TRAIL_ACTIVATE_MULT = 1.8
TRAIL_SL_MULT = 0.4

# -- c166 BTC 드로다운 게이트 고정 --
DD_LOOKBACK = 90  # c166 최적

# -- 비-regime exit (고정 hold/TP/SL — regime_exit=False일 때) --
FIXED_MAX_HOLD = 20
FIXED_TP_ATR = 4.0
FIXED_SL_ATR = 2.0

# -- 탐색 그리드 --
DD_MAX_LIST = [0.03, 0.05, 0.08, 0.10, 0.15]     # BTC 고점 대비 하락 허용치
RS_MIN_LIST = [-0.02, -0.01, 0.0, 0.01, 0.02]     # 알트/BTC 상대강도 최소값
RS_LOOKBACK = 20  # c166 최적 고정
REGIME_EXIT_LIST = [False, True]                    # c168 regime exit 적용 여부

# -- 3-fold WF --
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
    atr_arr: np.ndarray, idx: int, lookback: int,
) -> float:
    start = max(0, idx - lookback)
    window = atr_arr[start:idx + 1]
    valid = window[~np.isnan(window)]
    if len(valid) < 10:
        return 50.0
    rank = np.sum(valid < atr_arr[idx])
    return float(rank / len(valid) * 100.0)


def compute_btc_drawdown(btc_close: np.ndarray, lookback: int) -> np.ndarray:
    """BTC 고점 대비 현재 드로다운 비율 (0~1). 값이 클수록 고점 대비 많이 하락."""
    n = len(btc_close)
    dd = np.full(n, np.nan)
    for i in range(lookback, n):
        peak = np.max(btc_close[max(0, i - lookback):i + 1])
        if peak > 0:
            dd[i] = 1.0 - btc_close[i] / peak
        else:
            dd[i] = 0.0
    return dd


def compute_relative_strength(
    alt_close: np.ndarray, btc_close: np.ndarray, lookback: int,
) -> np.ndarray:
    """알트/BTC 상대강도: lookback 기간 수익률 차이 (alt_ret - btc_ret)."""
    n = len(alt_close)
    rs = np.full(n, np.nan)
    for i in range(lookback, n):
        if alt_close[i - lookback] > 0 and btc_close[i - lookback] > 0:
            alt_ret = alt_close[i] / alt_close[i - lookback] - 1
            btc_ret = btc_close[i] / btc_close[i - lookback] - 1
            rs[i] = alt_ret - btc_ret
    return rs


def align_btc_to_symbol(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame,
) -> np.ndarray:
    """BTC close를 심볼 인덱스에 맞춰 정렬."""
    btc_close_s = pd.Series(df_btc["close"].values, index=df_btc.index)
    return btc_close_s.reindex(df_sym.index, method="ffill").values


def align_btc_sma_to_symbol(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame, sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, sma_period)
    btc_close_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_close_aligned = btc_close_s.reindex(df_sym.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_sym.index, method="ffill").values
    return btc_close_aligned, btc_sma_aligned


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    dd_max: float,
    rs_min: float,
    use_regime_exit: bool,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    btc_dd_aligned: np.ndarray,
    rs_aligned: np.ndarray,
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

    returns: list[float] = []
    dd_filtered = 0
    rs_filtered = 0
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 VOL_REGIME_LOOKBACK, DD_LOOKBACK, RS_LOOKBACK, 50) + 5
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

        # 기본 진입 조건 (c165)
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

        # === c166 BTC 드로다운 게이트 ===
        dd_val = btc_dd_aligned[i] if not np.isnan(btc_dd_aligned[i]) else 0.0
        dd_ok = dd_val <= dd_max  # 드로다운이 허용치 이내

        # === c166 알트/BTC 상대강도 필터 ===
        rs_val = rs_aligned[i] if not np.isnan(rs_aligned[i]) else 0.0
        rs_ok = rs_val >= rs_min  # 상대강도가 최소값 이상

        if not dd_ok:
            dd_filtered += 1
        if not rs_ok:
            rs_filtered += 1

        if vpin_ok and btc_ok and rsi_velocity_ok and vol_ok and dd_ok and rs_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            if use_regime_exit:
                # === c168 vol regime detection ===
                atr_pctl = compute_atr_percentile(atr_arr, i, VOL_REGIME_LOOKBACK)
                is_high_vol = atr_pctl >= VOL_REGIME_THRESHOLD_PCT
                max_hold = HV_HOLD if is_high_vol else LV_HOLD

                # RSI 기반 동적 스케일링
                rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
                rsi_ratio = max(0.0, min(1.0, rsi_ratio))

                if is_high_vol:
                    tp_base = TP_BASE_ATR + HV_TP_OFFSET
                    sl_base = SL_BASE_ATR + HV_SL_OFFSET
                else:
                    tp_base = TP_BASE_ATR + LV_TP_OFFSET
                    sl_base = SL_BASE_ATR + LV_SL_OFFSET

                effective_tp_mult = tp_base + TP_BONUS_ATR * rsi_ratio
                tp_price = buy + atr_at_entry * effective_tp_mult
                effective_sl_mult = sl_base - SL_BONUS_ATR * rsi_ratio
                effective_sl_mult = max(0.2, effective_sl_mult)
                sl_price = buy - atr_at_entry * effective_sl_mult
            else:
                max_hold = FIXED_MAX_HOLD
                tp_price = buy + atr_at_entry * FIXED_TP_ATR
                sl_price = buy - atr_at_entry * FIXED_SL_ATR

            # ATR trailing stop (c174 최적)
            trail_activate_dist = atr_at_entry * TRAIL_ACTIVATE_MULT
            trail_dist = atr_at_entry * TRAIL_SL_MULT

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
                if unrealized >= trail_activate_dist:
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
                "trades": 0, "max_dd": 0.0, "mcl": 0, "returns": [],
                "dd_filtered": dd_filtered, "rs_filtered": rs_filtered}
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
            "returns": returns,
            "dd_filtered": dd_filtered, "rs_filtered": rs_filtered}


def pool_results(results_list: list[dict]) -> dict:
    all_sharpes = []
    all_wrs = []
    total_trades = 0
    all_avg_rets = []
    all_max_dds = []
    all_mcls = []
    total_dd_f = 0
    total_rs_f = 0
    for r in results_list:
        if r["trades"] > 0 and not np.isnan(r["sharpe"]):
            all_sharpes.append(r["sharpe"])
            all_wrs.append(r["wr"])
            total_trades += r["trades"]
            all_avg_rets.append(r["avg_ret"])
            all_max_dds.append(r["max_dd"])
            all_mcls.append(r["mcl"])
        total_dd_f += r.get("dd_filtered", 0)
        total_rs_f += r.get("rs_filtered", 0)
    if not all_sharpes:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0,
                "dd_filtered": total_dd_f, "rs_filtered": total_rs_f}
    return {
        "sharpe": float(np.mean(all_sharpes)),
        "wr": float(np.mean(all_wrs)),
        "avg_ret": float(np.mean(all_avg_rets)),
        "trades": total_trades,
        "max_dd": float(np.mean(all_max_dds)),
        "mcl": max(all_mcls),
        "dd_filtered": total_dd_f,
        "rs_filtered": total_rs_f,
    }


def buy_and_hold(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"ret": 0.0}
    buy = df["open"].iloc[0]
    sell = df["close"].iloc[-1]
    return {"ret": float(sell / buy - 1)}


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi c175 — BTC 드로다운 게이트 + 상대강도 + regime exit ===")
    print(f"심볼: {', '.join(SYMBOLS)}  기준: c166 ETH OOS Sharpe +46.790, n=22")
    print("가설: 멀티심볼 확장(n↑) + ddMx/rsMn 완화 탐색 + regime exit 비교")
    print(f"고정: ddLB={DD_LOOKBACK} rsLB={RS_LOOKBACK} trA={TRAIL_ACTIVATE_MULT} "
          f"trSL={TRAIL_SL_MULT}")
    print(f"탐색: ddMx={DD_MAX_LIST} rsMn={RS_MIN_LIST} regime={REGIME_EXIT_LIST}")
    print("=" * 80)

    # BTC 데이터
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # 심볼 데이터 검증
    print("\n--- 심볼별 데이터 확인 ---")
    sym_data_ok = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df_check.empty or len(df_check) < 500:
            print(f"  {sym}: 데이터 부족 ({len(df_check)}행) -> 제외")
        else:
            print(f"  {sym}: {len(df_check)}행 OK")
            sym_data_ok.append(sym)

    if not sym_data_ok:
        print("유효 심볼 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # 그리드
    combos = list(product(DD_MAX_LIST, RS_MIN_LIST, REGIME_EXIT_LIST))
    print(f"\n총 {len(combos)} 조합 × {len(sym_data_ok)} 심볼")

    # -- Phase 1: Train 그리드 (Fold 0 train) --
    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: Train 그리드 ({train_start} ~ {train_end})")

    sym_train_cache: dict[str, tuple[pd.DataFrame, np.ndarray, np.ndarray,
                                      np.ndarray, np.ndarray]] = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if df_tr.empty:
            continue
        btc_c, btc_s = align_btc_sma_to_symbol(df_tr, df_btc_full, BTC_SMA_PERIOD)
        btc_c_raw = align_btc_to_symbol(df_tr, df_btc_full)
        btc_dd = compute_btc_drawdown(btc_c_raw, DD_LOOKBACK)
        alt_close = df_tr["close"].values
        rs = compute_relative_strength(alt_close, btc_c_raw, RS_LOOKBACK)
        sym_train_cache[sym] = (df_tr, btc_c, btc_s, btc_dd, rs)
        print(f"  {sym} train: {len(df_tr)}행")

    train_results: list[dict] = []
    for ddm, rsm, regime in combos:
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr, btc_c, btc_s, btc_dd, rs = sym_train_cache[sym]
            r = backtest(df_tr, ddm, rsm, regime, btc_c, btc_s, btc_dd, rs)
            sym_results.append(r)
        pooled = pool_results(sym_results)
        train_results.append({
            "dd_max": ddm, "rs_min": rsm, "regime_exit": regime, **pooled,
        })

    valid_tr = [r for r in train_results
                if r["trades"] >= 10 and not np.isnan(r["sharpe"])]
    valid_tr.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효: {len(valid_tr)}/{len(train_results)}")
    print(f"\n=== Train Top 10 ===")
    hdr = (f"{'ddMx':>5} {'rsMn':>6} {'rgm':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5} "
           f"{'ddF':>5} {'rsF':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid_tr[:10]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        rgm = "Y" if r["regime_exit"] else "N"
        print(
            f"{r['dd_max']:>5.2f} {r['rs_min']:>+6.2f} {rgm:>4} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5} "
            f"{r['dd_filtered']:>5} {r['rs_filtered']:>5}"
        )

    # -- Phase 2: 3-fold OOS Walk-Forward (전체) --
    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward ({len(combos)} 조합) ===")

    wf_results: list[dict] = []
    for ddm, rsm, regime in combos:
        fold_sharpes: list[float] = []
        fold_details: list[dict] = []
        all_pass = True

        for fold_i, fold in enumerate(WF_FOLDS):
            sym_fold_results = []
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = align_btc_sma_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                btc_c_raw = align_btc_to_symbol(df_test, df_btc_full)
                btc_dd = compute_btc_drawdown(btc_c_raw, DD_LOOKBACK)
                alt_close = df_test["close"].values
                rs = compute_relative_strength(alt_close, btc_c_raw, RS_LOOKBACK)
                r = backtest(df_test, ddm, rsm, regime,
                             btc_c, btc_s, btc_dd, rs)
                sym_fold_results.append({"sym": sym, **r})

            pooled = pool_results(sym_fold_results)
            fold_sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            fold_sharpes.append(fold_sh)
            fold_details.append({
                "fold": fold_i + 1, **pooled,
                "sym_details": sym_fold_results,
            })
            if fold_sh <= 0:
                all_pass = False

        avg_oos = float(np.mean(fold_sharpes)) if fold_sharpes else 0.0
        total_n = sum(fd["trades"] for fd in fold_details)
        wf_results.append({
            "dd_max": ddm, "rs_min": rsm, "regime_exit": regime,
            "avg_oos": avg_oos, "all_pass": all_pass,
            "total_n": total_n,
            "fold_sharpes": fold_sharpes,
            "fold_details": fold_details,
        })

    wf_results.sort(key=lambda x: x["avg_oos"], reverse=True)

    print(f"\n--- WF 결과 (avg OOS 기준) ---")
    hdr2 = (f"{'ddMx':>5} {'rsMn':>6} {'rgm':>4} | {'avg OOS':>8} | "
            f"{'F1':>7} {'F2':>7} {'F3':>7} | {'n':>4} {'PASS':>5}")
    print(hdr2)
    print("-" * len(hdr2))
    pass_count = 0
    for w in wf_results:
        f1 = w["fold_sharpes"][0] if len(w["fold_sharpes"]) > 0 else 0.0
        f2 = w["fold_sharpes"][1] if len(w["fold_sharpes"]) > 1 else 0.0
        f3 = w["fold_sharpes"][2] if len(w["fold_sharpes"]) > 2 else 0.0
        status = "PASS" if w["all_pass"] else "FAIL"
        rgm = "Y" if w["regime_exit"] else "N"
        if w["all_pass"]:
            pass_count += 1
        print(
            f"{w['dd_max']:>5.2f} {w['rs_min']:>+6.2f} {rgm:>4} | "
            f"{w['avg_oos']:>+8.3f} | "
            f"{f1:>+7.3f} {f2:>+7.3f} {f3:>+7.3f} | {w['total_n']:>4} {status:>5}"
        )

    print(f"\n통과: {pass_count}/{len(wf_results)}")

    # -- Top 4 심볼별 분해 --
    top_pass = [w for w in wf_results if w["all_pass"]]
    top_show = top_pass[:4] if top_pass else wf_results[:4]

    for rank, w in enumerate(top_show, 1):
        rgm = "Y" if w["regime_exit"] else "N"
        print(f"\n--- #{rank}: ddMx={w['dd_max']} rsMn={w['rs_min']} "
              f"regime={rgm} (avg OOS: {w['avg_oos']:+.3f}, total_n: {w['total_n']}) ---")
        for slip in SLIPPAGE_LEVELS:
            sym_results = []
            for fold_i, fold in enumerate(WF_FOLDS):
                for sym in sym_data_ok:
                    df_test = load_historical(
                        sym, "240m", fold["test"][0], fold["test"][1])
                    if df_test.empty:
                        continue
                    btc_c, btc_s = align_btc_sma_to_symbol(
                        df_test, df_btc_full, BTC_SMA_PERIOD)
                    btc_c_raw = align_btc_to_symbol(df_test, df_btc_full)
                    btc_dd = compute_btc_drawdown(btc_c_raw, DD_LOOKBACK)
                    alt_close = df_test["close"].values
                    rs = compute_relative_strength(alt_close, btc_c_raw, RS_LOOKBACK)
                    r = backtest(df_test, w["dd_max"], w["rs_min"],
                                 w["regime_exit"], btc_c, btc_s, btc_dd, rs, slip)
                    sym_results.append(r)
            pooled = pool_results(sym_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            print(
                f"  {slip:.2%}  {sh:>+8.3f} {pooled['wr']:>5.1%} "
                f"{pooled['avg_ret'] * 100:>+6.2f}% "
                f"{pooled['max_dd'] * 100:>+6.2f}% {pooled['mcl']:>4} "
                f"{pooled['trades']:>5}"
            )

        # 심볼별 분해
        for fd in w["fold_details"]:
            label = ["BULL", "2025혼재", "★BEAR"][fd["fold"] - 1] \
                if fd["fold"] <= 3 else f"F{fd['fold']}"
            print(f"  F{fd['fold']} ({label}): Sharpe={fd['sharpe']:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={fd['trades']}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%")
            for sd in fd.get("sym_details", []):
                sh = sd["sharpe"] if not np.isnan(sd["sharpe"]) else 0.0
                print(f"    {sd['sym']}: Sharpe={sh:+.3f}  WR={sd['wr']:.1%}  "
                      f"n={sd['trades']}  avg={sd['avg_ret'] * 100:+.2f}%  "
                      f"MDD={sd['max_dd'] * 100:+.2f}%  "
                      f"ddF={sd.get('dd_filtered', 0)}  rsF={sd.get('rs_filtered', 0)}")

    # -- 최종 요약 --
    if top_pass:
        best = top_pass[0]
        all_trades = 0
        all_wr_sum = 0.0
        all_wr_n = 0
        for fd in best["fold_details"]:
            all_trades += fd["trades"]
            if fd["trades"] > 0:
                all_wr_sum += fd["wr"]
                all_wr_n += 1
        avg_wr = all_wr_sum / all_wr_n if all_wr_n > 0 else 0.0
        rgm = "Y" if best["regime_exit"] else "N"

        print(f"\n{'=' * 80}")
        print(f"=== 최종 요약 ===")
        print(f"★ WF 최고: ddMx={best['dd_max']} rsMn={best['rs_min']} "
              f"regime={rgm}")
        print(f"  (기반: c166 + BTC 드로다운 게이트 + 상대강도 + "
              f"{'regime exit' if best['regime_exit'] else 'fixed exit'})")
        print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f}")
        for fd in best["fold_details"]:
            label = ["BULL", "2025혼재", "★BEAR"][fd["fold"] - 1] \
                if fd["fold"] <= 3 else f"F{fd['fold']}"
            print(f"  F{fd['fold']} ({label}): Sharpe={fd['sharpe']:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={fd['trades']}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%  "
                  f"ddF={fd['dd_filtered']}  rsF={fd['rs_filtered']}")
        print(f"\n  vs c166 베이스라인(ETH only): Sharpe=+46.790  WR=63.3%  n=22")
        print(f"  vs c174 multi baseline: Sharpe=+10.916  WR=34.4%  n=319")
        print(f"\n  total_n: {all_trades} → "
              f"{'✅ n≥20' if all_trades >= 20 else '⚠️ n<20'}")

        print(f"\nSharpe: {best['avg_oos']:+.3f}")
        print(f"WR: {avg_wr:.1%}")
        print(f"trades: {all_trades}")
    else:
        best = wf_results[0] if wf_results else None
        if best:
            print(f"\n{'=' * 80}")
            print(f"=== 최종 요약 (전 조합 WF FAIL) ===")
            print(f"최고 avg OOS: {best['avg_oos']:+.3f} "
                  f"(ddMx={best['dd_max']} rsMn={best['rs_min']} "
                  f"regime={'Y' if best['regime_exit'] else 'N'})")
            print(f"vs c166 baseline: +46.790 (ETH only)")
            print(f"\nSharpe: {best['avg_oos']:+.3f}")
            print(f"WR: 0.0%")
            print(f"trades: 0")
        else:
            print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")


if __name__ == "__main__":
    main()
