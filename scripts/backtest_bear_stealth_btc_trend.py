"""
AVAX/SOL BEAR Stealth + btc_trend_neg 게이트 탐색 (사이클 108)

목적: W2(2024-2025) 구조적 실패 원인 — BTC 장기 상승 추세 중 일시적 dip
  - 가설: btc_trend_neg(BTC 10봉/20봉 수익률 < 0) 게이트로 W2 fake-BEAR 차단
  - btc_sma20 below 기준만으로는 Bull 내 dip 구분 불가
  - BTC 단기 트렌드 음수 조건 추가 → 순수 BEAR 국면만 진입

게이트 조합:
  BASE   : btc<SMA20 only (사이클 106~107 기준선, acc>1.0, CVD>0)
  GATE10 : BASE + btc_10bar_ret < 0 (BTC 10봉 수익률 음수)
  GATE20 : BASE + btc_20bar_ret < 0 (BTC 20봉 수익률 음수)
  GATE_B : BASE + btc_10bar_ret < 0 AND btc_20bar_ret < 0 (둘 다 음수)

통과 기준: 3창 중 2+ 창에서 WR>52%, avg>0.3%, n>=15
결론 기준: GATE* 중 2+ 창 통과 && W2 포함 시 → daemon 반영 후보
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
BTC_TREND_SHORT = 10   # 10봉 = 40h
BTC_TREND_LONG = 20    # 20봉 = 80h
RS_LOW = 0.5
RS_HIGH = 1.0
ACC_THRESH = 1.00
CVD_THRESH = 0.0
FWD = 6       # 24h = 6 × 4h candles
FEE = 0.0005

PASS_WR = 0.52
PASS_AVG = 0.003
PASS_N = 15   # 완화: 게이트 강화로 샘플 감소 예상

# Gate combos: (label, use_gate10, use_gate20)
COMBOS = [
    ("BASE",    False, False),
    ("GATE10",  True,  False),
    ("GATE20",  False, True),
    ("GATE_B",  True,  True),
]


def compute_sma(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(p - 1, len(arr)):
        out[i] = arr[i - p + 1 : i + 1].mean()
    return out


def compute_btc_trend(btc_closes: np.ndarray, lookback: int) -> np.ndarray:
    """BTC lookback-bar return. Negative = bearish trend."""
    trend = np.full(len(btc_closes), np.nan)
    for i in range(lookback, len(btc_closes)):
        trend[i] = btc_closes[i] / btc_closes[i - lookback] - 1.0
    return trend


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


def run_gate_window(
    btc_w: pd.DataFrame,
    alt_data: dict[str, pd.DataFrame],
    win_start: str,
    win_end: str,
    use_gate10: bool,
    use_gate20: bool,
) -> dict[str, dict]:
    """Run one gate combo × window, return per-symbol stats dict."""
    btc_c = btc_w["close"].values
    btc_sma = compute_sma(btc_c, SMA_P)
    btc_trend10 = compute_btc_trend(btc_c, BTC_TREND_SHORT)
    btc_trend20 = compute_btc_trend(btc_c, BTC_TREND_LONG)

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
        btc_t10_aligned = compute_btc_trend(btc_aligned, BTC_TREND_SHORT)
        btc_t20_aligned = compute_btc_trend(btc_aligned, BTC_TREND_LONG)

        cvd = compute_cvd_slope(c, v, W)
        acc = compute_acc(c, v, W)
        rs = compute_rs(c, btc_aligned, W)

        bear_rets: list[float] = []
        for i in range(W * 2, len(c) - FWD):
            if np.isnan(btc_sma_aligned[i]):
                continue
            # Gate 0: BTC below SMA20 (BEAR regime)
            in_bull = btc_aligned[i] > btc_sma_aligned[i]
            if in_bull:
                continue

            # Gate 1 (optional): BTC 10-bar trend negative
            if use_gate10:
                if np.isnan(btc_t10_aligned[i]) or btc_t10_aligned[i] >= 0:
                    continue

            # Gate 2 (optional): BTC 20-bar trend negative
            if use_gate20:
                if np.isnan(btc_t20_aligned[i]) or btc_t20_aligned[i] >= 0:
                    continue

            if any(np.isnan(x) for x in [cvd[i], acc[i], rs[i]]):
                continue

            # Alt quality filter
            if not (
                cvd[i] > CVD_THRESH
                and acc[i] > ACC_THRESH
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
    print("=== AVAX/SOL BEAR Stealth + btc_trend_neg 게이트 탐색 (사이클 108) ===")
    print(f"심볼: {[s.replace('KRW-','') for s in SYMBOLS]}")
    print(f"기본: W={W}, SMA{SMA_P}, RS=[{RS_LOW},{RS_HIGH}), FWD={FWD}bars")
    print(f"게이트: 10봉={BTC_TREND_SHORT}bars(40h), 20봉={BTC_TREND_LONG}bars(80h)")
    print(f"Pass 기준: n>={PASS_N}, WR>={PASS_WR:.0%}, avg>={PASS_AVG*100:.1f}%")

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

    # Precompute window-sliced BTC
    btc_wins = {}
    for label, start, end in WINDOWS:
        btc_wins[label] = btc_full[
            (btc_full.index >= start) & (btc_full.index <= end)
        ].copy()

    # ── Main loop ──────────────────────────────────────────────────────────
    combo_results: dict[str, dict[str, dict]] = {}

    for c_label, use_10, use_20 in COMBOS:
        combo_results[c_label] = {}
        for w_label, w_start, w_end in WINDOWS:
            btc_w = btc_wins[w_label]
            if len(btc_w) < SMA_P * 3:
                continue
            res = run_gate_window(btc_w, alt_data, w_start, w_end, use_10, use_20)
            combo_results[c_label][w_label] = res

    # ── Print results per combo ────────────────────────────────────────────
    for c_label, use_10, use_20 in COMBOS:
        gate_desc = []
        if use_10:
            gate_desc.append(f"btc_{BTC_TREND_SHORT}bar<0")
        if use_20:
            gate_desc.append(f"btc_{BTC_TREND_LONG}bar<0")
        gate_str = " + ".join(gate_desc) if gate_desc else "없음(기준선)"

        print(f"\n{'='*65}")
        print(f"  COMBO {c_label}: {gate_str}")
        print(f"{'='*65}")

        win_pass_count = 0
        for w_label, w_start, w_end in WINDOWS:
            res = combo_results[c_label].get(w_label, {})
            if not res:
                continue

            sym_pass = sum(1 for s in res.values() if s.get("pass", False))
            win_passed = sym_pass >= 1
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
    print("  btc_trend_neg 게이트 조합 비교 요약")
    print(f"{'='*65}")
    print(f"  {'조합':<8} {'gate10':>7} {'gate20':>7} {'창통과':>6} | W1 W2 W3")
    print(f"  {'-'*55}")

    best_combo = None
    best_win_pass = 0
    w2_pass_combos = []

    for c_label, use_10, use_20 in COMBOS:
        row = combo_results[c_label]
        win_passes = []
        for w_label, _, _ in WINDOWS:
            res = row.get(w_label, {})
            sym_pass = sum(1 for s in res.values() if s.get("pass", False))
            win_passes.append(sym_pass >= 1)
        wpc = sum(win_passes)
        w_str = " ".join("✅" if p else "❌" for p in win_passes)
        g10 = "✅" if use_10 else "—"
        g20 = "✅" if use_20 else "—"
        print(f"  {c_label:<8} {g10:>7} {g20:>7} {wpc:>6}  | {w_str}")
        if wpc > best_win_pass:
            best_win_pass = wpc
            best_combo = c_label
        if len(win_passes) >= 2 and win_passes[1]:  # W2 통과 여부
            w2_pass_combos.append(c_label)

    print(f"\n  최고 조합: {best_combo} ({best_win_pass}/3 창 통과)")

    if w2_pass_combos:
        print(f"\n  ✅ W2 포함 통과 조합 발견: {w2_pass_combos}")
        print("     → btc_trend_neg 게이트 효과 있음!")
        print(f"     → {w2_pass_combos[0]} 파라미터로 AVAX/SOL BEAR 브랜치 설계 검토")
    else:
        print("\n  ⚠️ W2 모든 조합 실패 지속")
        print("     → btc_trend_neg 게이트도 W2 구조적 실패 해소 불가")
        print("     → BEAR stealth 브랜치 보류 확정 or 신규 심볼/전략 전환")

    # ── BTC trend coverage analysis ───────────────────────────────────────
    print(f"\n{'='*65}")
    print("  BTC 트렌드 게이트 샘플 비율 분석 (BTC<SMA20 대비)")
    print(f"{'='*65}")
    btc_c = btc_full["close"].values
    btc_sma_all = compute_sma(btc_c, SMA_P)
    btc_t10_all = compute_btc_trend(btc_c, BTC_TREND_SHORT)
    btc_t20_all = compute_btc_trend(btc_c, BTC_TREND_LONG)

    for w_label, w_start, w_end in WINDOWS:
        mask_all = (btc_full.index >= w_start) & (btc_full.index <= w_end)
        idx = np.where(mask_all)[0]
        if len(idx) == 0:
            continue
        bear_mask = btc_c[idx] < btc_sma_all[idx]
        n_bear = np.sum(bear_mask)
        n_total = len(idx)

        n_gate10 = np.sum(bear_mask & (btc_t10_all[idx] < 0))
        n_gate20 = np.sum(bear_mask & (btc_t20_all[idx] < 0))
        n_gate_b = np.sum(bear_mask & (btc_t10_all[idx] < 0) & (btc_t20_all[idx] < 0))

        print(f"\n  {w_label} ({w_start[:7]}~{w_end[:7]})")
        print(f"  전체 bars: {n_total} | BTC<SMA20: {n_bear} ({n_bear/n_total:.0%})")
        print(f"  + gate10 : {n_gate10} ({n_gate10/n_bear:.0%} of bear)")
        print(f"  + gate20 : {n_gate20} ({n_gate20/n_bear:.0%} of bear)")
        print(f"  + gate_B : {n_gate_b} ({n_gate_b/n_bear:.0%} of bear)")


if __name__ == "__main__":
    main()
