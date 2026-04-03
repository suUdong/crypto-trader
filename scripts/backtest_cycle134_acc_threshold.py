"""
사이클 134: stealth_3gate acc 임계값 탐색
- 현재: alt acc > 1.0 (고정)
- 탐색: acc_min ∈ {1.0, 1.1, 1.2, 1.5}
- 고정: W=36, SMA=10, RS=[0.4,0.9), TP=10%, SL=1.0%, Gate4=OFF, MAX_HOLD=24
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-04), 슬리피지 0.10%
- 통과 기준: 2/2 창 Sharpe ≥ 5.0, n ≥ 20
- 가설: acc 상향이 신호 품질 강화 → Sharpe 9.941 베이스에서 추가 개선 가능
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

# Fixed params (사이클 129-133 최적값)
W = 36           # stealth_window
SMA_N = 10       # BTC SMA period
RS_LO = 0.4      # RS 하한 (사이클 132 확정)
RS_HI = 0.9      # RS 상한 (사이클 132 확정)
TP = 0.10        # take profit
SL = 0.010       # stop loss
MAX_HOLD = 24    # max hold bars
FEE = 0.001      # 0.10% round-trip

# 탐색 대상 acc 임계값
ACC_CANDIDATES = [1.0, 1.1, 1.2, 1.5]

# Walk-forward windows
WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-04"),
]

MIN_TRADES = 20
SHARPE_PASS = 5.0


# ─── Signal helpers ────────────────────────────────────────────────────────────

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def compute_btc_signal(
    df4h: pd.DataFrame,
    dfday: pd.DataFrame,
) -> pd.Series:
    """Gate 1+2: BTC>SMA10(daily) + BTC stealth(4h, W=36). Gate4=OFF."""
    # Gate 1: BTC > SMA10 (daily)
    day_sma = sma(dfday["close"], SMA_N)
    regime = dfday["close"] > day_sma
    idx = df4h.index.union(regime.index)
    reg4h = regime.reindex(idx).ffill().reindex(df4h.index).fillna(False)

    # Gate 2: BTC stealth accumulation (4h)
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
    acc_min: float,
) -> pd.Series:
    """Gate 3: alt RS∈[RS_LO, RS_HI) + alt acc > acc_min."""
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
    alt_gate = (rs >= RS_LO) & (rs < RS_HI) & (acc_v > acc_min)
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


# ─── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    t0 = time.time()
    print("=== stealth_3gate acc 임계값 탐색 (사이클 134) ===")
    print(f"고정: W={W}, SMA={SMA_N}, RS=[{RS_LO},{RS_HI}), TP={TP*100:.0f}%, SL={SL*100:.1f}%, Gate4=OFF")
    print(f"탐색: alt acc_min ∈ {ACC_CANDIDATES}")
    print(f"WF 창: {WINDOWS}")
    print(f"통과 기준: 2/2 창 Sharpe≥{SHARPE_PASS}, n≥{MIN_TRADES}")

    # Load BTC data
    print("\n[1/3] BTC 데이터 로드...")
    df_btc4h = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    df_btcday = load_historical(BTC_SYMBOL, "day", START, END)
    if df_btc4h is None or df_btcday is None or df_btc4h.empty:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC 4h: {len(df_btc4h)} rows, day: {len(df_btcday)} rows")

    # Compute BTC signal once (Gate4=OFF, fixed)
    btc_sig = compute_btc_signal(df_btc4h, df_btcday)
    print(f"  BTC stealth 활성봉: {int(btc_sig.sum())}")

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

    # Evaluate each acc_min
    print("\n[3/3] acc 임계값 탐색...")
    results = []

    for acc_min in ACC_CANDIDATES:
        label = f"acc>{acc_min:.1f}" + (" 📌 (현재)" if acc_min == 1.0 else "")

        # Compute alt entry signals
        alt_signals: dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
        for sym, df in alt_raw.items():
            entry = compute_alt_entry(df, df_btc4h, btc_sig, acc_min)
            if entry.sum() < 5:
                continue
            alt_signals[sym] = (df["close"].values, entry.values.astype(bool), pd.DatetimeIndex(df.index))

        # Walk-forward evaluation
        window_results: dict[str, dict] = {}
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
            "label": label,
            "acc_min": acc_min,
            "alt_syms": len(alt_signals),
            "w1_sharpe": w1_sh, "w1_n": w1.get("n", 0), "w1_wr": w1.get("wr", float("nan")),
            "w2_sharpe": w2_sh, "w2_n": w2.get("n", 0), "w2_wr": w2.get("wr", float("nan")),
            "passed": passed,
        })

        flag = "✅" if passed else "  "
        print(
            f"\n{flag} {label}"
            f"\n   alt 심볼: {len(alt_signals)}"
            f"\n   W1: Sharpe={w1_sh:.3f}  n={w1.get('n',0):4d}  WR={w1.get('wr', float('nan')):.3f}"
            f"\n   W2: Sharpe={w2_sh:.3f}  n={w2.get('n',0):4d}  WR={w2.get('wr', float('nan')):.3f}"
        )

    # Summary table
    print("\n=== 결과 요약 ===")
    print(f"{'acc_min':<10} {'alt_syms':>9} {'W1 Sharpe':>10} {'W1 n':>6} {'W2 Sharpe':>10} {'W2 n':>6} {'W2 WR':>7} {'통과':>5}")
    print("-" * 75)
    baseline_w2 = None
    best = None
    for r in results:
        flag = "✅" if r["passed"] else "  "
        if r["acc_min"] == 1.0:
            baseline_w2 = r["w2_sharpe"]
        print(
            f"{r['acc_min']:<10.1f} {r['alt_syms']:>9d} "
            f"{r['w1_sharpe']:>10.3f} {r['w1_n']:>6d} "
            f"{r['w2_sharpe']:>10.3f} {r['w2_n']:>6d} "
            f"{r['w2_wr']:>7.3f} {flag:>5}"
        )
        if r["passed"] and (best is None or r["w2_sharpe"] > best["w2_sharpe"]):
            best = r

    # Recommendation
    print("\n=== 권고 ===")
    if best and baseline_w2 is not None:
        delta = best["w2_sharpe"] - baseline_w2
        if best["acc_min"] == 1.0:
            print(f"현재 acc>1.0 유지 — 상향 임계값이 Sharpe를 개선하지 못함")
        elif delta > 0.3:
            print(f"acc_min: 1.0 → {best['acc_min']:.1f} 변경 권장 (W2 Sharpe +{delta:.3f})")
            print(f"  daemon.toml alt_acc_min: 1.0 → {best['acc_min']:.1f}")
        else:
            print(f"acc_min {best['acc_min']:.1f}이 미미하게 우세 (델타 {delta:+.3f}) — 현재 설정 유지")
    else:
        print("통과 후보 없음 — 현재 acc>1.0 유지")

    print(f"\n총 소요: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
