#!/usr/bin/env python3
"""
사이클 117: SUI stealth_3gate 파라미터 그리드 탐색
- 목표: W2 Sharpe +3.990 → 5.0+ 달성 가능한 파라미터 조합 발굴
- 기준선: W=36, RS[0.5,1.0), acc>1.0, CVD>0, TP=15%, SL=3%
- 탐색: TP × SL × RS범위 × W × ACC — 총 ~96 조합
- Windows: W2(2023-10-01~2025-03-31), W3(2024-06-01~2026-04-04)
- 성공 기준: W2+W3 모두 Sharpe ≥ 5.0, n ≥ 8
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical

INTERVAL = "240m"
BTC_SYMBOL = "KRW-BTC"
ALT_SYMBOL = "KRW-SUI"

SMA_P = 20
BTC_TREND_WINDOW = 10
FEE = 0.0005  # per side
MIN_TRADES = 8
SHARPE_MIN = 5.0  # 목표 임계값

# Walk-forward windows (SUI 2창 프레임워크)
WINDOWS = [
    ("W2", "2023-10-01", "2025-03-31"),
    ("W3", "2024-06-01", "2026-04-04"),
]

# 그리드 탐색 파라미터
GRID = {
    "W":       [24, 36],
    "acc":     [0.9, 1.0],
    "rs":      [(0.3, 1.0), (0.5, 1.0), (0.5, 1.5), (0.5, 2.0)],
    "tp":      [0.10, 0.12, 0.15, 0.20],
    "sl":      [0.02, 0.03, 0.04],
}


# ─── Indicator helpers ────────────────────────────────────────────────────────

def compute_sma(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(p - 1, len(arr)):
        out[i] = arr[i - p + 1: i + 1].mean()
    return out


def compute_acc(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    vpin = np.concatenate([[np.nan], buy / (vols[1:] + 1e-9)])
    acc = np.full(len(closes), np.nan)
    for i in range(w * 2, len(closes)):
        recent_mean = np.nanmean(vpin[i - w: i])
        older_mean = np.nanmean(vpin[i - w * 2: i - w])
        acc[i] = recent_mean / (older_mean + 1e-9)
    return acc


def compute_cvd_slope(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    cvd = np.cumsum(buy - vols[1:] / 2)
    cvd = np.concatenate([[0.0], cvd])
    slopes = np.full(len(closes), np.nan)
    avg_v = float(np.mean(vols))
    for i in range(w, len(closes)):
        slopes[i] = (cvd[i] - cvd[i - w]) / (avg_v + 1e-9)
    return slopes


def compute_rs(closes: np.ndarray, btc_closes: np.ndarray, w: int) -> np.ndarray:
    rs = np.full(len(closes), np.nan)
    for i in range(w, len(closes)):
        ar = closes[i] / closes[i - w] - 1.0
        br = btc_closes[i] / btc_closes[i - w] - 1.0
        rs[i] = (ar - br) / (abs(br) + 0.05)
    return rs


# ─── Single window backtest ───────────────────────────────────────────────────

def run_window(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    start: str,
    end: str,
    W: int,
    acc_thresh: float,
    rs_low: float,
    rs_high: float,
    tp: float,
    sl: float,
) -> dict:
    merged_alt = alt_df[(alt_df.index >= start) & (alt_df.index <= end)]
    btc_w = btc_df[(btc_df.index >= start) & (btc_df.index <= end)]
    btc_aligned = btc_w.reindex(merged_alt.index, method="ffill")

    if len(merged_alt) < W * 3 or len(btc_aligned) < W * 3:
        return {"n": 0, "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0}

    c = merged_alt["close"].values
    v = merged_alt["volume"].values
    bc = btc_aligned["close"].values

    btc_sma = compute_sma(bc, SMA_P)
    acc = compute_acc(c, v, W)
    cvd = compute_cvd_slope(c, v, W)
    rs = compute_rs(c, bc, W)

    FWD = 6  # fallback forward candles
    MAX_HOLD = 24  # 96h max hold

    trades: list[float] = []
    i = W * 2
    last_exit = 0

    while i < len(c) - FWD - 1:
        if i < last_exit:
            i += 1
            continue

        # Gate 1: BTC > SMA20
        if np.isnan(btc_sma[i]) or bc[i] <= btc_sma[i]:
            i += 1
            continue

        # Gate 4: btc_trend_pos
        if i < BTC_TREND_WINDOW or bc[i] <= bc[i - BTC_TREND_WINDOW]:
            i += 1
            continue

        # Gate 3: alt stealth
        if any(np.isnan(x) for x in [acc[i], cvd[i], rs[i]]):
            i += 1
            continue
        if acc[i] <= acc_thresh or cvd[i] <= 0.0:
            i += 1
            continue
        if not (rs_low <= rs[i] < rs_high):
            i += 1
            continue

        entry = c[i]
        tp_p = entry * (1 + tp)
        sl_p = entry * (1 - sl)
        ret = None
        hold = 0

        for j in range(i + 1, min(i + MAX_HOLD + 1, len(c))):
            price = c[j]
            hold += 1
            if price >= tp_p:
                ret = tp - 2 * FEE
                break
            elif price <= sl_p:
                ret = -sl - 2 * FEE
                break

        if ret is None:
            fwd_idx = min(i + FWD, len(c) - 1)
            ret = c[fwd_idx] / entry - 1.0 - 2 * FEE

        trades.append(ret)
        last_exit = i + max(hold, 1)
        i = last_exit

    if len(trades) < MIN_TRADES:
        return {"n": len(trades), "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0}

    arr = np.array(trades)
    sh = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6 / max(1, len(arr)))
    wr = float((arr > 0).mean()) * 100
    avg = float(arr.mean()) * 100
    return {"n": len(trades), "sharpe": float(sh), "wr": wr, "avg_ret": avg}


# ─── Main grid search ─────────────────────────────────────────────────────────

def main() -> None:
    print(f"=== 사이클 117: SUI stealth_3gate 파라미터 그리드 탐색 ===\n")
    print(f"목표: W2+W3 모두 Sharpe ≥ {SHARPE_MIN}, n ≥ {MIN_TRADES}\n")

    # 데이터 로드
    load_start = "2023-01-01"
    load_end = "2026-04-04"

    print(f"데이터 로드 중...")
    btc_df = load_historical(BTC_SYMBOL, INTERVAL, load_start, load_end)
    alt_df = load_historical(ALT_SYMBOL, INTERVAL, load_start, load_end)
    print(f"  BTC: {len(btc_df)}봉 ({btc_df.index[0].date()} ~ {btc_df.index[-1].date()})")
    print(f"  SUI: {len(alt_df)}봉 ({alt_df.index[0].date()} ~ {alt_df.index[-1].date()})")
    print()

    # 그리드 조합 생성
    combos = list(itertools.product(
        GRID["W"], GRID["acc"], GRID["rs"], GRID["tp"], GRID["sl"]
    ))
    total = len(combos)
    print(f"총 {total} 조합 탐색 시작...\n")

    results = []
    passing = []

    for idx, (W, acc_thresh, (rs_low, rs_high), tp, sl) in enumerate(combos):
        window_results = {}
        passes = 0
        for name, start, end in WINDOWS:
            r = run_window(alt_df, btc_df, start, end, W, acc_thresh, rs_low, rs_high, tp, sl)
            window_results[name] = r
            if not np.isnan(r["sharpe"]) and r["sharpe"] >= SHARPE_MIN and r["n"] >= MIN_TRADES:
                passes += 1

        row = {
            "W": W, "acc": acc_thresh,
            "rs_low": rs_low, "rs_high": rs_high,
            "tp": tp, "sl": sl,
            "passes": passes,
        }
        for name, r in window_results.items():
            row[f"{name}_sharpe"] = r["sharpe"]
            row[f"{name}_n"] = r["n"]
            row[f"{name}_wr"] = r["wr"]

        results.append(row)
        if passes == 2:
            passing.append(row)

        if (idx + 1) % 20 == 0:
            print(f"  진행: {idx+1}/{total} — 통과 {len(passing)}개")

    print(f"\n=== 결과 ===")
    print(f"총 {total} 조합 중 W2+W3 모두 통과: {len(passing)}개\n")

    if passing:
        print("─── 2/2창 통과 조합 (Sharpe 내림차순) ───")
        df_pass = pd.DataFrame(passing)
        df_pass["avg_sharpe"] = (df_pass["W2_sharpe"] + df_pass["W3_sharpe"]) / 2
        df_pass = df_pass.sort_values("avg_sharpe", ascending=False)
        print(f"{'W':>4} {'acc':>5} {'RS범위':>12} {'TP':>6} {'SL':>5} | {'W2 Sharpe':>10} W2n | {'W3 Sharpe':>10} W3n | {'avg':>8}")
        print("─" * 80)
        for _, row in df_pass.iterrows():
            rs_str = f"[{row['rs_low']:.1f},{row['rs_high']:.1f})"
            print(
                f"{int(row['W']):>4} {row['acc']:>5.1f} {rs_str:>12} "
                f"{row['tp']*100:>5.0f}% {row['sl']*100:>4.0f}% | "
                f"{row['W2_sharpe']:>10.3f} n={int(row['W2_n']):<3} | "
                f"{row['W3_sharpe']:>10.3f} n={int(row['W3_n']):<3} | "
                f"{row['avg_sharpe']:>8.3f}"
            )
    else:
        print("─── 통과 없음 — 상위 5개 (avg Sharpe 기준) ───")
        df_all = pd.DataFrame(results)
        df_all["avg_sharpe"] = df_all.apply(
            lambda r: (
                (r["W2_sharpe"] if not np.isnan(r["W2_sharpe"]) else 0)
                + (r["W3_sharpe"] if not np.isnan(r["W3_sharpe"]) else 0)
            ) / 2,
            axis=1
        )
        df_top = df_all.nlargest(10, "avg_sharpe")
        print(f"{'W':>4} {'acc':>5} {'RS범위':>12} {'TP':>6} {'SL':>5} | {'W2 Sharpe':>10} W2n | {'W3 Sharpe':>10} W3n | {'avg':>8} passes")
        print("─" * 95)
        for _, row in df_top.iterrows():
            rs_str = f"[{row['rs_low']:.1f},{row['rs_high']:.1f})"
            w2_s = f"{row['W2_sharpe']:.3f}" if not np.isnan(row['W2_sharpe']) else "  nan"
            w3_s = f"{row['W3_sharpe']:.3f}" if not np.isnan(row['W3_sharpe']) else "  nan"
            print(
                f"{int(row['W']):>4} {row['acc']:>5.1f} {rs_str:>12} "
                f"{row['tp']*100:>5.0f}% {row['sl']*100:>4.0f}% | "
                f"{w2_s:>10} n={int(row['W2_n']):<3} | "
                f"{w3_s:>10} n={int(row['W3_n']):<3} | "
                f"{row['avg_sharpe']:>8.3f} {int(row['passes'])}/2"
            )

    # 베이스라인 참조 출력
    print("\n─── 베이스라인 (W=36, acc>1.0, RS[0.5,1.0), TP=15%, SL=3%) ───")
    baseline_w2 = run_window(alt_df, btc_df, "2023-10-01", "2025-03-31",
                              36, 1.0, 0.5, 1.0, 0.15, 0.03)
    baseline_w3 = run_window(alt_df, btc_df, "2024-06-01", "2026-04-04",
                              36, 1.0, 0.5, 1.0, 0.15, 0.03)
    print(f"  W2: Sharpe={baseline_w2['sharpe']:.3f}, WR={baseline_w2['wr']:.1f}%, n={baseline_w2['n']}")
    print(f"  W3: Sharpe={baseline_w3['sharpe']:.3f}, WR={baseline_w3['wr']:.1f}%, n={baseline_w3['n']}")

    print("\n완료.")


if __name__ == "__main__":
    main()
