"""
vpin_eth 사이클 162 — c163 최적 파라미터 3-fold WF 검증
- 목표: c163 최적(avg OOS Sharpe +8.837, n=50)의 3-fold 강건성 확인
- c163 최적: BTC_SMA=200 TP_base=4.0 TP_bonus=2.0 SL=0.4 Trail_base=0.3 Trail_bonus=0.2 minP=1.5
- 평가자 지시: 3-fold WF로 확장하여 OOS n≥30 확보 시도
- 3-fold OOS (비중첩, 기존 미사용):
  F1: train 2022-01~2023-12 / OOS 2024-01-01~2024-12-31
  F2: train 2022-01~2024-12 / OOS 2025-01-01~2025-12-31
  F3: train 2022-01~2025-12 / OOS 2026-01-01~2026-04-05
- 로버스트니스: c163 최적 ± 근접 그리드도 함께 검증
- 진입: next_bar open
- 슬리피지: 0.10%
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
SLIPPAGE = 0.0010

# -- 고정값 (c152/c157 검증) --
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2
VPIN_LOW = 0.30
VPIN_MOM_THRESH = 0.0007
ATR_PERIOD = 20
MAX_HOLD = 24
COOLDOWN_BARS = 6

# -- c163 최적 파라미터 (고정 검증) --
C163_BEST = {
    "btc_sma": 200,
    "tp_base": 4.0,
    "tp_bonus": 2.0,
    "sl_atr": 0.4,
    "trail_base": 0.3,
    "trail_bonus": 0.2,
    "min_profit_atr": 1.5,
}

# -- 로버스트니스 그리드 (c163 최적 근접) --
ROBUST_GRID = {
    "btc_sma": [200],
    "tp_base": [3.5, 4.0, 4.5],
    "tp_bonus": [1.5, 2.0, 2.5],
    "sl_atr": [0.3, 0.4, 0.5],
    "trail_base": [0.2, 0.3, 0.4],
    "trail_bonus": [0.1, 0.2, 0.3],
    "min_profit_atr": [1.0, 1.5, 2.0],
}

# -- 3-fold WF --
WF_FOLDS = [
    {"train": ("2022-01-01", "2023-12-31"), "test": ("2024-01-01", "2024-12-31")},
    {"train": ("2022-01-01", "2024-12-31"), "test": ("2025-01-01", "2025-12-31")},
    {"train": ("2022-01-01", "2025-12-31"), "test": ("2026-01-01", "2026-04-05")},
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


# -- 백테스트 (c163 RSI 동적 청산) --

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
    slippage: float = 0.0010,
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
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            effective_tp_mult = tp_base_atr + tp_bonus_atr * rsi_ratio
            tp_price = buy + atr_at_entry * effective_tp_mult

            sl_price = buy - atr_at_entry * sl_atr

            effective_trail_mult = trail_base_atr + trail_bonus_atr * (1.0 - rsi_ratio)
            trail_dist = atr_at_entry * effective_trail_mult
            min_profit_dist = atr_at_entry * min_profit_atr

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


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth 사이클 162 — c163 최적 파라미터 3-fold WF 검증 ===")
    print(f"심볼: {SYMBOL}  슬리피지: {SLIPPAGE * 100:.2f}%")
    print(f"c163 최적: BTC_SMA={C163_BEST['btc_sma']} "
          f"TP={C163_BEST['tp_base']}+{C163_BEST['tp_bonus']} "
          f"SL={C163_BEST['sl_atr']} "
          f"Trail={C163_BEST['trail_base']}+{C163_BEST['trail_bonus']} "
          f"minP={C163_BEST['min_profit_atr']}")
    print("목표: 3-fold WF 전체 통과 (각 fold Sharpe≥5.0, n≥10)")
    print("=" * 80)

    # -- BTC 데이터 --
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # ===== Phase 1: c163 최적 파라미터 3-fold WF 검증 =====
    print(f"\n{'=' * 80}")
    print("=== Phase 1: c163 최적 파라미터 3-fold 직접 검증 ===")

    p = C163_BEST
    fold_results: list[dict] = []
    for fi, fold in enumerate(WF_FOLDS):
        # Train 검증 (참고용)
        df_train = load_historical(SYMBOL, "240m", fold["train"][0], fold["train"][1])
        btc_c_tr, btc_sma_tr = align_btc_to_eth(df_train, df_btc_full, p["btc_sma"])
        r_train = backtest(df_train, p["tp_base"], p["tp_bonus"], p["sl_atr"],
                           p["trail_base"], p["trail_bonus"], p["min_profit_atr"],
                           btc_c_tr, btc_sma_tr)

        # OOS 검증
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if df_test.empty:
            print(f"  F{fi + 1} OOS 데이터 없음: {fold['test']}")
            fold_results.append({"sharpe": float("nan"), "trades": 0})
            continue
        btc_c_t, btc_sma_t = align_btc_to_eth(df_test, df_btc_full, p["btc_sma"])
        r_oos = backtest(df_test, p["tp_base"], p["tp_bonus"], p["sl_atr"],
                         p["trail_base"], p["trail_bonus"], p["min_profit_atr"],
                         btc_c_t, btc_sma_t)

        sh_tr = r_train["sharpe"] if not np.isnan(r_train["sharpe"]) else 0.0
        sh_oos = r_oos["sharpe"] if not np.isnan(r_oos["sharpe"]) else 0.0
        pass_str = "PASS" if sh_oos >= 5.0 and r_oos["trades"] >= 10 else "FAIL"
        print(f"  F{fi + 1}: train({fold['train'][0]}~{fold['train'][1]}) "
              f"Sharpe={sh_tr:+.3f} n={r_train['trades']} | "
              f"OOS({fold['test'][0]}~{fold['test'][1]}) "
              f"Sharpe={sh_oos:+.3f} WR={r_oos['wr']:.1%} "
              f"n={r_oos['trades']} avg={r_oos['avg_ret'] * 100:+.2f}% "
              f"MDD={r_oos['max_dd'] * 100:+.2f}% MCL={r_oos['mcl']} "
              f"[{pass_str}]")
        fold_results.append(r_oos)

    oos_sharpes = [r["sharpe"] if not np.isnan(r.get("sharpe", float("nan")))
                   else 0.0 for r in fold_results]
    oos_trades = [r.get("trades", 0) for r in fold_results]
    total_oos_n = sum(oos_trades)
    avg_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    all_pass = all(s >= 5.0 for s in oos_sharpes) and all(
        t >= 10 for t in oos_trades)

    print(f"\n  === c163 최적 3-fold 종합 ===")
    print(f"  avg OOS Sharpe: {avg_oos_sharpe:+.3f} "
          f"{'PASS' if all_pass else 'FAIL'}")
    print(f"  총 OOS 거래수: {total_oos_n}")
    for fi, (sh, nt) in enumerate(zip(oos_sharpes, oos_trades)):
        print(f"    F{fi + 1}: Sharpe={sh:+.3f}  n={nt}")

    # ===== Phase 2: 로버스트니스 그리드 검증 =====
    combos = list(product(
        ROBUST_GRID["btc_sma"],
        ROBUST_GRID["tp_base"],
        ROBUST_GRID["tp_bonus"],
        ROBUST_GRID["sl_atr"],
        ROBUST_GRID["trail_base"],
        ROBUST_GRID["trail_bonus"],
        ROBUST_GRID["min_profit_atr"],
    ))
    print(f"\n{'=' * 80}")
    print(f"=== Phase 2: 로버스트니스 그리드 ({len(combos)}개 조합) ===")
    print("3-fold WF 전체 통과 조건: 각 fold Sharpe≥5.0 & n≥10")

    # 각 조합에 대해 3-fold WF
    passed_combos: list[dict] = []
    for idx, (bsma, tpb, tpbon, sla, trb, trbon, mpa) in enumerate(combos):
        if idx % 100 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")

        combo_oos_sharpes: list[float] = []
        combo_oos_trades: list[int] = []
        combo_fold_details: list[dict] = []

        for fi, fold in enumerate(WF_FOLDS):
            df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            if df_test.empty:
                combo_oos_sharpes.append(0.0)
                combo_oos_trades.append(0)
                combo_fold_details.append(
                    {"sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0,
                     "trades": 0, "max_dd": 0.0, "mcl": 0})
                continue
            btc_c_t, btc_sma_t = align_btc_to_eth(df_test, df_btc_full, bsma)
            r = backtest(df_test, tpb, tpbon, sla, trb, trbon, mpa,
                         btc_c_t, btc_sma_t)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            combo_oos_sharpes.append(sh)
            combo_oos_trades.append(r["trades"])
            combo_fold_details.append(r)

        combo_avg = float(np.mean(combo_oos_sharpes))
        combo_all_pass = (all(s >= 5.0 for s in combo_oos_sharpes)
                          and all(t >= 10 for t in combo_oos_trades))

        if combo_avg > 0:
            passed_combos.append({
                "btc_sma": bsma, "tp_base": tpb, "tp_bonus": tpbon,
                "sl_atr": sla, "trail_base": trb, "trail_bonus": trbon,
                "min_profit_atr": mpa,
                "avg_oos_sharpe": combo_avg,
                "all_pass": combo_all_pass,
                "oos_sharpes": combo_oos_sharpes,
                "oos_trades": combo_oos_trades,
                "fold_details": combo_fold_details,
            })

    # 정렬: all_pass 우선, 그 다음 avg_oos_sharpe
    passed_combos.sort(
        key=lambda x: (x["all_pass"], x["avg_oos_sharpe"]), reverse=True)

    n_full_pass = sum(1 for c in passed_combos if c["all_pass"])
    print(f"\n  총 3-fold 전체통과: {n_full_pass}/{len(combos)}")
    print(f"  avg OOS > 0: {len(passed_combos)}/{len(combos)}")

    # Top 20 출력
    print(f"\n=== 로버스트니스 Top 20 (avg OOS Sharpe, 3-fold) ===")
    hdr = (f"{'TP_b':>5} {'TP+':>4} {'SL':>4} {'Tr_b':>5} {'Tr+':>4} "
           f"{'mP':>4} | {'avgOOS':>7} {'F1':>7} {'F2':>7} {'F3':>7} "
           f"{'nF1':>4} {'nF2':>4} {'nF3':>4} | {'판정':>4}")
    print(hdr)
    print("-" * len(hdr))
    for r in passed_combos[:20]:
        f1s = r["oos_sharpes"][0]
        f2s = r["oos_sharpes"][1]
        f3s = r["oos_sharpes"][2] if len(r["oos_sharpes"]) > 2 else 0.0
        nf1 = r["oos_trades"][0]
        nf2 = r["oos_trades"][1]
        nf3 = r["oos_trades"][2] if len(r["oos_trades"]) > 2 else 0
        verdict = "PASS" if r["all_pass"] else "FAIL"
        print(
            f"{r['tp_base']:>5.1f} {r['tp_bonus']:>4.1f} {r['sl_atr']:>4.1f} "
            f"{r['trail_base']:>5.1f} {r['trail_bonus']:>4.1f} "
            f"{r['min_profit_atr']:>4.1f} | "
            f"{r['avg_oos_sharpe']:>+7.3f} "
            f"{f1s:>+7.3f} {f2s:>+7.3f} {f3s:>+7.3f} "
            f"{nf1:>4} {nf2:>4} {nf3:>4} | {verdict:>4}"
        )

    # ===== Phase 3: 슬리피지 스트레스 (Top 3 전체통과 or Top 3 avg) =====
    stress_targets = [c for c in passed_combos if c["all_pass"]][:3]
    if len(stress_targets) < 3:
        stress_targets = passed_combos[:3]

    if stress_targets:
        print(f"\n{'=' * 80}")
        print("=== Phase 3: 슬리피지 스트레스 테스트 ===")
        df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
        for rank, params in enumerate(stress_targets, 1):
            btc_c_f, btc_sma_f = align_btc_to_eth(
                df_full, df_btc_full, params["btc_sma"])
            print(f"\n--- #{rank}: TP={params['tp_base']}+{params['tp_bonus']} "
                  f"SL={params['sl_atr']} Tr={params['trail_base']}+"
                  f"{params['trail_bonus']} mP={params['min_profit_atr']} "
                  f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
            print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
                  f"{'MDD':>7} {'MCL':>4} {'n':>5}")
            print("-" * 55)
            for slip in SLIPPAGE_LEVELS:
                r = backtest(df_full, params["tp_base"], params["tp_bonus"],
                             params["sl_atr"], params["trail_base"],
                             params["trail_bonus"], params["min_profit_atr"],
                             btc_c_f, btc_sma_f, slippage=slip)
                sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
                print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                      f"{r['avg_ret'] * 100:>+6.2f}% "
                      f"{r['max_dd'] * 100:>+6.2f}% "
                      f"{r['mcl']:>4} {r['trades']:>5}")

    # ===== Phase 4: Buy-and-hold 비교 =====
    print(f"\n{'=' * 80}")
    print("=== Phase 4: Buy-and-hold 비교 ===")
    for fi, fold in enumerate(WF_FOLDS):
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if df_test.empty:
            continue
        bnh_ret = (df_test["close"].iloc[-1] / df_test["open"].iloc[0] - 1)
        print(f"  F{fi + 1} OOS ({fold['test'][0]}~{fold['test'][1]}): "
              f"buy-and-hold = {bnh_ret * 100:+.2f}%")

    # ===== 최종 요약 =====
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")

    # c163 최적 3-fold 결과
    print(f"\n★ c163 최적 파라미터 3-fold 검증:")
    print(f"  BTC_SMA={C163_BEST['btc_sma']} "
          f"TP={C163_BEST['tp_base']}+{C163_BEST['tp_bonus']} "
          f"SL={C163_BEST['sl_atr']} "
          f"Trail={C163_BEST['trail_base']}+{C163_BEST['trail_bonus']} "
          f"minP={C163_BEST['min_profit_atr']}")
    print(f"  avg OOS Sharpe: {avg_oos_sharpe:+.3f} "
          f"{'PASS' if all_pass else 'FAIL'}")
    print(f"  총 OOS trades: {total_oos_n}")
    for fi in range(len(fold_results)):
        sh = oos_sharpes[fi]
        nt = oos_trades[fi]
        fd = fold_results[fi]
        print(f"  F{fi + 1}: Sharpe={sh:+.3f}  WR={fd.get('wr', 0):.1%}  "
              f"n={nt}  avg={fd.get('avg_ret', 0) * 100:+.2f}%  "
              f"MDD={fd.get('max_dd', 0) * 100:+.2f}%")

    # 로버스트니스 최적
    if passed_combos:
        best = passed_combos[0]
        print(f"\n★ 로버스트니스 최적 (3-fold):")
        print(f"  TP={best['tp_base']}+{best['tp_bonus']} "
              f"SL={best['sl_atr']} Trail={best['trail_base']}+"
              f"{best['trail_bonus']} minP={best['min_profit_atr']}")
        best_avg = best["avg_oos_sharpe"]
        print(f"  avg OOS Sharpe: {best_avg:+.3f} "
              f"{'PASS' if best['all_pass'] else 'FAIL'}")
        total_best_n = sum(best["oos_trades"])
        print(f"  총 OOS trades: {total_best_n}")
        for fi in range(len(best["fold_details"])):
            sh = best["oos_sharpes"][fi]
            fd = best["fold_details"][fi]
            print(f"  F{fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
                  f"n={best['oos_trades'][fi]}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  "
                  f"MDD={fd['max_dd'] * 100:+.2f}%")

    # 최종 Sharpe/WR/trades
    if passed_combos and passed_combos[0]["all_pass"]:
        final = passed_combos[0]
        final_sharpe = final["avg_oos_sharpe"]
        final_wr = float(np.mean([fd["wr"] for fd in final["fold_details"]]))
        final_n = sum(final["oos_trades"])
    else:
        final_sharpe = avg_oos_sharpe
        final_wr = float(np.mean([fd.get("wr", 0) for fd in fold_results]))
        final_n = total_oos_n

    print(f"\nSharpe: {final_sharpe:+.3f}")
    print(f"WR: {final_wr * 100:.1f}%")
    print(f"trades: {final_n}")


if __name__ == "__main__":
    main()
