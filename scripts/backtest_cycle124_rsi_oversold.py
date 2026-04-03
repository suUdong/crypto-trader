"""
사이클 124: RSI oversold bounce 전략 백테스트
- 목적: BEAR 구간에서도 진입 가능한 long-only 전략 탐색
         BTC 레짐 필터 없이 단기 과매도 반등 포착
- 전략: RSI(14) 과매도 진입 → RSI 회복 or TP/SL/max_hold 청산
- 심볼: KRW-SOL, KRW-ETH, KRW-XRP
- 타임프레임: 240m (4시간봉)
- WF: W1 OOS=2024 (BULL/혼재), W2 OOS=2025-2026 (BEAR/혼재)
- 판정 기준: 2/2창 Sharpe > 3.0 && trades >= 6
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005  # 0.05% 수수료 (편도)
SLIPPAGE = 0.001  # 0.10% 슬리피지 (편도)

WINDOWS = [
    {
        "name": "W1",
        "is_start": "2022-01-01", "is_end": "2023-12-31",
        "oos_start": "2024-01-01", "oos_end": "2024-12-31",
    },
    {
        "name": "W2",
        "is_start": "2023-01-01", "is_end": "2024-12-31",
        "oos_start": "2025-01-01", "oos_end": "2026-04-04",
    },
]

SYMBOLS = ["KRW-SOL", "KRW-ETH", "KRW-XRP"]

# 그리드
RSI_ENTRY_LIST  = [25, 28, 30]
RSI_EXIT_LIST   = [45, 50, 55]
MAX_HOLD_LIST   = [12, 24, 36]
TP_LIST         = [0.05, 0.08, 0.10]
SL_LIST         = [0.02, 0.03, 0.04]

# 판정 기준
PASS_SHARPE = 3.0
PASS_TRADES = 6


# ─── 지표 계산 ────────────────────────────────────────────────────────────────

def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


# ─── 백테스트 엔진 ────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    rsi_entry: float,
    rsi_exit: float,
    tp: float,
    sl: float,
    max_hold: int,
    slippage: float = SLIPPAGE,
) -> dict:
    closes  = df["close"].values
    highs   = df["high"].values
    lows    = df["low"].values

    rsi_vals = rsi(closes)
    n = len(closes)

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count  = 0

    for i in range(15, n):
        if not in_pos:
            # 진입 조건: RSI 과매도 (이전 봉에서 처음 과매도 진입)
            if rsi_vals[i-1] >= rsi_entry and rsi_vals[i] < rsi_entry:
                entry_price = closes[i] * (1 + slippage + FEE)
                in_pos = True
                hold_count = 0
        else:
            hold_count += 1
            current_return = (closes[i] - entry_price) / entry_price

            # TP 확인
            if highs[i] >= entry_price * (1 + tp):
                exit_price = entry_price * (1 + tp) * (1 - slippage - FEE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append(pnl)
                in_pos = False
                continue

            # SL 확인
            if lows[i] <= entry_price * (1 - sl):
                exit_price = entry_price * (1 - sl) * (1 - slippage - FEE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append(pnl)
                in_pos = False
                continue

            # RSI 회복 청산
            if rsi_vals[i] > rsi_exit:
                exit_price = closes[i] * (1 - slippage - FEE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append(pnl)
                in_pos = False
                continue

            # max_hold 청산
            if hold_count >= max_hold:
                exit_price = closes[i] * (1 - slippage - FEE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append(pnl)
                in_pos = False
                continue

    if not trades or len(trades) < PASS_TRADES:
        return {"sharpe": float("nan"), "wr": float("nan"), "avg": float("nan"), "n": len(trades)}

    arr = np.array(trades)
    sharpe = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6)  # 연환산 (240m = 하루 6봉)
    wr = (arr > 0).mean()
    avg = arr.mean()
    return {"sharpe": sharpe, "wr": wr, "avg": avg, "n": len(trades)}


# ─── 워크포워드 ──────────────────────────────────────────────────────────────

def walk_forward(symbol: str, params: dict) -> list[dict]:
    results = []
    for w in WINDOWS:
        df_all = load_historical(symbol, "240m",
                                 w["is_start"], w["oos_end"])
        if df_all is None or len(df_all) < 100:
            results.append({"window": w["name"], "sharpe": float("nan"), "n": 0})
            continue

        df_oos = df_all[
            (df_all.index >= w["oos_start"]) &
            (df_all.index <= w["oos_end"])
        ]
        if len(df_oos) < 30:
            results.append({"window": w["name"], "sharpe": float("nan"), "n": 0})
            continue

        res = backtest(df_oos, **params)
        results.append({"window": w["name"], **res})
    return results


# ─── 그리드 탐색 ──────────────────────────────────────────────────────────────

def grid_search(symbol: str) -> list[dict]:
    all_results = []
    param_grid = list(product(RSI_ENTRY_LIST, RSI_EXIT_LIST, MAX_HOLD_LIST, TP_LIST, SL_LIST))
    print(f"\n{'='*60}")
    print(f"[{symbol}] 그리드 탐색 {len(param_grid)} 조합")
    print(f"{'='*60}")

    for rsi_e, rsi_x, mh, tp, sl in param_grid:
        params = {
            "rsi_entry": rsi_e,
            "rsi_exit": rsi_x,
            "max_hold": mh,
            "tp": tp,
            "sl": sl,
        }
        wf_res = walk_forward(symbol, params)

        sharpes = [r["sharpe"] for r in wf_res if not np.isnan(r["sharpe"])]
        ns = [r["n"] for r in wf_res]
        passed = sum(
            1 for r in wf_res
            if not np.isnan(r["sharpe"]) and r["sharpe"] >= PASS_SHARPE and r.get("n", 0) >= PASS_TRADES
        )

        avg_sharpe = np.mean(sharpes) if sharpes else float("nan")

        all_results.append({
            "symbol": symbol,
            "rsi_entry": rsi_e,
            "rsi_exit": rsi_x,
            "max_hold": mh,
            "tp": f"{tp*100:.0f}%",
            "sl": f"{sl*100:.0f}%",
            "w1_sharpe": wf_res[0]["sharpe"] if wf_res else float("nan"),
            "w1_n": wf_res[0].get("n", 0) if wf_res else 0,
            "w2_sharpe": wf_res[1]["sharpe"] if len(wf_res) > 1 else float("nan"),
            "w2_n": wf_res[1].get("n", 0) if len(wf_res) > 1 else 0,
            "avg_sharpe": avg_sharpe,
            "passed": passed,
            "total_windows": len(WINDOWS),
        })

    return all_results


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("사이클 124: RSI Oversold Bounce 전략 백테스트")
    print(f"슬리피지: {SLIPPAGE*100:.2f}% (편도)")
    print(f"판정 기준: Sharpe > {PASS_SHARPE} && n >= {PASS_TRADES} (2/2창)")
    print("=" * 70)

    all_results: list[dict] = []
    for sym in SYMBOLS:
        results = grid_search(sym)
        all_results.extend(results)

    df = pd.DataFrame(all_results)

    # 2/2창 통과 후보
    passed_2_2 = df[df["passed"] == df["total_windows"]].sort_values("avg_sharpe", ascending=False)
    print(f"\n{'='*70}")
    print(f"2/2창 통과 조합: {len(passed_2_2)}개")
    print(f"{'='*70}")
    if len(passed_2_2) > 0:
        print(passed_2_2[["symbol","rsi_entry","rsi_exit","max_hold","tp","sl",
                           "w1_sharpe","w1_n","w2_sharpe","w2_n","avg_sharpe"]].to_string(index=False))
    else:
        print("없음")

    # 1/2창 통과 상위 10개
    passed_1_2 = df[df["passed"] == 1].sort_values("avg_sharpe", ascending=False).head(10)
    print(f"\n{'='*70}")
    print(f"1/2창 통과 상위 10개 (참고용)")
    print(f"{'='*70}")
    if len(passed_1_2) > 0:
        print(passed_1_2[["symbol","rsi_entry","rsi_exit","max_hold","tp","sl",
                           "w1_sharpe","w1_n","w2_sharpe","w2_n","avg_sharpe"]].to_string(index=False))

    # 심볼별 최고 avg Sharpe
    print(f"\n{'='*70}")
    print("심볼별 최고 avg Sharpe (2창 평균, trades >= 6 기준)")
    print(f"{'='*70}")
    for sym in SYMBOLS:
        sym_df = df[df["symbol"] == sym]
        valid = sym_df[
            (~sym_df["w1_sharpe"].isna()) &
            (~sym_df["w2_sharpe"].isna()) &
            (sym_df["w1_n"] >= PASS_TRADES) &
            (sym_df["w2_n"] >= PASS_TRADES)
        ]
        if len(valid) == 0:
            print(f"{sym}: 유효 결과 없음")
            continue
        best = valid.sort_values("avg_sharpe", ascending=False).iloc[0]
        print(f"{sym}: avg_sharpe={best['avg_sharpe']:.3f} "
              f"(W1={best['w1_sharpe']:.3f}/n={best['w1_n']}, "
              f"W2={best['w2_sharpe']:.3f}/n={best['w2_n']}) "
              f"rsi_e={best['rsi_entry']} rsi_x={best['rsi_exit']} "
              f"hold={best['max_hold']} tp={best['tp']} sl={best['sl']}")


if __name__ == "__main__":
    main()
