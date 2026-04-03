"""
AVAX/LINK/SOL/APT BEAR Stealth Walk-Forward Validation (사이클 106)

가설: 사이클 104에서 BEAR 레짐 양의 avg 포착(AVAX 52.4%/+0.83%, LINK 50.0%/+0.47%,
     SOL 51.2%/+0.36%, APT 52.7%/+0.31%) — 표본 부족(n=126-198) 검증 필요.

방법:
  - 3개 시간 창으로 슬라이딩 WF 분할:
      W1: 2022-01-01 ~ 2023-12-31
      W2: 2024-01-01 ~ 2025-03-31
      W3: 2025-04-01 ~ 2026-04-03 (최근 12개월)
  - 각 창에서 BEAR 레짐 alt stealth signal 성과 측정
  - 일관성 있는 엣지 여부 판단

통과 기준 (walk-forward 유효):
  - 3 창 중 2+ : WR > 52%, avg > 0.3%, n >= 30
  - Sharpe 중간값 > 0.5

결론 기대:
  - 2/3 이상 통과 → BEAR stealth (심볼 특화) 전략 추가 탐색 가치 있음
  - 1/3 이하 → 사이클 104 결과는 noise — 현재 Gate 1 필수 설계 유지
"""
from __future__ import annotations

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

# Walk-forward windows
WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2025-03-31"),
    ("W3", "2025-04-01", "2026-04-03"),
]

# Focus symbols (BEAR양수 포착된 4개)
SYMBOLS = ["KRW-AVAX", "KRW-LINK", "KRW-SOL", "KRW-APT"]

# Stealth params (daemon 최적값)
W = 36
SMA_P = 20
RS_LOW = 0.5
RS_HIGH = 1.0
CVD_THRESH = 0.0
ACC_THRESH = 1.0

FWD = 6      # 24h (6 * 4h candles)
FEE = 0.0005

PASS_WR = 0.52
PASS_AVG = 0.003  # 0.3%
PASS_N = 30


def compute_sma(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(p - 1, len(arr)):
        out[i] = arr[i - p + 1 : i + 1].mean()
    return out


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


def compute_acc(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    vpin = np.concatenate([[np.nan], buy / (vols[1:] + 1e-9)])
    acc = np.full(len(closes), np.nan)
    for i in range(w * 2, len(closes)):
        r = np.nanmean(vpin[i - w : i])
        o = np.nanmean(vpin[i - w * 2 : i - w])
        acc[i] = r / (o + 1e-9)
    return acc


def compute_rs(closes: np.ndarray, btc_closes: np.ndarray, w: int) -> np.ndarray:
    rs = np.full(len(closes), np.nan)
    for i in range(w, len(closes)):
        ar = closes[i] / closes[i - w] - 1.0
        br = btc_closes[i] / btc_closes[i - w] - 1.0
        rs[i] = (ar - br) / (abs(br) + 0.05)
    return rs


def run_window(
    label: str, start: str, end: str,
    btc_full: pd.DataFrame,
    alt_data: dict[str, pd.DataFrame],
) -> None:
    """Run one walk-forward window and print results."""
    print(f"\n{'='*60}")
    print(f"  {label}: {start} ~ {end}")
    print(f"{'='*60}")

    btc_w = btc_full[(btc_full.index >= start) & (btc_full.index <= end)].copy()
    if len(btc_w) < SMA_P * 3:
        print(f"  BTC 데이터 부족 ({len(btc_w)} bars)")
        return

    btc_c = btc_w["close"].values
    btc_sma = compute_sma(btc_c, SMA_P)

    bull_pct = np.nanmean(btc_c[SMA_P:] > btc_sma[SMA_P:]) * 100
    print(f"  BTC BULL 비율: {bull_pct:.1f}%")

    all_bear: list[float] = []
    sym_rows = []

    for sym in SYMBOLS:
        df_full = alt_data.get(sym)
        if df_full is None:
            continue
        df_w = df_full[(df_full.index >= start) & (df_full.index <= end)].copy()
        if len(df_w) < W * 3:
            continue

        # Align BTC to same timestamps
        aligned = btc_w.reindex(df_w.index, method="ffill")
        if len(aligned) < W * 3:
            continue

        c = df_w["close"].values
        v = df_w["volume"].values
        btc_aligned = aligned["close"].values
        btc_sma_aligned = compute_sma(btc_aligned, SMA_P)

        cvd = compute_cvd_slope(c, v, W)
        acc = compute_acc(c, v, W)
        rs = compute_rs(c, btc_aligned, W)

        bear_rets: list[float] = []
        bull_rets: list[float] = []

        for i in range(W * 2, len(c) - FWD):
            if np.isnan(btc_sma_aligned[i]):
                continue
            in_bull = btc_aligned[i] > btc_sma_aligned[i]

            if any(np.isnan(x) for x in [cvd[i], acc[i], rs[i]]):
                continue

            if not (cvd[i] > CVD_THRESH and acc[i] > ACC_THRESH and RS_LOW <= rs[i] < RS_HIGH):
                continue

            fwd = c[i + FWD] / c[i] - 1.0 - 2 * FEE

            if in_bull:
                bull_rets.append(fwd)
            else:
                bear_rets.append(fwd)

        def stats(rets: list[float]) -> tuple[int, float, float, float]:
            if not rets:
                return 0, 0.0, 0.0, 0.0
            a = np.array(rets)
            wr = float(np.mean(a > 0))
            avg = float(np.mean(a))
            sh = float(np.mean(a) / (np.std(a) + 1e-9) * np.sqrt(252 * 6)) if len(a) > 1 else 0.0
            return len(a), wr, avg, sh

        bn, bwr, bavg, bsh = stats(bear_rets)
        un, uwr, uavg, ush = stats(bull_rets)

        pass_flag = "✅" if (bn >= PASS_N and bwr >= PASS_WR and bavg >= PASS_AVG) else "❌"
        sym_rows.append({
            "sym": sym.replace("KRW-", ""),
            "bear_n": bn, "bear_wr": bwr, "bear_avg_pct": bavg * 100,
            "bear_sharpe": bsh, "pass": pass_flag,
            "bull_n": un, "bull_wr": uwr, "bull_avg_pct": uavg * 100,
        })
        all_bear.extend(bear_rets)

    if not sym_rows:
        print("  결과 없음")
        return

    print(f"\n  {'심볼':<6} {'BearN':>6} {'WR':>6} {'Avg%':>7} {'Sharpe':>7} {'통과':>4} | {'BullN':>6} {'BullWR':>6} {'BullAvg%':>8}")
    print(f"  {'-'*70}")
    pass_count = 0
    for r in sym_rows:
        print(
            f"  {r['sym']:<6} {r['bear_n']:>6} {r['bear_wr']:>6.1%} "
            f"{r['bear_avg_pct']:>7.2f}% {r['bear_sharpe']:>7.3f} {r['pass']:>4} | "
            f"{r['bull_n']:>6} {r['bull_wr']:>6.1%} {r['bull_avg_pct']:>8.2f}%"
        )
        if r["pass"] == "✅":
            pass_count += 1

    # Aggregate bear
    if all_bear:
        a = np.array(all_bear)
        agg_wr = float(np.mean(a > 0))
        agg_avg = float(np.mean(a)) * 100
        agg_sh = float(np.mean(a) / (np.std(a) + 1e-9) * np.sqrt(252 * 6))
        print(f"\n  [집계 BEAR] n={len(all_bear)}, WR={agg_wr:.1%}, avg={agg_avg:.2f}%, Sharpe={agg_sh:.3f}")

    print(f"\n  {label} 통과: {pass_count}/{len(sym_rows)} 심볼")
    return pass_count, len(sym_rows)


def main() -> None:
    print("=== AVAX/LINK/SOL/APT BEAR Stealth Walk-Forward (사이클 106) ===")
    print(f"Symbols: {SYMBOLS}")
    print(f"Stealth: W={W}, SMA{SMA_P}, RS=[{RS_LOW},{RS_HIGH}), CVD>0, acc>1.0")
    print(f"Pass 기준: n>={PASS_N}, WR>={PASS_WR:.0%}, avg>={PASS_AVG*100:.1f}%")
    print(f"FWD: {FWD} bars (24h), Fee: {FEE*2*100:.2f}% RT")

    # Load all data (full range)
    full_start = "2022-01-01"
    full_end = "2026-04-03"

    print("\nLoading BTC...")
    btc_df = load_historical(BTC_SYMBOL, INTERVAL, full_start, full_end)
    if btc_df is None:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"BTC: {len(btc_df)} bars")

    print("Loading alt symbols...")
    alt_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = load_historical(sym, INTERVAL, full_start, full_end)
        if df is not None:
            alt_data[sym] = df
            print(f"  {sym}: {len(df)} bars")
        else:
            print(f"  {sym}: NOT FOUND")

    # Run each window
    window_results = []
    for label, start, end in WINDOWS:
        result = run_window(label, start, end, btc_df, alt_data)
        if result:
            window_results.append((label, result[0], result[1]))

    # Summary
    print(f"\n{'='*60}")
    print("  WALK-FORWARD 종합 결과")
    print(f"{'='*60}")
    total_pass = sum(r[1] for r in window_results)
    total_sym_windows = sum(r[2] for r in window_results)

    for label, p, t in window_results:
        print(f"  {label}: {p}/{t} 심볼 통과")

    # Window-level pass (at least 2 symbols pass per window)
    window_pass = sum(1 for _, p, t in window_results if p >= 2)
    print(f"\n  창 통과 (2+심볼 기준): {window_pass}/{len(window_results)}")

    if window_pass >= 2:
        print("\n  ✅ BEAR stealth 엣지 유망 — 필터 강화 또는 심볼 확대 검토")
        print("     추천: acc_thresh 강화 (1.05) 또는 CVD 슬로프 최소값 추가")
    elif window_pass == 1:
        print("\n  ⚠️ 일부 창에서만 엣지 — 불안정, 추가 표본 필요")
    else:
        print("\n  ❌ BEAR stealth 엣지 없음 — Gate 1 필수 설계 유지")
        print("     사이클 104 BEAR 양수는 noise 확인됨")


if __name__ == "__main__":
    main()
