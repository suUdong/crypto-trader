"""
사이클 128: KRW-SOL Bollinger Band 반등 빠른 검증
- ETH BB bounce (사이클 126/128) 전패 — SOL에서 같은 패턴인지 확인
- 핵심 파라미터 범위만 실행 (상위 유망 조합 위주)
- 판정: 2/2창 Sharpe > 5.0 && n >= 6
"""
from __future__ import annotations
import sys
from pathlib import Path
from itertools import product
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005
SLIPPAGE_LIST = [0.001, 0.002]  # 0.10%, 0.20% (빠른 검증)

WINDOWS = [
    {"name": "W1", "is_start": "2022-01-01", "is_end": "2023-12-31",
     "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2023-01-01", "is_end": "2024-12-31",
     "oos_start": "2025-01-01", "oos_end": "2026-04-04"},
]

SYMBOL = "KRW-SOL"

# ETH 상위 조합 기반 좁힌 그리드
BB_PERIOD_LIST   = [15, 20, 25]
BB_STD_LIST      = [2.0, 2.5]
ENTRY_PCT_LIST   = [0.0, 0.01]
TP_LIST          = [0.08, 0.15]
SL_LIST          = [0.02, 0.03]
MAX_HOLD_LIST    = [24, 48]
BB_EXIT_MID_LIST = [False]

# 총 조합: 3×2×2×2×2×2×1 = 96
PASS_SHARPE = 5.0
PASS_TRADES = 6


def bollinger_bands(closes, period, n_std):
    mid   = np.full(len(closes), np.nan)
    upper = np.full(len(closes), np.nan)
    lower = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        m = window.mean()
        s = window.std(ddof=1)
        mid[i]   = m
        upper[i] = m + n_std * s
        lower[i] = m - n_std * s
    return upper, mid, lower


def backtest(df, bb_period, bb_std, entry_pct, tp, sl, max_hold, bb_exit_mid, slippage):
    closes = df["close"].values
    upper, mid, lower = bollinger_bands(closes, bb_period, bb_std)

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_i = 0

    for i in range(bb_period, len(df)):
        if np.isnan(lower[i]):
            continue
        if not in_trade:
            threshold = lower[i] * (1 - entry_pct)
            if closes[i] < threshold:
                entry_price = closes[i] * (1 + FEE + slippage)
                entry_i = i
                in_trade = True
        else:
            current_price = closes[i]
            hold_bars = i - entry_i
            pnl_pct = (current_price / entry_price) - 1

            exit_reason = None
            if pnl_pct >= tp:
                exit_reason = "TP"
            elif pnl_pct <= -sl:
                exit_reason = "SL"
            elif bb_exit_mid and current_price >= mid[i]:
                exit_reason = "MID"
            elif hold_bars >= max_hold:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_price = current_price * (1 - FEE - slippage)
                ret = (exit_price / entry_price) - 1
                trades.append({"ret": ret, "bars": hold_bars})
                in_trade = False

    if not trades:
        return {"sharpe": np.nan, "n": 0, "wr": np.nan, "avg_ret": np.nan}

    rets = np.array([t["ret"] for t in trades])
    n = len(rets)
    avg = rets.mean()
    std = rets.std(ddof=1) if n > 1 else np.nan
    sharpe = (avg / std * np.sqrt(252 * 6)) if (std and std > 0) else np.nan
    wr = (rets > 0).mean()
    return {"sharpe": sharpe, "n": n, "wr": wr, "avg_ret": avg}


def run_window(df, window, params, slippage):
    oos_df = df[(df.index >= window["oos_start"]) & (df.index < window["oos_end"])]
    if len(oos_df) < 50:
        return {"sharpe": np.nan, "n": 0}
    return backtest(oos_df.copy(), slippage=slippage, **params)


def main():
    print(f"{'='*60}")
    print(f"[{SYMBOL}] BB Bounce Quick Check (96 조합)")
    print(f"{'='*60}")

    df_all = load_historical(SYMBOL, "240m")
    df_all = df_all.sort_index()

    combos = list(product(
        BB_PERIOD_LIST, BB_STD_LIST, ENTRY_PCT_LIST,
        TP_LIST, SL_LIST, MAX_HOLD_LIST, BB_EXIT_MID_LIST
    ))

    results = []
    for slip in SLIPPAGE_LIST:
        for c in combos:
            bb_period, bb_std, entry_pct, tp, sl, max_hold, bb_exit_mid = c
            params = dict(bb_period=bb_period, bb_std=bb_std, entry_pct=entry_pct,
                          tp=tp, sl=sl, max_hold=max_hold, bb_exit_mid=bb_exit_mid)
            w_results = {}
            for w in WINDOWS:
                r = run_window(df_all, w, params, slip)
                w_results[w["name"]] = r

            passed = all(
                (not np.isnan(w_results[w["name"]]["sharpe"])) and
                w_results[w["name"]]["sharpe"] >= PASS_SHARPE and
                w_results[w["name"]]["n"] >= PASS_TRADES
                for w in WINDOWS
            )
            results.append({
                "slip": slip, "bb_period": bb_period, "bb_std": bb_std,
                "entry_pct": entry_pct, "tp": tp, "sl": sl, "max_hold": max_hold,
                "bb_exit_mid": bb_exit_mid,
                "W1_sharpe": w_results["W1"]["sharpe"], "W1_n": w_results["W1"]["n"],
                "W2_sharpe": w_results["W2"]["sharpe"], "W2_n": w_results["W2"]["n"],
                "passed": int(passed),
            })

    rdf = pd.DataFrame(results)

    for slip in SLIPPAGE_LIST:
        sub = rdf[rdf["slip"] == slip]
        passed = sub[sub["passed"] == 1]
        print(f"\n[슬리피지 {slip*100:.2f}%] 통과 {len(passed)}개")
        if len(passed) > 0:
            print(passed[["bb_period","bb_std","entry_pct","tp","sl","max_hold","W1_sharpe","W1_n","W2_sharpe","W2_n"]].to_string(index=False))

    print(f"\n{'='*60}")
    print(f"슬리피지 0.10% 기준 상위 10개")
    top = rdf[rdf["slip"] == 0.001].sort_values(["passed","W2_sharpe"], ascending=[False, False]).head(10)
    print(top[["bb_period","bb_std","entry_pct","tp","sl","max_hold","passed","W1_sharpe","W1_n","W2_sharpe","W2_n"]].to_string(index=False))


if __name__ == "__main__":
    main()
