"""
사이클 163: stealth_3gate 심볼 확장 스캔 (corrected engine, BTC_ACC_MIN=1.0)
- 확정 파라미터: TP=5%/SL=1.0% (c149 검증), W=36, SMA=10, RS=[0.4,0.9)
- BTC_ACC_MIN=1.0 (c144 재검증 결과), alt_acc>1.0, MAX_HOLD=24
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-05)
- 목적: c143은 편향 엔진 결과 → corrected 엔진으로 14→20+ 심볼 확장 재스캔
- 슬리피지 0.10% 포함 (왕복)
- 통과 기준: W2 Sharpe ≥ 5.0, W2 n ≥ 10
- 포트폴리오 수준 분석: 현재 14개 vs 확장 세트 비교
"""
from __future__ import annotations

import json
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
END = "2026-04-05"

# 확정 파라미터 (c144/c149 검증)
W = 36
SMA_N = 10
RS_LO = 0.4
RS_HI = 0.9
BTC_ACC_MIN = 1.0   # c144 재검증: 1.2→1.0
ALT_ACC_MIN = 1.0
MAX_HOLD = 24
TP = 0.05
SL = 0.010
SLIPPAGE = 0.001     # 0.10% round-trip
FEE = 0.001          # 0.10% round-trip

WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-05"),
]

# 통과 기준
MIN_TRADES_W2 = 10
SHARPE_PASS = 5.0

# 현재 daemon 14 심볼
CURRENT_WALLET = {
    "KRW-AVAX", "KRW-LINK", "KRW-APT", "KRW-XRP", "KRW-ADA",
    "KRW-DOT", "KRW-ATOM", "KRW-ASTR", "KRW-CELO", "KRW-CHZ",
    "KRW-IOST", "KRW-NEO", "KRW-PEPE", "KRW-THETA",
}

# 제외 심볼
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
    acc_v = (
        (ac / c_ma.replace(0.0, np.nan)) * (vc / v_ma.replace(0.0, np.nan))
    ).reindex(df_alt.index)

    alt_gate = (rs >= RS_LO) & (rs < RS_HI) & (acc_v > ALT_ACC_MIN)
    return btc_sig.reindex(df_alt.index).fillna(False) & alt_gate.fillna(False)


def run_symbol(
    closes: np.ndarray, entry: np.ndarray
) -> list[tuple[float, int]]:
    """Returns list of (return, bar_index) tuples."""
    trades: list[tuple[float, int]] = []
    i = 0
    n = len(closes)
    while i < n - 1:
        if entry[i]:
            bp = closes[i + 1]  # next bar open = next bar's close approx
            bp_slip = bp * (1 + SLIPPAGE / 2)  # buy slippage
            limit = min(i + MAX_HOLD + 1, n)
            ret = None
            for j in range(i + 2, limit):
                r = closes[j] / bp_slip - 1
                if r >= TP:
                    ret = TP - FEE - SLIPPAGE
                    trades.append((ret, i))
                    i = j + 1
                    break
                if r <= -SL:
                    ret = -SL - FEE - SLIPPAGE
                    trades.append((ret, i))
                    i = j + 1
                    break
            if ret is None:
                exit_j = min(i + MAX_HOLD, n - 1)
                ret = closes[exit_j] / bp_slip - 1 - FEE - SLIPPAGE
                trades.append((ret, i))
                i = exit_j + 1
        else:
            i += 1
    return trades


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


def compute_btc_corr(
    df_alt: pd.DataFrame, df_btc: pd.DataFrame, window: str = "W2"
) -> float:
    """30-day rolling return correlation with BTC during W2."""
    ws = pd.Timestamp(WINDOWS[1][1])
    we = pd.Timestamp(WINDOWS[1][2])
    common = df_alt.index.intersection(df_btc.index)
    common = common[(common >= ws) & (common <= we)]
    if len(common) < 60:
        return float("nan")
    alt_r = df_alt["close"].reindex(common).pct_change(6)  # ~24h return
    btc_r = df_btc["close"].reindex(common).pct_change(6)
    corr = alt_r.corr(btc_r)
    return float(corr) if not np.isnan(corr) else float("nan")


def main() -> None:
    t0 = time.time()
    print("=" * 70)
    print("=== c163: stealth_3gate 심볼 확장 스캔 (corrected engine) ===")
    print("=" * 70)
    print(f"파라미터: TP={TP*100:.0f}%, SL={SL*100:.1f}%, W={W}, SMA={SMA_N}")
    print(f"RS=[{RS_LO},{RS_HI}), BTC_ACC_MIN={BTC_ACC_MIN}, MAX_HOLD={MAX_HOLD}")
    print(f"슬리피지: {SLIPPAGE*100:.2f}% (편도)")
    print(f"WF: {WINDOWS}")
    print(f"통과: W2 Sharpe≥{SHARPE_PASS}, n≥{MIN_TRADES_W2}")
    print(f"현재 wallet: {len(CURRENT_WALLET)}개")

    # Load BTC data
    print("\n[1/4] BTC 데이터 로드...")
    df_btc4h = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    df_btcday = load_historical(BTC_SYMBOL, "day", START, END)
    if df_btc4h is None or df_btcday is None or df_btc4h.empty:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC 4h: {len(df_btc4h)} rows, day: {len(df_btcday)} rows")

    # Load all alt symbols
    print("[2/4] 알트 심볼 데이터 로드...")
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

    # BTC signal
    print("[3/4] BTC 신호 계산...")
    btc_sig = compute_btc_signal(df_btc4h, df_btcday)
    print(f"  BTC 활성봉: {int(btc_sig.sum())}")

    # Per-symbol analysis
    print("[4/4] 심볼별 walk-forward 분석...")
    results = []
    for sym, df in alt_raw.items():
        entry = compute_alt_entry(df, df_btc4h, btc_sig)
        total_signals = int(entry.sum())
        if total_signals < 3:
            continue

        dates = pd.DatetimeIndex(df.index)
        closes_all = df["close"].values
        entry_all = entry.values.astype(bool)

        # BTC correlation
        btc_corr = compute_btc_corr(df, df_btc4h)

        window_res: dict[str, dict] = {}
        for wname, wstart, wend in WINDOWS:
            ws = pd.Timestamp(wstart)
            we = pd.Timestamp(wend)
            mask = (dates >= ws) & (dates <= we)
            if mask.sum() < W * 2:
                window_res[wname] = {
                    "n": 0, "sharpe": float("nan"),
                    "wr": float("nan"), "avg": float("nan"),
                }
                continue
            trades = run_symbol(closes_all[mask], entry_all[mask])
            rets = [t[0] for t in trades]
            n = len(rets)
            if n < 3:
                window_res[wname] = {
                    "n": n, "sharpe": float("nan"),
                    "wr": float("nan"), "avg": float("nan"),
                }
            else:
                a = np.array(rets)
                window_res[wname] = {
                    "n": n,
                    "sharpe": sharpe(rets),
                    "wr": float(np.mean(a > 0)),
                    "avg": float(a.mean() * 100),
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
            "W2_avg": w2.get("avg", float("nan")),
            "btc_corr": btc_corr,
            "pass": passed,
        })

    # Sort by W2 Sharpe
    results.sort(
        key=lambda x: x["W2_sh"] if not np.isnan(x["W2_sh"]) else -999,
        reverse=True,
    )

    # Print all passing results
    print(f"\n총 분석 심볼: {len(results)}개")
    passing = [r for r in results if r["pass"]]
    print(f"통과 심볼: {len(passing)}개\n")

    hdr = (
        f"{'심볼':>14} {'지갑':>4} | {'W1 Sh':>8} {'W1 n':>5} | "
        f"{'W2 Sh':>8} {'W2 n':>5} {'W2 WR':>7} {'W2 avg':>7} | "
        f"{'BTC상관':>7} | 통과"
    )
    print(hdr)
    print("-" * 95)

    new_candidates = []
    wallet_results = []
    for r in results:
        if not r["pass"] and not r["in_wallet"]:
            continue  # only show passing or wallet symbols
        mark = "✅" if r["pass"] else "❌"
        wallet_mark = "★" if r["in_wallet"] else " "
        wr_s = f"{r['W2_wr']*100:.1f}%" if not np.isnan(r["W2_wr"]) else "  N/A"
        avg_s = f"{r['W2_avg']:+.2f}%" if not np.isnan(r["W2_avg"]) else "   N/A"
        w1_s = f"{r['W1_sh']:>8.3f}" if not np.isnan(r["W1_sh"]) else "     nan"
        w2_s = f"{r['W2_sh']:>8.3f}" if not np.isnan(r["W2_sh"]) else "     nan"
        corr_s = f"{r['btc_corr']:>+.3f}" if not np.isnan(r["btc_corr"]) else "   nan"
        print(
            f"{r['sym']:>14} {wallet_mark:>4} | "
            f"{w1_s} {r['W1_n']:>5} | "
            f"{w2_s} {r['W2_n']:>5} {wr_s:>7} {avg_s:>7} | "
            f"{corr_s:>7} | {mark}"
        )
        if r["pass"] and not r["in_wallet"]:
            new_candidates.append(r)
        if r["in_wallet"]:
            wallet_results.append(r)

    # Wallet summary
    print("\n" + "=" * 70)
    print("=== 현재 daemon 14심볼 성과 ===")
    wallet_results.sort(
        key=lambda x: x["W2_sh"] if not np.isnan(x["W2_sh"]) else -999,
        reverse=True,
    )
    w_pass = sum(1 for r in wallet_results if r["pass"])
    w_total_n = sum(r["W2_n"] for r in wallet_results)
    for r in wallet_results:
        mark = "✅" if r["pass"] else "❌"
        w2_s = f"{r['W2_sh']:.3f}" if not np.isnan(r["W2_sh"]) else "nan"
        corr_s = f"{r['btc_corr']:+.3f}" if not np.isnan(r["btc_corr"]) else "nan"
        print(
            f"  {mark} {r['sym']}: W2 Sharpe {w2_s} "
            f"(n={r['W2_n']}, WR={r['W2_wr']*100:.1f}%, "
            f"BTC상관={corr_s})"
        )
    print(f"  합계: {w_pass}/{len(wallet_results)} 통과, W2 n={w_total_n}")

    # New candidates
    print(f"\n=== 신규 후보 ({len(new_candidates)}개) ===")
    if new_candidates:
        # Filter for low BTC correlation
        low_corr = [
            r for r in new_candidates
            if not np.isnan(r["btc_corr"]) and r["btc_corr"] < 0.5
        ]
        print(f"  전체 후보: {len(new_candidates)}개")
        print(f"  BTC 상관 < 0.5: {len(low_corr)}개\n")

        for r in new_candidates:
            w2_s = f"{r['W2_sh']:.3f}" if not np.isnan(r["W2_sh"]) else "nan"
            corr_s = (
                f"{r['btc_corr']:+.3f}"
                if not np.isnan(r["btc_corr"]) else "nan"
            )
            low_tag = " ★LOW_CORR" if (
                not np.isnan(r["btc_corr"]) and r["btc_corr"] < 0.5
            ) else ""
            print(
                f"  ✅ {r['sym']}: W2 Sharpe {w2_s} "
                f"(n={r['W2_n']}, WR={r['W2_wr']*100:.1f}%, "
                f"BTC상관={corr_s}){low_tag}"
            )
    else:
        print("  신규 후보 없음")

    # Portfolio-level analysis
    print("\n" + "=" * 70)
    print("=== 포트폴리오 수준 분석 (W2 구간) ===")

    # Collect all W2 trades for current wallet
    wallet_trades: list[float] = []
    for sym in sorted(CURRENT_WALLET):
        if sym not in alt_raw:
            continue
        df = alt_raw[sym]
        entry = compute_alt_entry(df, df_btc4h, btc_sig)
        dates = pd.DatetimeIndex(df.index)
        ws = pd.Timestamp(WINDOWS[1][1])
        we = pd.Timestamp(WINDOWS[1][2])
        mask = (dates >= ws) & (dates <= we)
        if mask.sum() < W * 2:
            continue
        trades = run_symbol(df["close"].values[mask], entry.values[mask].astype(bool))
        wallet_trades.extend([t[0] for t in trades])

    wallet_sh = sharpe(wallet_trades)
    wallet_wr = np.mean(np.array(wallet_trades) > 0) if wallet_trades else 0
    wallet_avg = np.mean(wallet_trades) * 100 if wallet_trades else 0
    print(
        f"  현재 14심볼: Sharpe {wallet_sh:.3f}, "
        f"n={len(wallet_trades)}, WR={wallet_wr*100:.1f}%, "
        f"avg={wallet_avg:+.2f}%"
    )

    # Test expansion sets
    if new_candidates:
        for add_count in [3, 5, 7, 10]:
            to_add = new_candidates[:add_count]
            if len(to_add) < add_count and len(to_add) == len(new_candidates):
                add_count = len(to_add)
            expanded_trades = list(wallet_trades)
            added_syms = []
            for r in to_add:
                sym = r["sym"]
                if sym not in alt_raw:
                    continue
                df = alt_raw[sym]
                entry = compute_alt_entry(df, df_btc4h, btc_sig)
                dates = pd.DatetimeIndex(df.index)
                ws = pd.Timestamp(WINDOWS[1][1])
                we = pd.Timestamp(WINDOWS[1][2])
                mask = (dates >= ws) & (dates <= we)
                if mask.sum() < W * 2:
                    continue
                trades = run_symbol(
                    df["close"].values[mask],
                    entry.values[mask].astype(bool),
                )
                expanded_trades.extend([t[0] for t in trades])
                added_syms.append(sym)

            exp_sh = sharpe(expanded_trades)
            exp_wr = np.mean(np.array(expanded_trades) > 0)
            exp_avg = np.mean(expanded_trades) * 100
            delta = exp_sh - wallet_sh if not np.isnan(exp_sh) else 0
            print(
                f"  +{len(added_syms)}({len(CURRENT_WALLET)+len(added_syms)}심볼): "
                f"Sharpe {exp_sh:.3f} (Δ{delta:+.3f}), "
                f"n={len(expanded_trades)}, WR={exp_wr*100:.1f}%, "
                f"avg={exp_avg:+.2f}%"
            )

    # Final recommendation
    print("\n" + "=" * 70)
    if new_candidates:
        best_set = new_candidates[:7]  # top 7 new
        best_syms = [r["sym"] for r in best_set]
        print(f"=== 추천: daemon symbols 추가 후보 (상위 {len(best_syms)}개) ===")
        for r in best_set:
            w2_s = f"{r['W2_sh']:.3f}" if not np.isnan(r["W2_sh"]) else "nan"
            corr_s = (
                f"{r['btc_corr']:+.3f}"
                if not np.isnan(r["btc_corr"]) else "nan"
            )
            print(f"  {r['sym']}: Sharpe {w2_s}, n={r['W2_n']}, corr={corr_s}")
        print(f"\n  추가 시 symbols: {sorted(list(CURRENT_WALLET) + best_syms)}")
    else:
        print("=== 결론: 확장 후보 없음 — 현재 14심볼 유지 ===")

    elapsed = time.time() - t0
    print(f"\n소요: {elapsed:.1f}초")


if __name__ == "__main__":
    main()
