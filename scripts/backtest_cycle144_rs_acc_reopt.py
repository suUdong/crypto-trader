"""
사이클 144: stealth_3gate RS범위 + BTC_ACC_MIN 2D 재최적화 (14심볼 기준)
- 배경: 사이클 143에서 7→14심볼 확장 후 W2 Sharpe 9.547→13.183 (+3.636)
  RS=[0.4,0.9)/ACC=1.2는 7심볼 기준 최적값 → 14심볼 기준 재검증 필요
- 고정: TP=5%, SL=1.0%, W=36, SMA=10, MAX_HOLD=24 (사이클 141 확정)
- 14심볼: AVAX/LINK/APT/XRP/ADA/DOT/ATOM/ASTR/CELO/CHZ/IOST/NEO/PEPE/THETA
- 탐색: RS_LO × RS_HI × BTC_ACC_MIN 3D 그리드
- WF: W1(2022-01-01~2023-12-31), W2(2024-01-01~2026-04-04)
- 현재 기준선: W2 Sharpe=13.183 (n=71, WR=59.2%)
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

# 고정 파라미터 (사이클 141 확정)
W = 36
SMA_N = 10
ALT_ACC_MIN = 1.0
MAX_HOLD = 24
TP = 0.05
SL = 0.010
FEE = 0.001

# 14심볼 (사이클 143 확정)
TARGET_SYMBOLS = [
    "KRW-AVAX", "KRW-LINK", "KRW-APT", "KRW-XRP",
    "KRW-ADA", "KRW-DOT", "KRW-ATOM", "KRW-ASTR",
    "KRW-CELO", "KRW-CHZ", "KRW-IOST", "KRW-NEO",
    "KRW-PEPE", "KRW-THETA",
]

# 탐색 그리드
RS_LOWS = [0.3, 0.35, 0.4, 0.45, 0.5]
RS_HIGHS = [0.8, 0.85, 0.9, 0.95, 1.0]
BTC_ACCS = [1.0, 1.1, 1.2, 1.3, 1.5]

WINDOWS = [
    ("W1", "2022-01-01", "2023-12-31"),
    ("W2", "2024-01-01", "2026-04-04"),
]

BASELINE_W2 = 13.183  # 사이클 143 기준선


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def compute_btc_signal(df4h: pd.DataFrame, dfday: pd.DataFrame, btc_acc_min: float) -> pd.Series:
    """Gate 1+2: BTC>SMA10(daily) + BTC stealth(4h, W=36, acc>btc_acc_min)."""
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
    stealth = (ret_w < 1.0) & (acc > btc_acc_min)

    return (reg4h & stealth).fillna(False)


def compute_alt_entry(
    df_alt: pd.DataFrame,
    df_btc4h: pd.DataFrame,
    btc_sig: pd.Series,
    rs_lo: float,
    rs_hi: float,
) -> pd.Series:
    """Gate 3: alt RS∈[rs_lo, rs_hi) + alt acc > ALT_ACC_MIN."""
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

    alt_gate = (rs >= rs_lo) & (rs < rs_hi) & (acc_v > ALT_ACC_MIN)
    return (btc_sig.reindex(df_alt.index).fillna(False) & alt_gate.fillna(False))


def run_symbol(closes: np.ndarray, entry: np.ndarray) -> list[float]:
    rets: list[float] = []
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


def main() -> None:
    t0 = time.time()
    total_combos = len(RS_LOWS) * len(RS_HIGHS) * len(BTC_ACCS)
    print("=== stealth_3gate RS+ACC 2D 재최적화 (사이클 144) ===")
    print(f"14심볼 기준 / 그리드 {total_combos}개 조합")
    print(f"고정: TP={TP*100:.0f}%, SL={SL*100:.1f}%, W={W}, SMA={SMA_N}, MAX_HOLD={MAX_HOLD}")
    print(f"기준선 W2 Sharpe: {BASELINE_W2} (사이클 143, RS=[0.4,0.9), ACC=1.2)")

    # BTC 데이터 로드
    print("\n[1/3] BTC 데이터 로드...")
    df_btc4h = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    df_btcday = load_historical(BTC_SYMBOL, "day", START, END)
    if df_btc4h is None or df_btcday is None or df_btc4h.empty:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC 4h: {len(df_btc4h)}행, day: {len(df_btcday)}행")

    # 알트 데이터 로드
    print("[2/3] 14심볼 데이터 로드...")
    alt_data: dict[str, pd.DataFrame] = {}
    for sym in TARGET_SYMBOLS:
        df = load_historical(sym, INTERVAL, START, END)
        if df is not None and not df.empty:
            alt_data[sym] = df
            print(f"  {sym}: {len(df)}행")
        else:
            print(f"  {sym}: 데이터 없음 — 스킵")
    print(f"  유효 심볼: {len(alt_data)}개")

    # 그리드 탐색
    print("\n[3/3] 그리드 탐색...")
    results = []

    # BTC 신호는 ACC에 따라 달라지므로 ACC별로 BTC 신호 캐싱
    btc_signals: dict[float, pd.Series] = {}

    for combo_idx, (rs_lo, rs_hi, btc_acc) in enumerate(product(RS_LOWS, RS_HIGHS, BTC_ACCS)):
        if rs_lo >= rs_hi:
            continue

        # BTC 신호 캐싱 (ACC 변경 시만 재계산)
        if btc_acc not in btc_signals:
            btc_signals[btc_acc] = compute_btc_signal(df_btc4h, df_btcday, btc_acc)
        btc_sig = btc_signals[btc_acc]

        # W1/W2별 집계
        window_results: dict[str, dict] = {}
        for wname, wstart, wend in WINDOWS:
            all_rets: list[float] = []
            for sym, df_alt in alt_data.items():
                entry_sig = compute_alt_entry(df_alt, df_btc4h, btc_sig, rs_lo, rs_hi)
                mask = (df_alt.index >= wstart) & (df_alt.index < wend)
                df_w = df_alt[mask]
                sig_w = entry_sig.reindex(df_w.index).fillna(False)
                if len(df_w) < W + 2:
                    continue
                rets = run_symbol(df_w["close"].values, sig_w.values)
                all_rets.extend(rets)
            sp = sharpe(all_rets)
            n = len(all_rets)
            wr = float(np.mean([r > 0 for r in all_rets])) if all_rets else float("nan")
            window_results[wname] = {"sharpe": sp, "n": n, "wr": wr}

        w1 = window_results.get("W1", {})
        w2 = window_results.get("W2", {})
        results.append({
            "rs_lo": rs_lo,
            "rs_hi": rs_hi,
            "btc_acc": btc_acc,
            "W1_sharpe": w1.get("sharpe", float("nan")),
            "W1_n": w1.get("n", 0),
            "W2_sharpe": w2.get("sharpe", float("nan")),
            "W2_n": w2.get("n", 0),
            "W2_wr": w2.get("wr", float("nan")),
        })

        if (combo_idx + 1) % 10 == 0:
            elapsed = time.time() - t0
            print(f"  {combo_idx+1}/{total_combos} 완료 ({elapsed:.0f}s)")

    # 결과 정렬 및 출력
    df_res = pd.DataFrame(results).dropna(subset=["W2_sharpe"])
    df_res = df_res.sort_values("W2_sharpe", ascending=False).reset_index(drop=True)

    print(f"\n{'='*90}")
    print("=== W2 Sharpe 상위 20개 조합 ===")
    print(f"{'RS_LO':>6} {'RS_HI':>6} {'ACC':>5} | {'W1_Sh':>7} {'W1_n':>6} | {'W2_Sh':>7} {'W2_n':>6} {'W2_WR':>7} | {'ΔW2':>7} {'통과':>4}")
    print("-" * 90)
    for _, row in df_res.head(20).iterrows():
        delta = row["W2_sharpe"] - BASELINE_W2
        pass_flag = "✅" if row["W2_sharpe"] >= BASELINE_W2 else "❌"
        print(
            f"{row['rs_lo']:>6.2f} {row['rs_hi']:>6.2f} {row['btc_acc']:>5.1f} | "
            f"{row['W1_sharpe']:>7.3f} {int(row['W1_n']):>6} | "
            f"{row['W2_sharpe']:>7.3f} {int(row['W2_n']):>6} {row['W2_wr']*100:>6.1f}% | "
            f"{delta:>+7.3f} {pass_flag:>4}"
        )

    # 현재 기준선 행
    baseline_row = df_res[(df_res["rs_lo"] == 0.4) & (df_res["rs_hi"] == 0.9) & (df_res["btc_acc"] == 1.2)]
    if not baseline_row.empty:
        r = baseline_row.iloc[0]
        print(f"\n[기준선] RS=[0.4,0.9) ACC=1.2: W1={r['W1_sharpe']:.3f}(n={int(r['W1_n'])}), W2={r['W2_sharpe']:.3f}(n={int(r['W2_n'])})")

    # 베스트 조합
    best = df_res.iloc[0]
    print(f"\n[최적] RS=[{best['rs_lo']:.2f},{best['rs_hi']:.2f}) ACC={best['btc_acc']:.1f}")
    print(f"  W1 Sharpe: {best['W1_sharpe']:.3f} (n={int(best['W1_n'])})")
    print(f"  W2 Sharpe: {best['W2_sharpe']:.3f} (n={int(best['W2_n'])}, WR={best['W2_wr']*100:.1f}%)")
    print(f"  ΔW2: {best['W2_sharpe'] - BASELINE_W2:+.3f} vs 기준선({BASELINE_W2})")

    elapsed = time.time() - t0
    print(f"\n소요: {elapsed:.1f}s")

    # CSV 저장
    out_csv = Path("scripts/cycle144_rs_acc_results.csv")
    df_res.to_csv(out_csv, index=False)
    print(f"결과 저장: {out_csv}")


if __name__ == "__main__":
    main()
