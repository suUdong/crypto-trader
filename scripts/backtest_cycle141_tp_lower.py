"""
사이클 141: stealth_3gate 저TP 탐색 (TP=5%/6%/7%)
- 사이클 140 확정: TP=8%/SL=1.0% → W2 Sharpe 11.204
- 패턴: TP 낮을수록 W2 Sharpe 개선(BEAR 단기수익), 8%>10%>12%>15%
- 탐색: TP ∈ {0.05, 0.06, 0.07} × SL ∈ {0.008, 0.010} (6조합)
- 비교 베이스라인: TP=8%/SL=1.0% (W2 Sharpe 11.204)
- 고정: W=36, SMA=10, RS=[0.4,0.9), BTC_ACC_MIN=1.2, alt_acc>1.0, MAX_HOLD=24
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-04), 슬리피지 0.10%
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

# Fixed params (사이클 129-140 최적값)
W = 36
SMA_N = 10
RS_LO = 0.4
RS_HI = 0.9
BTC_ACC_MIN = 1.2
ALT_ACC_MIN = 1.0
MAX_HOLD = 24
FEE = 0.001  # 0.10% round-trip

# 사이클 140 베이스라인
BASELINE_TP = 0.08
BASELINE_SL = 0.010
BASELINE_W2_SHARPE = 11.204

# 탐색 대상: 저TP 범위 + 비교용 베이스라인 포함
TP_CANDIDATES: list[float] = [0.05, 0.06, 0.07, 0.08]
SL_CANDIDATES: list[float] = [0.008, 0.010]

WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-04"),
]

MIN_TRADES = 20
SHARPE_PASS = 5.0


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def compute_btc_signal(df4h: pd.DataFrame, dfday: pd.DataFrame) -> pd.Series:
    """Gate 1+2: BTC>SMA10(daily) + BTC stealth(4h, W=36, acc>BTC_ACC_MIN)."""
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
    stealth = (ret_w < 1.0) & (acc > BTC_ACC_MIN)

    return (reg4h & stealth).fillna(False)


def compute_alt_entry(
    df_alt: pd.DataFrame,
    df_btc4h: pd.DataFrame,
    btc_sig: pd.Series,
) -> pd.Series:
    """Gate 3: alt RS∈[RS_LO, RS_HI) + alt acc > ALT_ACC_MIN"""
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

    alt_gate = (rs >= RS_LO) & (rs < RS_HI) & (acc_v > ALT_ACC_MIN)
    return (btc_sig.reindex(df_alt.index).fillna(False) & alt_gate.fillna(False))


def run_symbol(closes: np.ndarray, entry: np.ndarray, tp: float, sl: float) -> list[float]:
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
                if r >= tp:
                    ret = tp - FEE
                    i = j + 1
                    break
                if r <= -sl:
                    ret = -sl - FEE
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


def main() -> None:
    t0 = time.time()
    print("=== stealth_3gate 저TP 탐색 (사이클 141) ===")
    print(f"고정: W={W}, SMA={SMA_N}, RS=[{RS_LO},{RS_HI}), BTC_ACC_MIN={BTC_ACC_MIN}, alt_acc>{ALT_ACC_MIN}, MAX_HOLD={MAX_HOLD}")
    print(f"탐색: TP ∈ {[f'{v*100:.0f}%' for v in TP_CANDIDATES]} × SL ∈ {[f'{v*100:.1f}%' for v in SL_CANDIDATES]}")
    print(f"베이스라인: TP={BASELINE_TP*100:.0f}%, SL={BASELINE_SL*100:.1f}%, W2 Sharpe={BASELINE_W2_SHARPE}")
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

    # Load alt symbols
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

    # Pre-compute BTC signal (fixed)
    print("\n[3/3] BTC 신호 계산 (BTC_ACC_MIN=1.2 고정)...")
    btc_sig = compute_btc_signal(df_btc4h, df_btcday)
    print(f"  BTC 활성봉: {int(btc_sig.sum())}")

    # Pre-compute alt entry signals (fixed across all TP/SL)
    print("알트 진입 신호 계산 (TP/SL 무관, 고정)...")
    alt_signals: dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
    for sym, df in alt_raw.items():
        entry = compute_alt_entry(df, df_btc4h, btc_sig)
        if entry.sum() < 5:
            continue
        alt_signals[sym] = (df["close"].values, entry.values.astype(bool), pd.DatetimeIndex(df.index))
    print(f"  유효 알트 심볼: {len(alt_signals)}개")

    # Pre-slice per window (shared across TP/SL)
    sliced: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
    for wname, wstart, wend in WINDOWS:
        ws = pd.Timestamp(wstart)
        we = pd.Timestamp(wend)
        sliced[wname] = {}
        for sym, (closes, entry, dates) in alt_signals.items():
            mask = (dates >= ws) & (dates <= we)
            if mask.sum() < W * 2:
                continue
            sliced[wname][sym] = (closes[mask], entry[mask])

    # Run grid search
    total = len(TP_CANDIDATES) * len(SL_CANDIDATES)
    print(f"\n[그리드 탐색] {total}조합...")
    results = []
    idx_combo = 0

    for tp in TP_CANDIDATES:
        for sl in SL_CANDIDATES:
            idx_combo += 1
            is_baseline = (abs(tp - BASELINE_TP) < 1e-6 and abs(sl - BASELINE_SL) < 1e-6)

            window_results: dict[str, dict] = {}
            for wname, _, _ in WINDOWS:
                all_rets: list[float] = []
                for sym, (closes, entry) in sliced[wname].items():
                    rets = run_symbol(closes, entry, tp, sl)
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
            delta_w2 = w2_sh - BASELINE_W2_SHARPE if not np.isnan(w2_sh) else float("nan")

            row: dict = {
                "TP": f"{tp*100:.0f}%", "SL": f"{sl*100:.1f}%",
                "is_baseline": is_baseline,
                "W1_sh": w1_sh, "W1_n": w1.get("n", 0),
                "W2_sh": w2_sh, "W2_n": w2.get("n", 0), "W2_wr": w2.get("wr", float("nan")),
                "delta_w2": delta_w2, "pass": passed,
            }
            results.append(row)
            flag = "✅" if passed else "  "
            base_mark = " ← 현재" if is_baseline else ""
            delta_str = f" (Δ{delta_w2:+.3f})" if not np.isnan(delta_w2) else ""
            print(
                f"{flag} [{idx_combo:2d}/{total}] TP={tp*100:.0f}%/SL={sl*100:.1f}%{base_mark}"
                f"  W1={w1_sh:.3f}(n={w1.get('n',0)}) W2={w2_sh:.3f}"
                f"(n={w2.get('n',0)},WR={w2.get('wr',float('nan')):.3f}){delta_str}"
            )

    # Sort by W2 Sharpe
    results.sort(key=lambda x: x["W2_sh"] if not np.isnan(x["W2_sh"]) else -999, reverse=True)

    print("\n=== 결과 요약 (W2 Sharpe 내림차순) ===")
    print(f"{'TP':>6} {'SL':>6} | {'W1 Sh':>8} {'W1 n':>6} | {'W2 Sh':>8} {'W2 n':>6} {'W2 WR':>7} | {'ΔW2':>8} | 통과")
    print("-" * 80)
    for r in results:
        mark = "✅" if r["pass"] else "❌"
        w2_wr = r["W2_wr"]
        wr_str = f"{w2_wr*100:.1f}%" if not np.isnan(w2_wr) else "  N/A"
        delta_str = f"{r['delta_w2']:>+8.3f}" if not np.isnan(r["delta_w2"]) else "     nan"
        print(
            f"{r['TP']:>6} {r['SL']:>6} | "
            f"{r['W1_sh']:>8.3f} {r['W1_n']:>6} | "
            f"{r['W2_sh']:>8.3f} {r['W2_n']:>6} {wr_str:>7} | "
            f"{delta_str} | {mark}"
        )

    best = results[0]
    print(f"\n최적: TP={best['TP']}/SL={best['SL']} → W2 Sharpe {best['W2_sh']:.3f} (ΔW2={best['delta_w2']:+.3f})")
    print(f"소요: {time.time()-t0:.1f}초")

    # CSV 저장
    out_csv = _root / "scripts" / "cycle141_tp_lower_results.csv"
    pd.DataFrame(results).to_csv(out_csv, index=False)
    print(f"결과 저장: {out_csv}")


if __name__ == "__main__":
    main()
