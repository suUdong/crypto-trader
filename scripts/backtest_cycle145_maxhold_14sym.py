"""
사이클 145: stealth_3gate MAX_HOLD 재탐색 (14심볼, TP=5%, 수정된 엔진 기준)

- 배경: 사이클 138 MAX_HOLD 탐색은 전체 심볼 + TP=10% 기준 → 현재 파라미터와 불일치
  - 사이클 143: 7→14심볼 확장
  - 사이클 141: TP=5%/SL=1.0% 확정
  - 사이클 144-R: ACC=1.0 확정 (수정된 엔진 기준)
- 탐색: MAX_HOLD ∈ {12, 18, 24, 30, 36}봉
- 고정: W=36, SMA=10, RS=[0.4,0.9), TP=5%, SL=1.0%, ACC=1.0
- 14심볼: AVAX/LINK/APT/XRP/ADA/DOT/ATOM/ASTR/CELO/CHZ/IOST/NEO/PEPE/THETA
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-04)
- 현재 기준선: MAX_HOLD=24, W2 Sharpe=13.703 (사이클 144-R, 수정 엔진)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical

INTERVAL = "240m"
BTC_SYMBOL = "KRW-BTC"
START = "2022-01-01"
END = "2026-04-04"

# 사이클 141-144-R 확정 파라미터
W = 36
SMA_N = 10
RS_LO = 0.4
RS_HI = 0.9
TP = 0.05       # 사이클 141 확정 (10%→5%)
SL = 0.010
ACC_MIN = 1.0   # 사이클 144-R 확정
FEE = 0.001

MAX_HOLD_CANDIDATES: list[int] = [12, 18, 24, 30, 36]

WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-04"),
]

# 사이클 143 확정 14심볼
TARGET_SYMBOLS = [
    "KRW-AVAX", "KRW-LINK", "KRW-APT", "KRW-XRP",
    "KRW-ADA", "KRW-DOT", "KRW-ATOM", "KRW-ASTR",
    "KRW-CELO", "KRW-CHZ", "KRW-IOST", "KRW-NEO",
    "KRW-PEPE", "KRW-THETA",
]

MIN_TRADES = 20
SHARPE_PASS = 5.0
BASELINE_W2 = 13.703  # 사이클 144-R 기준선 (MAX_HOLD=24)


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def compute_btc_signal(df4h: pd.DataFrame, dfday: pd.DataFrame) -> pd.Series:
    day_sma = sma(dfday["close"], SMA_N)
    regime = dfday["close"] > day_sma
    idx = df4h.index.union(regime.index)
    reg4h = regime.reindex(idx).ffill().reindex(df4h.index).fillna(False)

    c = df4h["close"]
    v = df4h["volume"]
    c_ma = c.rolling(W, min_periods=W).mean()
    v_ma = v.rolling(W, min_periods=W).mean()
    ret_w = c / c.shift(W)
    acc = (c / c_ma.replace(0.0, np.nan)) * (v / v_ma.replace(0.0, np.nan))
    stealth = (ret_w < 1.0) & (acc > ACC_MIN)

    return (reg4h & stealth).fillna(False)


def compute_alt_entry(
    df_alt: pd.DataFrame, df_btc4h: pd.DataFrame, btc_sig: pd.Series
) -> pd.Series:
    idx = df_alt.index.intersection(df_btc4h.index)
    if len(idx) < W * 2:
        return pd.Series(False, index=df_alt.index)

    ac = df_alt["close"].reindex(idx)
    vc = df_alt["volume"].reindex(idx)
    bc = df_btc4h["close"].reindex(idx)

    alt_ret = ac / ac.shift(W)
    btc_ret = bc / bc.shift(W)
    rs = (alt_ret / btc_ret.replace(0.0, np.nan)).reindex(df_alt.index)

    c_ma = ac.rolling(W, min_periods=W).mean()
    v_ma = vc.rolling(W, min_periods=W).mean()
    acc_v = ((ac / c_ma.replace(0.0, np.nan)) * (vc / v_ma.replace(0.0, np.nan))).reindex(df_alt.index)

    alt_gate = (rs >= RS_LO) & (rs < RS_HI) & (acc_v > ACC_MIN)
    return (btc_sig.reindex(df_alt.index).fillna(False) & alt_gate.fillna(False))


def run_symbol(closes: np.ndarray, entry: np.ndarray, max_hold: int) -> list[float]:
    rets = []
    i = 0
    n = len(closes)
    while i < n - 1:
        if entry[i]:
            bp = closes[i + 1]  # 다음봉 close (next-bar entry)
            limit = min(i + max_hold + 1, n)
            ret = None
            for j in range(i + 1, limit):
                r = closes[j] / bp - 1
                if r >= TP:
                    ret = TP - FEE
                    i = j + 1
                    break
                if r <= -SL:
                    ret = -SL - FEE
                    i = j + 1
                    break
            if ret is None:
                exit_j = min(i + max_hold, n - 1)
                ret = closes[exit_j] / bp - 1 - FEE
                i = exit_j + 1
            rets.append(ret)
        else:
            i += 1
    return rets


def sharpe(rets: list[float]) -> float:
    if len(rets) < 3:
        return float("nan")
    a = np.array(rets)
    std = a.std()
    if std < 1e-9:
        return float("nan")
    return float(a.mean() / std * np.sqrt(252))


def main() -> None:
    t0 = time.time()
    print("=== stealth_3gate MAX_HOLD 재탐색 (사이클 145) ===")
    print(f"14심볼 기준 / TP=5%, SL=1.0%, ACC=1.0 (수정 엔진 기준)")
    print(f"탐색: MAX_HOLD ∈ {MAX_HOLD_CANDIDATES} (4h봉)")
    print(f"기준선: W2 Sharpe={BASELINE_W2} (MAX_HOLD=24, 사이클 144-R)\n")

    print("[1/3] BTC 데이터 로드...")
    df_btc4h = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    df_btcday = load_historical(BTC_SYMBOL, "day", START, END)
    if df_btc4h is None or df_btcday is None or df_btc4h.empty:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC 4h: {len(df_btc4h)}행, day: {len(df_btcday)}행")

    btc_sig = compute_btc_signal(df_btc4h, df_btcday)
    print(f"  BTC stealth 활성봉: {int(btc_sig.sum())}")

    print("[2/3] 14심볼 데이터 로드...")
    alt_data: dict[str, pd.DataFrame] = {}
    for sym in TARGET_SYMBOLS:
        df = load_historical(sym, INTERVAL, START, END)
        if df is not None and not df.empty:
            alt_data[sym] = df
            print(f"  {sym}: {len(df)}행")
        else:
            print(f"  {sym}: ⚠ 데이터 없음")
    print(f"  유효 심볼: {len(alt_data)}개")

    # Pre-compute alt entry signals
    alt_signals: dict[str, pd.Series] = {}
    for sym, df in alt_data.items():
        sig = compute_alt_entry(df, df_btc4h, btc_sig)
        if sig.sum() > 0:
            alt_signals[sym] = sig

    print(f"  진입 신호 있는 심볼: {len(alt_signals)}개\n")

    print("[3/3] MAX_HOLD 탐색...")
    results = []
    for max_hold in MAX_HOLD_CANDIDATES:
        hold_days = max_hold * 4 / 24
        all_rets: dict[str, list[float]] = {"W1": [], "W2": []}

        for win_name, w_start, w_end in WINDOWS:
            ws = pd.Timestamp(w_start)
            we = pd.Timestamp(w_end)
            for sym, sig in alt_signals.items():
                df = alt_data[sym]
                mask = (df.index >= ws) & (df.index <= we)
                sig_mask = sig.reindex(df.index).fillna(False) & mask
                closes = df["close"].values
                entry = sig_mask.values
                rets = run_symbol(closes, entry, max_hold)
                all_rets[win_name].extend(rets)

        w1_sh = sharpe(all_rets["W1"])
        w2_sh = sharpe(all_rets["W2"])
        w1 = {
            "n": len(all_rets["W1"]),
            "wr": np.mean([r > 0 for r in all_rets["W1"]]) if all_rets["W1"] else float("nan"),
            "avg": np.mean(all_rets["W1"]) * 100 if all_rets["W1"] else float("nan"),
        }
        w2 = {
            "n": len(all_rets["W2"]),
            "wr": np.mean([r > 0 for r in all_rets["W2"]]) if all_rets["W2"] else float("nan"),
            "avg": np.mean(all_rets["W2"]) * 100 if all_rets["W2"] else float("nan"),
        }
        passed = (
            not np.isnan(w1_sh) and w1_sh >= SHARPE_PASS
            and not np.isnan(w2_sh) and w2_sh >= SHARPE_PASS
            and w2["n"] >= MIN_TRADES
        )
        current = " ← 현재" if max_hold == 24 else ""
        flag = "✅" if passed else "  "
        results.append({
            "max_hold": max_hold, "hold_days": hold_days,
            "w1_sharpe": w1_sh, "w1_n": w1["n"], "w1_wr": w1["wr"], "w1_avg": w1["avg"],
            "w2_sharpe": w2_sh, "w2_n": w2["n"], "w2_wr": w2["wr"], "w2_avg": w2["avg"],
            "passed": passed,
        })
        delta = w2_sh - BASELINE_W2 if not np.isnan(w2_sh) else float("nan")
        print(
            f"{flag} MAX_HOLD={max_hold}봉 ({hold_days:.1f}일){current}"
            f"  W1: Sh={w1_sh:.3f} n={w1['n']} WR={w1['wr']:.1%}  "
            f"W2: Sh={w2_sh:.3f} n={w2['n']} WR={w2['wr']:.1%} avg={w2['avg']:.2f}%"
            f"  ΔW2={delta:+.3f}"
        )

    print("\n=== 결과 요약 ===")
    print(f"{'MAX_HOLD':<12} {'W1 Sh':>8} {'W1 n':>6} {'W1 WR':>7} "
          f"{'W2 Sh':>8} {'W2 n':>6} {'W2 WR':>7} {'W2 avg%':>8} {'ΔW2':>8} {'통과':>5}")
    print("-" * 85)
    best = None
    for r in results:
        flag = "✅" if r["passed"] else "  "
        cur = "*" if r["max_hold"] == 24 else " "
        delta = r["w2_sharpe"] - BASELINE_W2
        print(
            f"{cur}{r['max_hold']}봉({r['hold_days']:.1f}일){'':<4}"
            f"{r['w1_sharpe']:>8.3f} {r['w1_n']:>6d} {r['w1_wr']:>7.1%} "
            f"{r['w2_sharpe']:>8.3f} {r['w2_n']:>6d} {r['w2_wr']:>7.1%} {r['w2_avg']:>8.2f}"
            f"  {delta:>+7.3f}  {flag}"
        )
        if r["passed"] and (best is None or r["w2_sharpe"] > best["w2_sharpe"]):
            best = r

    print(f"\n기준선: MAX_HOLD=24, W2 Sharpe={BASELINE_W2}")
    if best is not None and best["max_hold"] != 24:
        delta = best["w2_sharpe"] - BASELINE_W2
        if delta > 0.1:
            print(f"✅ 채택 권장: MAX_HOLD={best['max_hold']}봉 (W2 Sharpe {delta:+.3f})")
            print(f"   daemon.toml: max_holding_bars={best['max_hold']}")
        else:
            print(f"미미한 개선 (Δ{delta:+.3f}) — MAX_HOLD=24 유지")
    elif best and best["max_hold"] == 24:
        print("현재 MAX_HOLD=24 최적 확인 — 변경 불필요")
    else:
        print("통과 후보 없음")

    print(f"\n총 소요: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
