#!/usr/bin/env python3
"""
TRX N 필터 그리드 탐색 (사이클 96)

목적:
  사이클 93에서 TRX N=12 Sharpe=+0.41로 다른 심볼(SOL +0.76, ETH +0.78, XRP +0.53) 대비 낮음.
  TRX에서 최적 N값을 N=[4,6,8,10,12,16,20] 전 범위에서 탐색.
  btc_trend_pos 필터 on/off 비교 (사이클 94-95 검증 완료).

설정:
  심볼: KRW-TRX 단독
  캔들: 240m(4h), 2022-01 ~ 2026-04
  기준: 4개 심볼 확정 TP=12%, SL=3%

Usage:
    .venv/bin/python3 scripts/backtest_trx_n_grid.py
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

# ── Config ────────────────────────────────────────────────────────────────────
CTYPE      = "240m"
START      = "2022-01-01"
END        = "2026-04-03"
SMA_WINDOW = 20
LOOKBACK   = 12
RECENT_W   = 4
RS_WINDOW  = 20
TREND_W    = 10   # btc_trend_pos: 10봉 수익률 > 0

TP  = 0.12
SL  = 0.03
MAX_BARS = 24   # 최대 보유봉 (96h)

N_LIST = [0, 4, 6, 8, 10, 12, 16, 20]


# ── Signal Functions ──────────────────────────────────────────────────────────

def compute_stealth(
    trx: pd.DataFrame,
    btc: pd.DataFrame,
    btc_idx: int,
) -> bool:
    """TRX stealth_3gate 신호 (accumulation + cvd + rs)."""
    if btc_idx < max(LOOKBACK + RECENT_W, RS_WINDOW):
        return False
    btc_ts = btc.index[btc_idx]
    if btc_ts not in trx.index:
        return False
    alt_idx = trx.index.get_loc(btc_ts)
    if not isinstance(alt_idx, int):
        alt_idx = int(alt_idx)
    if alt_idx < max(LOOKBACK + RECENT_W, RS_WINDOW):
        return False

    win     = trx.iloc[alt_idx - LOOKBACK: alt_idx]
    btc_win = btc.iloc[btc_idx - LOOKBACK: btc_idx]
    if len(win) < LOOKBACK or len(btc_win) < LOOKBACK:
        return False

    c = win["close"].values
    o = win["open"].values
    h = win["high"].values
    lv = win["low"].values
    v = win["volume"].values

    raw_ret  = float(c[-1]) / max(float(c[0]), 1e-9) - 1.0
    rng      = np.clip(h - lv, 1e-9, None)
    vpin     = np.abs(c - o) / rng
    acc      = vpin[-RECENT_W:].mean() / max(vpin[:-RECENT_W].mean(), 1e-9)
    sign_vol = np.where(c >= o, v, -v)
    cvd_slope = float(np.sum(sign_vol[-RECENT_W:])) / max(abs(float(np.sum(sign_vol))), 1e-9)

    rs_alt   = trx.iloc[alt_idx - RS_WINDOW: alt_idx]["close"].values
    rs_btc   = btc.iloc[btc_idx - RS_WINDOW: btc_idx]["close"].values
    alt_chg  = float(rs_alt[-1]) / max(float(rs_alt[0]), 1e-9) - 1.0
    btc_chg  = float(rs_btc[-1]) / max(float(rs_btc[0]), 1e-9) - 1.0
    rs = (1.0 + alt_chg) / max(1.0 + btc_chg, 1e-9) if btc_chg > -1 else 0.0

    return bool((raw_ret < 0.0) and (acc > 1.0) and (cvd_slope > 0.0) and (0.5 <= rs < 1.0))


def sim_tp_sl(
    df: pd.DataFrame,
    entry_idx: int,
    tp: float = TP,
    sl: float = SL,
    max_bars: int = MAX_BARS,
) -> tuple[float, str]:
    if entry_idx >= len(df) - 1:
        return 0.0, "expired"
    ep = df["close"].iloc[entry_idx]
    tp_p = ep * (1 + tp)
    sl_p = ep * (1 - sl)
    for i in range(entry_idx + 1, min(entry_idx + max_bars + 1, len(df))):
        if df["low"].iloc[i] <= sl_p:
            return -sl, "sl"
        if df["high"].iloc[i] >= tp_p:
            return tp, "tp"
    final = df["close"].iloc[min(entry_idx + max_bars, len(df) - 1)]
    return final / ep - 1.0, "expired"


def run_trx_backtest(
    btc: pd.DataFrame,
    trx: pd.DataFrame,
    events: list[int],
    label: str,
) -> dict:
    """이벤트 리스트에서 TRX stealth 진입 시뮬레이션."""
    rets: list[float] = []
    tp_cnt = sl_cnt = exp_cnt = 0

    for trans_idx in events:
        entered = False
        for fwd in range(7):
            check_idx = trans_idx + fwd
            if check_idx >= len(btc):
                break
            if entered:
                break
            btc_ts = btc.index[check_idx]
            if btc_ts not in trx.index:
                continue
            alt_idx = trx.index.get_loc(btc_ts)
            if not isinstance(alt_idx, int):
                alt_idx = int(alt_idx)
            if not compute_stealth(trx, btc, check_idx):
                continue
            ret, exit_type = sim_tp_sl(trx, alt_idx)
            rets.append(ret)
            if exit_type == "tp":
                tp_cnt += 1
            elif exit_type == "sl":
                sl_cnt += 1
            else:
                exp_cnt += 1
            entered = True

    if not rets:
        return {"label": label, "events": len(events), "n": 0,
                "wr": 0.0, "avg": 0.0, "sharpe": 0.0}

    wr  = sum(1 for r in rets if r > 0) / len(rets)
    avg = float(np.mean(rets))
    std = float(np.std(rets)) if len(rets) > 1 else 0.0
    sh  = avg / std if std > 0 else 0.0
    return {
        "label":  label,
        "events": len(events),
        "n":      len(rets),
        "wr":     wr,
        "avg":    avg,
        "sharpe": sh,
        "tp":     tp_cnt,
        "sl":     sl_cnt,
        "exp":    exp_cnt,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 68)
    print("TRX N 필터 그리드 탐색 (사이클 96)")
    print(f"목적: N=[{N_LIST}] × btc_trend_pos on/off → 최적 N 확정")
    print("=" * 68)

    print(f"\nLoading BTC {CTYPE} ({START} ~ {END})...")
    btc = load_historical("KRW-BTC", CTYPE, START, END)
    print(f"BTC rows: {len(btc)}")

    print("Loading TRX...")
    trx = load_historical("KRW-TRX", CTYPE, START, END)
    print(f"TRX rows: {len(trx)}")

    # SMA20 + btc_trend_pos
    btc["sma20"]      = btc["close"].rolling(SMA_WINDOW).mean()
    btc["above_sma"]  = btc["close"] > btc["sma20"]
    trend_ret         = btc["close"] / btc["close"].shift(TREND_W) - 1.0
    btc["trend_pos"]  = (trend_ret > 0).astype(float)

    min_idx = SMA_WINDOW + LOOKBACK + RECENT_W + max(N_LIST) + TREND_W

    # SMA20 최초 돌파 이벤트
    raw_transitions: list[int] = []
    for i in range(min_idx, len(btc) - max(N_LIST) - 30):
        if not btc["above_sma"].iloc[i - 1] and btc["above_sma"].iloc[i]:
            raw_transitions.append(i)

    print(f"\nSMA20 최초 돌파 이벤트 총 {len(raw_transitions)}개")

    # N 필터별 이벤트 생성 (btc_trend_pos off)
    filtered_base: dict[int, list[int]] = {}
    for n in N_LIST:
        if n == 0:
            filtered_base[0] = raw_transitions
            continue
        filt = []
        for idx in raw_transitions:
            if idx + n >= len(btc):
                continue
            if all(btc["above_sma"].iloc[idx + k] for k in range(1, n + 1)):
                filt.append(idx)
        filtered_base[n] = filt

    # N 필터별 이벤트 생성 (btc_trend_pos on)
    filtered_trend: dict[int, list[int]] = {}
    for n in N_LIST:
        base = filtered_base[n]
        filt = []
        for idx in base:
            if idx < TREND_W:
                continue
            if btc["trend_pos"].iloc[idx] == 1.0:
                filt.append(idx)
        filtered_trend[n] = filt

    print("\n=== 이벤트 수 (N 필터 × btc_trend_pos) ===")
    print(f"{'N':>4} {'base 이벤트':>12} {'+ trend_pos':>12}")
    print("-" * 32)
    for n in N_LIST:
        print(f"N={n:>2} {len(filtered_base[n]):>12} {len(filtered_trend[n]):>12}")

    # ── 백테스트 실행 ─────────────────────────────────────────────────────────
    print("\n=== TRX 백테스트 결과 (N 필터 only) ===")
    print(f"{'필터':30s} {'이벤트':>6} {'진입':>5} {'WR%':>6} {'avg%':>7} {'Sharpe':>8}")
    print("-" * 66)

    results_base  = []
    results_trend = []

    for n in N_LIST:
        evts  = filtered_base[n]
        label = f"N={n} ({n*4}h)" if n > 0 else "기준선 (N=0)"
        r = run_trx_backtest(btc, trx, evts, label)
        results_base.append(r)
        print(
            f"{r['label']:30s} {r['events']:>6} {r['n']:>5} "
            f"{r['wr']*100:>5.1f}% {r['avg']*100:>+6.2f}% {r['sharpe']:>+8.2f}"
        )

    print("\n=== TRX 백테스트 결과 (N 필터 + btc_trend_pos) ===")
    print(f"{'필터':35s} {'이벤트':>6} {'진입':>5} {'WR%':>6} {'avg%':>7} {'Sharpe':>8}")
    print("-" * 71)

    best_sh = -999.0
    best_r  = None
    for n in N_LIST:
        evts  = filtered_trend[n]
        label = f"N={n}+trend ({n*4}h)" if n > 0 else "기준선+trend"
        r = run_trx_backtest(btc, trx, evts, label)
        results_trend.append(r)
        marker = " ★" if n in (8, 12) else ""
        print(
            f"{r['label']:35s} {r['events']:>6} {r['n']:>5} "
            f"{r['wr']*100:>5.1f}% {r['avg']*100:>+6.2f}% {r['sharpe']:>+8.2f}{marker}"
        )
        if r["n"] >= 10 and r["sharpe"] > best_sh:
            best_sh = r["sharpe"]
            best_r  = r

    # ── 비교 요약 ─────────────────────────────────────────────────────────────
    print("\n=== N=8 vs N=12 직접 비교 (TRX) ===")
    for n in (8, 12):
        rb = next(r for r in results_base if r["label"].startswith(f"N={n}"))
        rt = next(r for r in results_trend if r["label"].startswith(f"N={n}+"))
        print(f"N={n} base:  n={rb['n']:3d}, WR={rb['wr']*100:.1f}%, Sharpe={rb['sharpe']:+.2f}")
        print(f"N={n}+trend: n={rt['n']:3d}, WR={rt['wr']*100:.1f}%, Sharpe={rt['sharpe']:+.2f}  (Δ={rt['sharpe']-rb['sharpe']:+.2f})")
        print()

    if best_r:
        print(f"★ 최우수 (n≥10): {best_r['label']}")
        print(f"  진입={best_r['n']}, WR={best_r['wr']*100:.1f}%, avg={best_r['avg']*100:+.2f}%, Sharpe={best_r['sharpe']:+.2f}")


if __name__ == "__main__":
    main()
