"""
사이클 143: stealth_3gate 신규 심볼 스캔
- 확정 파라미터: TP=5%/SL=1.0% (사이클 141 최적, W2 Sharpe 12.126)
- 고정: W=36, SMA=10, RS=[0.4,0.9), BTC_ACC_MIN=1.2, alt_acc>1.0, MAX_HOLD=24
- 목적: 현재 wallet(AVAX/LINK/APT/XRP/ADA/DOT/ATOM) 외 신규 종목 탐색
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-04)
- 통과 기준: W2 Sharpe ≥ 5.0, n ≥ 10
- 출력: 심볼별 W1/W2 Sharpe 랭킹 (현재 wallet 포함 비교)
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

# 확정 파라미터 (사이클 141)
W = 36
SMA_N = 10
RS_LO = 0.4
RS_HI = 0.9
BTC_ACC_MIN = 1.2
ALT_ACC_MIN = 1.0
MAX_HOLD = 24
TP = 0.05
SL = 0.010
FEE = 0.001  # 0.10% round-trip

WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-04"),
]

# 통과 기준
MIN_TRADES_W2 = 10
SHARPE_PASS = 5.0

# 현재 wallet 심볼 (비교 대상)
CURRENT_WALLET = {"KRW-AVAX", "KRW-LINK", "KRW-APT", "KRW-XRP", "KRW-ADA", "KRW-DOT", "KRW-ATOM"}

# 제외 심볼 (스테이블, BTC 자신)
EXCLUDE = {"KRW-BTC", "KRW-USDT", "KRW-USDC"}


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
            if sym not in EXCLUDE:
                syms.add(sym)
    return sorted(syms)


def main() -> None:
    t0 = time.time()
    print("=== stealth_3gate 신규 심볼 스캔 (사이클 143) ===")
    print(f"파라미터: TP={TP*100:.0f}%, SL={SL*100:.1f}%, W={W}, SMA={SMA_N}")
    print(f"RS=[{RS_LO},{RS_HI}), BTC_ACC_MIN={BTC_ACC_MIN}, alt_acc>{ALT_ACC_MIN}, MAX_HOLD={MAX_HOLD}")
    print(f"WF: {WINDOWS}")
    print(f"통과 기준: W2 Sharpe≥{SHARPE_PASS}, W2 n≥{MIN_TRADES_W2}")
    print(f"현재 wallet: {sorted(CURRENT_WALLET)}")

    # Load BTC data
    print("\n[1/3] BTC 데이터 로드...")
    df_btc4h = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    df_btcday = load_historical(BTC_SYMBOL, "day", START, END)
    if df_btc4h is None or df_btcday is None or df_btc4h.empty:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC 4h: {len(df_btc4h)} rows, day: {len(df_btcday)} rows")

    # Load all alt symbols
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

    # Pre-compute BTC signal
    print("\n[3/3] BTC 신호 계산...")
    btc_sig = compute_btc_signal(df_btc4h, df_btcday)
    print(f"  BTC 활성봉: {int(btc_sig.sum())}")

    # Per-symbol analysis
    print("\n심볼별 walk-forward 분석...")
    results = []
    for sym, df in alt_raw.items():
        entry = compute_alt_entry(df, df_btc4h, btc_sig)
        total_signals = int(entry.sum())
        if total_signals < 3:
            continue

        dates = pd.DatetimeIndex(df.index)
        closes_all = df["close"].values
        entry_all = entry.values.astype(bool)

        window_res: dict[str, dict] = {}
        for wname, wstart, wend in WINDOWS:
            ws = pd.Timestamp(wstart)
            we = pd.Timestamp(wend)
            mask = (dates >= ws) & (dates <= we)
            if mask.sum() < W * 2:
                window_res[wname] = {"n": 0, "sharpe": float("nan"), "wr": float("nan")}
                continue
            rets = run_symbol(closes_all[mask], entry_all[mask])
            n = len(rets)
            if n < 3:
                window_res[wname] = {"n": n, "sharpe": float("nan"), "wr": float("nan")}
            else:
                a = np.array(rets)
                window_res[wname] = {
                    "n": n,
                    "sharpe": sharpe(rets),
                    "wr": float(np.mean(a > 0)),
                }

        w1 = window_res.get("W1", {})
        w2 = window_res.get("W2", {})
        w1_sh = w1.get("sharpe", float("nan"))
        w2_sh = w2.get("sharpe", float("nan"))
        w2_n = w2.get("n", 0)

        passed = (
            not np.isnan(w2_sh) and w2_sh >= SHARPE_PASS
            and w2_n >= MIN_TRADES_W2
        )
        in_wallet = sym in CURRENT_WALLET

        results.append({
            "sym": sym,
            "in_wallet": in_wallet,
            "total_sig": total_signals,
            "W1_sh": w1_sh,
            "W1_n": w1.get("n", 0),
            "W2_sh": w2_sh,
            "W2_n": w2_n,
            "W2_wr": w2.get("wr", float("nan")),
            "pass": passed,
        })

    # Sort by W2 Sharpe
    results.sort(key=lambda x: x["W2_sh"] if not np.isnan(x["W2_sh"]) else -999, reverse=True)

    # Print all results
    print(f"\n총 분석 심볼: {len(results)}개")
    print(f"{'심볼':>14} {'지갑':>4} | {'W1 Sh':>8} {'W1 n':>5} | {'W2 Sh':>8} {'W2 n':>5} {'W2 WR':>7} | 통과")
    print("-" * 78)

    new_candidates = []
    wallet_results = []
    for r in results:
        mark = "✅" if r["pass"] else "  "
        wallet_mark = "★" if r["in_wallet"] else " "
        wr_str = f"{r['W2_wr']*100:.1f}%" if not np.isnan(r["W2_wr"]) else " N/A"
        w1_str = f"{r['W1_sh']:>8.3f}" if not np.isnan(r["W1_sh"]) else "     nan"
        w2_str = f"{r['W2_sh']:>8.3f}" if not np.isnan(r["W2_sh"]) else "     nan"
        print(
            f"{r['sym']:>14} {wallet_mark:>4} | "
            f"{w1_str} {r['W1_n']:>5} | "
            f"{w2_str} {r['W2_n']:>5} {wr_str:>7} | {mark}"
        )
        if r["pass"] and not r["in_wallet"]:
            new_candidates.append(r)
        if r["in_wallet"]:
            wallet_results.append(r)

    # Summary
    print("\n" + "=" * 50)
    print("=== 현재 wallet 심볼 성과 ===")
    if wallet_results:
        wallet_results.sort(key=lambda x: x["W2_sh"] if not np.isnan(x["W2_sh"]) else -999, reverse=True)
        for r in wallet_results:
            mark = "✅" if r["pass"] else "❌"
            w2_str = f"{r['W2_sh']:.3f}" if not np.isnan(r["W2_sh"]) else "nan"
            print(f"  {mark} {r['sym']}: W2 Sharpe {w2_str} (n={r['W2_n']}, WR={r['W2_wr']*100:.1f}%)")
    else:
        print("  (없음)")

    print(f"\n=== 신규 후보 ({len(new_candidates)}개, W2 Sharpe≥{SHARPE_PASS}, n≥{MIN_TRADES_W2}) ===")
    if new_candidates:
        for r in new_candidates:
            w2_str = f"{r['W2_sh']:.3f}" if not np.isnan(r["W2_sh"]) else "nan"
            print(f"  ✅ {r['sym']}: W2 Sharpe {w2_str} (n={r['W2_n']}, WR={r['W2_wr']*100:.1f}%)")
        print(f"\n  daemon.toml symbols 추가 후보:")
        print(f"  {[r['sym'] for r in new_candidates[:5]]}")
    else:
        print("  신규 후보 없음 — 현재 wallet 심볼이 최적")

    print(f"\n소요: {time.time()-t0:.1f}초")

    # Save CSV
    out_csv = _root / "scripts" / "cycle143_symbol_scan_results.csv"
    pd.DataFrame(results).to_csv(out_csv, index=False)
    print(f"결과 저장: {out_csv}")


if __name__ == "__main__":
    main()
