"""
사이클 130: stealth_3gate BTC SMA period 최적화
- Gate4=OFF, TP=10%, SL=1.0%, MAX_HOLD=24 고정 (사이클 129 최적값)
- BTC SMA period: [10, 15, 20, 25, 30] 탐색
  (현재 SMA20 고정이며 한번도 최적화되지 않음)
- W=36, RS[0.5,1.0), acc>1.0 고정
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-04)
- 슬리피지: 0.10% (실질, FEE에 포함)
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

# Fixed stealth params (사이클 129 최적값)
W = 36
RS_LO = 0.5
RS_HI = 1.0
TP = 0.10
SL = 0.010
MAX_HOLD = 24
FEE = 0.001  # 0.10% round-trip (슬리피지 포함)

# 탐색: SMA period
SMA_PERIOD_LIST = [10, 15, 20, 25, 30]

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


def compute_btc_signal(df4h: pd.DataFrame, dfday: pd.DataFrame, sma_n: int) -> pd.Series:
    """Gate 1+2: BTC>SMA_N(daily) + BTC stealth accumulation (4h)."""
    day_sma = sma(dfday["close"], sma_n)
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
    """Gate 3: alt RS∈[RS_LO,RS_HI) + alt acc>1."""
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
    alt_gate = (rs >= RS_LO) & (rs < RS_HI) & (acc_v > 1.0)
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
    print("=== stealth_3gate SMA period 최적화 (사이클 130) ===")
    print(f"W={W}, RS=[{RS_LO},{RS_HI}), TP={TP*100:.0f}%, SL={SL*100:.1f}%, MAX_HOLD={MAX_HOLD}")
    print(f"Gate4=OFF (btc_trend_pos_gate=False)")
    print(f"SMA periods: {SMA_PERIOD_LIST}")
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

    # Load alt symbols (common across all SMA periods)
    print("[2/3] 알트 심볼 데이터 로드...")
    symbols = get_krw_symbols()
    alt_raw: dict[str, tuple[pd.DataFrame, np.ndarray]] = {}
    loaded = 0
    for sym in symbols:
        try:
            df = load_historical(sym, INTERVAL, START, END)
            if df is None or df.empty or len(df) < W * 4:
                continue
            alt_raw[sym] = (df, pd.DatetimeIndex(df.index))
            loaded += 1
        except Exception:
            pass
    print(f"  {loaded}개 심볼 로드 완료 ({time.time()-t0:.1f}s)")

    # Grid: SMA period
    print("\n[3/3] SMA period 탐색...")
    results = []

    for sma_n in SMA_PERIOD_LIST:
        # Compute BTC signal for this SMA
        btc_sig = compute_btc_signal(df_btc4h, df_btcday, sma_n)
        btc_active = int(btc_sig.sum())

        # Compute alt entry signals
        alt_signals: dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
        for sym, (df, dates) in alt_raw.items():
            entry = compute_alt_entry(df, df_btc4h, btc_sig)
            if entry.sum() < 5:
                continue
            alt_signals[sym] = (df["close"].values, entry.values.astype(bool), dates)

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
            "sma_n": sma_n,
            "btc_active_bars": btc_active,
            "alt_syms": len(alt_signals),
            "w1_sharpe": w1_sh, "w1_n": w1.get("n", 0), "w1_wr": w1.get("wr", float("nan")),
            "w2_sharpe": w2_sh, "w2_n": w2.get("n", 0), "w2_wr": w2.get("wr", float("nan")),
            "passed": passed,
        })

        flag = "✅" if passed else "  "
        print(
            f"{flag} SMA={sma_n:2d} | BTC활성={btc_active:4d} alt={len(alt_signals):3d} | "
            f"W1={w1_sh:.3f}(n={w1.get('n',0):4d}) W2={w2_sh:.3f}(n={w2.get('n',0):4d}) "
            f"({time.time()-t0:.1f}s)"
        )

    total_time = time.time() - t0
    print(f"\n완료: {total_time:.1f}초")

    # 결과 요약
    passed_list = [r for r in results if r["passed"]]
    print(f"\n=== 통과 조합 (2/2 Sharpe≥{SHARPE_PASS}): {len(passed_list)}/{len(results)} ===")

    print(f"\n=== 전체 결과 (W2 Sharpe 기준 정렬) ===")
    for r in sorted(results, key=lambda x: x.get("w2_sharpe", 0) if not np.isnan(x.get("w2_sharpe", float("nan"))) else 0, reverse=True):
        flag = "✅" if r["passed"] else ("📌" if r["sma_n"] == 20 else "  ")
        print(
            f"{flag} SMA={r['sma_n']:2d} | "
            f"W1={r['w1_sharpe']:.3f}(n={r['w1_n']:4d},wr={r['w1_wr']*100:.1f}%) "
            f"W2={r['w2_sharpe']:.3f}(n={r['w2_n']:4d},wr={r['w2_wr']*100:.1f}%)"
        )

    # Save CSV
    df_res = pd.DataFrame(results)
    out_path = _root / "scripts" / "cycle130_sma_period_results.csv"
    df_res.to_csv(out_path, index=False)
    print(f"\n결과 저장: {out_path}")

    # 결론
    baseline = next((r for r in results if r["sma_n"] == 20), None)
    best = max(results, key=lambda x: x.get("w2_sharpe", 0) if not np.isnan(x.get("w2_sharpe", float("nan"))) else 0)
    if baseline:
        print(f"\n기준선 (SMA=20): W1={baseline['w1_sharpe']:.3f}(n={baseline['w1_n']}) W2={baseline['w2_sharpe']:.3f}(n={baseline['w2_n']})")
    print(f"최우수: SMA={best['sma_n']} W2={best['w2_sharpe']:.3f}(n={best['w2_n']})")

    if best["w2_sharpe"] > (baseline["w2_sharpe"] if baseline else 0) + 0.05:
        print(f"\n→ SMA={best['sma_n']}이 현재(SMA=20)보다 W2 Sharpe {best['w2_sharpe'] - baseline['w2_sharpe']:.3f} 우위")
        print(f"  daemon.toml stealth_sma_period 변경 권장: 20 → {best['sma_n']}")
    else:
        print(f"\n→ SMA=20이 이미 최적 또는 동등 수준 — daemon 변경 불필요")


if __name__ == "__main__":
    main()
