"""
NEAR acc/RS 그리드 탐색 (사이클 110)

가설: NEAR W2 Sharpe +2.262 (acc>1.0, RS[0.5,1.0)) → acc 완화 + RS 범위 조정으로
      W2 Sharpe 3.0 달성 가능한가?

탐색 범위:
  - acc_thresh: [0.7, 0.8, 0.9, 1.0]
  - rs_range: [(0.3,0.8), (0.4,0.9), (0.5,1.0), (0.3,1.0)]
  → 4×4 = 16 조합

성공 기준: Sharpe > 3.0, n >= 30, 2/3 창 이상 통과
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical

INTERVAL = "240m"
BTC_SYMBOL = "KRW-BTC"
SYMBOL = "KRW-NEAR"

# Fixed daemon params
W = 36
SMA_P = 20
CVD_THRESH = 0.0
BTC_TREND_WINDOW = 10

TP = 0.15
SL = 0.03
MAX_HOLD = 24
FWD = 6
FEE = 0.0005

MIN_TRADES = 30
SHARPE_MIN = 3.0

# Walk-forward windows
WINDOWS = [
    ("W1", "2022-01-01", "2024-03-31"),
    ("W2", "2023-06-01", "2025-03-31"),
    ("W3", "2024-06-01", "2026-04-04"),
]

# Grid
ACC_GRID = [0.7, 0.8, 0.9, 1.0]
RS_GRID = [(0.3, 0.8), (0.4, 0.9), (0.5, 1.0), (0.3, 1.0)]


def compute_sma(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(p - 1, len(arr)):
        out[i] = arr[i - p + 1 : i + 1].mean()
    return out


def compute_acc(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    vpin = np.concatenate([[np.nan], buy / (vols[1:] + 1e-9)])
    acc = np.full(len(closes), np.nan)
    for i in range(w * 2, len(closes)):
        recent_mean = np.nanmean(vpin[i - w : i])
        older_mean = np.nanmean(vpin[i - w * 2 : i - w])
        acc[i] = recent_mean / (older_mean + 1e-9)
    return acc


def compute_cvd_slope(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    cvd = np.cumsum(buy - vols[1:] / 2)
    cvd = np.concatenate([[0.0], cvd])
    slopes = np.full(len(closes), np.nan)
    avg_v = np.mean(vols)
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


def run_window(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    start: str,
    end: str,
    acc_thresh: float,
    rs_low: float,
    rs_high: float,
) -> dict:
    merged_alt = alt_df[(alt_df.index >= start) & (alt_df.index <= end)]
    btc_w = btc_df[(btc_df.index >= start) & (btc_df.index <= end)]
    btc_aligned = btc_w.reindex(merged_alt.index, method="ffill")

    if len(merged_alt) < W * 3 or len(btc_aligned) < W * 3:
        return {"n": 0, "sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0}

    c = merged_alt["close"].values
    v = merged_alt["volume"].values
    bc = btc_aligned["close"].values

    btc_sma = compute_sma(bc, SMA_P)
    acc = compute_acc(c, v, W)
    cvd = compute_cvd_slope(c, v, W)
    rs = compute_rs(c, bc, W)

    trades: list[float] = []
    i = W * 2
    last_exit = 0

    while i < len(c) - FWD - 1:
        if i < last_exit:
            i += 1
            continue

        if np.isnan(btc_sma[i]) or bc[i] <= btc_sma[i]:
            i += 1
            continue

        if i < BTC_TREND_WINDOW or bc[i] <= bc[i - BTC_TREND_WINDOW]:
            i += 1
            continue

        if any(np.isnan(x) for x in [acc[i], cvd[i], rs[i]]):
            i += 1
            continue
        if acc[i] <= acc_thresh or cvd[i] <= CVD_THRESH:
            i += 1
            continue
        if not (rs_low <= rs[i] < rs_high):
            i += 1
            continue

        entry = c[i]
        tp_p = entry * (1 + TP)
        sl_p = entry * (1 - SL)
        ret = None
        hold = 0

        for j in range(i + 1, min(i + MAX_HOLD + 1, len(c))):
            price = c[j]
            hold += 1
            if price >= tp_p:
                ret = TP - 2 * FEE
                break
            elif price <= sl_p:
                ret = -SL - 2 * FEE
                break

        if ret is None:
            fwd_idx = min(i + FWD, len(c) - 1)
            ret = c[fwd_idx] / entry - 1.0 - 2 * FEE

        trades.append(ret)
        last_exit = i + max(hold, 1)
        i = last_exit

    if len(trades) < MIN_TRADES:
        return {"n": len(trades), "sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0}

    arr = np.array(trades)
    sh = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6 / max(1, len(arr)))
    wr = float((arr > 0).mean()) * 100
    avg = float(arr.mean()) * 100
    return {"n": len(trades), "sharpe": sh, "wr": wr, "avg_ret": avg}


def main() -> None:
    print("=" * 70)
    print("NEAR acc/RS 그리드 탐색 (사이클 110)")
    print(f"심볼: NEAR | acc_grid={ACC_GRID}")
    print(f"rs_grid={RS_GRID}")
    print(f"MIN_TRADES={MIN_TRADES} | SHARPE_MIN={SHARPE_MIN}")
    print("=" * 70)

    print("\n[데이터 로드 중...]")
    btc_df = load_historical(BTC_SYMBOL, INTERVAL, "2022-01-01", "2026-04-04")
    near_df = load_historical(SYMBOL, INTERVAL, "2022-01-01", "2026-04-04")

    if btc_df is None or near_df is None:
        print("ERROR: 데이터 로드 실패")
        return

    print(f"  BTC: {len(btc_df)} 봉")
    print(f"  NEAR: {len(near_df)} 봉 ({near_df.index[0].date()} ~ {near_df.index[-1].date()})")

    best_passes = 0
    best_config = None
    best_results = None
    all_results = []

    total = len(ACC_GRID) * len(RS_GRID)
    done = 0

    for acc_t, (rs_l, rs_h) in product(ACC_GRID, RS_GRID):
        done += 1
        passes = 0
        window_results = {}

        for wname, wstart, wend in WINDOWS:
            r = run_window(near_df, btc_df, wstart, wend, acc_t, rs_l, rs_h)
            window_results[wname] = r
            if r["sharpe"] >= SHARPE_MIN and r["n"] >= MIN_TRADES:
                passes += 1

        config_key = f"acc>{acc_t:.1f} RS[{rs_l},{rs_h})"
        all_results.append({
            "config": config_key,
            "acc": acc_t,
            "rs_low": rs_l,
            "rs_high": rs_h,
            "passes": passes,
            "windows": window_results,
        })

        if passes > best_passes:
            best_passes = passes
            best_config = config_key
            best_results = window_results

        # 진행 출력 (2/3 이상 통과한 경우만 상세)
        if passes >= 2:
            icon = "🏆"
        elif passes == 1:
            icon = "⚠️"
        else:
            icon = "  "
        print(f"[{done:02d}/{total}] {icon} {config_key}: {passes}/3 창 통과", end="")
        if passes >= 1:
            for wname, r in window_results.items():
                if r["sharpe"] >= SHARPE_MIN and r["n"] >= MIN_TRADES:
                    print(f" | {wname} Sharpe={r['sharpe']:+.3f}(n={r['n']})", end="")
        print()

    # ─── 최종 요약 ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("NEAR 그리드 탐색 요약")
    print("=" * 70)

    # 2창 이상 통과한 결과 필터링
    winners = [r for r in all_results if r["passes"] >= 2]
    if winners:
        print(f"\n🏆 2창 이상 통과: {len(winners)}개")
        for w in sorted(winners, key=lambda x: -x["passes"]):
            print(f"\n  설정: {w['config']} ({w['passes']}/3 창)")
            for wname, r in w["windows"].items():
                flag = "✅" if r["sharpe"] >= SHARPE_MIN and r["n"] >= MIN_TRADES else "❌"
                print(
                    f"    {flag} {wname}: Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1f}%"
                    f" avg={r['avg_ret']:+.2f}% n={r['n']}"
                )
    else:
        print("\n❌ 2창 이상 통과한 설정 없음 — NEAR 엣지 부재 확정")
        # 가장 좋은 1창 통과 결과 출력
        one_pass = [r for r in all_results if r["passes"] == 1]
        if one_pass:
            best_one = max(one_pass, key=lambda x: max(
                v["sharpe"] for v in x["windows"].values()
            ))
            print(f"\n  최고 1창 통과: {best_one['config']}")
            for wname, r in best_one["windows"].items():
                flag = "✅" if r["sharpe"] >= SHARPE_MIN and r["n"] >= MIN_TRADES else "❌"
                print(
                    f"    {flag} {wname}: Sharpe={r['sharpe']:+.3f} n={r['n']}"
                )

    # W2 기준 최고 Sharpe 랭킹 (Top 5)
    print("\n[W2 Sharpe 기준 Top 5]")
    ranked = sorted(
        all_results,
        key=lambda x: x["windows"].get("W2", {}).get("sharpe", -999),
        reverse=True,
    )[:5]
    for r in ranked:
        w2 = r["windows"].get("W2", {})
        w3 = r["windows"].get("W3", {})
        print(
            f"  {r['config']}: W2={w2.get('sharpe', 0):+.3f}(n={w2.get('n', 0)})"
            f" W3={w3.get('sharpe', 0):+.3f}(n={w3.get('n', 0)})"
            f" → {r['passes']}/3"
        )

    print("\n[결론]")
    if winners:
        print(f"✅ NEAR acc/RS 조정으로 2창 통과 달성 — 베스트 설정: {best_config}")
        print("   → SUI와 함께 daemon stealth_3gate_wallet_1 추가 후보 검토")
    else:
        print("❌ NEAR는 acc/RS 조정에도 2창 통과 불가 — 탐색 종료")
        print("   → 다른 심볼 탐색 또는 전략 변경 필요")


if __name__ == "__main__":
    main()
