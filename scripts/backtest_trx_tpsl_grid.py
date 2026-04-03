"""
TRX momentum TP/SL 파라미터 정밀화 (사이클 85)
- 목적: lb=12 adx=25 확정 TRX에서 최적 TP/SL 조합 선정
- 사이클 84 결과: lb=12 TP12 SL4(3/3✅), TP10 SL3(3/3✅) 모두 통과 → 정밀 비교 필요
- 그리드: TP=[8,10,12,15,20]% × SL=[2,3,4,5,6]%
- 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6
- 최종 목표: daemon pre-staging 파라미터 단일 확정
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-TRX"
FEE = 0.0005
ENTRY_THRESHOLD = 0.005
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
MAX_HOLD = 48

# 확정 파라미터 (사이클 84)
LOOKBACK = 12
ADX_THRESH = 25.0
VOL_MULT = 2.0

# TP/SL 그리드
TP_GRID = [0.08, 0.10, 0.12, 0.15, 0.20]
SL_GRID = [0.02, 0.03, 0.04, 0.05, 0.06]

WALK_FORWARD = {
    "name": "walk-forward",
    "is_start": "2022-01-01",
    "is_end": "2024-12-31",
    "oos_start": "2025-01-01",
    "oos_end": "2026-04-04",
}

SLIDING = [
    {"name": "W1", "is_start": "2022-01-01", "is_end": "2023-12-31",
     "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2023-01-01", "is_end": "2024-12-31",
     "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"name": "W3", "is_start": "2024-01-01", "is_end": "2025-12-31",
     "oos_start": "2026-01-01", "oos_end": "2026-04-04"},
]

OOS_SHARPE_MIN = 3.0
OOS_WR_MIN = 0.45
OOS_TRADES_MIN = 6


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


def backtest(df: pd.DataFrame, tp: float, sl: float) -> dict:
    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[: n - LOOKBACK] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_calc(h, lo, c, 14)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    i = LOOKBACK + RSI_PERIOD + 28
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i])
            and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i])
            and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i])
            and adx_arr[i] > ADX_THRESH
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


def main() -> None:
    print("=" * 70)
    print("TRX momentum TP/SL 파라미터 정밀화 (사이클 85)")
    print(f"심볼: {SYMBOL} | lb={LOOKBACK}, adx={ADX_THRESH}, vol={VOL_MULT}")
    print(f"TP 그리드: {[int(t*100) for t in TP_GRID]}%")
    print(f"SL 그리드: {[int(s*100) for s in SL_GRID]}%")
    print("=" * 70)

    # 데이터 로드
    wf = WALK_FORWARD
    df_is = load_historical(SYMBOL, "240m", wf["is_start"], wf["is_end"])
    df_oos = load_historical(SYMBOL, "240m", wf["oos_start"], wf["oos_end"])
    print(f"데이터: IS={len(df_is)}행 ({wf['is_start']}~{wf['is_end']}), "
          f"OOS={len(df_oos)}행 ({wf['oos_start']}~{wf['oos_end']})")

    if len(df_is) < 100 or len(df_oos) < 50:
        print("▶ 데이터 부족 — 중단")
        return

    # 슬라이딩 데이터 미리 로드
    slide_dfs = []
    for w in SLIDING:
        d = load_historical(SYMBOL, "240m", w["oos_start"], w["oos_end"])
        slide_dfs.append(d)
        print(f"슬라이딩 {w['name']} OOS={len(d)}행")

    print()

    # ━━━ PHASE 1: Walk-forward 그리드 ━━━
    print("━" * 70)
    print("PHASE 1: Walk-forward 그리드 (OOS=2025-2026)")
    print(f"{'TP':>4} {'SL':>4} | {'IS Sh':>8} {'IS WR':>7} {'IS T':>5} | "
          f"{'OOS Sh':>8} {'OOS WR':>7} {'OOS T':>6} | 판정")
    print("-" * 70)

    wf_passed: list[tuple[float, float, dict, dict]] = []  # (tp, sl, is_r, oos_r)

    for tp in TP_GRID:
        for sl in SL_GRID:
            is_r = backtest(df_is, tp, sl)
            oos_r = backtest(df_oos, tp, sl)
            pass_flag = (
                not np.isnan(oos_r["sharpe"])
                and oos_r["sharpe"] >= OOS_SHARPE_MIN
                and oos_r["wr"] >= OOS_WR_MIN
                and oos_r["trades"] >= OOS_TRADES_MIN
            )
            status = "✅" if pass_flag else "  "
            print(
                f"TP={int(tp*100):>2}% SL={int(sl*100):>2}% | "
                f"{is_r['sharpe']:+8.2f} {is_r['wr']:7.1%} {is_r['trades']:5d} | "
                f"{oos_r['sharpe']:+8.2f} {oos_r['wr']:7.1%} {oos_r['trades']:6d} | {status}"
            )
            if pass_flag:
                wf_passed.append((tp, sl, is_r, oos_r))

    print(f"\n▶ walk-forward 통과: {len(wf_passed)}개")

    if not wf_passed:
        print("❌ 전 후보 탈락")
        return

    # ━━━ PHASE 2: 슬라이딩 검증 ━━━
    print()
    print("━" * 70)
    print("PHASE 2: 슬라이딩 3구간 검증 (walk-forward 통과 후보만)")
    print()

    slide_results = []
    for tp, sl, is_r, oos_r in wf_passed:
        print(f"  TP={int(tp*100)}% SL={int(sl*100)}% (OOS Sh={oos_r['sharpe']:+.2f}, WR={oos_r['wr']:.1%})")
        slide_pass = 0
        slide_detail = []
        for w, df_s in zip(SLIDING, slide_dfs):
            s_r = backtest(df_s, tp, sl)
            ok = (
                not np.isnan(s_r["sharpe"])
                and s_r["sharpe"] >= OOS_SHARPE_MIN
                and s_r["wr"] >= OOS_WR_MIN
                and s_r["trades"] >= OOS_TRADES_MIN
            )
            if ok:
                slide_pass += 1
            status = "✅" if ok else "❌"
            print(f"    {w['name']} {w['oos_start'][:4]}: {status} Sh={s_r['sharpe']:+.2f} WR={s_r['wr']:.1%} T={s_r['trades']}")
            slide_detail.append({"window": w["name"], "ok": ok, **s_r})

        verdict = "◆ 이중통과" if slide_pass == 3 else ("조건부" if slide_pass >= 2 else "탈락")
        print(f"    → {slide_pass}/3 {verdict}")
        print()
        slide_results.append({
            "tp": tp, "sl": sl,
            "wf_sharpe": oos_r["sharpe"], "wf_wr": oos_r["wr"], "wf_trades": oos_r["trades"],
            "slide_pass": slide_pass, "verdict": verdict,
            "detail": slide_detail,
        })

    # ━━━ 최종 요약 ━━━
    print("━" * 70)
    print("최종 결과 요약")
    print(f"{'TP':>4} {'SL':>4} | {'WF Sh':>8} {'WF WR':>7} | {'슬라이딩':>8} | 판정")
    print("-" * 50)

    best = None
    for r in sorted(slide_results, key=lambda x: (-x["slide_pass"], -x["wf_sharpe"])):
        print(
            f"TP={int(r['tp']*100):>2}% SL={int(r['sl']*100):>2}% | "
            f"{r['wf_sharpe']:+8.2f} {r['wf_wr']:7.1%} | "
            f"{r['slide_pass']}/3 {'★' if r['slide_pass']==3 else ' ':>3} | {r['verdict']}"
        )
        if best is None and r["slide_pass"] >= 2:
            best = r

    print()
    if best:
        print(f"★ 추천 파라미터: TP={int(best['tp']*100)}%, SL={int(best['sl']*100)}%")
        print(f"  WF OOS Sharpe={best['wf_sharpe']:+.2f}, WR={best['wf_wr']:.1%}, 슬라이딩={best['slide_pass']}/3")
        print()
        print("daemon pre-staging (TRX):")
        print(f"  lb={LOOKBACK}, adx={ADX_THRESH}, vol_mult={VOL_MULT}")
        print(f"  TP={int(best['tp']*100)}%, SL={int(best['sl']*100)}%")
    else:
        print("❌ 슬라이딩 2/3 이상 통과 후보 없음")


if __name__ == "__main__":
    main()
