"""
잔여 상위 유동성 심볼 L1 momentum walk-forward 스크리닝 (사이클 87)
- 목적: BNB/LTC 데이터 없음 → LINK/NEAR/HBAR/INJ 대체 스크리닝
         L1 momentum edge 후보 풀 소진 마지막 확인
- 심볼: KRW-LINK, KRW-NEAR, KRW-HBAR, KRW-INJ
- 설정: 4h봉, walk-forward (IS=2022-2024 / OOS=2025-2026)
- 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6
- 슬라이딩: walk-forward 통과 후보만 3구간 검증
- 참고: SOL/ETH/XRP/TRX 이중통과 확정, BCH/DOGE/ADA/AVAX/ATOM/DOT 탈락
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005
ENTRY_THRESHOLD = 0.005
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
MAX_HOLD = 48

WINDOWS = [
    {
        "name": "walk-forward",
        "is_start": "2022-01-01",
        "is_end": "2024-12-31",
        "oos_start": "2025-01-01",
        "oos_end": "2026-04-04",
    },
]

SLIDING = [
    {
        "name": "W1",
        "is_start": "2022-01-01",
        "is_end": "2023-12-31",
        "oos_start": "2024-01-01",
        "oos_end": "2024-12-31",
    },
    {
        "name": "W2",
        "is_start": "2023-01-01",
        "is_end": "2024-12-31",
        "oos_start": "2025-01-01",
        "oos_end": "2025-12-31",
    },
    {
        "name": "W3",
        "is_start": "2024-01-01",
        "is_end": "2025-12-31",
        "oos_start": "2026-01-01",
        "oos_end": "2026-04-04",
    },
]

CANDIDATES = [
    {"lookback": 12, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "lb=12 adx=25 (SOL/ETH/TRX 기준)"},
    {"lookback": 8,  "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "lb=8  adx=25 (XRP 기준)"},
    {"lookback": 12, "adx": 25.0, "vol_mult": 2.0, "tp": 0.10, "sl": 0.03, "label": "lb=12 adx=25 TP10 SL3"},
    {"lookback": 16, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "lb=16 adx=25"},
    {"lookback": 20, "adx": 20.0, "vol_mult": 1.5, "tp": 0.15, "sl": 0.05, "label": "lb=20 adx=20 TP15 SL5"},
]

SYMBOLS = ["KRW-LINK", "KRW-NEAR", "KRW-HBAR", "KRW-INJ"]


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def adx_calc(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
    )
    dm_p = np.where(
        (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
        np.maximum(highs[1:] - highs[:-1], 0.0),
        0.0,
    )
    dm_m = np.where(
        (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
        np.maximum(lows[:-1] - lows[1:], 0.0),
        0.0,
    )
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period - 1] = tr[:period].sum()
    dip_s[period - 1] = dm_p[:period].sum()
    dim_s[period - 1] = dm_m[:period].sum()
    for i in range(period, n - 1):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        dip_s[i] = dip_s[i - 1] - dip_s[i - 1] / period + dm_p[i]
        dim_s[i] = dim_s[i - 1] - dim_s[i - 1] / period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dip_s / (atr_s + 1e-9)
        di_m = 100 * dim_s / (atr_s + 1e-9)
        dx = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2 * period - 2] = dx[period - 1 : 2 * period - 1].mean()
    for i in range(2 * period - 1, n - 1):
        adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


def backtest(df: pd.DataFrame, lookback: int, adx_thresh: float, vol_mult: float, tp: float, sl: float) -> dict:
    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[: n - lookback] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_calc(h, lo, c, 14)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > vol_mult * vol_ma

    returns: list[float] = []
    i = lookback + RSI_PERIOD + 28
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i])
            and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i])
            and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i])
            and adx_arr[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE)
                    i = j
                    break
                if ret <= -sl:
                    returns.append(-sl - FEE)
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def run_symbol(symbol: str) -> dict:
    print(f"\n{'='*70}")
    print(f"심볼: {symbol}")
    print(f"{'='*70}")

    OOS_SHARPE_MIN = 3.0
    OOS_WR_MIN = 0.45
    OOS_TRADES_MIN = 6

    # Walk-forward 먼저
    wf = WINDOWS[0]
    print(f"\n[WALK-FORWARD] IS={wf['is_start']}~{wf['is_end']} / OOS={wf['oos_start']}~{wf['oos_end']}")
    df_is = load_historical(symbol, "240m", wf["is_start"], wf["is_end"])
    df_oos = load_historical(symbol, "240m", wf["oos_start"], wf["oos_end"])
    print(f"  IS={len(df_is)}행, OOS={len(df_oos)}행")

    if len(df_is) < 100 or len(df_oos) < 50:
        print(f"  ▶ {symbol} 데이터 부족 — 스킵")
        return {"symbol": symbol, "verdict": "데이터부족", "best_cand": None}

    wf_results = []
    for cand in CANDIDATES:
        is_r = backtest(df_is, cand["lookback"], cand["adx"], cand["vol_mult"], cand["tp"], cand["sl"])
        oos_r = backtest(df_oos, cand["lookback"], cand["adx"], cand["vol_mult"], cand["tp"], cand["sl"])
        pass_flag = (
            not np.isnan(oos_r["sharpe"])
            and oos_r["sharpe"] >= OOS_SHARPE_MIN
            and oos_r["wr"] >= OOS_WR_MIN
            and oos_r["trades"] >= OOS_TRADES_MIN
        )
        wf_results.append((cand, is_r, oos_r, pass_flag))
        status = "✅ PASS" if pass_flag else "❌ FAIL"
        print(
            f"  {cand['label']:40s} | IS Sh={is_r['sharpe']:+.2f} | "
            f"OOS Sh={oos_r['sharpe']:+.2f} WR={oos_r['wr']:.1%} T={oos_r['trades']} | {status}"
        )

    passed = [(c, ir, oor) for c, ir, oor, p in wf_results if p]
    if not passed:
        print(f"\n  ▶ {symbol} walk-forward 전 후보 탈락 — 슬라이딩 검증 생략")
        return {"symbol": symbol, "verdict": "탈락", "best_cand": None}

    print(f"\n  ▶ walk-forward 통과 {len(passed)}개 → 슬라이딩 검증 진행")

    best_result: dict = {"symbol": symbol, "verdict": "탈락", "best_cand": None, "slide_pass": 0}

    # 슬라이딩 검증 (walk-forward 통과 후보만)
    for cand, _, oor in passed:
        print(f"\n  [슬라이딩] {cand['label']}")
        slide_pass = 0
        for w in SLIDING:
            df_oos_s = load_historical(symbol, "240m", w["oos_start"], w["oos_end"])
            oos_r = backtest(df_oos_s, cand["lookback"], cand["adx"], cand["vol_mult"], cand["tp"], cand["sl"])
            ok = (
                not np.isnan(oos_r["sharpe"])
                and oos_r["sharpe"] >= OOS_SHARPE_MIN
                and oos_r["wr"] >= OOS_WR_MIN
                and oos_r["trades"] >= OOS_TRADES_MIN
            )
            if ok:
                slide_pass += 1
            status = "✅" if ok else "❌"
            print(f"    {w['name']} OOS={w['oos_start'][:4]}: {status} Sh={oos_r['sharpe']:+.2f} WR={oos_r['wr']:.1%} T={oos_r['trades']}")

        if slide_pass >= 3:
            verdict = "◆ 이중 통과 ★★"
        elif slide_pass >= 2:
            verdict = "◆ 조건부 채택"
        else:
            verdict = "✗ 탈락"
        print(f"    슬라이딩 결과: {slide_pass}/3 → {verdict}")

        if slide_pass >= 2 and slide_pass > best_result.get("slide_pass", 0):
            best_result = {
                "symbol": symbol,
                "verdict": "이중통과" if slide_pass >= 3 else "조건부채택",
                "best_cand": cand,
                "slide_pass": slide_pass,
                "oos_sharpe": oor["sharpe"],
                "oos_wr": oor["wr"],
                "oos_trades": oor["trades"],
            }

    return best_result


def main() -> None:
    print("=" * 70)
    print("잔여 상위 유동성 심볼 L1 momentum walk-forward 스크리닝 (사이클 87)")
    print("목적: BNB/LTC 데이터 없음 → LINK/NEAR/HBAR/INJ 대체 검증")
    print("      L1 momentum edge 후보 풀 소진 마지막 확인")
    print("확정 심볼: SOL/ETH/XRP/TRX (이중통과)")
    print("탈락 심볼: BCH/DOGE/ADA/AVAX/ATOM/DOT")
    print("기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6")
    print("=" * 70)

    summary = []
    for symbol in SYMBOLS:
        result = run_symbol(symbol)
        summary.append(result)

    print("\n" + "=" * 70)
    print("최종 요약")
    print("=" * 70)
    for r in summary:
        symbol = r["symbol"]
        verdict = r["verdict"]
        if r.get("best_cand"):
            c = r["best_cand"]
            print(
                f"  {symbol:12s} → {verdict} | {c['label']} | "
                f"slide={r['slide_pass']}/3 | OOS Sh={r.get('oos_sharpe', 0):+.2f} WR={r.get('oos_wr', 0):.1%}"
            )
        else:
            print(f"  {symbol:12s} → {verdict}")
    print("=" * 70)

    passed = [r for r in summary if r.get("best_cand")]
    if passed:
        print(f"\n⚡ 신규 채택 후보 {len(passed)}개 발견!")
        for r in passed:
            print(f"   → {r['symbol']} ({r['verdict']})")
    else:
        print("\n✓ 모든 심볼 탈락 — L1 momentum edge = SOL/ETH/XRP/TRX 4개 확정")
    print("=" * 70)


if __name__ == "__main__":
    main()
