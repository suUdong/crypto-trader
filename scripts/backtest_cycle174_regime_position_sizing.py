"""
c174: vol_regime 기반 동적 포지션 사이징 — 3-fold WF 검증 (ETH/SOL/XRP)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
평가자 [explore]: capital_allocator.py에 vol_regime 기반 동적 사이징 로직 추가.
BEAR(HV regime): max_position 50%, BULL(LV regime): max_position 100%.

가설: ATR percentile 기반 HV/LV 레짐 감지로 HV 구간에서 포지션 축소하면
      Sharpe 유지하면서 MDD 개선 가능.

기반: c165 최적 파라미터 (VPIN=0.35 MOM=0.0007 Hold=20 CD=4)
설계:
  - ATR lookback [60, 90, 120] × HV threshold [40, 50, 60]
  - HV size_mult [0.3, 0.5, 0.7] × LV size_mult [1.0]
  - 3 × 3 × 3 = 27 조합 + baseline(no regime sizing)
  - 멀티심볼: ETH/SOL/XRP (c165/c170 검증 심볼)
  - 3-fold WF (c174 OOS 윈도우):
    F1: train 2022-01-01~2024-03-31 → OOS 2024-04-01~2025-01-31
    F2: train 2022-07-01~2024-09-30 → OOS 2024-10-01~2025-07-31
    F3: train 2023-01-01~2025-03-31 → OOS 2025-04-01~2026-04-05
  - 비교: baseline(고정 사이징) vs regime-adaptive 사이징
  - 핵심 지표: Sharpe, MDD 개선률, trade count 변화
  - 슬리피지 스트레스 포함
  - 다음봉시가 진입

통과 기준: avg OOS Sharpe >= 5.0 AND 모든 fold >= 1.0 AND MDD 개선 > 0%
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

# -- 심볼 --
SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]
FEE = 0.0005

# -- 고정값 (c152/c157/c163/c164/c165 검증 완료) --
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

# -- c164 최적 고정 --
RSI_DELTA_LB = 3
RSI_DELTA_MIN = 0.0
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD = 20
VOL_SMA_PERIOD = 20

# -- c163 최적 고정 (TP/Trail) --
BTC_SMA_PERIOD = 200
TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

# -- c165 최적 진입 (고정) --
VPIN_LOW = 0.35
MOM_THRESH = 0.0007
MAX_HOLD = 20
COOLDOWN_BARS = 4

# -- 레짐 포지션 사이징 그리드 --
ATR_LB_LIST = [60, 90, 120]
HV_THRESH_LIST = [40, 50, 60]
HV_SIZE_MULT_LIST = [0.3, 0.5, 0.7]
LV_SIZE_MULT = 1.0  # LV에서는 풀 사이즈 고정

# -- 3-fold WF (c174 OOS 윈도우 — oos_window_registry 등록 완료) --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# -- 지표 (c165/c171 동일) --

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


def compute_atr_percentile(atr_arr: np.ndarray, lookback: int) -> np.ndarray:
    n = len(atr_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = atr_arr[i - lookback:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) < 10:
            continue
        result[i] = float(np.sum(valid <= atr_arr[i]) / len(valid) * 100)
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


# -- 백테스트 (포지션 사이징 추가) --

def backtest(
    df: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    slippage: float = 0.0005,
    *,
    atr_lb: int = 0,
    hv_thresh: float = 50.0,
    hv_size_mult: float = 1.0,
    lv_size_mult: float = 1.0,
) -> dict:
    """
    c165 VPIN 전략 백테스트 + vol_regime 포지션 사이징.
    atr_lb=0이면 레짐 사이징 비활성(baseline).
    size_mult는 수익/손실에 곱해지는 가상 배수.
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

    # ATR percentile for regime sizing
    use_regime_sizing = atr_lb > 0
    if use_regime_sizing:
        atr_pctl_arr = compute_atr_percentile(atr_arr, atr_lb)
    else:
        atr_pctl_arr = np.full(n, np.nan)

    returns: list[float] = []
    size_mults_used: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 atr_lb if use_regime_sizing else 0, 50) + 5
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

        # 진입 조건
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

        if vpin_ok and btc_ok and rsi_velocity_ok and vol_ok:
            # 레짐 기반 포지션 사이즈 결정
            size_mult = 1.0
            if use_regime_sizing and not np.isnan(atr_pctl_arr[i]):
                if atr_pctl_arr[i] > hv_thresh:
                    size_mult = hv_size_mult
                else:
                    size_mult = lv_size_mult

            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # TP/SL/Trail (c163/c164 검증)
            effective_tp_mult = TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
            tp_price = buy + atr_at_entry * effective_tp_mult

            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            effective_trail_mult = (
                TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            )
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

            # 포지션 사이즈 배수 적용 (수익/손실에 곱함)
            adjusted_ret = exit_ret * size_mult
            returns.append(adjusted_ret)
            size_mults_used.append(size_mult)

            if adjusted_ret < 0:
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
                "avg_size_mult": 1.0, "hv_trade_pct": 0.0}

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

    sm = np.array(size_mults_used)
    avg_sm = float(sm.mean()) if len(sm) > 0 else 1.0
    hv_pct = float((sm < 1.0).mean()) if len(sm) > 0 else 0.0

    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl,
            "returns": returns, "avg_size_mult": avg_sm,
            "hv_trade_pct": hv_pct}


def compute_buy_and_hold(df: pd.DataFrame) -> float:
    if df.empty or len(df) < 2:
        return 0.0
    return float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)


def main() -> None:
    print("=" * 80)
    print("=== c174: vol_regime 포지션 사이징 — 3-fold WF (ETH/SOL/XRP) ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"기반: c165 VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD} CD={COOLDOWN_BARS}")
    print(f"레짐 그리드: ATR_LB {ATR_LB_LIST} × HV_TH {HV_THRESH_LIST} "
          f"× HV_SIZE {HV_SIZE_MULT_LIST} = "
          f"{len(ATR_LB_LIST) * len(HV_THRESH_LIST) * len(HV_SIZE_MULT_LIST)} combos")
    print("=" * 80)

    # -- BTC 데이터 --
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # -- 심볼 데이터 확인 --
    print("\n--- 심볼 데이터 확인 ---")
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        print(f"  {sym}: {len(df_check)}행" if not df_check.empty else f"  {sym}: 없음")

    combos = list(product(ATR_LB_LIST, HV_THRESH_LIST, HV_SIZE_MULT_LIST))
    print(f"\n총 레짐 조합: {len(combos)}개 + 1 baseline = {len(combos) + 1}")

    # ══════════════════════════════════════════════════════════════════════════
    # 1) 멀티심볼 풀링 baseline (레짐 사이징 없음)
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("=== STEP 1: Baseline (고정 사이징) — 3-fold WF ===")

    baseline_fold_sharpes: list[float] = []
    baseline_fold_trades: list[int] = []
    baseline_fold_mdds: list[float] = []
    baseline_fold_details: list[list[dict]] = []

    for fi, fold in enumerate(WF_FOLDS):
        fold_returns_all: list[float] = []
        fold_sym_details: list[dict] = []
        for sym in SYMBOLS:
            df_test = load_historical(sym, "240m", fold["test"][0], fold["test"][1])
            if df_test.empty:
                fold_sym_details.append(
                    {"sym": sym, "sharpe": 0.0, "trades": 0, "max_dd": 0.0})
                continue
            btc_c, btc_s = align_btc_to_symbol(df_test, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_test, btc_c, btc_s)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            fold_returns_all.extend(r.get("returns", []))
            fold_sym_details.append({
                "sym": sym, "sharpe": sh, "trades": r["trades"],
                "max_dd": r["max_dd"], "wr": r["wr"],
                "avg_ret": r["avg_ret"],
            })

        # 풀링 Sharpe
        if len(fold_returns_all) >= 3:
            arr = np.array(fold_returns_all)
            pool_sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
            cum = np.cumsum(arr)
            pk = np.maximum.accumulate(cum)
            pool_mdd = float((cum - pk).min())
        else:
            pool_sh = 0.0
            pool_mdd = 0.0
        pool_n = len(fold_returns_all)

        baseline_fold_sharpes.append(pool_sh)
        baseline_fold_trades.append(pool_n)
        baseline_fold_mdds.append(pool_mdd)
        baseline_fold_details.append(fold_sym_details)

        print(f"  F{fi + 1} ({fold['test'][0]}~{fold['test'][1]}): "
              f"Sharpe={pool_sh:+.3f} n={pool_n} MDD={pool_mdd * 100:+.2f}%")
        for sd in fold_sym_details:
            print(f"    {sd['sym']}: Sharpe={sd['sharpe']:+.3f} n={sd['trades']} "
                  f"MDD={sd.get('max_dd', 0) * 100:+.2f}%")

    baseline_avg = float(np.mean(baseline_fold_sharpes))
    baseline_avg_mdd = float(np.mean(baseline_fold_mdds))
    baseline_total_n = sum(baseline_fold_trades)
    print(f"\n  Baseline avg OOS Sharpe: {baseline_avg:+.3f} | "
          f"avg MDD: {baseline_avg_mdd * 100:+.2f}% | total n: {baseline_total_n}")

    # ══════════════════════════════════════════════════════════════════════════
    # 2) 레짐 사이징 그리드 — 3-fold WF
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("=== STEP 2: 레짐 사이징 그리드 — 3-fold WF ===")
    print(f"{'#':>3} {'atrLB':>6} {'hvTH':>5} {'hvSz':>5} | "
          f"{'avgOOS':>8} {'avgMDD':>8} {'ΔMDD':>6} {'ΔSh':>6} | "
          f"{'F1':>7} {'F2':>7} {'F3':>7} {'n':>5} {'hvPct':>6}")
    print("-" * 95)

    wf_results: list[dict] = []
    combo_idx = 0

    for atr_lb, hv_th, hv_sz in combos:
        combo_idx += 1
        fold_sharpes: list[float] = []
        fold_trades: list[int] = []
        fold_mdds: list[float] = []
        fold_hv_pcts: list[float] = []
        fold_sym_details_all: list[list[dict]] = []

        for fi, fold in enumerate(WF_FOLDS):
            fold_returns_all: list[float] = []
            fold_sym_details: list[dict] = []
            fold_hv_trades = []

            for sym in SYMBOLS:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    fold_sym_details.append(
                        {"sym": sym, "sharpe": 0.0, "trades": 0, "max_dd": 0.0})
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(
                    df_test, btc_c, btc_s,
                    atr_lb=atr_lb, hv_thresh=hv_th,
                    hv_size_mult=hv_sz, lv_size_mult=LV_SIZE_MULT,
                )
                sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
                fold_returns_all.extend(r.get("returns", []))
                fold_hv_trades.append(r.get("hv_trade_pct", 0.0))
                fold_sym_details.append({
                    "sym": sym, "sharpe": sh, "trades": r["trades"],
                    "max_dd": r["max_dd"],
                })

            if len(fold_returns_all) >= 3:
                arr = np.array(fold_returns_all)
                pool_sh = float(
                    arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
                cum = np.cumsum(arr)
                pk = np.maximum.accumulate(cum)
                pool_mdd = float((cum - pk).min())
            else:
                pool_sh = 0.0
                pool_mdd = 0.0

            fold_sharpes.append(pool_sh)
            fold_trades.append(len(fold_returns_all))
            fold_mdds.append(pool_mdd)
            fold_hv_pcts.append(
                float(np.mean(fold_hv_trades)) if fold_hv_trades else 0.0)
            fold_sym_details_all.append(fold_sym_details)

        avg_sh = float(np.mean(fold_sharpes))
        min_sh = min(fold_sharpes)
        avg_mdd = float(np.mean(fold_mdds))
        total_n = sum(fold_trades)
        avg_hv_pct = float(np.mean(fold_hv_pcts))

        delta_sh = avg_sh - baseline_avg
        delta_mdd = avg_mdd - baseline_avg_mdd  # less negative = improvement

        wf_results.append({
            "atr_lb": atr_lb, "hv_thresh": hv_th, "hv_size_mult": hv_sz,
            "avg_oos_sharpe": avg_sh, "min_oos_sharpe": min_sh,
            "avg_mdd": avg_mdd, "delta_mdd": delta_mdd, "delta_sh": delta_sh,
            "oos_sharpes": fold_sharpes, "oos_trades": fold_trades,
            "oos_mdds": fold_mdds, "total_n": total_n,
            "avg_hv_pct": avg_hv_pct,
            "fold_sym_details": fold_sym_details_all,
        })

        print(f"{combo_idx:>3} {atr_lb:>6} {hv_th:>5} {hv_sz:>5.1f} | "
              f"{avg_sh:>+8.3f} {avg_mdd * 100:>+7.2f}% {delta_mdd * 100:>+5.2f} "
              f"{delta_sh:>+5.2f} | "
              f"{fold_sharpes[0]:>+7.3f} {fold_sharpes[1]:>+7.3f} "
              f"{fold_sharpes[2]:>+7.3f} {total_n:>5} {avg_hv_pct * 100:>5.1f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # 3) 결과 분석
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("=== STEP 3: 결과 분석 ===")

    # MDD 개선 기준 정렬 (delta_mdd > 0 = 개선)
    wf_sorted_mdd = sorted(wf_results, key=lambda x: x["delta_mdd"], reverse=True)
    # Sharpe 기준 정렬
    wf_sorted_sh = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"], reverse=True)

    # Sharpe 유지 + MDD 개선 조합 (Sharpe 감소 < 10% AND MDD 개선 > 0)
    good_combos = [
        r for r in wf_results
        if r["delta_mdd"] > 0 and r["delta_sh"] > -abs(baseline_avg) * 0.1
        and r["min_oos_sharpe"] >= 1.0
    ]
    good_combos.sort(key=lambda x: x["delta_mdd"], reverse=True)

    print(f"\n  Baseline: avg Sharpe {baseline_avg:+.3f} | "
          f"avg MDD {baseline_avg_mdd * 100:+.2f}%")
    print(f"  총 조합: {len(combos)}")
    print(f"  Sharpe 유지 + MDD 개선: {len(good_combos)}/{len(combos)}")

    print(f"\n--- Top 10 MDD 개선 (Sharpe 유지) ---")
    print(f"{'#':>3} {'atrLB':>6} {'hvTH':>5} {'hvSz':>5} | "
          f"{'avgSh':>8} {'ΔSh':>6} {'avgMDD':>8} {'ΔMDD':>6} | "
          f"{'F1':>7} {'F2':>7} {'F3':>7} {'n':>5}")
    print("-" * 90)
    for rank, r in enumerate(good_combos[:10], 1):
        print(f"{rank:>3} {r['atr_lb']:>6} {r['hv_thresh']:>5} "
              f"{r['hv_size_mult']:>5.1f} | "
              f"{r['avg_oos_sharpe']:>+8.3f} {r['delta_sh']:>+5.2f} "
              f"{r['avg_mdd'] * 100:>+7.2f}% {r['delta_mdd'] * 100:>+5.2f} | "
              f"{r['oos_sharpes'][0]:>+7.3f} {r['oos_sharpes'][1]:>+7.3f} "
              f"{r['oos_sharpes'][2]:>+7.3f} {r['total_n']:>5}")

    print(f"\n--- Top 5 Sharpe ---")
    for rank, r in enumerate(wf_sorted_sh[:5], 1):
        print(f"  #{rank}: atrLB={r['atr_lb']} hvTH={r['hv_thresh']} "
              f"hvSz={r['hv_size_mult']} → "
              f"Sharpe {r['avg_oos_sharpe']:+.3f} (Δ{r['delta_sh']:+.3f}) "
              f"MDD {r['avg_mdd'] * 100:+.2f}% (Δ{r['delta_mdd'] * 100:+.2f})")

    # ══════════════════════════════════════════════════════════════════════════
    # 4) 최적 조합 상세 + 심볼별 분해
    # ══════════════════════════════════════════════════════════════════════════
    # 최적 = MDD 개선 최대이면서 Sharpe >= baseline * 0.9
    if good_combos:
        best = good_combos[0]
    elif wf_sorted_sh:
        best = wf_sorted_sh[0]
    else:
        print("\n유효 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    print(f"\n{'=' * 80}")
    print(f"=== 최적 조합 상세 ===")
    print(f"  ATR_LB={best['atr_lb']} HV_THRESH={best['hv_thresh']} "
          f"HV_SIZE={best['hv_size_mult']}")
    print(f"  avg OOS Sharpe: {best['avg_oos_sharpe']:+.3f} "
          f"(baseline {baseline_avg:+.3f}, Δ{best['delta_sh']:+.3f})")
    print(f"  avg MDD: {best['avg_mdd'] * 100:+.2f}% "
          f"(baseline {baseline_avg_mdd * 100:+.2f}%, "
          f"Δ{best['delta_mdd'] * 100:+.2f}%)")
    print(f"  avg HV trade ratio: {best['avg_hv_pct'] * 100:.1f}%")
    print(f"  total trades: {best['total_n']}")

    # Fold별 심볼별 상세
    for fi in range(3):
        fold = WF_FOLDS[fi]
        print(f"\n  --- F{fi+1} ({fold['test'][0]}~{fold['test'][1]}) ---")
        print(f"    Pool: Sharpe={best['oos_sharpes'][fi]:+.3f} "
              f"n={best['oos_trades'][fi]} MDD={best['oos_mdds'][fi]*100:+.2f}%")
        if fi < len(best["fold_sym_details"]):
            for sd in best["fold_sym_details"][fi]:
                print(f"      {sd['sym']}: Sharpe={sd['sharpe']:+.3f} "
                      f"n={sd['trades']} MDD={sd['max_dd']*100:+.2f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # 5) 슬리피지 스트레스
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 (최적 + baseline 비교) ===")
    print(f"  {'slip':>6} | {'Regime Sh':>10} {'Regime MDD':>10} | "
          f"{'Base Sh':>10} {'Base MDD':>10} | {'ΔSh':>6} {'ΔMDD':>6} {'n':>5}")
    print(f"  {'-' * 75}")

    best_sh_overall = 0.0
    best_wr_overall = 0.0
    best_n_overall = 0

    for slip in SLIPPAGE_LEVELS:
        regime_rets: list[float] = []
        base_rets: list[float] = []

        for sym in SYMBOLS:
            df_full = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
            if df_full.empty:
                continue
            btc_c, btc_s = align_btc_to_symbol(df_full, df_btc_full, BTC_SMA_PERIOD)

            r_regime = backtest(
                df_full, btc_c, btc_s, slippage=slip,
                atr_lb=best["atr_lb"], hv_thresh=best["hv_thresh"],
                hv_size_mult=best["hv_size_mult"],
                lv_size_mult=LV_SIZE_MULT,
            )
            r_base = backtest(df_full, btc_c, btc_s, slippage=slip)

            regime_rets.extend(r_regime.get("returns", []))
            base_rets.extend(r_base.get("returns", []))

        if len(regime_rets) >= 3:
            ra = np.array(regime_rets)
            r_sh = float(ra.mean() / (ra.std() + 1e-9) * np.sqrt(252 * 6))
            r_wr = float((ra > 0).mean())
            cum = np.cumsum(ra)
            pk = np.maximum.accumulate(cum)
            r_mdd = float((cum - pk).min())
        else:
            r_sh, r_wr, r_mdd = 0.0, 0.0, 0.0

        if len(base_rets) >= 3:
            ba = np.array(base_rets)
            b_sh = float(ba.mean() / (ba.std() + 1e-9) * np.sqrt(252 * 6))
            cum = np.cumsum(ba)
            pk = np.maximum.accumulate(cum)
            b_mdd = float((cum - pk).min())
        else:
            b_sh, b_mdd = 0.0, 0.0

        d_sh = r_sh - b_sh
        d_mdd = r_mdd - b_mdd

        print(f"  {slip*100:>5.2f}% | {r_sh:>+10.3f} {r_mdd*100:>+9.2f}% | "
              f"{b_sh:>+10.3f} {b_mdd*100:>+9.2f}% | "
              f"{d_sh:>+5.2f} {d_mdd*100:>+5.2f} {len(regime_rets):>5}")

        if slip == 0.0010:
            best_sh_overall = r_sh
            best_wr_overall = r_wr
            best_n_overall = len(regime_rets)

    # ══════════════════════════════════════════════════════════════════════════
    # 6) Baseline 대비 비교 요약
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("=== Baseline 대비 비교 ===")
    print(f"  Baseline (고정 사이징): avg OOS Sharpe {baseline_avg:+.3f} | "
          f"avg MDD {baseline_avg_mdd * 100:+.2f}% | n={baseline_total_n}")
    print(f"  Regime (최적):          avg OOS Sharpe {best['avg_oos_sharpe']:+.3f} | "
          f"avg MDD {best['avg_mdd'] * 100:+.2f}% | n={best['total_n']}")
    print(f"  Δ Sharpe: {best['delta_sh']:+.3f}")
    print(f"  Δ MDD:    {best['delta_mdd'] * 100:+.2f}% "
          f"({'개선' if best['delta_mdd'] > 0 else '악화'})")
    print(f"  HV 거래 비율: {best['avg_hv_pct'] * 100:.1f}%")

    # 배포 판단
    deploy_ok = (
        best["avg_oos_sharpe"] >= 5.0
        and best["min_oos_sharpe"] >= 1.0
        and best["delta_mdd"] > 0
    )
    print(f"\n  배포 가능: {'✅' if deploy_ok else '❌'}")
    if not deploy_ok:
        reasons: list[str] = []
        if best["avg_oos_sharpe"] < 5.0:
            reasons.append(f"avg Sharpe {best['avg_oos_sharpe']:+.3f} < 5.0")
        if best["min_oos_sharpe"] < 1.0:
            reasons.append(f"min Sharpe {best['min_oos_sharpe']:+.3f} < 1.0")
        if best["delta_mdd"] <= 0:
            reasons.append(f"MDD 악화 Δ{best['delta_mdd']*100:+.2f}%")
        print(f"  사유: {'; '.join(reasons)}")

    # 최종 요약 (research_loop parsing용)
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: ATR_LB={best['atr_lb']} "
          f"HV_THRESH={best['hv_thresh']} HV_SIZE={best['hv_size_mult']}")
    print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} "
          f"Hold={MAX_HOLD} CD={COOLDOWN_BARS})")
    print(f"  (c164 고정: dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} "
          f"minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD})")
    print(f"  avg OOS Sharpe: {best['avg_oos_sharpe']:+.3f} "
          f"{'PASS' if best['avg_oos_sharpe'] >= 5.0 else 'FAIL'}")
    print(f"  avg MDD: {best['avg_mdd'] * 100:+.2f}% "
          f"(baseline {baseline_avg_mdd * 100:+.2f}%)")
    print(f"  Δ MDD: {best['delta_mdd'] * 100:+.2f}% "
          f"({'개선' if best['delta_mdd'] > 0 else '악화'})")
    for fi in range(3):
        print(f"  Fold {fi+1}: Sharpe={best['oos_sharpes'][fi]:+.3f}  "
              f"trades={best['oos_trades'][fi]}  "
              f"MDD={best['oos_mdds'][fi]*100:+.2f}%")

    print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
    print(f"WR: {best_wr_overall * 100:.1f}%")
    print(f"trades: {best['total_n']}")


if __name__ == "__main__":
    main()
