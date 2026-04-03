"""
사이클 132: stealth_3gate RS 범위 최적화
- SMA=10, W=36, Gate4=OFF, TP=10%, SL=1.0%, MAX_HOLD=24 고정 (사이클 130/131 최적값)
- RS 범위 [RS_LO, RS_HI) 탐색: alt/BTC 상대강도 비율
  현재 [0.5, 1.0): 너무 약하지도 너무 강하지도 않은 종목
  → 다른 범위에서 더 나은 엣지 존재 여부 검증
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-04)
- 슬리피지: 0.10%
- 통과 기준: 2/2 창 Sharpe ≥ 5.0, n ≥ 20
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

# Fixed params (사이클 130/131 최적값)
W = 36           # stealth_window (사이클 131 확정)
SMA_N = 10       # SMA period (사이클 130 확정)
TP = 0.10        # take profit (사이클 129 확정)
SL = 0.010       # stop loss (사이클 129 확정)
MAX_HOLD = 24    # max hold bars
FEE = 0.001      # 0.10% round-trip

# 탐색: RS 범위 (RS_LO, RS_HI)
# RS = alt_ret_W / btc_ret_W (W봉 수익률 비율)
# 현재: [0.5, 1.0) = BTC 대비 50~100% 수익률 종목
RS_RANGES = [
    (0.5, 1.0),   # 현재 baseline
    (0.3, 1.0),   # 하한 완화 (더 약한 종목 포함)
    (0.4, 1.0),   # 하한 소폭 완화
    (0.6, 1.0),   # 하한 강화 (더 강한 종목만)
    (0.5, 1.5),   # 상한 완화 (일부 아웃퍼포머 포함)
    (0.5, 2.0),   # 상한 크게 완화
    (0.5, float("inf")),  # 상한 제거 (RS_LO만 적용)
    (0.3, 1.5),   # 양방향 완화
    (0.4, 0.9),   # 양방향 약간 타이트
    (0.6, 1.2),   # 중간 범위
    (0.0, 1.0),   # 하한 제거 (RS_HI만 적용)
    (0.0, float("inf")),  # RS 필터 없음 (pure acc>1.0만)
]

# Walk-forward windows
WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-04"),
]

MIN_TRADES = 20
SHARPE_PASS = 5.0


# ─── Signal helpers ───────────────────────────────────────────────────────────

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def compute_btc_signal(df4h: pd.DataFrame, dfday: pd.DataFrame) -> pd.Series:
    """Gate 1+2: BTC>SMA10(daily) + BTC stealth accumulation (4h, W=36)."""
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
    stealth = (ret_w < 1.0) & (acc > 1.0)
    return (reg4h & stealth).fillna(False)


def compute_alt_entry(
    df_alt: pd.DataFrame,
    df_btc4h: pd.DataFrame,
    btc_sig: pd.Series,
    rs_lo: float,
    rs_hi: float,
) -> pd.Series:
    """Gate 3: alt RS∈[rs_lo, rs_hi) + alt acc>1."""
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
    alt_gate = (rs >= rs_lo) & (rs < rs_hi) & (acc_v > 1.0)
    return (btc_sig.reindex(df_alt.index).fillna(False) & alt_gate.fillna(False))


def run_symbol(closes: np.ndarray, entry: np.ndarray) -> list[float]:
    rets = []
    i = 0
    n = len(closes)
    while i < n - 1:
        if entry[i]:
            bp = closes[i + 1]
            limit = min(i + MAX_HOLD + 1, n)
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
                exit_j = min(i + MAX_HOLD, n - 1)
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


def get_krw_symbols() -> list[str]:
    base = _root / "data" / "historical" / "monthly" / INTERVAL
    syms = set()
    for year_dir in base.iterdir():
        if not year_dir.is_dir():
            continue
        for f in year_dir.glob("KRW-*.zip"):
            sym = f.name.split("_")[0]
            if sym != BTC_SYMBOL:
                syms.add(sym)
    return sorted(syms)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    t0 = time.time()
    print("=== stealth_3gate RS 범위 최적화 (사이클 132) ===")
    print(f"고정: W={W}, SMA={SMA_N}, TP={TP*100:.0f}%, SL={SL*100:.1f}%, MAX_HOLD={MAX_HOLD}, Gate4=OFF")
    print(f"탐색: RS 범위 {len(RS_RANGES)}개 조합")
    print(f"WF 창: {[(w, s, e) for w, s, e in WINDOWS]}")
    print(f"통과 기준: 2/2 창 Sharpe≥{SHARPE_PASS}, n≥{MIN_TRADES}")

    # Load BTC data
    print("\n[1/3] BTC 데이터 로드...")
    df_btc4h = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    df_btcday = load_historical(BTC_SYMBOL, "day", START, END)
    if df_btc4h is None or df_btcday is None or df_btc4h.empty:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC 4h: {len(df_btc4h)} rows, day: {len(df_btcday)} rows")

    # Compute BTC signal once (fixed W=36, SMA=10)
    btc_sig = compute_btc_signal(df_btc4h, df_btcday)
    btc_active = int(btc_sig.sum())
    print(f"  BTC stealth 활성봉: {btc_active}개")

    # Load all alt symbols once
    print("[2/3] 알트 심볼 데이터 로드...")
    symbols = get_krw_symbols()
    alt_raw: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = load_historical(sym, INTERVAL, START, END)
            if df is None or df.empty or len(df) < W * 4:
                continue
            alt_raw[sym] = df
        except Exception:
            pass
    print(f"  {len(alt_raw)}개 심볼 로드 완료 ({time.time()-t0:.1f}s)")

    # Grid: RS 범위 탐색
    print("\n[3/3] RS 범위 탐색...")
    results = []

    for rs_lo, rs_hi in RS_RANGES:
        rs_hi_str = f"{rs_hi:.1f}" if rs_hi != float("inf") else "∞"
        range_label = f"[{rs_lo},{rs_hi_str})"
        baseline_mark = " 📌(현재)" if (rs_lo, rs_hi) == (0.5, 1.0) else ""

        # Compute alt entry signals for this RS range
        alt_signals: dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
        for sym, df in alt_raw.items():
            entry = compute_alt_entry(df, df_btc4h, btc_sig, rs_lo, rs_hi)
            if entry.sum() < 5:
                continue
            alt_signals[sym] = (df["close"].values, entry.values.astype(bool), pd.DatetimeIndex(df.index))

        # Walk-forward evaluation
        window_results = {}
        for wname, wstart, wend in WINDOWS:
            ws = pd.Timestamp(wstart)
            we = pd.Timestamp(wend)
            all_rets: list[float] = []
            for sym, (closes, entry, dates) in alt_signals.items():
                mask = (dates >= ws) & (dates <= we)
                if mask.sum() < W * 2:
                    continue
                rets = run_symbol(closes[mask], entry[mask])
                all_rets.extend(rets)
            n_trades = len(all_rets)
            if n_trades < MIN_TRADES:
                window_results[wname] = {"n": n_trades, "sharpe": float("nan"), "wr": float("nan")}
            else:
                a = np.array(all_rets)
                window_results[wname] = {
                    "n": n_trades,
                    "sharpe": sharpe(all_rets),
                    "wr": float(np.mean(a > 0)),
                }

        w1 = window_results.get("W1", {})
        w2 = window_results.get("W2", {})
        w1_sh = w1.get("sharpe", float("nan"))
        w2_sh = w2.get("sharpe", float("nan"))
        passed = (
            not np.isnan(w1_sh) and w1_sh >= SHARPE_PASS
            and not np.isnan(w2_sh) and w2_sh >= SHARPE_PASS
        )
        results.append({
            "rs_lo": rs_lo,
            "rs_hi": rs_hi,
            "range_label": range_label,
            "alt_syms": len(alt_signals),
            "w1_sharpe": w1_sh, "w1_n": w1.get("n", 0), "w1_wr": w1.get("wr", float("nan")),
            "w2_sharpe": w2_sh, "w2_n": w2.get("n", 0), "w2_wr": w2.get("wr", float("nan")),
            "passed": passed,
        })

        flag = "✅" if passed else "  "
        print(
            f"{flag} RS{range_label}{baseline_mark} | alt={len(alt_signals):3d} | "
            f"W1={w1_sh:.3f}(n={w1.get('n',0):4d}) W2={w2_sh:.3f}(n={w2.get('n',0):4d}) "
            f"WR={w2.get('wr', float('nan')):.3f}"
        )

    # Summary
    print("\n=== 결과 요약 (W2 Sharpe 내림차순) ===")
    passed_only = [r for r in results if r["passed"]]
    all_sorted = sorted(results, key=lambda x: x["w2_sharpe"] if not np.isnan(x["w2_sharpe"]) else -999, reverse=True)

    for r in all_sorted:
        flag = "✅" if r["passed"] else "  "
        baseline_mark = " 📌(현재)" if (r["rs_lo"], r["rs_hi"]) == (0.5, 1.0) else ""
        print(
            f"{flag} RS{r['range_label']}{baseline_mark} → "
            f"W2 Sharpe={r['w2_sharpe']:.3f} (W1={r['w1_sharpe']:.3f}) "
            f"alt={r['alt_syms']} n={r['w2_n']}"
        )

    print(f"\n통과: {len(passed_only)}/{len(results)}개")
    if passed_only:
        best = max(passed_only, key=lambda x: x["w2_sharpe"])
        print(f"최우수: RS{best['range_label']} W2 Sharpe={best['w2_sharpe']:.3f}")
        baseline = next((r for r in results if (r["rs_lo"], r["rs_hi"]) == (0.5, 1.0)), None)
        if baseline:
            delta = best["w2_sharpe"] - baseline["w2_sharpe"]
            print(f"기준 대비 개선: {delta:+.3f} (기준 W2={baseline['w2_sharpe']:.3f})")

    print(f"\n총 소요: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
