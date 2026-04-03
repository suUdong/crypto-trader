#!/usr/bin/env python3
"""
TRX TP/SL 그리드 탐색 — N=8 major BULL cycle 필터 적용 (사이클 90)

사이클 89 결과:
  N=8 필터 + stealth_3gate → TRX Sharpe +0.21 (TP=12%, SL=3%)
  SOL/ETH/XRP 대비 낮음 → TP/SL 최적화 필요

목표: Sharpe +0.21 → +0.40
그리드:
  TP: [6, 8, 10, 12, 15, 18, 20, 25]%
  SL: [2, 3, 4, 5]%

Usage:
    .venv/bin/python3 scripts/backtest_trx_n8_tpsl.py
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

SYMBOL = "KRW-TRX"
BTC_SYM = "KRW-BTC"

TP_LIST = [0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]
SL_LIST = [0.02, 0.03, 0.04, 0.05]

FORWARD_BARS = 24


def find_major_bull_events(btc: pd.DataFrame, confirm_n: int = CONFIRM_N) -> list[int]:
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


def compute_trx_stealth(
    trx_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    btc_idx: int,
    lb: int = LOOKBACK,
    rw: int = RECENT_W,
    rs_window: int = 20,
) -> bool:
    if btc_idx < max(lb + rw, rs_window):
        return False
    btc_ts = btc_df.index[btc_idx]
    if btc_ts not in trx_df.index:
        return False
    alt_idx = trx_df.index.get_loc(btc_ts)
    if not isinstance(alt_idx, int):
        alt_idx = int(alt_idx)
    if alt_idx < max(lb + rw, rs_window):
        return False

    win = trx_df.iloc[alt_idx - lb: alt_idx]
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

    rs_win_alt = trx_df.iloc[alt_idx - rs_window: alt_idx]["close"].values
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
    max_bars: int = FORWARD_BARS,
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
    trx: pd.DataFrame,
    events: list[int],
    tp: float,
    sl: float,
) -> dict:
    rets: list[float] = []
    exits = {"tp": 0, "sl": 0, "expired": 0}

    for trans_idx in events:
        for fwd in range(0, 7):
            check_idx = trans_idx + fwd
            if check_idx >= len(btc):
                break
            if not compute_trx_stealth(trx, btc, check_idx):
                continue
            btc_ts = btc.index[check_idx]
            if btc_ts not in trx.index:
                continue
            alt_idx = trx.index.get_loc(btc_ts)
            if not isinstance(alt_idx, int):
                alt_idx = int(alt_idx)
            ret, exit_type = sim_tp_sl(trx, alt_idx, tp=tp, sl=sl)
            rets.append(ret)
            exits[exit_type] += 1
            break

    if not rets:
        return {"n": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0,
                "tp_pct": 0.0, "sl_pct": 0.0, "exp_pct": 0.0}

    n = len(rets)
    wr = sum(1 for r in rets if r > 0) / n
    avg = float(np.mean(rets))
    std = float(np.std(rets)) if n > 1 else 0.0
    sharpe = avg / std if std > 0 else 0.0

    return {
        "n": n, "wr": wr, "avg": avg, "sharpe": sharpe,
        "tp_pct": exits["tp"] / n,
        "sl_pct": exits["sl"] / n,
        "exp_pct": exits["expired"] / n,
    }


def main() -> None:
    print(f"Loading BTC {CTYPE} ({START} ~ {END})...")
    btc = load_historical(BTC_SYM, CTYPE, START, END)
    print(f"BTC rows: {len(btc)}")

    print("Loading TRX data...")
    trx = load_historical(SYMBOL, CTYPE, START, END)
    print(f"TRX rows: {len(trx)}")

    events = find_major_bull_events(btc, CONFIRM_N)
    print(f"\nN={CONFIRM_N} major BULL 이벤트: {len(events)}개\n")

    # 베이스라인
    base = run_backtest(btc, trx, events, tp=0.12, sl=0.03)
    print(f"[베이스라인] TP=12%, SL=3%: n={base['n']}, WR={base['wr']*100:.1f}%, "
          f"avg={base['avg']*100:+.2f}%, Sharpe={base['sharpe']:+.2f}")
    print(f"  (TP비율={base['tp_pct']*100:.0f}% / SL비율={base['sl_pct']*100:.0f}% / "
          f"만료={base['exp_pct']*100:.0f}%)")

    # 그리드 탐색
    print(f"\n{'='*72}")
    print(f"{'TP':>6} {'SL':>5} {'n':>5} {'WR%':>6} {'avg_ret':>8} {'Sharpe':>8}  TP%  SL%  Exp%")
    print("-" * 72)

    results = []
    for tp in TP_LIST:
        for sl in SL_LIST:
            r = run_backtest(btc, trx, events, tp=tp, sl=sl)
            r["tp_param"] = tp
            r["sl_param"] = sl
            results.append(r)
            marker = " ◀" if tp == 0.12 and sl == 0.03 else ""
            print(
                f"{tp*100:>5.0f}% {sl*100:>4.0f}% {r['n']:>5} "
                f"{r['wr']*100:>5.1f}% {r['avg']*100:>+7.2f}% {r['sharpe']:>+8.2f}  "
                f"{r['tp_pct']*100:>3.0f}% {r['sl_pct']*100:>3.0f}% {r['exp_pct']*100:>3.0f}%{marker}"
            )

    valid = [r for r in results if r["n"] >= 10]
    if not valid:
        print("\n[경고] 유효 결과(n≥10) 없음")
        return

    best_sh = max(valid, key=lambda x: x["sharpe"])
    best_wr = max(valid, key=lambda x: x["wr"])

    print(f"\n{'='*72}")
    print("최적 요약")
    print(f"{'='*72}")
    print(f"Sharpe 최적: TP={best_sh['tp_param']*100:.0f}%, SL={best_sh['sl_param']*100:.0f}% "
          f"→ n={best_sh['n']}, WR={best_sh['wr']*100:.1f}%, "
          f"avg={best_sh['avg']*100:+.2f}%, Sharpe={best_sh['sharpe']:+.2f}")
    print(f"WR 최적:     TP={best_wr['tp_param']*100:.0f}%, SL={best_wr['sl_param']*100:.0f}% "
          f"→ n={best_wr['n']}, WR={best_wr['wr']*100:.1f}%, "
          f"avg={best_wr['avg']*100:+.2f}%, Sharpe={best_wr['sharpe']:+.2f}")

    print(f"\n베이스라인 대비 Sharpe 개선: {base['sharpe']:+.2f} → {best_sh['sharpe']:+.2f} "
          f"(+{best_sh['sharpe'] - base['sharpe']:.2f})")

    top5 = sorted(valid, key=lambda x: -x["sharpe"])[:5]
    print(f"\nTop-5 Sharpe 후보:")
    for i, r in enumerate(top5, 1):
        print(f"  {i}. TP={r['tp_param']*100:.0f}%, SL={r['sl_param']*100:.0f}% "
              f"→ Sharpe={r['sharpe']:+.2f}, WR={r['wr']*100:.1f}%, n={r['n']}")


if __name__ == "__main__":
    main()


def run_backtest_ext(
    btc: pd.DataFrame,
    trx: pd.DataFrame,
    events: list[int],
    tp: float,
    sl: float,
    max_bars: int,
) -> dict:
    """max_bars 파라미터화 버전."""
    rets: list[float] = []
    exits = {"tp": 0, "sl": 0, "expired": 0}
    for trans_idx in events:
        for fwd in range(0, 7):
            check_idx = trans_idx + fwd
            if check_idx >= len(btc):
                break
            if not compute_trx_stealth(trx, btc, check_idx):
                continue
            btc_ts = btc.index[check_idx]
            if btc_ts not in trx.index:
                continue
            alt_idx = trx.index.get_loc(btc_ts)
            if not isinstance(alt_idx, int):
                alt_idx = int(alt_idx)
            ret, exit_type = sim_tp_sl(trx, alt_idx, tp=tp, sl=sl, max_bars=max_bars)
            rets.append(ret)
            exits[exit_type] += 1
            break
    if not rets:
        return {"n": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0,
                "tp_pct": 0.0, "sl_pct": 0.0, "exp_pct": 0.0}
    n = len(rets)
    wr = sum(1 for r in rets if r > 0) / n
    avg = float(np.mean(rets))
    std = float(np.std(rets)) if n > 1 else 0.0
    sharpe = avg / std if std > 0 else 0.0
    return {"n": n, "wr": wr, "avg": avg, "sharpe": sharpe,
            "tp_pct": exits["tp"] / n, "sl_pct": exits["sl"] / n, "exp_pct": exits["expired"] / n}


if __name__ == "__main_extended__":
    pass
