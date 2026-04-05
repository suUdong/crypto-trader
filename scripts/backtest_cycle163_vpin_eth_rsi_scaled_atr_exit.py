"""
vpin_eth 사이클 163 — RSI 수준 기반 동적 ATR 청산 스케일링
- 기반: c160 ATR-scaled TP/SL (OOS Sharpe +3.179), c161 BTC gate (OOS +15.297)
- 핵심 관찰:
  1) c160: ATR 스케일링으로 변동성 적응 → train +8.808, OOS Fold2 불안정 (+1.352)
  2) c161: BTC gate + 볼륨 필터 → 높은 Sharpe but 거래수 26건 과소
  3) 미탐색 영역: 진입 시점의 RSI 수준이 청산 파라미터에 반영되지 않음
- 가설: RSI 수준이 진입 신호 강도를 반영
  RSI가 RSI_FLOOR에 가까울수록 (과매도 깊은 곳) = 강한 반등 기대 → 넓은 TP, 좁은 trail
  RSI가 RSI_CEILING에 가까울수록 = 약한 신호 → 좁은 TP, 넓은 trail (빠른 차익 실현)
  공식: rsi_ratio = (RSI_CEILING - rsi_at_entry) / (RSI_CEILING - RSI_FLOOR)
        tp_atr = tp_base + tp_bonus * rsi_ratio  (RSI 낮을수록 TP 넓음)
        trail_atr = trail_base + trail_bonus * (1 - rsi_ratio)  (RSI 높을수록 trail 넓음)
- BTC gate 포함 (c155/c161 검증), 볼륨 필터 제외 (거래수 보존)
- 탐색:
  BTC_SMA: [100, 200]
  TP_BASE_ATR: [3.0, 3.5, 4.0]
  TP_BONUS_ATR: [0.0, 1.0, 2.0]  (rsi_ratio=1일 때 최대 bonus)
  SL_ATR: [0.4, 0.5, 0.6]
  TRAIL_BASE_ATR: [0.3, 0.5]
  TRAIL_BONUS_ATR: [0.0, 0.2, 0.4]
  MIN_PROFIT_ATR: [1.0, 1.5, 2.0]
- 2-fold walkforward + 슬리피지 스트레스
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

SYMBOL = "KRW-ETH"
FEE = 0.0005

# -- 고정값 (c152/c157 검증 완료) --
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

# -- 진입 파라미터 (c157 최적 고정) --
VPIN_LOW = 0.30
VPIN_MOM_THRESH = 0.0007
ATR_PERIOD = 20
MAX_HOLD = 24
COOLDOWN_BARS = 6

# -- 탐색 그리드 --
BTC_SMA_LIST = [100, 200]
TP_BASE_ATR_LIST = [3.0, 3.5, 4.0]
TP_BONUS_ATR_LIST = [0.0, 1.0, 2.0]
SL_ATR_LIST = [0.4, 0.5, 0.6]
TRAIL_BASE_ATR_LIST = [0.3, 0.5]
TRAIL_BONUS_ATR_LIST = [0.0, 0.2, 0.4]
MIN_PROFIT_ATR_LIST = [1.0, 1.5, 2.0]

# -- Walkforward 기간 --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
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


def align_btc_to_eth(
    df_eth: pd.DataFrame, df_btc: pd.DataFrame, btc_sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, btc_sma_period)
    btc_close_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_close_aligned = btc_close_s.reindex(df_eth.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_eth.index, method="ffill").values
    return btc_close_aligned, btc_sma_aligned


# -- 백테스트 (RSI 동적 청산) --

def backtest(
    df: pd.DataFrame,
    tp_base_atr: float,
    tp_bonus_atr: float,
    sl_atr: float,
    trail_base_atr: float,
    trail_bonus_atr: float,
    min_profit_atr: float,
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

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, 50) + 5
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

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0):
            i += 1
            continue

        # -- 진입 조건 --
        vpin_ok = (
            vpin_val < VPIN_LOW
            and mom_val >= VPIN_MOM_THRESH
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )
        btc_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )

        if vpin_ok and btc_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링
            # rsi_ratio: 1.0 (RSI=RSI_FLOOR, 깊은 과매도) ~ 0.0 (RSI=RSI_CEILING)
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # TP: RSI 낮을수록(과매도) → 넓은 TP (강한 반등 기대)
            effective_tp_mult = tp_base_atr + tp_bonus_atr * rsi_ratio
            tp_price = buy + atr_at_entry * effective_tp_mult

            # SL: 고정 (ATR 기반)
            sl_price = buy - atr_at_entry * sl_atr

            # Trail: RSI 높을수록 → 넓은 trail (빠른 차익 실현)
            effective_trail_mult = trail_base_atr + trail_bonus_atr * (1.0 - rsi_ratio)
            trail_dist = atr_at_entry * effective_trail_mult
            min_profit_dist = atr_at_entry * min_profit_atr

            exit_ret = None
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                current_price = c[j]

                # TP
                if current_price >= tp_price:
                    exit_ret = (tp_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # SL
                if current_price <= sl_price:
                    exit_ret = (sl_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # 최고가 갱신
                if current_price > peak_price:
                    peak_price = current_price

                # 트레일링 스톱
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


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth 사이클 163 — RSI 수준 기반 동적 ATR 청산 스케일링 ===")
    print(f"심볼: {SYMBOL}  목표: OOS Sharpe >= 5.0")
    print("가설: RSI 수준이 진입 강도 반영 → 청산 파라미터 동적 조절")
    print("  RSI 낮음(과매도) = 강한 반등 → 넓은 TP + 좁은 trail")
    print("  RSI 높음 = 약한 신호 → 좁은 TP + 넓은 trail (빠른 차익)")
    print("기준선: c160 ATR OOS +3.179, c161 BTC gate OOS +15.297")
    print("=" * 80)

    # -- BTC 데이터 로드 --
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # -- Phase 1: train 그리드 서치 --
    train_start, train_end = WF_FOLDS[0]["train"]
    df_train = load_historical(SYMBOL, "240m", train_start, train_end)
    if df_train.empty:
        print("train 데이터 없음.")
        return
    print(f"\ntrain 데이터: {len(df_train)}행 ({train_start} ~ {train_end})")

    # c160 기준선 (고정 ATR TP/SL, BTC gate 없음)
    print("\n--- c160 기준선 (ATR=20 TP=4.0 SL=0.5, BTC gate 없음, RSI 스케일링 없음) ---")
    btc_c_tr, _ = align_btc_to_eth(df_train, df_btc_full, 200)
    base = backtest(df_train, 4.0, 0.0, 0.5, 0.5, 0.0, 1.5,
                    btc_c_tr, np.full(len(df_train), np.inf))
    print(f"  Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"n={base['trades']}")

    combos = list(product(
        BTC_SMA_LIST,
        TP_BASE_ATR_LIST, TP_BONUS_ATR_LIST,
        SL_ATR_LIST,
        TRAIL_BASE_ATR_LIST, TRAIL_BONUS_ATR_LIST,
        MIN_PROFIT_ATR_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (btc_sma_p, tp_b, tp_bon, sl_a, tr_b, tr_bon, mp_a) in enumerate(combos):
        if idx % 200 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        btc_c_tr, btc_sma_tr = align_btc_to_eth(df_train, df_btc_full, btc_sma_p)
        r = backtest(df_train, tp_b, tp_bon, sl_a, tr_b, tr_bon, mp_a,
                     btc_c_tr, btc_sma_tr)
        results.append({
            "btc_sma": btc_sma_p,
            "tp_base": tp_b, "tp_bonus": tp_bon,
            "sl_atr": sl_a,
            "trail_base": tr_b, "trail_bonus": tr_bon,
            "min_profit_atr": mp_a,
            **r,
        })

    valid = [r for r in results
             if r["trades"] >= 15
             and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=15): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 20 (Sharpe 기준) ===")
    hdr = (f"{'BTC':>4} {'TP_b':>5} {'TP+':>4} {'SL':>4} "
           f"{'Tr_b':>5} {'Tr+':>4} {'mP':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['btc_sma']:>4} {r['tp_base']:>5.1f} {r['tp_bonus']:>4.1f} "
            f"{r['sl_atr']:>4.1f} "
            f"{r['trail_base']:>5.1f} {r['trail_bonus']:>4.1f} "
            f"{r['min_profit_atr']:>4.1f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 2: OOS Walk-Forward (Top 20 고유) --
    seen: set[tuple] = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["btc_sma"], r["tp_base"], r["tp_bonus"], r["sl_atr"],
               r["trail_base"], r["trail_bonus"], r["min_profit_atr"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 20:
            break

    print(f"\n{'=' * 80}")
    print(f"=== OOS Walk-Forward 검증 (Top {len(unique_top)} 고유, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        btc_sma_p = params["btc_sma"]
        tp_b = params["tp_base"]
        tp_bon = params["tp_bonus"]
        sl_a = params["sl_atr"]
        tr_b = params["trail_base"]
        tr_bon = params["trail_bonus"]
        mp_a = params["min_profit_atr"]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                continue
            btc_c_t, btc_sma_t = align_btc_to_eth(df_test, df_btc_full, btc_sma_p)
            r = backtest(df_test, tp_b, tp_bon, sl_a, tr_b, tr_bon, mp_a,
                         btc_c_t, btc_sma_t)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            all_pass = all(s >= 5.0 for s in oos_sharpes)
            print(f"  #{rank}: BTC={btc_sma_p} TP={tp_b}+{tp_bon} "
                  f"SL={sl_a} Tr={tr_b}+{tr_bon} mP={mp_a} | "
                  f"train={params['sharpe']:+.3f} -> avg_OOS={avg_oos:+.3f} "
                  f"min_OOS={min_oos:+.3f} "
                  f"{'PASS' if all_pass else 'FAIL'}")
            wf_results.append({
                **params,
                "train_sharpe": params["sharpe"],
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
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
    print("=== 슬리피지 스트레스 테스트 (OOS Top 3) ===")

    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    for rank, params in enumerate(wf_top3, 1):
        btc_sma_p = params["btc_sma"]
        tp_b = params["tp_base"]
        tp_bon = params["tp_bonus"]
        sl_a = params["sl_atr"]
        tr_b = params["trail_base"]
        tr_bon = params["trail_bonus"]
        mp_a = params["min_profit_atr"]
        btc_c_f, btc_sma_f = align_btc_to_eth(df_full, df_btc_full, btc_sma_p)
        print(f"\n--- #{rank}: BTC={btc_sma_p} TP={tp_b}+{tp_bon} "
              f"SL={sl_a} Tr={tr_b}+{tr_bon} mP={mp_a} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_full, tp_b, tp_bon, sl_a, tr_b, tr_bon, mp_a,
                         btc_c_f, btc_sma_f, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # -- RSI 스케일링 vs 고정 ATR OOS 비교 --
    print(f"\n{'=' * 80}")
    print("=== c160 고정 ATR vs c163 RSI 동적 ATR OOS 비교 ===")
    for fold_i, fold in enumerate(WF_FOLDS):
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if not df_test.empty:
            btc_c_t, _ = align_btc_to_eth(df_test, df_btc_full, 200)
            # c160 기준선 (고정 ATR, BTC gate 없음)
            r = backtest(df_test, 4.0, 0.0, 0.5, 0.5, 0.0, 1.5,
                         btc_c_t, np.full(len(df_test), np.inf))
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  [c160 고정] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  "
                  f"MDD={r['max_dd'] * 100:+.2f}%")
    best = wf_sorted[0]
    for fold_i, fd in enumerate(best["fold_details"]):
        sh = best["oos_sharpes"][fold_i]
        print(f"  [c163 최적] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
              f"WR={fd['wr']:.1%}  n={best['oos_trades'][fold_i]}  "
              f"avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: BTC_SMA={best['btc_sma']} "
          f"TP_base={best['tp_base']} TP_bonus={best['tp_bonus']} "
          f"SL={best['sl_atr']} "
          f"Trail_base={best['trail_base']} Trail_bonus={best['trail_bonus']} "
          f"minP={best['min_profit_atr']}")
    print(f"  (고정: VPIN_LOW={VPIN_LOW} MOM={VPIN_MOM_THRESH} "
          f"ATR={ATR_PERIOD} hold={MAX_HOLD} cool={COOLDOWN_BARS})")
    oos_avg = best["avg_oos_sharpe"]
    status = "PASS >=5.0" if oos_avg >= 5.0 else "FAIL <5.0"
    print(f"  avg OOS Sharpe: {oos_avg:+.3f} {status}")
    print(f"  train Sharpe: {best['train_sharpe']:+.3f}")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={best['oos_trades'][fi]}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    total_trades = sum(best["oos_trades"])
    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))

    print(f"\nSharpe: {oos_avg:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
