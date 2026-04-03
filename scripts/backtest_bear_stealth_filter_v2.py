"""
AVAX/SOL BEAR Stealth 필터 강화 탐색 (사이클 107)

목적: 사이클 106 W2(2024-2025) 실패 원인 해소
  - AVAX/SOL BEAR stealth acc>1.0이 W2에서 실패 → 강한 Bull 레짐 잡음
  - 시도: acc>1.05, CVD_slope>0.3, 두 조합 동시 테스트

필터 조합:
  BASE  : acc>1.0,  CVD_slope>0.0  (사이클 106 기준선)
  ACCV  : acc>1.05, CVD_slope>0.0  (acc 강화)
  CVDV  : acc>1.0,  CVD_slope>0.3  (CVD 슬로프 최소값 추가)
  BOTH  : acc>1.05, CVD_slope>0.3  (둘 다 강화)

통과 기준: 3창 중 2+ 창에서 WR>52%, avg>0.3%, n>=20
결론 기준: BOTH/ACCV/CVDV 중 2/3 창 통과 조합 → 추가 탐색 가치
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
SYMBOLS = ["KRW-AVAX", "KRW-SOL"]

WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2025-03-31"),
    ("W3", "2025-04-01", "2026-04-03"),
]

W = 36
SMA_P = 20
RS_LOW = 0.5
RS_HIGH = 1.0
FWD = 6      # 24h = 6 × 4h candles
FEE = 0.0005

PASS_WR = 0.52
PASS_AVG = 0.003
PASS_N = 20  # 106보다 완화 (필터 강화로 샘플 감소 예상)

# Filter combos: (label, acc_thresh, cvd_slope_thresh)
COMBOS = [
    ("BASE",  1.00, 0.0),
    ("ACCV",  1.05, 0.0),
    ("CVDV",  1.00, 0.3),
    ("BOTH",  1.05, 0.3),
]


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
    avg_v = float(np.mean(vols))
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


def run_combo_window(
    btc_w: pd.DataFrame,
    alt_data: dict[str, pd.DataFrame],
    win_start: str,
    win_end: str,
    acc_thresh: float,
    cvd_slope_thresh: float,
) -> dict[str, dict]:
    """Run one combo×window, return per-symbol stats dict."""
    btc_c = btc_w["close"].values
    btc_sma = compute_sma(btc_c, SMA_P)

    results = {}
    for sym in SYMBOLS:
        df_full = alt_data.get(sym)
        if df_full is None:
            continue
        df_w = df_full[(df_full.index >= win_start) & (df_full.index <= win_end)].copy()
        if len(df_w) < W * 3:
            continue

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
        for i in range(W * 2, len(c) - FWD):
            if np.isnan(btc_sma_aligned[i]):
                continue
            in_bull = btc_aligned[i] > btc_sma_aligned[i]
            if in_bull:
                continue  # BEAR only
            if any(np.isnan(x) for x in [cvd[i], acc[i], rs[i]]):
                continue
            if not (
                cvd[i] > cvd_slope_thresh
                and acc[i] > acc_thresh
                and RS_LOW <= rs[i] < RS_HIGH
            ):
                continue
            fwd = c[i + FWD] / c[i] - 1.0 - 2 * FEE
            bear_rets.append(fwd)

        if not bear_rets:
            results[sym] = {"n": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0, "pass": False}
            continue
        a = np.array(bear_rets)
        n = len(a)
        wr = float(np.mean(a > 0))
        avg = float(np.mean(a))
        sh = float(np.mean(a) / (np.std(a) + 1e-9) * np.sqrt(252 * 6)) if n > 1 else 0.0
        passed = n >= PASS_N and wr >= PASS_WR and avg >= PASS_AVG
        results[sym] = {"n": n, "wr": wr, "avg": avg, "sharpe": sh, "pass": passed}
    return results


def main() -> None:
    print("=== AVAX/SOL BEAR Stealth 필터 강화 탐색 (사이클 107) ===")
    print(f"심볼: {[s.replace('KRW-','') for s in SYMBOLS]}")
    print(f"기본: W={W}, SMA{SMA_P}, RS=[{RS_LOW},{RS_HIGH}), FWD={FWD}bars")
    print(f"Pass 기준: n>={PASS_N}, WR>={PASS_WR:.0%}, avg>={PASS_AVG*100:.1f}%")
    print(f"필터 조합: {[(c[0],f'acc>{c[1]:.2f}',f'cvd_slope>{c[2]:.1f}') for c in COMBOS]}")

    full_start = "2022-01-01"
    full_end = "2026-04-03"

    print("\nLoading BTC...")
    btc_full = load_historical(BTC_SYMBOL, INTERVAL, full_start, full_end)
    if btc_full is None:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"BTC: {len(btc_full)} bars")

    print("Loading alts...")
    alt_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = load_historical(sym, INTERVAL, full_start, full_end)
        if df is not None:
            alt_data[sym] = df
            print(f"  {sym}: {len(df)} bars")
        else:
            print(f"  {sym}: NOT FOUND")

    # Precompute window-sliced BTC (for alignment)
    btc_wins = {}
    for label, start, end in WINDOWS:
        btc_wins[label] = btc_full[
            (btc_full.index >= start) & (btc_full.index <= end)
        ].copy()

    # ── Main loop ──────────────────────────────────────────────────────────
    # combo × window → sym stats
    # Structure: combo_results[combo_label][win_label] = {sym: stats}
    combo_results: dict[str, dict[str, dict]] = {}

    for c_label, acc_t, cvd_t in COMBOS:
        combo_results[c_label] = {}
        for w_label, w_start, w_end in WINDOWS:
            btc_w = btc_wins[w_label]
            if len(btc_w) < SMA_P * 3:
                continue
            res = run_combo_window(btc_w, alt_data, w_start, w_end, acc_t, cvd_t)
            combo_results[c_label][w_label] = res

    # ── Print results per combo ────────────────────────────────────────────
    for c_label, acc_t, cvd_t in COMBOS:
        print(f"\n{'='*65}")
        print(f"  COMBO {c_label}: acc>{acc_t:.2f}, CVD_slope>{cvd_t:.1f}")
        print(f"{'='*65}")

        win_pass_count = 0
        for w_label, w_start, w_end in WINDOWS:
            res = combo_results[c_label].get(w_label, {})
            if not res:
                continue

            sym_pass = sum(1 for s in res.values() if s.get("pass", False))
            win_passed = sym_pass >= 1  # at least 1 sym passes per window
            win_pass_count += int(win_passed)

            flag = "✅" if win_passed else "❌"
            print(f"\n  {w_label} ({w_start[:7]}~{w_end[:7]}) {flag}")
            print(f"  {'심볼':<6} {'n':>5} {'WR':>6} {'avg%':>7} {'Sharpe':>7} {'통과':>4}")
            print(f"  {'-'*40}")
            for sym, s in res.items():
                p = "✅" if s["pass"] else "❌"
                print(
                    f"  {sym.replace('KRW-',''):<6} {s['n']:>5} "
                    f"{s['wr']:>6.1%} {s['avg']*100:>7.2f}% "
                    f"{s['sharpe']:>7.3f} {p:>4}"
                )

        print(f"\n  → 창 통과: {win_pass_count}/3")

    # ── Summary comparison ────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("  필터 조합 비교 요약")
    print(f"{'='*65}")
    print(f"  {'조합':<6} {'acc':>6} {'cvd':>6} {'창통과':>6} | W1 W2 W3")
    print(f"  {'-'*50}")

    best_combo = None
    best_win_pass = 0

    for c_label, acc_t, cvd_t in COMBOS:
        row = combo_results[c_label]
        win_passes = []
        for w_label, _, _ in WINDOWS:
            res = row.get(w_label, {})
            sym_pass = sum(1 for s in res.values() if s.get("pass", False))
            win_passes.append(sym_pass >= 1)
        wpc = sum(win_passes)
        w_str = " ".join("✅" if p else "❌" for p in win_passes)
        print(f"  {c_label:<6} {acc_t:>6.2f} {cvd_t:>6.1f} {wpc:>6}  | {w_str}")
        if wpc > best_win_pass:
            best_win_pass = wpc
            best_combo = c_label

    print(f"\n  최고 조합: {best_combo} ({best_win_pass}/3 창 통과)")

    if best_win_pass >= 2:
        print("\n  ✅ W2 포함 일관성 개선 → daemon 반영 후보")
        print(f"     추천: {best_combo} 파라미터로 AVAX/SOL BEAR 브랜치 설계")
    elif best_win_pass == 1:
        print("\n  ⚠️ 필터 강화로도 W2 실패 지속 → BEAR stealth 브랜치 보류")
        print("     결론: W2(2024-2025 Bull 강세) 구조적 실패 — 레짐 감지 필요")
    else:
        print("\n  ❌ 필터 강화 효과 없음 → BEAR stealth 아이디어 기각")
        print("     다음: 신규 심볼 탐색 또는 다른 BEAR 전략 접근")


if __name__ == "__main__":
    main()
