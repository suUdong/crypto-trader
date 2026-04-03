"""
stealth_3gate TP/SL 그리드 탐색 (사이클 129)

가설: W=36, SMA20, RS[0.5,1.0) 고정 상태에서 TP/SL이 미최적화 → Sharpe 4.682 → 5.0+ 달성?

설정:
  - W=36, SMA20, RS[0.5,1.0), acc>1.0 (daemon 확정 파라미터)
  - Gate 1: BTC > SMA20 (daily)
  - Gate 2: BTC stealth (price declining + vol acc > 1)
  - Gate 3: alt RS∈[0.5,1.0) + alt acc > 1.0
  - TP: [0.08, 0.10, 0.12, 0.15, 0.18, 0.20]
  - SL: [0.015, 0.02, 0.03, 0.04]
  - MAX_HOLD: [24, 36] (×4h = 96h / 144h)
  - Walk-forward: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-04)
  - Sharpe 계산: annualized (×√252, 일거래 기준)

통과 기준: 2/2 창 모두 Sharpe ≥ 5.0, n ≥ 20
"""
from __future__ import annotations

import sys
import time
from itertools import product
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

# Fixed stealth params
W = 36
SMA_N = 20
RS_LO = 0.5
RS_HI = 1.0

# Grid
TP_LIST = [0.08, 0.10, 0.12, 0.15, 0.18, 0.20]
SL_LIST = [0.015, 0.02, 0.03, 0.04]
MAX_HOLD_LIST = [24, 36]

# Walk-forward windows
WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-04"),
]

MIN_TRADES = 20
SHARPE_PASS = 5.0
FEE = 0.001  # 0.10% round-trip


# ─── Signal helpers (vectorized) ──────────────────────────────────────────────

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def compute_btc_signal(df4h: pd.DataFrame, dfday: pd.DataFrame) -> pd.Series:
    """Gate 1+2: BTC regime + BTC stealth accumulation."""
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
    df_alt: pd.DataFrame, df_btc4h: pd.DataFrame, btc_sig: pd.Series
) -> pd.Series:
    """Gate 3: alt RS∈[RS_LO,RS_HI) + alt acc>1 combined with BTC gates."""
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
    acc = ((ac / c_ma.replace(0.0, np.nan)) * (vc / v_ma.replace(0.0, np.nan))).reindex(df_alt.index)
    alt_gate = (rs >= RS_LO) & (rs < RS_HI) & (acc > 1.0)
    return (btc_sig.reindex(df_alt.index).fillna(False) & alt_gate.fillna(False))


# ─── Trade simulation ─────────────────────────────────────────────────────────

def run_symbol(closes: np.ndarray, entry: np.ndarray, tp: float, sl: float, max_hold: int) -> list[float]:
    rets = []
    i = 0
    n = len(closes)
    while i < n - 1:
        if entry[i]:
            bp = closes[i + 1]
            limit = min(i + max_hold + 1, n)
            ret = None
            for j in range(i + 1, limit):
                r = closes[j] / bp - 1
                if r >= tp:
                    ret = tp - FEE
                    i = j + 1
                    break
                if r <= -sl:
                    ret = -sl - FEE
                    i = j + 1
                    break
            if ret is None:
                # max_hold exit
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


# ─── Load symbols ─────────────────────────────────────────────────────────────

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
    print("=== stealth_3gate TP/SL 그리드 탐색 (사이클 129) ===")
    print(f"W={W}, SMA={SMA_N}, RS=[{RS_LO},{RS_HI}), acc>1.0, Fee={FEE*100:.2f}%")
    print(f"TP: {TP_LIST}")
    print(f"SL: {SL_LIST}")
    print(f"MAX_HOLD: {MAX_HOLD_LIST}")
    print(f"WF 창: {[(w, s, e) for w, s, e in WINDOWS]}")

    # Load BTC data
    print("\n[1/3] BTC 데이터 로드...")
    df_btc4h = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    df_btcday = load_historical(BTC_SYMBOL, "day", START, END)
    if df_btc4h is None or df_btcday is None or df_btc4h.empty:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC 4h: {len(df_btc4h)} rows, day: {len(df_btcday)} rows")

    # Compute BTC signal (Gates 1+2)
    btc_sig = compute_btc_signal(df_btc4h, df_btcday)
    print(f"  BTC signal 발생: {btc_sig.sum()} / {len(btc_sig)} 봉")

    # Load alt symbols
    print("[2/3] 알트 심볼 데이터 및 신호 계산...")
    symbols = get_krw_symbols()
    print(f"  총 {len(symbols)}개 심볼 발견")

    # Pre-compute entry signals per symbol
    alt_signals: dict[str, tuple[np.ndarray, np.ndarray]] = {}  # {sym: (closes, entry_bool)}
    loaded = 0
    for sym in symbols:
        try:
            df = load_historical(sym, INTERVAL, START, END)
            if df is None or df.empty or len(df) < W * 4:
                continue
            entry = compute_alt_entry(df, df_btc4h, btc_sig)
            if entry.sum() < 5:
                continue
            alt_signals[sym] = (df["close"].values, entry.values.astype(bool), pd.DatetimeIndex(df.index))
            loaded += 1
        except Exception as e:
            pass
    print(f"  {loaded}개 심볼 신호 계산 완료 ({time.time()-t0:.1f}s)")

    # Grid search
    print("\n[3/3] 그리드 탐색 실행...")
    grid = list(product(TP_LIST, SL_LIST, MAX_HOLD_LIST))
    print(f"  {len(grid)} 조합 × {len(WINDOWS)} 창 = {len(grid)*len(WINDOWS)} 실험")
    print(f"  활성 심볼: {loaded}개")

    results = []
    for idx_combo, (tp, sl, mh) in enumerate(grid):
        window_results = {}
        for wname, wstart, wend in WINDOWS:
            ws = pd.Timestamp(wstart)
            we = pd.Timestamp(wend)
            all_rets: list[float] = []
            for sym, (closes, entry, dates) in alt_signals.items():
                # Filter to window
                mask = (dates >= ws) & (dates <= we)
                if mask.sum() < W * 2:
                    continue
                c_w = closes[mask]
                e_w = entry[mask]
                rets = run_symbol(c_w, e_w, tp, sl, mh)
                all_rets.extend(rets)
            n_trades = len(all_rets)
            if n_trades < MIN_TRADES:
                window_results[wname] = {"n": n_trades, "sharpe": float("nan"), "wr": float("nan"), "avg": float("nan")}
            else:
                a = np.array(all_rets)
                window_results[wname] = {
                    "n": n_trades,
                    "sharpe": sharpe(all_rets),
                    "wr": float(np.mean(a > 0)),
                    "avg": float(np.mean(a)),
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
            "tp": tp, "sl": sl, "max_hold": mh,
            "w1_sharpe": w1_sh, "w1_n": w1.get("n", 0),
            "w1_wr": w1.get("wr", float("nan")),
            "w1_avg": w1.get("avg", float("nan")),
            "w2_sharpe": w2_sh, "w2_n": w2.get("n", 0),
            "w2_wr": w2.get("wr", float("nan")),
            "w2_avg": w2.get("avg", float("nan")),
            "passed": passed,
        })
        if (idx_combo + 1) % 12 == 0:
            print(f"  진행: {idx_combo+1}/{len(grid)} ({time.time()-t0:.0f}s)")

    total_time = time.time() - t0
    print(f"\n완료: {total_time:.1f}초")

    df_res = pd.DataFrame(results)
    passed_df = df_res[df_res["passed"]]
    print(f"\n=== 통과 조합 (W1+W2 모두 Sharpe≥{SHARPE_PASS}, n≥{MIN_TRADES}): {len(passed_df)}개 ===")
    if len(passed_df) > 0:
        print(passed_df.sort_values("w2_sharpe", ascending=False).to_string(index=False))

    print(f"\n=== Top-15 (W2 Sharpe 기준, 기준값 TP=15% SL=3% 포함) ===")
    # Make sure baseline is shown
    baseline = df_res[(df_res["tp"] == 0.15) & (df_res["sl"] == 0.03)]
    top = df_res.sort_values("w2_sharpe", ascending=False).head(15)
    show = pd.concat([top, baseline]).drop_duplicates().sort_values("w2_sharpe", ascending=False)
    for _, row in show.iterrows():
        flag = "✅" if row["passed"] else ("📌" if (row["tp"] == 0.15 and row["sl"] == 0.03) else "  ")
        print(
            f"{flag} TP={row['tp']*100:.0f}% SL={row['sl']*100:.1f}% hold={int(row['max_hold'])} | "
            f"W1: S={row['w1_sharpe']:.3f} n={int(row['w1_n'])} wr={row['w1_wr']*100:.1f}% avg={row['w1_avg']*100:.2f}% | "
            f"W2: S={row['w2_sharpe']:.3f} n={int(row['w2_n'])} wr={row['w2_wr']*100:.1f}% avg={row['w2_avg']*100:.2f}%"
        )

    # Save CSV
    out_path = _root / "scripts" / "cycle129_stealth_tpsl_results.csv"
    df_res.to_csv(out_path, index=False)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
