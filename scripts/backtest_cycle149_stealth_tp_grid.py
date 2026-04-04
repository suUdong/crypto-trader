"""
사이클 149: stealth_3gate TP 세밀 그리드 탐색
- 현행 daemon: TP=5%/SL=1.0%, ACC_MIN=1.0, SMA=10, RS=[0.4,0.9), W=36, 14심볼
- 사이클 142: ACC_MIN=1.2 기준, TP=3/4/5만 탐색 → TP=5%/SL=0.8% 소폭 우위(+0.127)
- 미탐색: TP=6%/7%, SL=1.5%, 그리고 ACC_MIN=1.0 기준 전체 재검증
- 탐색: TP∈{3,4,5,6,7}% × SL∈{0.8,1.0,1.5}% = 15조합
- 고정: W=36, SMA=10, RS=[0.4,0.9), BTC_ACC_MIN=1.0, alt_acc>1.0, MAX_HOLD=24
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-05), 슬리피지 0.10%
- 14심볼: AVAX,LINK,APT,XRP,ADA,DOT,ATOM,ASTR,CELO,CHZ,IOST,NEO,PEPE,THETA
- 통과: 2/2창 Sharpe≥5.0, n≥30
- BH 대비 비교 포함
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
END = "2026-04-05"

# Fixed params (현행 daemon 기준)
W = 36
SMA_N = 10
RS_LO = 0.4
RS_HI = 0.9
BTC_ACC_MIN = 1.0   # 사이클 144 재검증: 1.15→1.0
ALT_ACC_MIN = 1.0
MAX_HOLD = 24
FEE = 0.001  # 0.10% round-trip (슬리피지 포함)

# 14 daemon symbols (W2 비교용)
DAEMON_SYMBOLS = [
    "KRW-AVAX", "KRW-LINK", "KRW-APT", "KRW-XRP", "KRW-ADA", "KRW-DOT",
    "KRW-ATOM", "KRW-ASTR", "KRW-CELO", "KRW-CHZ", "KRW-IOST", "KRW-NEO",
    "KRW-PEPE", "KRW-THETA",
]
DAEMON_SET = set(DAEMON_SYMBOLS)

# Grid
TP_CANDIDATES = [0.03, 0.04, 0.05, 0.06, 0.07]
SL_CANDIDATES = [0.008, 0.010, 0.015]

WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-05"),
]

MIN_TRADES = 30
SHARPE_PASS = 5.0

# 현행 daemon 베이스라인
BASELINE_TP = 0.05
BASELINE_SL = 0.010


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
    closes: np.ndarray, entry: np.ndarray, tp: float, sl: float
) -> list[float]:
    """진입: 신호 다음봉 시가(=closes[i+1]) 사용."""
    rets: list[float] = []
    i = 0
    n = len(closes)
    while i < n - 1:
        if entry[i]:
            bp = closes[i + 1]  # next bar open proxy (4h close ≈ next open)
            limit = min(i + 1 + MAX_HOLD, n)
            ret = None
            for j in range(i + 2, limit):
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
                exit_j = min(i + 1 + MAX_HOLD, n - 1)
                ret = closes[exit_j] / bp - 1 - FEE
                i = exit_j + 1
            rets.append(ret)
        else:
            i += 1
    return rets


def buy_and_hold(closes: np.ndarray) -> float:
    """Buy & hold return for the period."""
    if len(closes) < 2:
        return 0.0
    return float(closes[-1] / closes[0] - 1)


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
    print("=== stealth_3gate TP 세밀 그리드 (사이클 149) ===")
    print(f"고정: W={W}, SMA={SMA_N}, RS=[{RS_LO},{RS_HI}), "
          f"BTC_ACC_MIN={BTC_ACC_MIN}, MAX_HOLD={MAX_HOLD}")
    print(f"탐색: TP∈{[f'{v*100:.0f}%' for v in TP_CANDIDATES]} "
          f"× SL∈{[f'{v*100:.1f}%' for v in SL_CANDIDATES]} = {len(TP_CANDIDATES)*len(SL_CANDIDATES)}조합")
    print(f"심볼: {len(DAEMON_SYMBOLS)}개 (daemon 14심볼 한정)")
    print(f"거래비용: {FEE*100:.2f}% 왕복")
    print(f"통과: 2/2창 Sharpe≥{SHARPE_PASS}, n≥{MIN_TRADES}")
    print()

    # Load BTC data
    print("[1/4] BTC 데이터 로드...")
    df_btc4h = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    df_btcday = load_historical(BTC_SYMBOL, "day", START, END)
    if df_btc4h is None or df_btcday is None or df_btc4h.empty:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC 4h: {len(df_btc4h)} rows, day: {len(df_btcday)} rows")

    # Load ALL symbols (WF W1 검증을 위해 전체 심볼 필요, daemon 14개 별도 추적)
    print("[2/4] 전체 심볼 로드 (WF W1 충분한 n 확보)...")
    base = _root / "data" / "historical" / "monthly" / INTERVAL
    all_syms: set[str] = set()
    for year_dir in base.iterdir():
        if not year_dir.is_dir():
            continue
        for f in year_dir.glob("KRW-*.zip"):
            sym = f.name.split("_")[0]
            if sym != BTC_SYMBOL:
                all_syms.add(sym)
    alt_raw: dict[str, pd.DataFrame] = {}
    for sym in sorted(all_syms):
        try:
            df = load_historical(sym, INTERVAL, START, END)
            if df is None or df.empty or len(df) < W * 4:
                continue
            alt_raw[sym] = df
        except Exception:
            pass
    n_daemon = sum(1 for s in alt_raw if s in DAEMON_SET)
    print(f"  {len(alt_raw)}개 심볼 로드 (daemon {n_daemon}개 포함, {time.time()-t0:.1f}s)")

    # BTC signal
    print("[3/4] BTC 신호 계산...")
    btc_sig = compute_btc_signal(df_btc4h, df_btcday)
    print(f"  BTC 활성봉: {int(btc_sig.sum())}")

    # Alt entry signals (fixed, TP/SL 무관)
    print("[4/4] 알트 진입 신호 계산...")
    alt_signals: dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
    for sym, df in alt_raw.items():
        entry = compute_alt_entry(df, df_btc4h, btc_sig)
        if entry.sum() < 3:
            continue
        alt_signals[sym] = (
            df["close"].values,
            entry.values.astype(bool),
            pd.DatetimeIndex(df.index),
        )
    print(f"  유효 심볼: {len(alt_signals)}개, "
          f"총 신호: {sum(e.sum() for _, e, _ in alt_signals.values())}개")

    # Pre-slice per window
    sliced: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
    bh_rets: dict[str, dict[str, float]] = {}  # window -> sym -> BH return
    for wname, wstart, wend in WINDOWS:
        ws, we = pd.Timestamp(wstart), pd.Timestamp(wend)
        sliced[wname] = {}
        bh_rets[wname] = {}
        for sym, (closes, entry, dates) in alt_signals.items():
            mask = (dates >= ws) & (dates <= we)
            if mask.sum() < W * 2:
                continue
            sliced[wname][sym] = (closes[mask], entry[mask])
            bh_rets[wname][sym] = buy_and_hold(closes[mask])

    # BH average per window
    for wname in ["W1", "W2"]:
        avg_bh = np.mean(list(bh_rets[wname].values())) if bh_rets[wname] else 0.0
        print(f"  {wname} BH 평균: {avg_bh*100:.1f}% ({len(bh_rets[wname])}심볼)")

    # Pre-slice daemon-only W2 for deployment comparison
    daemon_sliced_w2: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    ws2, we2 = pd.Timestamp("2024-01-01"), pd.Timestamp("2026-04-05")
    for sym, (closes, entry, dates) in alt_signals.items():
        if sym not in DAEMON_SET:
            continue
        mask = (dates >= ws2) & (dates <= we2)
        if mask.sum() < W * 2:
            continue
        daemon_sliced_w2[sym] = (closes[mask], entry[mask])
    print(f"  daemon W2 심볼: {len(daemon_sliced_w2)}개")

    # Grid search
    total = len(TP_CANDIDATES) * len(SL_CANDIDATES)
    print(f"\n[그리드 탐색] {total}조합...\n")
    results = []
    idx_combo = 0

    for tp in TP_CANDIDATES:
        for sl in SL_CANDIDATES:
            idx_combo += 1
            is_baseline = abs(tp - BASELINE_TP) < 1e-6 and abs(sl - BASELINE_SL) < 1e-6

            window_results: dict[str, dict] = {}
            for wname, _, _ in WINDOWS:
                all_rets: list[float] = []
                for sym, (closes, entry) in sliced[wname].items():
                    all_rets.extend(run_symbol(closes, entry, tp, sl))
                n_trades = len(all_rets)
                if n_trades < MIN_TRADES:
                    window_results[wname] = {
                        "n": n_trades, "sharpe": float("nan"),
                        "wr": float("nan"), "avg_ret": float("nan"),
                    }
                else:
                    a = np.array(all_rets)
                    window_results[wname] = {
                        "n": n_trades,
                        "sharpe": sharpe(all_rets),
                        "wr": float(np.mean(a > 0)),
                        "avg_ret": float(a.mean()),
                    }

            # Daemon-only W2
            d_rets: list[float] = []
            for sym, (closes, entry) in daemon_sliced_w2.items():
                d_rets.extend(run_symbol(closes, entry, tp, sl))
            d_n = len(d_rets)
            if d_n >= 10:
                da = np.array(d_rets)
                d_sh = sharpe(d_rets)
                d_wr = float(np.mean(da > 0))
            else:
                d_sh = float("nan")
                d_wr = float("nan")

            w1 = window_results.get("W1", {})
            w2 = window_results.get("W2", {})
            w1_sh = w1.get("sharpe", float("nan"))
            w2_sh = w2.get("sharpe", float("nan"))
            passed = (
                not np.isnan(w1_sh) and w1_sh >= SHARPE_PASS
                and not np.isnan(w2_sh) and w2_sh >= SHARPE_PASS
            )

            row = {
                "TP": f"{tp*100:.0f}%", "SL": f"{sl*100:.1f}%",
                "tp_raw": tp, "sl_raw": sl,
                "is_baseline": is_baseline,
                "W1_sh": w1_sh, "W1_n": w1.get("n", 0),
                "W1_wr": w1.get("wr", float("nan")),
                "W2_sh": w2_sh, "W2_n": w2.get("n", 0),
                "W2_wr": w2.get("wr", float("nan")),
                "W2_avg": w2.get("avg_ret", float("nan")),
                "D_W2_sh": d_sh, "D_W2_n": d_n, "D_W2_wr": d_wr,
                "pass": passed,
            }
            results.append(row)

            flag = "✅" if passed else "  "
            base_mark = " ← daemon" if is_baseline else ""
            d_str = f" D:Sh={d_sh:+.3f}(n={d_n})" if not np.isnan(d_sh) else ""
            print(
                f"{flag} [{idx_combo:2d}/{total}] TP={tp*100:.0f}%/SL={sl*100:.1f}%{base_mark}"
                f"  W1={w1_sh:+.3f}(n={w1.get('n',0)}) "
                f"W2={w2_sh:+.3f}(n={w2.get('n',0)}, WR={w2.get('wr',0)*100:.1f}%)"
                f"{d_str}"
            )

    # Sort by W2 Sharpe
    results.sort(
        key=lambda x: x["W2_sh"] if not np.isnan(x["W2_sh"]) else -999,
        reverse=True,
    )

    print("\n" + "=" * 95)
    print("=== 결과 요약 (W2 Sharpe 내림차순) ===")
    print(f"{'TP':>5} {'SL':>5} | {'W1 Sh':>7} {'W1 n':>5} {'W1 WR':>6} | "
          f"{'W2 Sh':>7} {'W2 n':>5} {'W2 WR':>6} {'W2 avg':>7} | "
          f"{'D_W2':>7} {'D_n':>4} | 통과")
    print("-" * 110)
    for r in results:
        mark = "✅" if r["pass"] else "❌"
        base = " ← daemon" if r["is_baseline"] else ""
        w1_wr = f"{r['W1_wr']*100:.1f}%" if not np.isnan(r["W1_wr"]) else "  N/A"
        w2_wr = f"{r['W2_wr']*100:.1f}%" if not np.isnan(r["W2_wr"]) else "  N/A"
        w2_avg = f"{r['W2_avg']*100:.2f}%" if not np.isnan(r["W2_avg"]) else "   N/A"
        d_sh = f"{r['D_W2_sh']:>+7.3f}" if not np.isnan(r["D_W2_sh"]) else "    nan"
        print(
            f"{r['TP']:>5} {r['SL']:>5} | "
            f"{r['W1_sh']:>+7.3f} {r['W1_n']:>5} {w1_wr:>6} | "
            f"{r['W2_sh']:>+7.3f} {r['W2_n']:>5} {w2_wr:>6} {w2_avg:>7} | "
            f"{d_sh} {r['D_W2_n']:>4} | "
            f"{mark}{base}"
        )

    # Baseline comparison
    baseline_w2 = next(
        (r["W2_sh"] for r in results if r["is_baseline"]), float("nan")
    )
    best = results[0]
    delta = best["W2_sh"] - baseline_w2 if not np.isnan(baseline_w2) else float("nan")

    print(f"\n현행 daemon: TP={BASELINE_TP*100:.0f}%/SL={BASELINE_SL*100:.1f}% → "
          f"W2 Sharpe={baseline_w2:.3f}")
    print(f"최적: TP={best['TP']}/SL={best['SL']} → "
          f"W2 Sharpe={best['W2_sh']:.3f} (Δ={delta:+.3f})")

    if best["pass"] and delta > 0.5:
        print(f"\n🔥 daemon 업데이트 후보: TP={best['TP']}/SL={best['SL']}")
        print(f"  W2 개선: {delta:+.3f}, n={best['W2_n']}")
    elif best["pass"]:
        print(f"\n현행 유지 권장 (최적 Δ={delta:+.3f} — 유의미한 개선 없음)")
    else:
        print("\n⚠️ 모든 조합 통과 실패")

    print(f"\n소요: {time.time()-t0:.1f}초")

    # BH vs strategy comparison
    print("\n=== BH 대비 비교 (W2, 상위 3개) ===")
    avg_bh_w2 = np.mean(list(bh_rets["W2"].values())) if bh_rets["W2"] else 0.0
    for r in results[:3]:
        if np.isnan(r["W2_avg"]):
            continue
        # Annualized: W2 spans ~2.25y, ~n trades
        strat_cumul = r["W2_avg"] * r["W2_n"]
        print(f"  TP={r['TP']}/SL={r['SL']}: 전략 누적={strat_cumul*100:.1f}% "
              f"vs BH 평균={avg_bh_w2*100:.1f}% ({r['W2_n']}건)")

    # Output key metrics
    print(f"\nSharpe: {best['W2_sh']:+.3f}")
    print(f"WR: {best['W2_wr']*100:.1f}%")
    print(f"trades: {best['W2_n']}")

    # CSV
    out_csv = _root / "scripts" / "cycle149_stealth_tp_grid_results.csv"
    save_cols = [
        "TP", "SL", "is_baseline", "W1_sh", "W1_n", "W1_wr",
        "W2_sh", "W2_n", "W2_wr", "W2_avg", "D_W2_sh", "D_W2_n", "D_W2_wr", "pass",
    ]
    pd.DataFrame(results)[save_cols].to_csv(out_csv, index=False)
    print(f"결과: {out_csv}")


if __name__ == "__main__":
    main()
