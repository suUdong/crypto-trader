"""
ralph 사이클 173 — c176 ATR 백분위+캔들 바디 필터를 DOGE/AVAX/ADA/SUI/LINK 5심볼로 확장 검증
- c176 최적: ATR_PCTILE_LB=60, ATR_PCTILE_THRESH=30, BODY_RATIO_MIN=0.7
  ETH/SOL/XRP avg OOS Sharpe +16.345 (n=58) vs c165 baseline +11.290 (n=319)
- 가설: c176 필터가 5개 추가 심볼에서도 일반화되는지 검증
  → 일반화 성공 시 daemon.toml 업데이트 근거, 실패 시 ETH/SOL/XRP 특화 판정
- 각 심볼 c171 최적 VPIN 파라미터 사용 (c165 그리드 결과)
- 비교: baseline (thresh=0, body=0) vs filtered (thresh=30, body=0.7)
- 3-fold WF + 슬리피지 스트레스
- 진입: next_bar open
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

# -- 심볼별 c171 최적 VPIN 파라미터 --
SYMBOL_PARAMS = {
    "KRW-DOGE": {"vpin_low": 0.40, "mom_thresh": 0.0005},
    "KRW-AVAX": {"vpin_low": 0.30, "mom_thresh": 0.0005},
    "KRW-ADA":  {"vpin_low": 0.30, "mom_thresh": 0.0007},
    "KRW-SUI":  {"vpin_low": 0.30, "mom_thresh": 0.0005},
    "KRW-LINK": {"vpin_low": 0.40, "mom_thresh": 0.0005},
}

FEE = 0.0005

# -- c165 공통 고정값 --
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

# -- c176 필터 설정 --
ATR_PCTILE_LB = 60
# 비교 세트: baseline(0,0) vs filtered(30,0.7)
FILTER_CONFIGS = [
    {"name": "baseline", "atr_pctile_thresh": 0, "body_ratio_min": 0.0},
    {"name": "c176_filter", "atr_pctile_thresh": 30, "body_ratio_min": 0.7},
]

# -- 3-fold WF (c176 동일) --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# -- 지표 함수 (c176과 동일) --

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


def compute_atr_percentile(atr_arr: np.ndarray, lookback: int = 40) -> np.ndarray:
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
    vpin_low: float,
    mom_thresh: float,
    atr_pctile_thresh: float,
    body_ratio_min: float,
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

        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # 진입 조건 (심볼별 VPIN/MOM 파라미터)
        vpin_ok = (
            vpin_val < vpin_low
            and mom_val >= mom_thresh
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

        # ATR 백분위 필터
        atr_pctile_ok = True
        if atr_pctile_thresh > 0:
            if np.isnan(atr_pctile_val):
                atr_pctile_ok = False
            else:
                atr_pctile_ok = atr_pctile_val >= atr_pctile_thresh

        # 캔들 바디 비율 필터 (양봉 필수)
        body_ok = True
        if body_ratio_min > 0:
            if np.isnan(body_val):
                body_ok = False
            else:
                body_ok = body_val >= body_ratio_min and c[i] >= o[i]

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok):
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


def buy_and_hold(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 0.0
    return float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)


def main() -> None:
    print("=" * 80)
    print("=== ralph c173 — c176 ATR pctile+body 필터 5심볼 확장 검증 ===")
    print(f"심볼: {', '.join(SYMBOL_PARAMS.keys())}")
    print(f"c176 최적: ATR_PCTILE_LB={ATR_PCTILE_LB} THRESH=30 BODY=0.7")
    print(f"비교: baseline (no filter) vs c176_filter")
    print("=" * 80)

    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # -- 데이터 확인 --
    print("\n--- 심볼별 데이터 확인 ---")
    valid_symbols: list[str] = []
    for sym in SYMBOL_PARAMS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df_check.empty or len(df_check) < 500:
            print(f"  {sym}: 데이터 부족 ({len(df_check)}행) → 제외")
        else:
            print(f"  {sym}: {len(df_check)}행 OK")
            valid_symbols.append(sym)

    if not valid_symbols:
        print("유효 심볼 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # -- 3-fold WF 검증 --
    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 ===")

    for fc in FILTER_CONFIGS:
        fname = fc["name"]
        atr_th = fc["atr_pctile_thresh"]
        body_min = fc["body_ratio_min"]

        print(f"\n{'=' * 80}")
        print(f"=== 필터: {fname} (ATR_THRESH={atr_th}, BODY_MIN={body_min}) ===")

        all_fold_results: dict[str, list[dict]] = {s: [] for s in valid_symbols}
        all_bh: dict[str, list[float]] = {s: [] for s in valid_symbols}

        for fold_idx, fold in enumerate(WF_FOLDS):
            test_start, test_end = fold["test"]
            print(f"\n--- Fold {fold_idx + 1} OOS [{test_start} ~ {test_end}] ---")

            for sym in valid_symbols:
                params = SYMBOL_PARAMS[sym]
                df_test = load_historical(sym, "240m", test_start, test_end)
                if df_test.empty or len(df_test) < 100:
                    print(f"  {sym}: 데이터 부족 → 스킵")
                    continue

                btc_c, btc_s = align_btc_to_symbol(df_test, df_btc_full,
                                                    BTC_SMA_PERIOD)
                r = backtest(df_test, params["vpin_low"], params["mom_thresh"],
                             atr_th, body_min, btc_c, btc_s)
                bh = buy_and_hold(df_test)

                all_fold_results[sym].append(r)
                all_bh[sym].append(bh)

                sh_str = f"{r['sharpe']:+.3f}" if not np.isnan(r['sharpe']) \
                    else "  nan"
                print(f"  {sym}: Sharpe={sh_str}  WR={r['wr']:.1%}  "
                      f"n={r['trades']}  avg={r['avg_ret'] * 100:+.2f}%  "
                      f"MDD={r['max_dd'] * 100:+.2f}%  BH={bh * 100:+.1f}%")

        # -- 심볼별 요약 --
        print(f"\n{'=' * 80}")
        print(f"=== 심볼별 OOS 요약 ({fname}) ===")
        print(f"{'심볼':<10} {'avg Sharpe':>10} {'avg WR':>8} "
              f"{'total n':>8} {'avg MDD':>10} {'avg BH':>8}")
        print("-" * 60)

        total_trades = 0
        all_sharpes: list[float] = []

        for sym in valid_symbols:
            fold_results = all_fold_results[sym]
            bh_list = all_bh[sym]
            if not fold_results:
                print(f"  {sym}: 데이터 없음")
                continue

            sharpes = [r["sharpe"] for r in fold_results
                       if not np.isnan(r["sharpe"])]
            wrs = [r["wr"] for r in fold_results if r["trades"] > 0]
            trades = sum(r["trades"] for r in fold_results)
            mdds = [r["max_dd"] for r in fold_results if r["trades"] > 0]

            if sharpes:
                avg_sh = np.mean(sharpes)
                avg_wr = np.mean(wrs) if wrs else 0.0
                avg_mdd = np.mean(mdds) if mdds else 0.0
                avg_bh = np.mean(bh_list) if bh_list else 0.0
                total_trades += trades
                all_sharpes.append(avg_sh)

                print(f"  {sym:<10} {avg_sh:>+10.3f} {avg_wr:>7.1%} "
                      f"{trades:>8} {avg_mdd * 100:>+9.2f}% "
                      f"{avg_bh * 100:>+7.1f}%")

                # Fold 상세
                for fi, fr in enumerate(fold_results):
                    sh_s = f"{fr['sharpe']:+.3f}" if not np.isnan(fr['sharpe']) \
                        else "  nan"
                    print(f"    F{fi+1}: Sharpe={sh_s}  n={fr['trades']}  "
                          f"WR={fr['wr']:.1%}  avg={fr['avg_ret']*100:+.2f}%")

        if all_sharpes:
            grand_avg = float(np.mean(all_sharpes))
            print(f"\n  ★ 전체 평균 OOS Sharpe: {grand_avg:+.3f}  "
                  f"total trades: {total_trades}")

    # -- 슬리피지 스트레스 (c176_filter만) --
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (c176_filter) ===")
    print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
          f"{'MDD':>8} {'MCL':>4} {'n':>6}")
    print("-" * 55)

    for slip in SLIPPAGE_LEVELS:
        all_returns: list[float] = []
        for sym in valid_symbols:
            params = SYMBOL_PARAMS[sym]
            for fold in WF_FOLDS:
                test_start, test_end = fold["test"]
                df_test = load_historical(sym, "240m", test_start, test_end)
                if df_test.empty or len(df_test) < 100:
                    continue
                btc_c, btc_s = align_btc_to_symbol(df_test, df_btc_full,
                                                    BTC_SMA_PERIOD)
                r = backtest(df_test, params["vpin_low"], params["mom_thresh"],
                             30, 0.7, btc_c, btc_s, slippage=slip)
                all_returns.extend(r.get("returns", []))

        if len(all_returns) >= 3:
            arr = np.array(all_returns)
            sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
            wr = float((arr > 0).mean())
            cum = np.cumsum(arr)
            peak_c = np.maximum.accumulate(cum)
            dd = cum - peak_c
            max_dd = float(dd.min())
            mcl = 0
            cur = 0
            for rv in arr:
                if rv < 0:
                    cur += 1
                    mcl = max(mcl, cur)
                else:
                    cur = 0
            print(f"  {slip:.2%}  {sh:+8.3f} {wr:>5.1%} "
                  f"{arr.mean() * 100:>+6.2f}% {max_dd * 100:>+7.2f}% "
                  f"{mcl:>4} {len(arr):>6}")
        else:
            print(f"  {slip:.2%}  거래 없음")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")

    for fc in FILTER_CONFIGS:
        fname = fc["name"]
        atr_th = fc["atr_pctile_thresh"]
        body_min = fc["body_ratio_min"]

        sym_sharpes: list[float] = []
        sym_trades = 0
        for sym in valid_symbols:
            params = SYMBOL_PARAMS[sym]
            fold_sharpes: list[float] = []
            for fold in WF_FOLDS:
                test_start, test_end = fold["test"]
                df_test = load_historical(sym, "240m", test_start, test_end)
                if df_test.empty or len(df_test) < 100:
                    continue
                btc_c, btc_s = align_btc_to_symbol(df_test, df_btc_full,
                                                    BTC_SMA_PERIOD)
                r = backtest(df_test, params["vpin_low"], params["mom_thresh"],
                             atr_th, body_min, btc_c, btc_s)
                if not np.isnan(r["sharpe"]) and r["trades"] > 0:
                    fold_sharpes.append(r["sharpe"])
                    sym_trades += r["trades"]
            if fold_sharpes:
                sym_sharpes.append(float(np.mean(fold_sharpes)))

        if sym_sharpes:
            grand = float(np.mean(sym_sharpes))
            print(f"  {fname}: avg OOS Sharpe={grand:+.3f}  "
                  f"total trades={sym_trades}  symbols={len(sym_sharpes)}")
        else:
            print(f"  {fname}: 유효 결과 없음")

    # -- 결론 출력용 Sharpe/WR/trades (c176_filter 기준) --
    final_returns: list[float] = []
    for sym in valid_symbols:
        params = SYMBOL_PARAMS[sym]
        for fold in WF_FOLDS:
            test_start, test_end = fold["test"]
            df_test = load_historical(sym, "240m", test_start, test_end)
            if df_test.empty or len(df_test) < 100:
                continue
            btc_c, btc_s = align_btc_to_symbol(df_test, df_btc_full,
                                                BTC_SMA_PERIOD)
            r = backtest(df_test, params["vpin_low"], params["mom_thresh"],
                         30, 0.7, btc_c, btc_s)
            final_returns.extend(r.get("returns", []))

    if final_returns:
        arr = np.array(final_returns)
        sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
        wr = float((arr > 0).mean())
        print(f"\nSharpe: {sh:+.3f}")
        print(f"WR: {wr:.1%}")
        print(f"trades: {len(arr)}")
    else:
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")


if __name__ == "__main__":
    main()
