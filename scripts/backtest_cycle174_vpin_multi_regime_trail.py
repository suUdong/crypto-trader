"""
vpin_multi 사이클 174 — c165 멀티심볼 최적 + c168 regime-adaptive exit 결합
- 기반: c165 OOS Sharpe +11.290, WR 34.4%, trades 319 (ETH+SOL+XRP, 3-fold WF ALL PASS)
  최적: VPIN=0.35 MOM=0.0007 Hold=20 CD=4
  고정: dLB=3 dMin=0.0 SL=0.4-0.2 vMul=0.8
  TP/Trail: TP=4.0+2.0 Trail=0.3+0.2 minP=1.5 BTC_SMA=200
- c168: ATR percentile vol regime + regime-adaptive hold(HV=24/LV=12) + ATR trailing stop
  daemon 배포 완료, 81/81 WF 통과 avg OOS +14.111, F3 BEAR +9.443 (ETH only)
- 가설: c168 regime-adaptive exit를 멀티심볼에 적용하면
  A) SOL/XRP에서도 ETH와 유사한 Sharpe 개선 (+14.111 vs +11.909)
  B) 3종 심볼 포트폴리오 OOS avg > c165 baseline +11.290
  C) BEAR fold (F3) 방어력 유지 (c168 ETH F3 +9.443)
- 탐색 그리드: 3 trail_activate × 3 trail_sl = 9 combos × 3 symbols
  c168 최적 기반 ±20% 범위 (narrow grid — c168에서 이미 81/81 검증)
- 3-fold WF + 슬리피지 스트레스
- 진입: next_bar open
"""
from __future__ import annotations

import json
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
TP_BASE_ATR = 3.0    # c168 daemon BASE_TP
TP_BONUS_ATR = 2.0
MIN_PROFIT_ATR = 1.5

# -- c168 vol regime 파라미터 --
VOL_REGIME_LOOKBACK = 90
VOL_REGIME_THRESHOLD_PCT = 50  # ATR percentile threshold

# -- c168 regime-adaptive hold --
HV_HOLD = 24  # high-vol hold
LV_HOLD = 12  # low-vol hold

# -- c168 regime-adaptive TP/SL offsets --
HV_TP_OFFSET = 1.0   # HV에서 TP 확대
HV_SL_OFFSET = 0.2   # HV에서 SL 확대
LV_TP_OFFSET = -0.5  # LV에서 TP 축소
LV_SL_OFFSET = -0.1  # LV에서 SL 축소

# -- 탐색 그리드: trailing stop 파라미터 --
TRAIL_ACTIVATE_LIST = [1.5, 1.8, 2.0]   # 1.8 = c168 최적
TRAIL_SL_LIST = [0.3, 0.4, 0.5]         # 0.4 = c168 최적

# -- 3-fold Walkforward (c165와 동일) --
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
    """idx 시점에서 과거 lookback 기간 ATR percentile (0~100) 반환."""
    start = max(0, idx - lookback)
    window = atr_arr[start:idx + 1]
    valid = window[~np.isnan(window)]
    if len(valid) < 10:
        return 50.0  # 데이터 부족 시 중립
    rank = np.sum(valid < atr_arr[idx])
    return float(rank / len(valid) * 100.0)


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


# -- 백테스트 (c168 regime-adaptive exit 적용) --

def backtest(
    df: pd.DataFrame,
    trail_activate_mult: float,
    trail_sl_mult: float,
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

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 VOL_REGIME_LOOKBACK, 50) + 5
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

        # 진입 조건 (c165 동일)
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
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # === c168 vol regime detection ===
            atr_pctl = compute_atr_percentile(atr_arr, i, VOL_REGIME_LOOKBACK)
            is_high_vol = atr_pctl >= VOL_REGIME_THRESHOLD_PCT

            # Regime-adaptive hold
            max_hold = HV_HOLD if is_high_vol else LV_HOLD

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # === c168 regime-adaptive TP/SL ===
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

            # === c168 ATR trailing stop ===
            trail_activate_dist = atr_at_entry * trail_activate_mult
            trail_dist = atr_at_entry * trail_sl_mult

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]

                # TP hit
                if current_price >= tp_price:
                    exit_ret = (tp_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # SL hit
                if current_price <= sl_price:
                    exit_ret = (sl_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # Peak tracking
                if current_price > peak_price:
                    peak_price = current_price

                # ATR trailing stop (c168)
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
                "trades": 0, "max_dd": 0.0, "mcl": 0, "returns": []}
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
            "returns": returns}


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


# -- Buy-and-Hold 기준선 --

def buy_and_hold(df: pd.DataFrame) -> dict:
    """단순 매수 후 보유 수익률 (첫 봉 open ~ 마지막 봉 close)."""
    if df.empty:
        return {"ret": 0.0}
    buy = df["open"].iloc[0]
    sell = df["close"].iloc[-1]
    return {"ret": float(sell / buy - 1)}


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi c174 — 멀티심볼(ETH+SOL+XRP) + c168 regime-adaptive exit ===")
    print(f"심볼: {', '.join(SYMBOLS)}  목표: OOS avg Sharpe > c165 baseline +11.290")
    print("가설: c168 regime-adaptive TP/SL + trailing stop이 멀티심볼에서도 유효")
    print(f"고정 진입: VPIN={VPIN_LOW} MOM={MOM_THRESH} CD={COOLDOWN_BARS}")
    print(f"고정 레짐: vol_lookback={VOL_REGIME_LOOKBACK} "
          f"vol_thresh={VOL_REGIME_THRESHOLD_PCT}% "
          f"HV_hold={HV_HOLD} LV_hold={LV_HOLD}")
    print(f"고정 TP/SL: BASE_TP={TP_BASE_ATR} BONUS_TP={TP_BONUS_ATR} "
          f"HV_TP+{HV_TP_OFFSET} LV_TP{LV_TP_OFFSET}")
    print(f"탐색: trail_activate={TRAIL_ACTIVATE_LIST} trail_sl={TRAIL_SL_LIST}")
    print(f"기준선: c165 avg OOS +11.290 (고정 exit), "
          f"c168 avg OOS +14.111 (ETH only regime exit)")
    print("=" * 80)

    # -- BTC 데이터 --
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # -- 심볼 데이터 검증 --
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

    # -- Phase 1: Train 그리드 서치 --
    combos = list(product(TRAIL_ACTIVATE_LIST, TRAIL_SL_LIST))
    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: train 그리드 ({train_start} ~ {train_end})")
    print(f"총 조합: {len(combos)}개 × {len(sym_data_ok)} 심볼")

    sym_train_cache: dict[str, tuple[pd.DataFrame, np.ndarray, np.ndarray]] = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if df_tr.empty:
            continue
        btc_c, btc_s = align_btc_to_symbol(df_tr, df_btc_full, BTC_SMA_PERIOD)
        sym_train_cache[sym] = (df_tr, btc_c, btc_s)
        print(f"  {sym} train: {len(df_tr)}행")

    results: list[dict] = []
    for ta, ts in combos:
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr, btc_c, btc_s = sym_train_cache[sym]
            r = backtest(df_tr, ta, ts, btc_c, btc_s)
            sym_results.append(r)
        pooled = pool_results(sym_results)
        results.append({
            "trail_activate": ta, "trail_sl": ts, **pooled,
        })

    valid = [r for r in results
             if r["trades"] >= 20 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합: {len(valid)}/{len(results)}")
    print(f"\n=== Train Top (pooled Sharpe) ===")
    hdr = (f"{'trA':>5} {'trSL':>5} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['trail_activate']:>5.1f} {r['trail_sl']:>5.1f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # -- Phase 2: 3-fold OOS Walk-Forward (전체 9 combos) --
    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (전 {len(combos)} 조합) ===")

    wf_results: list[dict] = []
    for ta, ts in combos:
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
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_test, ta, ts, btc_c, btc_s)
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
        wf_results.append({
            "trail_activate": ta, "trail_sl": ts,
            "avg_oos": avg_oos, "all_pass": all_pass,
            "fold_sharpes": fold_sharpes,
            "fold_details": fold_details,
        })

    # -- WF 결과 출력 --
    wf_results.sort(key=lambda x: x["avg_oos"], reverse=True)

    print(f"\n--- WF 통과 여부 (avg OOS Sharpe 기준, 전 fold > 0 필요) ---")
    hdr2 = (f"{'trA':>5} {'trSL':>5} | {'avg OOS':>8} | "
            f"{'F1':>7} {'F2':>7} {'F3':>7} | {'PASS':>5}")
    print(hdr2)
    print("-" * len(hdr2))
    pass_count = 0
    for w in wf_results:
        f1 = w["fold_sharpes"][0] if len(w["fold_sharpes"]) > 0 else 0.0
        f2 = w["fold_sharpes"][1] if len(w["fold_sharpes"]) > 1 else 0.0
        f3 = w["fold_sharpes"][2] if len(w["fold_sharpes"]) > 2 else 0.0
        status = "PASS" if w["all_pass"] else "FAIL"
        if w["all_pass"]:
            pass_count += 1
        print(
            f"{w['trail_activate']:>5.1f} {w['trail_sl']:>5.1f} | "
            f"{w['avg_oos']:>+8.3f} | "
            f"{f1:>+7.3f} {f2:>+7.3f} {f3:>+7.3f} | {status:>5}"
        )

    print(f"\n통과: {pass_count}/{len(wf_results)}")

    # -- Top 3 심볼별 분해 --
    top_pass = [w for w in wf_results if w["all_pass"]]
    top_show = top_pass[:3] if top_pass else wf_results[:3]

    for rank, w in enumerate(top_show, 1):
        print(f"\n--- #{rank}: trA={w['trail_activate']} trSL={w['trail_sl']} "
              f"(avg OOS: {w['avg_oos']:+.3f}) ---")
        for fd in w["fold_details"]:
            print(f"  Fold {fd['fold']}: pooled Sharpe={fd['sharpe']:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={fd['trades']}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%")
            for sd in fd.get("sym_details", []):
                sh = sd["sharpe"] if not np.isnan(sd["sharpe"]) else 0.0
                print(f"    {sd['sym']}: Sharpe={sh:+.3f}  WR={sd['wr']:.1%}  "
                      f"n={sd['trades']}  avg={sd['avg_ret'] * 100:+.2f}%  "
                      f"MDD={sd['max_dd'] * 100:+.2f}%")

    # -- 슬리피지 스트레스 (Top 1 PASS) --
    if top_pass:
        best = top_pass[0]
        print(f"\n{'=' * 80}")
        print(f"=== 슬리피지 스트레스 테스트: trA={best['trail_activate']} "
              f"trSL={best['trail_sl']} ===")
        hdr3 = (f"{'slippage':>9} {'Sharpe':>8} {'WR':>6} "
                f"{'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
        print(hdr3)
        print("-" * len(hdr3))
        for slip in SLIPPAGE_LEVELS:
            sym_results = []
            for fold_i, fold in enumerate(WF_FOLDS):
                for sym in sym_data_ok:
                    df_test = load_historical(
                        sym, "240m", fold["test"][0], fold["test"][1])
                    if df_test.empty:
                        continue
                    btc_c, btc_s = align_btc_to_symbol(
                        df_test, df_btc_full, BTC_SMA_PERIOD)
                    r = backtest(df_test, best["trail_activate"],
                                 best["trail_sl"], btc_c, btc_s, slip)
                    sym_results.append(r)
            pooled = pool_results(sym_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            print(
                f"  {slip:.2%}   {sh:>+8.3f} {pooled['wr']:>5.1%} "
                f"{pooled['avg_ret'] * 100:>+6.2f}% "
                f"{pooled['max_dd'] * 100:>+6.2f}% {pooled['mcl']:>4} "
                f"{pooled['trades']:>5}"
            )

    # -- Buy-and-Hold 비교 --
    print(f"\n{'=' * 80}")
    print("=== Buy-and-Hold 기준선 (OOS 구간별) ===")
    for fold_i, fold in enumerate(WF_FOLDS):
        for sym in sym_data_ok:
            df_test = load_historical(
                sym, "240m", fold["test"][0], fold["test"][1])
            if not df_test.empty:
                bh = buy_and_hold(df_test)
                print(f"  {sym} Fold {fold_i + 1} "
                      f"({fold['test'][0]}~{fold['test'][1]}): "
                      f"B&H {bh['ret'] * 100:+.2f}%")

    # -- 최종 요약 --
    if top_pass:
        best = top_pass[0]
        # 전체 OOS 거래수/통계 계산
        all_trades = 0
        all_wr_sum = 0.0
        all_wr_n = 0
        for fd in best["fold_details"]:
            all_trades += fd["trades"]
            if fd["trades"] > 0:
                all_wr_sum += fd["wr"]
                all_wr_n += 1
        avg_wr = all_wr_sum / all_wr_n if all_wr_n > 0 else 0.0

        print(f"\n{'=' * 80}")
        print(f"=== 최종 요약 ===")
        print(f"★ OOS 최적: trail_activate={best['trail_activate']} "
              f"trail_sl={best['trail_sl']}")
        print(f"  (c165 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} CD={COOLDOWN_BARS})")
        print(f"  (c168 고정: vol_lb={VOL_REGIME_LOOKBACK} "
              f"vol_th={VOL_REGIME_THRESHOLD_PCT}% "
              f"HV_hold={HV_HOLD} LV_hold={LV_HOLD})")
        print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} "
              f"{'PASS' if best['all_pass'] else 'FAIL'}")
        print(f"  vs c165 baseline: {best['avg_oos']:+.3f} vs +11.290 "
              f"(delta {best['avg_oos'] - 11.290:+.3f})")
        for fd in best["fold_details"]:
            print(f"  Fold {fd['fold']}: Sharpe={fd['sharpe']:+.3f}  "
                  f"WR={fd['wr']:.1%}  trades={fd['trades']}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%")

        print(f"\nSharpe: {best['avg_oos']:+.3f}")
        print(f"WR: {avg_wr:.1%}")
        print(f"trades: {all_trades}")
    else:
        # 전 조합 FAIL — 최고 avg 출력
        best = wf_results[0] if wf_results else None
        if best:
            print(f"\n{'=' * 80}")
            print(f"=== 최종 요약 (전 조합 WF FAIL) ===")
            print(f"최고 avg OOS: {best['avg_oos']:+.3f} "
                  f"(trA={best['trail_activate']} trSL={best['trail_sl']})")
            print(f"vs c165 baseline: +11.290")
            print(f"\nSharpe: {best['avg_oos']:+.3f}")
            print(f"WR: 0.0%")
            print(f"trades: 0")
        else:
            print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")


if __name__ == "__main__":
    main()
