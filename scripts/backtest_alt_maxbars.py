#!/usr/bin/env python3
"""
SOL/ETH/XRP max_bars 최적화 — N=8 major BULL cycle 필터 (사이클 91)

사이클 90 결과:
  TRX max_bars=24(96h) → Sharpe +0.14
  TRX max_bars=48(192h) → Sharpe +0.36 ← 보유기간이 핵심 변수

목표: SOL/ETH/XRP도 동일 문제(만료율 과다) 여부 확인
그리드:
  max_bars: [12, 24, 36, 48, 72]
  TP/SL: 사이클 83-85 확정값 유지 (SOL 12/4, ETH 10/3, XRP 12/4)

Usage:
    .venv/bin/python3 scripts/backtest_alt_maxbars.py
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
CTYPE = "240m"
START = "2022-01-01"
END   = "2026-04-03"
SMA_WINDOW = 20
CONFIRM_N = 8           # N=8 (32h) 확정 필터

LOOKBACK = 12
RECENT_W = 4

ALT_SYMBOLS = ["KRW-SOL", "KRW-ETH", "KRW-XRP"]
BTC_SYM = "KRW-BTC"

# 사이클 83-85 확정 TP/SL
TP_SL = {
    "KRW-SOL": (0.12, 0.04),
    "KRW-ETH": (0.10, 0.03),
    "KRW-XRP": (0.12, 0.04),
}

MAX_BARS_LIST = [12, 24, 36, 48, 72]


# ── Event Detection ───────────────────────────────────────────────────────────
def find_major_bull_events(btc: pd.DataFrame, confirm_n: int = CONFIRM_N) -> list[int]:
    """BTC SMA20 돌파 후 confirm_n봉 연속 유지 시점 반환."""
    close = btc["close"].values
    sma = pd.Series(close).rolling(SMA_WINDOW).mean().values
    events: list[int] = []
    in_bull = False
    consec = 0
    for i in range(SMA_WINDOW, len(btc)):
        if close[i] > sma[i]:
            consec += 1
            if not in_bull and consec >= confirm_n:
                events.append(i)
                in_bull = True
        else:
            consec = 0
            in_bull = False
    return events


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


def run_backtest(
    btc: pd.DataFrame,
    alt: pd.DataFrame,
    events: list[int],
    tp: float,
    sl: float,
    max_bars: int,
) -> dict:
    rets: list[float] = []
    exits = {"tp": 0, "sl": 0, "expired": 0}

    for trans_idx in events:
        for fwd in range(0, 7):
            check_idx = trans_idx + fwd
            if check_idx >= len(btc):
                break
            if not compute_alt_stealth(alt, btc, check_idx):
                continue
            btc_ts = btc.index[check_idx]
            if btc_ts not in alt.index:
                continue
            alt_idx = alt.index.get_loc(btc_ts)
            if not isinstance(alt_idx, int):
                alt_idx = int(alt_idx)
            ret, exit_type = sim_tp_sl(alt, alt_idx, tp=tp, sl=sl, max_bars=max_bars)
            rets.append(ret)
            exits[exit_type] += 1
            break  # 이벤트당 첫 진입만

    if len(rets) == 0:
        return {"n": 0, "wr": 0.0, "avg_ret": 0.0, "sharpe": float("nan"), "expired_pct": 0.0}

    arr = np.array(rets)
    wr = float((arr > 0).mean())
    avg = float(arr.mean())
    std = float(arr.std())
    sharpe = avg / std if std > 1e-9 else 0.0
    expired_pct = exits["expired"] / len(rets)
    return {
        "n": len(rets),
        "wr": round(wr * 100, 1),
        "avg_ret": round(avg * 100, 2),
        "sharpe": round(sharpe, 2),
        "expired_pct": round(expired_pct * 100, 1),
        "tp_cnt": exits["tp"],
        "sl_cnt": exits["sl"],
        "exp_cnt": exits["expired"],
    }


def main() -> None:
    print("=== SOL/ETH/XRP max_bars 최적화 (N=8 Major BULL cycle 필터) ===")
    print(f"기간: {START} ~ {END}, 캔들: {CTYPE}")
    print(f"CONFIRM_N={CONFIRM_N}봉({CONFIRM_N*4}h), SMA{SMA_WINDOW}")
    print()

    # 데이터 로드
    print("데이터 로드 중...")
    btc = load_historical(BTC_SYM, CTYPE, START, END)
    alts = {}
    for sym in ALT_SYMBOLS:
        alts[sym] = load_historical(sym, CTYPE, START, END)
        print(f"  {sym}: {len(alts[sym])} bars")
    print(f"  BTC: {len(btc)} bars")

    # N=8 이벤트 탐지
    events = find_major_bull_events(btc, CONFIRM_N)
    print(f"\nN={CONFIRM_N} 이벤트 수: {len(events)}개")

    # 심볼별 max_bars 그리드 탐색
    print("\n" + "="*70)
    for sym in ALT_SYMBOLS:
        tp, sl = TP_SL[sym]
        alt = alts[sym]
        print(f"\n--- {sym} (TP={tp*100:.0f}%, SL={sl*100:.0f}%) ---")
        print(f"{'max_bars':>10} {'시간':>6} | {'n':>4} {'WR%':>6} {'avg_ret%':>9} {'Sharpe':>8} {'만료율%':>8}")
        print("-" * 60)

        best_sharpe = -999.0
        best_row = None
        for mb in MAX_BARS_LIST:
            r = run_backtest(btc, alt, events, tp=tp, sl=sl, max_bars=mb)
            hours = mb * 4
            sharpe_str = f"{r['sharpe']:+.2f}" if not np.isnan(r['sharpe']) else "  N/A"
            print(
                f"{mb:>10}봉 {hours:>4}h | "
                f"{r['n']:>4} {r['wr']:>6.1f} {r['avg_ret']:>+9.2f}% {sharpe_str:>8} {r['expired_pct']:>7.1f}%"
            )
            if not np.isnan(r['sharpe']) and r['sharpe'] > best_sharpe and r['n'] >= 5:
                best_sharpe = r['sharpe']
                best_row = (mb, r)

        if best_row:
            mb, r = best_row
            print(f"  ★ 최적: max_bars={mb}({mb*4}h) → Sharpe={r['sharpe']:+.2f}, WR={r['wr']:.1f}%")

    print("\n" + "="*70)
    print("분석 완료.")
    print()
    print("비교 기준 (사이클 89, N=8 필터, max_bars=24):")
    print("  SOL: WR≈54.5%")
    print("  ETH: WR≈63.9%")
    print("  XRP: WR≈64.9%")
    print()
    print("참고 (사이클 90, TRX max_bars 최적화):")
    print("  TRX max_bars=24: Sharpe≈+0.14, 만료율≈68%")
    print("  TRX max_bars=48: Sharpe≈+0.36, 만료율≈50%  ← 채택")


if __name__ == "__main__":
    main()
