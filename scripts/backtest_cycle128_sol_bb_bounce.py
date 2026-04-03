"""
사이클 126: Bollinger Band 하단 이탈 반등 전략 백테스트
- 목적: RSI 계열(사이클 124/125) 슬리피지 내성 취약 → 다른 BEAR 엣지 탐색
         BB 하단 이탈(2σ 통계적 과매도) 후 반등 포착
- 전략: close < BB_lower → 다음 봉 오픈 진입 → TP/SL/max_hold 청산
         선택: BB 중간선(SMA) 도달 시 청산 (bb_exit_mid=True)
- 심볼: KRW-ETH (사이클 124/125에서 가장 강한 엣지 확인)
- 타임프레임: 240m (4시간봉)
- WF: W1 OOS=2024, W2 OOS=2025-2026
- 판정 기준: 2/2창 Sharpe > 5.0 && trades >= 6
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005       # 0.05% 수수료 (편도)
SLIPPAGE_LIST = [0.001, 0.002, 0.003]  # 0.10%, 0.20%, 0.30%

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

SYMBOL = "KRW-SOL"

# 그리드
BB_PERIOD_LIST   = [15, 20, 25]
BB_STD_LIST      = [2.0, 2.5]
ENTRY_PCT_LIST   = [0.0, 0.005, 0.01]    # BB 하단에서 추가 이탈 % (0=이탈 즉시)
TP_LIST          = [0.05, 0.08, 0.10, 0.15]
SL_LIST          = [0.02, 0.03]
MAX_HOLD_LIST    = [12, 24, 48]
BB_EXIT_MID_LIST = [False, True]          # SMA 도달 시 청산 여부

# 총 조합: 3×2×3×4×2×3×2 = 864
# 판정 기준
PASS_SHARPE = 5.0
PASS_TRADES = 6


# ─── 지표 계산 ────────────────────────────────────────────────────────────────

def bollinger_bands(closes: np.ndarray, period: int, n_std: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """BB 상/중/하단 반환"""
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


# ─── 백테스트 엔진 ────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    bb_period: int,
    bb_std: float,
    entry_pct: float,
    tp: float,
    sl: float,
    max_hold: int,
    bb_exit_mid: bool,
    slippage: float,
) -> dict:
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n = len(closes)

    _, bb_mid, bb_lower = bollinger_bands(closes, bb_period, bb_std)

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count  = 0
    entry_bb_mid = 0.0  # 진입 시점의 BB 중간선 저장

    for i in range(bb_period, n):
        if np.isnan(bb_lower[i]):
            continue

        if not in_pos:
            # 진입 조건: 이전 봉이 처음 BB 하단 이탈 (크로스다운)
            # entry_pct만큼 추가 이탈 필요 (0.0 = 이탈 즉시)
            threshold = bb_lower[i-1] * (1 - entry_pct)
            prev_threshold = bb_lower[i-2] * (1 - entry_pct) if i >= bb_period + 1 else float("inf")

            # 처음 이탈: 이전봉이 이탈, 그 이전봉은 이탈 안함
            if not np.isnan(bb_lower[i-1]) and closes[i-1] < threshold:
                # 이전이전봉이 이탈 안했거나 첫 봉인 경우만 진입 (첫 이탈)
                if i < bb_period + 1 or closes[i-2] >= prev_threshold:
                    entry_price = closes[i] * (1 + slippage + FEE)
                    in_pos = True
                    hold_count = 0
                    entry_bb_mid = bb_mid[i] if not np.isnan(bb_mid[i]) else entry_price * 1.05
        else:
            hold_count += 1
            # BB 중간선 업데이트
            current_bb_mid = bb_mid[i] if not np.isnan(bb_mid[i]) else entry_bb_mid

            # TP 확인
            if highs[i] >= entry_price * (1 + tp):
                exit_price = entry_price * (1 + tp) * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue

            # SL 확인
            if lows[i] <= entry_price * (1 - sl):
                exit_price = entry_price * (1 - sl) * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue

            # BB 중간선 청산 (bb_exit_mid=True)
            if bb_exit_mid and closes[i] >= current_bb_mid:
                exit_price = closes[i] * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue

            # max_hold 청산
            if hold_count >= max_hold:
                exit_price = closes[i] * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue

    if len(trades) < PASS_TRADES:
        return {"sharpe": float("nan"), "wr": float("nan"), "avg": float("nan"), "n": len(trades)}

    arr = np.array(trades)
    sharpe = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6)
    wr = (arr > 0).mean()
    avg = arr.mean()
    return {"sharpe": sharpe, "wr": wr, "avg": avg, "n": len(trades)}


# ─── 워크포워드 ──────────────────────────────────────────────────────────────

def walk_forward(params: dict, slippage: float) -> list[dict]:
    results = []
    for w in WINDOWS:
        df_all = load_historical(SYMBOL, "240m", w["is_start"], w["oos_end"])
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

        res = backtest(df_oos, slippage=slippage, **params)
        results.append({"window": w["name"], **res})
    return results


# ─── 그리드 탐색 ──────────────────────────────────────────────────────────────

def grid_search() -> list[dict]:
    all_results = []
    param_grid = list(product(
        BB_PERIOD_LIST, BB_STD_LIST, ENTRY_PCT_LIST,
        TP_LIST, SL_LIST, MAX_HOLD_LIST, BB_EXIT_MID_LIST
    ))
    print(f"\n{'='*60}")
    print(f"[{SYMBOL}] Bollinger Band Bounce 그리드 탐색 {len(param_grid)} 조합")
    print(f"판정 기준: 2/2창 Sharpe > {PASS_SHARPE} && n >= {PASS_TRADES}")
    print(f"{'='*60}")

    for bb_p, bb_s, e_pct, tp, sl, mh, bb_mid_exit in param_grid:
        params = {
            "bb_period": bb_p,
            "bb_std": bb_s,
            "entry_pct": e_pct,
            "tp": tp,
            "sl": sl,
            "max_hold": mh,
            "bb_exit_mid": bb_mid_exit,
        }

        for slippage in SLIPPAGE_LIST:
            wf_res = walk_forward(params, slippage)
            sharpes = [r["sharpe"] for r in wf_res if not np.isnan(r["sharpe"])]
            ns = [r["n"] for r in wf_res]
            passed = sum(
                1 for r in wf_res
                if not np.isnan(r["sharpe"])
                and r["sharpe"] >= PASS_SHARPE
                and r.get("n", 0) >= PASS_TRADES
            )

            row = {
                "bb_period": bb_p,
                "bb_std": bb_s,
                "entry_pct": e_pct,
                "tp": tp,
                "sl": sl,
                "max_hold": mh,
                "bb_exit_mid": bb_mid_exit,
                "slippage": slippage,
                "passed": passed,
                "avg_sharpe": np.mean(sharpes) if sharpes else float("nan"),
            }
            for r in wf_res:
                row[f"{r['window']}_sharpe"] = r.get("sharpe", float("nan"))
                row[f"{r['window']}_n"] = r.get("n", 0)
                row[f"{r['window']}_wr"] = r.get("wr", float("nan"))
                row[f"{r['window']}_avg"] = r.get("avg", float("nan"))
            all_results.append(row)

    return all_results


# ─── 결과 출력 ────────────────────────────────────────────────────────────────

def print_summary(results: list[dict]) -> None:
    df = pd.DataFrame(results)
    df = df.sort_values("avg_sharpe", ascending=False)

    print(f"\n{'='*70}")
    print("■ 2/2창 Sharpe≥5.0 통과 조합 (슬리피지별)")
    print(f"{'='*70}")

    for slippage in SLIPPAGE_LIST:
        sub = df[(df["slippage"] == slippage) & (df["passed"] == 2)].head(10)
        print(f"\n[슬리피지 {slippage*100:.2f}%] — 통과 {len(sub)}개")
        if not sub.empty:
            cols = ["bb_period", "bb_std", "entry_pct", "tp", "sl", "max_hold",
                    "bb_exit_mid", "W1_sharpe", "W1_n", "W2_sharpe", "W2_n", "W2_wr"]
            print(sub[cols].to_string(index=False))

    print(f"\n{'='*70}")
    print("■ 슬리피지 0.10% 기준 상위 20개 (2/2 통과 우선)")
    print(f"{'='*70}")
    top = df[df["slippage"] == SLIPPAGE_LIST[0]].head(20)
    cols = ["bb_period", "bb_std", "entry_pct", "tp", "sl", "max_hold",
            "bb_exit_mid", "passed", "W1_sharpe", "W1_n", "W2_sharpe", "W2_n"]
    print(top[cols].to_string(index=False))


def main() -> None:
    results = grid_search()
    print_summary(results)

    # CSV 저장
    df_out = pd.DataFrame(results)
    out_path = Path(__file__).parent / "cycle128_sol_bb_bounce_results.csv"
    df_out.to_csv(out_path, index=False)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
