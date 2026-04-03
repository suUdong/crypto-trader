#!/usr/bin/env python3
"""
Major BULL cycle 필터 적용 재검증 (사이클 89)

사이클 88 결론: SMA20 돌파 489개 이벤트 중 false breakout 과다
              → stealth_3gate vs buy-and-hold 우위 없음

이번 목표:
  1. "연속 N봉 SMA20 유지" 필터로 진짜 major BULL cycle 시작만 추출
     N = 3, 5, 8, 12 파라미터 테스트
  2. 필터 적용 전후 이벤트 수 비교 (489개 → 얼마나 압축?)
  3. 필터 적용 후 stealth_3gate 성과 재검증 (WR/Sharpe 개선 여부)
  4. 단순 보유 대비 우위 확인

현재 시장 상황: pre_bull=+0.673 → BULL 전환 임박
이 필터 결과가 "현재 전환이 major cycle인지" 판별 기준이 됨.

Usage:
    .venv/bin/python3 scripts/backtest_major_bull_filter.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))

from historical_loader import load_historical  # noqa: E402

# ── Config ───────────────────────────────────────────────────────────────────
CTYPE = "240m"          # 4h 캔들
START = "2022-01-01"
END   = "2026-04-03"
SMA_WINDOW = 20

LOOKBACK = 12           # pre_bull 계산 윈도우
RECENT_W = 4
ALT_SYMBOLS = ["KRW-SOL", "KRW-ETH", "KRW-XRP", "KRW-TRX"]

# 4개 심볼 TP/SL 파라미터 (확정값 사이클 83-85)
TP_SL = {
    "KRW-SOL": (0.12, 0.04),
    "KRW-ETH": (0.10, 0.03),
    "KRW-XRP": (0.12, 0.04),
    "KRW-TRX": (0.12, 0.03),
}

# Major BULL cycle 필터: 연속 N봉 SMA20 위 유지 (돌파 후 확인)
CONFIRM_N_LIST = [3, 5, 8, 12]

FORWARD_BARS_STEALTH = 24   # stealth 진입 후 최대 보유봉
FORWARD_BARS_BUY = [6, 12, 24]  # 단순 보유 측정 (24h, 48h, 96h)


# ── Helpers ──────────────────────────────────────────────────────────────────

def compute_alt_stealth(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    btc_idx: int,
    lb: int = LOOKBACK,
    rw: int = RECENT_W,
    rs_window: int = 20,
) -> bool:
    """alt stealth_3gate 조건 확인 (True/False)."""
    if btc_idx < max(lb + rw, rs_window):
        return False
    btc_ts = btc_df.index[btc_idx]
    if btc_ts not in alt_df.index:
        return False
    alt_idx = alt_df.index.get_loc(btc_ts)
    if not isinstance(alt_idx, int):
        alt_idx = int(alt_idx)
    if alt_idx < max(lb + rw, rs_window):
        return False

    win = alt_df.iloc[alt_idx - lb: alt_idx]
    btc_win = btc_df.iloc[btc_idx - lb: btc_idx]
    if len(win) < lb or len(btc_win) < lb:
        return False

    c = win["close"].values
    o = win["open"].values
    h = win["high"].values
    lv = win["low"].values
    v = win["volume"].values

    raw_ret = float(c[-1]) / max(float(c[0]), 1e-9) - 1.0
    rng = np.clip(h - lv, 1e-9, None)
    vpin = np.abs(c - o) / rng
    acc = vpin[-rw:].mean() / max(vpin[:-rw].mean(), 1e-9)
    sign_vol = np.where(c >= o, v, -v)
    cvd_slope = float(np.sum(sign_vol[-rw:])) / max(abs(float(np.sum(sign_vol))), 1e-9)

    rs_win_alt = alt_df.iloc[alt_idx - rs_window: alt_idx]["close"].values
    rs_win_btc = btc_df.iloc[btc_idx - rs_window: btc_idx]["close"].values
    alt_chg = float(rs_win_alt[-1]) / max(float(rs_win_alt[0]), 1e-9) - 1.0
    btc_chg = float(rs_win_btc[-1]) / max(float(rs_win_btc[0]), 1e-9) - 1.0
    rs = (1.0 + alt_chg) / max(1.0 + btc_chg, 1e-9) if btc_chg > -1 else 0.0

    return bool((raw_ret < 0.0) and (acc > 1.0) and (cvd_slope > 0.0) and (0.5 <= rs < 1.0))


def sim_tp_sl(
    df: pd.DataFrame,
    entry_idx: int,
    tp: float,
    sl: float,
    max_bars: int = 24,
) -> tuple[float, str]:
    """TP/SL 시뮬레이션."""
    if entry_idx >= len(df) - 1:
        return 0.0, "expired"
    entry_price = df["close"].iloc[entry_idx]
    tp_price = entry_price * (1 + tp)
    sl_price = entry_price * (1 - sl)
    for i in range(entry_idx + 1, min(entry_idx + max_bars + 1, len(df))):
        if df["low"].iloc[i] <= sl_price:
            return -sl, "sl"
        if df["high"].iloc[i] >= tp_price:
            return tp, "tp"
    final_price = df["close"].iloc[min(entry_idx + max_bars, len(df) - 1)]
    return final_price / entry_price - 1.0, "expired"


def run_stealth_backtest(
    btc: pd.DataFrame,
    alt_data: dict[str, pd.DataFrame],
    events: list[int],
    label: str,
) -> dict:
    """주어진 이벤트 리스트에서 stealth_3gate 백테스트 실행."""
    results: dict[str, list[float]] = {sym: [] for sym in ALT_SYMBOLS}
    exits: dict[str, dict[str, int]] = {sym: {"tp": 0, "sl": 0, "expired": 0} for sym in ALT_SYMBOLS}

    for trans_idx in events:
        for fwd in range(0, 7):  # 전환 후 6봉(24h) 이내 stealth 탐색
            check_idx = trans_idx + fwd
            if check_idx >= len(btc):
                break
            for sym in ALT_SYMBOLS:
                adf = alt_data[sym]
                btc_ts = btc.index[check_idx]
                if btc_ts not in adf.index:
                    continue
                alt_idx = adf.index.get_loc(btc_ts)
                if not isinstance(alt_idx, int):
                    alt_idx = int(alt_idx)

                if not compute_alt_stealth(adf, btc, check_idx):
                    continue

                tp, sl = TP_SL[sym]
                ret, exit_type = sim_tp_sl(adf, alt_idx, tp=tp, sl=sl, max_bars=FORWARD_BARS_STEALTH)
                results[sym].append(ret)
                exits[sym][exit_type] += 1
                break  # 심볼당 첫 진입만

    all_rets: list[float] = []
    sym_stats = {}
    for sym in ALT_SYMBOLS:
        rets = results[sym]
        if not rets:
            sym_stats[sym] = {"n": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0}
            continue
        wr = sum(1 for r in rets if r > 0) / len(rets)
        avg = float(np.mean(rets))
        std = float(np.std(rets)) if len(rets) > 1 else 0.0
        sh = avg / std if std > 0 else 0.0
        sym_stats[sym] = {
            "n": len(rets), "wr": wr, "avg": avg, "sharpe": sh,
            "tp": exits[sym]["tp"], "sl": exits[sym]["sl"], "exp": exits[sym]["expired"],
        }
        all_rets.extend(rets)

    total_stats: dict = {}
    if all_rets:
        wr = sum(1 for r in all_rets if r > 0) / len(all_rets)
        avg = float(np.mean(all_rets))
        std = float(np.std(all_rets)) if len(all_rets) > 1 else 0.0
        sh = avg / std if std > 0 else 0.0
        total_stats = {"n": len(all_rets), "wr": wr, "avg": avg, "sharpe": sh}

    return {"label": label, "events": len(events), "sym_stats": sym_stats, "total": total_stats}


def print_result(r: dict) -> None:
    label = r["label"]
    n_ev = r["events"]
    print(f"\n--- {label} (이벤트 {n_ev}개) ---")
    print(f"{'심볼':12s} {'진입수':>6} {'WR%':>6} {'avg_ret':>8} {'Sharpe':>7}")
    print("-" * 48)
    for sym in ALT_SYMBOLS:
        s = r["sym_stats"].get(sym, {})
        if not s or s.get("n", 0) == 0:
            print(f"{sym:12s} {'0':>6}")
            continue
        print(
            f"{sym:12s} {s['n']:>6} {s['wr']*100:>5.1f}% "
            f"{s['avg']*100:>+7.2f}% {s['sharpe']:>+7.2f}"
        )
    if r["total"]:
        t = r["total"]
        print("-" * 48)
        print(
            f"{'TOTAL':12s} {t['n']:>6} {t['wr']*100:>5.1f}% "
            f"{t['avg']*100:>+7.2f}% {t['sharpe']:>+7.2f}"
        )


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Loading BTC {CTYPE} data ({START} ~ {END})...")
    btc = load_historical("KRW-BTC", CTYPE, START, END)
    print(f"BTC rows: {len(btc)}")

    print("Loading alt data...")
    alt_data: dict[str, pd.DataFrame] = {}
    for sym in ALT_SYMBOLS:
        df = load_historical(sym, CTYPE, START, END)
        alt_data[sym] = df
        print(f"  {sym}: {len(df)} rows")

    # BTC SMA20
    btc["sma20"] = btc["close"].rolling(SMA_WINDOW).mean()
    btc["above_sma"] = btc["close"] > btc["sma20"]

    min_idx = SMA_WINDOW + LOOKBACK + RECENT_W + max(CONFIRM_N_LIST)

    # 기준선: SMA20 최초 돌파 이벤트 (489개 재현)
    raw_transitions = []
    for i in range(min_idx, len(btc) - max(FORWARD_BARS_BUY)):
        if not btc["above_sma"].iloc[i - 1] and btc["above_sma"].iloc[i]:
            raw_transitions.append(i)

    print(f"\n=== 기준선: SMA20 최초 돌파 이벤트 {len(raw_transitions)}개 ===")

    # ── 분석 1: 필터별 이벤트 압축 효과 ──────────────────────────────────────
    print("\n=== 분석 1: 연속 N봉 SMA20 유지 필터 — 이벤트 압축 효과 ===")
    print(f"{'N봉 필터':>8} {'이벤트수':>8} {'압축률':>8} {'설명':}")
    print("-" * 55)

    filtered_events: dict[int, list[int]] = {}
    for n in CONFIRM_N_LIST:
        filtered = []
        for idx in raw_transitions:
            # 돌파 후 N봉 연속 SMA20 위 유지 확인
            if idx + n >= len(btc):
                continue
            sustained = all(btc["above_sma"].iloc[idx + k] for k in range(1, n + 1))
            if sustained:
                filtered.append(idx)
        filtered_events[n] = filtered
        ratio = len(filtered) / len(raw_transitions) * 100 if raw_transitions else 0
        print(f"N={n:>6} {len(filtered):>8} {ratio:>7.1f}%  ({n*4}h 연속 SMA20 유지)")

    # ── 분석 2: 각 필터에서 stealth_3gate 성과 ───────────────────────────────
    print("\n=== 분석 2: 필터별 stealth_3gate 성과 비교 ===")

    # 기준선 (필터 없음)
    baseline = run_stealth_backtest(btc, alt_data, raw_transitions, "기준선 (N=0, 489개)")
    print_result(baseline)

    all_results = [baseline]
    for n in CONFIRM_N_LIST:
        evts = filtered_events[n]
        label = f"N={n} 필터 ({n*4}h 유지, {len(evts)}개)"
        r = run_stealth_backtest(btc, alt_data, evts, label)
        print_result(r)
        all_results.append(r)

    # ── 분석 3: 단순 보유 기준선 (필터별) ────────────────────────────────────
    print("\n=== 분석 3: 필터별 단순 보유 성과 비교 ===")
    print(f"{'필터':20s} {'n':>4} {'SOL_96h':>9} {'ETH_96h':>9} {'XRP_96h':>9} {'TRX_96h':>9}")
    print("-" * 68)

    def buy_hold_96h(events: list[int], sym: str) -> float:
        adf = alt_data[sym]
        rets = []
        for trans_idx in events:
            if trans_idx + 24 >= len(btc):
                continue
            btc_ts = btc.index[trans_idx]
            if btc_ts not in adf.index:
                continue
            alt_idx = adf.index.get_loc(btc_ts)
            if not isinstance(alt_idx, int):
                alt_idx = int(alt_idx)
            exit_idx = alt_idx + 24  # 96h = 24봉
            if exit_idx < len(adf):
                rets.append(adf["close"].iloc[exit_idx] / adf["close"].iloc[alt_idx] - 1.0)
        return float(np.mean(rets)) * 100 if rets else 0.0

    for n, label in [(0, "기준선 (N=0)")] + [(n, f"N={n}") for n in CONFIRM_N_LIST]:
        evts = raw_transitions if n == 0 else filtered_events[n]
        row = [f"{label:20s}", f"{len(evts):>4}"]
        for sym in ALT_SYMBOLS:
            row.append(f"{buy_hold_96h(evts, sym):>+8.2f}%")
        print(" ".join(row))

    # ── 최종 비교 요약 ────────────────────────────────────────────────────────
    print("\n=== 최종 요약: 필터별 stealth_3gate 통합 Sharpe ===")
    print(f"{'필터':30s} {'이벤트수':>8} {'진입수':>6} {'WR%':>6} {'avg_ret':>8} {'Sharpe':>8}")
    print("-" * 72)
    for r in all_results:
        t = r.get("total", {})
        if not t:
            print(f"{r['label']:30s} {r['events']:>8} {'(no trades)':>6}")
            continue
        print(
            f"{r['label']:30s} {r['events']:>8} {t['n']:>6} "
            f"{t['wr']*100:>5.1f}% {t['avg']*100:>+7.2f}% {t['sharpe']:>+8.2f}"
        )

    # ── 현재 상황에서의 시사점 ────────────────────────────────────────────────
    print("\n=== 현재 시장 시사점 ===")
    print("현재: BTC BEAR | pre_bull=+0.673 | 전환 임박 신호")
    print()
    print("N봉 필터 적용 시 현재 전환이 'major cycle'인지 판별 기준:")
    for n in CONFIRM_N_LIST:
        print(f"  → N={n}: 전환 확인 후 {n*4}h({n}봉) 연속 SMA20 위 유지 시 major cycle 확정")
    print()
    print("권장: N=5 (20h) 필터 — false breakout 제거 vs 진입 지연 균형")
    print("  XRP/TRX/ETH: N=5 필터 이후에도 stealth 진입 가능하면 진입 우선")
    print("  SOL: WR=32% 기록 낮음 → N=8 이상 필터 후 진입 고려")


if __name__ == "__main__":
    main()
