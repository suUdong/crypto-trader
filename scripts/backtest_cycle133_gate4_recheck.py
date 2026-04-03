"""
사이클 133: stealth_3gate Gate4(btc_trend_pos_gate) ON/OFF 재검증
- RS[0.4,0.9) 변경 후 Gate4 비교가 무효화됨 (사이클 130은 RS[0.5,1.0) 기준)
- 고정: W=36, SMA=10, RS[0.4,0.9), TP=10%, SL=1.0%, MAX_HOLD=24
- Gate4=OFF (현재 daemon): 기준선
- Gate4=ON (btc_trend_pos_gate): BTC 10봉 수익률 > 0 추가 조건
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

# Fixed params (사이클 129-132 최적값)
W = 36           # stealth_window
SMA_N = 10       # BTC SMA period
RS_LO = 0.4      # RS 하한 (사이클 132 확정)
RS_HI = 0.9      # RS 상한 (사이클 132 확정)
TP = 0.10        # take profit
SL = 0.010       # stop loss
MAX_HOLD = 24    # max hold bars
FEE = 0.001      # 0.10% round-trip
GATE4_WINDOW = 10  # BTC trend window (btc_trend_window=10)

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
    gate4_on: bool,
) -> pd.Series:
    """Gate 1+2(+Gate4): BTC>SMA10(daily) + BTC stealth(4h, W=36) [+ BTC 10봉>0]."""
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

    btc_sig = reg4h & stealth

    # Gate 4: BTC 10봉 수익률 > 0 (btc_trend_pos_gate)
    if gate4_on:
        btc_trend_pos = (c / c.shift(GATE4_WINDOW) - 1) > 0
        btc_sig = btc_sig & btc_trend_pos.fillna(False)

    return btc_sig.fillna(False)


def compute_alt_entry(
    df_alt: pd.DataFrame,
    df_btc4h: pd.DataFrame,
    btc_sig: pd.Series,
) -> pd.Series:
    """Gate 3: alt RS∈[RS_LO, RS_HI) + alt acc>1."""
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


# ─── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    t0 = time.time()
    print("=== stealth_3gate Gate4 재검증 (사이클 133) ===")
    print(f"고정: W={W}, SMA={SMA_N}, RS=[{RS_LO},{RS_HI}), TP={TP*100:.0f}%, SL={SL*100:.1f}%, MAX_HOLD={MAX_HOLD}")
    print(f"탐색: Gate4=OFF vs Gate4=ON (btc_trend_pos_gate, window={GATE4_WINDOW})")
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

    # Evaluate Gate4=OFF and Gate4=ON
    print("\n[3/3] Gate4 ON/OFF 비교...")
    cases = [
        ("Gate4=OFF (현재 daemon) 📌", False),
        ("Gate4=ON  (btc_trend_pos_gate)", True),
    ]

    results = []
    for label, gate4_on in cases:
        btc_sig = compute_btc_signal(df_btc4h, df_btcday, gate4_on=gate4_on)
        btc_active = int(btc_sig.sum())

        # Compute alt entry signals
        alt_signals: dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
        for sym, df in alt_raw.items():
            entry = compute_alt_entry(df, df_btc4h, btc_sig)
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
            "gate4_on": gate4_on,
            "btc_active": btc_active,
            "alt_syms": len(alt_signals),
            "w1_sharpe": w1_sh, "w1_n": w1.get("n", 0), "w1_wr": w1.get("wr", float("nan")),
            "w2_sharpe": w2_sh, "w2_n": w2.get("n", 0), "w2_wr": w2.get("wr", float("nan")),
            "passed": passed,
        })

        flag = "✅" if passed else "  "
        print(
            f"\n{flag} {label}"
            f"\n   BTC stealth 활성봉: {btc_active} | alt 심볼: {len(alt_signals)}"
            f"\n   W1: Sharpe={w1_sh:.3f}  n={w1.get('n',0):4d}  WR={w1.get('wr', float('nan')):.3f}"
            f"\n   W2: Sharpe={w2_sh:.3f}  n={w2.get('n',0):4d}  WR={w2.get('wr', float('nan')):.3f}"
        )

    # Summary
    print("\n=== 결과 요약 ===")
    r_off = next((r for r in results if not r["gate4_on"]), None)
    r_on = next((r for r in results if r["gate4_on"]), None)

    if r_off and r_on:
        delta_w2 = r_on["w2_sharpe"] - r_off["w2_sharpe"]
        delta_w1 = r_on["w1_sharpe"] - r_off["w1_sharpe"]
        print(f"Gate4=ON vs Gate4=OFF 비교:")
        print(f"  W2 Sharpe: {r_off['w2_sharpe']:.3f} (OFF) vs {r_on['w2_sharpe']:.3f} (ON)  → 델타: {delta_w2:+.3f}")
        print(f"  W1 Sharpe: {r_off['w1_sharpe']:.3f} (OFF) vs {r_on['w1_sharpe']:.3f} (ON)  → 델타: {delta_w1:+.3f}")
        print(f"  W2 거래수: {r_off['w2_n']:4d} (OFF) vs {r_on['w2_n']:4d} (ON)")

        if delta_w2 > 0.2:
            winner = "Gate4=ON"
            recommendation = f"btc_trend_pos_gate: false → true 변경 권장 (+{delta_w2:.3f})"
        elif delta_w2 < -0.2:
            winner = "Gate4=OFF"
            recommendation = f"현재 설정(btc_trend_pos_gate=false) 유지 ({delta_w2:+.3f})"
        else:
            winner = "차이 없음"
            recommendation = f"Gate4 효과 미미 ({delta_w2:+.3f}) — 현재 설정 유지"

        print(f"\n판정: {winner}")
        print(f"권고: {recommendation}")

    print(f"\n총 소요: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
