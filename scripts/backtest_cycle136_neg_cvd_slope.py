"""
사이클 136: stealth_3gate 역방향 CVD slope 게이트 탐색
- 가설: 스텔스 진입 시점 CVD slope mean=-0.40 (사이클 135 발견)
  → 강한 음의 CVD slope가 "진짜 스텔스 누적" 품질 지표일 수 있음
- 현재: cvd_slope 필터 없음 (미활용)
- 탐색: alt cvd_slope_threshold ∈ {None(OFF), -0.1, -0.2, -0.3, -0.5}
  → 조건: cvd_slope < threshold (더 강한 매도압력)
- 고정: W=36, SMA=10, RS=[0.4,0.9), TP=10%, SL=1.0%, Gate4=OFF, acc>1.0, MAX_HOLD=24
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

# Fixed params (사이클 129-134 최적값)
W = 36           # stealth_window
SMA_N = 10       # BTC SMA period
RS_LO = 0.4      # RS 하한 (사이클 132 확정)
RS_HI = 0.9      # RS 상한 (사이클 132 확정)
TP = 0.10        # take profit
SL = 0.010       # stop loss
MAX_HOLD = 24    # max hold bars
ACC_MIN = 1.0    # alt acc threshold (사이클 134 확정)
FEE = 0.001      # 0.10% round-trip

CVD_WINDOW = 12  # cvd slope 계산 창 (4h×12 = 2일)

# 탐색 대상 역방향 cvd_slope 임계값 (None = OFF, 조건: cvd_slope < threshold)
CVD_CANDIDATES: list[float | None] = [None, -0.1, -0.2, -0.3, -0.5]

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


def compute_cvd_slope(df: pd.DataFrame) -> pd.Series:
    """
    CVD slope = CVD.diff(CVD_WINDOW) / (vol_ma * CVD_WINDOW)
    CVD per bar = volume * sign(close - open)
    음수 = 매도 압력 우세
    """
    direction = np.sign(df["close"] - df["open"])
    cvd_raw = df["volume"] * direction
    cvd_cumsum = cvd_raw.cumsum()
    vol_ma = df["volume"].rolling(CVD_WINDOW, min_periods=CVD_WINDOW).mean()
    slope = cvd_cumsum.diff(CVD_WINDOW) / (vol_ma.replace(0.0, np.nan) * CVD_WINDOW)
    return slope


def compute_btc_signal(
    df4h: pd.DataFrame,
    dfday: pd.DataFrame,
) -> pd.Series:
    """Gate 1+2: BTC>SMA10(daily) + BTC stealth(4h, W=36). Gate4=OFF."""
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
    cvd_threshold: float | None,
) -> pd.Series:
    """
    Gate 3: alt RS∈[RS_LO, RS_HI) + alt acc > ACC_MIN
    Gate 5 (optional): alt cvd_slope < cvd_threshold (역방향 — 강한 매도압력)
    """
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

    alt_gate = (rs >= RS_LO) & (rs < RS_HI) & (acc_v > ACC_MIN)

    if cvd_threshold is not None:
        cvd_slope = compute_cvd_slope(df_alt).reindex(df_alt.index)
        # 역방향: slope가 threshold보다 더 음수여야 함 (강한 매도압력)
        alt_gate = alt_gate & (cvd_slope < cvd_threshold)

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
    print("=== stealth_3gate 역방향 CVD slope 게이트 탐색 (사이클 136) ===")
    print(f"가설: 스텔스 진입 시점 CVD slope mean=-0.40 → 강한 매도압력이 오히려 스텔스 품질 지표")
    print(f"고정: W={W}, SMA={SMA_N}, RS=[{RS_LO},{RS_HI}), TP={TP*100:.0f}%, SL={SL*100:.1f}%, Gate4=OFF, acc>{ACC_MIN}")
    print(f"CVD 창: {CVD_WINDOW}봉 ({CVD_WINDOW*4}h)")
    print(f"탐색: cvd_slope < threshold, threshold ∈ {CVD_CANDIDATES}")
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

    # Evaluate each cvd_slope threshold
    print("\n[3/3] 역방향 cvd_slope 임계값 탐색...")
    results = []

    # CVD slope 분포 확인 (참고용)
    sample_slopes = []
    for sym, df in list(alt_raw.items())[:20]:
        cvd_s = compute_cvd_slope(df)
        # 스텔스 조건 만족 시점만
        c = df["close"]
        v = df["volume"]
        c_ma = c.rolling(W, min_periods=W).mean()
        v_ma = v.rolling(W, min_periods=W).mean()
        ret_w = c / c.shift(W)
        acc_v = (c / c_ma.replace(0.0, np.nan)) * (v / v_ma.replace(0.0, np.nan))
        stealth_mask = (ret_w < 1.0) & (acc_v > ACC_MIN)
        vals = cvd_s[stealth_mask].dropna().values
        if len(vals) > 0:
            sample_slopes.extend(vals.tolist())
    if sample_slopes:
        arr = np.array(sample_slopes)
        print(f"\n  [참고] 알트 스텔스 진입 시점 CVD slope 분포 (n={len(arr)}, 20개 심볼 샘플):")
        print(f"    mean={arr.mean():.3f}, std={arr.std():.3f}, "
              f"p10={np.percentile(arr,10):.3f}, p25={np.percentile(arr,25):.3f}, "
              f"p50={np.percentile(arr,50):.3f}, p75={np.percentile(arr,75):.3f}")
        print(f"    (음수 비율: {(arr<0).mean():.1%})")

    for cvd_thresh in CVD_CANDIDATES:
        # Compute alt entry signals
        alt_signals: dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
        for sym, df in alt_raw.items():
            entry = compute_alt_entry(df, df_btc4h, btc_sig, cvd_thresh)
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
        label_str = "None(OFF)" if cvd_thresh is None else f"< {cvd_thresh:.1f}"
        results.append({
            "label": label_str,
            "cvd_thresh": cvd_thresh,
            "alt_syms": len(alt_signals),
            "w1_sharpe": w1_sh, "w1_n": w1.get("n", 0), "w1_wr": w1.get("wr", float("nan")),
            "w2_sharpe": w2_sh, "w2_n": w2.get("n", 0), "w2_wr": w2.get("wr", float("nan")),
            "passed": passed,
        })

        flag = "✅" if passed else "  "
        print(
            f"\n{flag} cvd_slope {label_str}"
            f"\n   alt 심볼: {len(alt_signals)}"
            f"\n   W1: Sharpe={w1_sh:.3f}  n={w1.get('n',0):4d}  WR={w1.get('wr', float('nan')):.3f}"
            f"\n   W2: Sharpe={w2_sh:.3f}  n={w2.get('n',0):4d}  WR={w2.get('wr', float('nan')):.3f}"
        )

    # Summary table
    print("\n=== 결과 요약 ===")
    print(f"{'cvd_thresh':<14} {'alt_syms':>9} {'W1 Sharpe':>10} {'W1 n':>6} {'W2 Sharpe':>10} {'W2 n':>6} {'W2 WR':>7} {'통과':>5}")
    print("-" * 80)
    baseline_w2 = None
    best = None
    for r in results:
        flag = "✅" if r["passed"] else "  "
        if r["cvd_thresh"] is None:
            baseline_w2 = r["w2_sharpe"]
        print(
            f"{r['label']:<14} {r['alt_syms']:>9d} "
            f"{r['w1_sharpe']:>10.3f} {r['w1_n']:>6d} "
            f"{r['w2_sharpe']:>10.3f} {r['w2_n']:>6d} "
            f"{r['w2_wr']:>7.3f} {flag:>5}"
        )
        if r["passed"] and (best is None or r["w2_sharpe"] > best["w2_sharpe"]):
            best = r

    # Recommendation
    print("\n=== 권고 ===")
    if baseline_w2 is not None:
        if best is not None and best["cvd_thresh"] is not None:
            delta = best["w2_sharpe"] - baseline_w2
            if delta > 0.3:
                print(f"cvd_slope {best['label']} 추가 권장 (W2 Sharpe +{delta:.3f} vs 베이스라인 {baseline_w2:.3f})")
                print(f"  → 역방향 CVD slope이 스텔스 품질 필터로 유효")
            else:
                print(f"cvd_slope {best['label']} 미미하게 우세 (델타 {delta:+.3f}) — 현재 설정 유지 권장")
        else:
            print("통과 후보 없음 or 현재 설정(None)이 최선 — cvd_slope 역방향 필터도 스텔스와 incompatible")
    else:
        print("베이스라인 없음 — 결과 확인 필요")

    print(f"\n총 소요: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
