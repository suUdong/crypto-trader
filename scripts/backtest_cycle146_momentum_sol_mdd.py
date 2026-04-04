"""
momentum_sol MDD/drawdown 정밀 분석 + 멀티심볼 검증
- W1 최적 파라미터로 MDD, 최대연속손실, 월별 수익분포 분석
- SOL 외 ETH/XRP/SUI 동일 파라미터 검증 → 범용성 확인
- 사이클 146
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

START = "2022-01-01"
END   = "2026-12-31"
FEE   = 0.0005

# ── W1 최적 파라미터 (momentum_sol_grid 결과) ────────────────────────────────
LOOKBACK        = 20
ADX_THRESHOLD   = 20.0
VOL_MULT        = 1.5
TP              = 0.08
SL              = 0.03
ENTRY_THRESHOLD = 0.005
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 75.0
MAX_HOLD        = 48

# 추가 파라미터 그리드 — TP/SL 미세 조정으로 MDD 개선 탐색
TP_FINE = [0.06, 0.07, 0.08, 0.09, 0.10]
SL_FINE = [0.02, 0.025, 0.03, 0.035]

SYMBOLS = ["KRW-SOL", "KRW-ETH", "KRW-XRP", "KRW-SUI"]


# ── 지표 ──────────────────────────────────────────────────────────────────────

def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
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


def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    dm_p = np.where(
        (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
        np.maximum(highs[1:] - highs[:-1], 0.0), 0.0,
    )
    dm_m = np.where(
        (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
        np.maximum(lows[:-1] - lows[1:], 0.0), 0.0,
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
        dx   = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2 * period - 2] = dx[period - 1:2 * period - 1].mean()
    for i in range(2 * period - 1, n - 1):
        adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


# ── 백테스트 (상세 트레이드 기록) ─────────────────────────────────────────────

def backtest_detailed(
    df: pd.DataFrame,
    lookback: int,
    adx_thresh: float,
    vol_mult: float,
    tp: float,
    sl: float,
) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    v  = df["volume"].values
    n  = len(c)
    idx = df.index

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n - lookback] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx(h, lo, c, 14)
    vol_ma  = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok  = v > vol_mult * vol_ma

    trades: list[dict] = []
    i = lookback + RSI_PERIOD + 28
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            entry_time = idx[i]
            ret = 0.0
            exit_j = i + 1
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    ret = tp - FEE
                    exit_j = j
                    break
                if ret <= -sl:
                    ret = -sl - FEE
                    exit_j = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                ret = c[hold_end] / buy - 1 - FEE
                exit_j = hold_end
            trades.append({
                "entry": entry_time, "exit": idx[exit_j],
                "ret": ret, "bars_held": exit_j - i,
            })
            i = exit_j
        else:
            i += 1

    if len(trades) < 3:
        return {
            "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
            "trades": 0, "max_dd": 0.0, "max_consec_loss": 0,
            "trade_list": [],
        }

    rets = np.array([t["ret"] for t in trades])
    sh   = float(rets.mean() / (rets.std() + 1e-9) * np.sqrt(252 * 6))
    wr   = float((rets > 0).mean())
    cum  = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(cum)
    dd   = (cum - peak) / peak
    max_dd = float(dd.min())

    # 최대 연속 손실
    max_consec = 0
    cur_consec = 0
    for r in rets:
        if r < 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(rets.mean()),
        "trades": len(rets), "max_dd": max_dd,
        "max_consec_loss": max_consec, "trade_list": trades,
    }


def print_monthly_pnl(trades: list[dict]) -> None:
    if not trades:
        return
    df = pd.DataFrame(trades)
    df["month"] = pd.to_datetime(df["entry"]).dt.to_period("M")
    monthly = df.groupby("month").agg(
        count=("ret", "count"),
        mean_ret=("ret", "mean"),
        total_ret=("ret", "sum"),
        wr=("ret", lambda x: (x > 0).mean()),
    )
    print("\n=== 월별 수익 분포 ===")
    print(f"{'월':>10} {'거래수':>6} {'평균%':>8} {'합산%':>8} {'WR':>6}")
    print("-" * 45)
    for period, row in monthly.iterrows():
        print(
            f"{str(period):>10} {int(row['count']):>6} "
            f"{row['mean_ret']*100:>+7.2f}% {row['total_ret']*100:>+7.2f}% "
            f"{row['wr']:>5.1%}"
        )


def main() -> None:
    print("=== momentum_sol MDD/drawdown 분석 + 멀티심볼 검증 (사이클 146) ===\n")

    # ── Part 1: SOL 기본 파라미터 상세 분석 ───────────────────────────────────
    print(f"[Part 1] KRW-SOL 상세 분석 (lb={LOOKBACK} adx={ADX_THRESHOLD} "
          f"vol={VOL_MULT} TP={TP} SL={SL})")
    df_sol = load_historical("KRW-SOL", "240m", START, END)
    if df_sol.empty:
        print("SOL 데이터 없음.")
        return
    print(f"데이터: {len(df_sol)}행\n")

    r = backtest_detailed(df_sol, LOOKBACK, ADX_THRESHOLD, VOL_MULT, TP, SL)
    sh_str = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "nan"
    print(f"  Sharpe: {sh_str}")
    print(f"  WR: {r['wr']:.1%}")
    print(f"  trades: {r['trades']}")
    print(f"  avg_ret: {r['avg_ret']*100:+.2f}%")
    print(f"  MDD: {r['max_dd']*100:+.1f}%")
    print(f"  최대연속손실: {r['max_consec_loss']}회")

    print_monthly_pnl(r["trade_list"])

    # ── Part 2: TP/SL fine-grid → MDD 개선 탐색 ──────────────────────────────
    print(f"\n\n[Part 2] TP/SL fine-grid → MDD 최소화 (Sharpe ≥ 10.0 유지)")
    print(f"{'TP':>5} {'SL':>6} | {'Sharpe':>7} {'WR':>6} {'avg%':>7} "
          f"{'MDD':>7} {'CL':>4} {'trades':>7}")
    print("-" * 65)

    grid_results: list[dict] = []
    for tp, sl in sorted(product(TP_FINE, SL_FINE)):
        r2 = backtest_detailed(df_sol, LOOKBACK, ADX_THRESHOLD, VOL_MULT, tp, sl)
        grid_results.append({"tp": tp, "sl": sl, **r2})
        sh = f"{r2['sharpe']:+.3f}" if not np.isnan(r2["sharpe"]) else "  nan"
        print(
            f"{tp:>5.2f} {sl:>6.3f} | {sh:>7} {r2['wr']:>5.1%} "
            f"{r2['avg_ret']*100:>+6.2f}% {r2['max_dd']*100:>+6.1f}% "
            f"{r2['max_consec_loss']:>4} {r2['trades']:>7}"
        )

    # MDD 기준 정렬 (Sharpe ≥ 10 필터)
    viable = [
        g for g in grid_results
        if not np.isnan(g["sharpe"]) and g["sharpe"] >= 10.0
    ]
    if viable:
        viable.sort(key=lambda x: x["max_dd"], reverse=True)  # max_dd is negative
        best_mdd = viable[0]
        print(f"\n★ MDD 최적 (Sharpe≥10): TP={best_mdd['tp']} SL={best_mdd['sl']}")
        print(f"  Sharpe: {best_mdd['sharpe']:+.3f}  MDD: {best_mdd['max_dd']*100:+.1f}%")
    else:
        print("\n⚠️ Sharpe ≥ 10.0 조합 없음 — 임계값 완화 필요")

    # ── Part 3: 멀티심볼 검증 ─────────────────────────────────────────────────
    print(f"\n\n[Part 3] 멀티심볼 검증 (동일 파라미터)")
    print(f"{'심볼':>10} | {'Sharpe':>7} {'WR':>6} {'avg%':>7} "
          f"{'MDD':>7} {'CL':>4} {'trades':>7}")
    print("-" * 60)

    for sym in SYMBOLS:
        try:
            df_sym = load_historical(sym, "240m", START, END)
        except FileNotFoundError:
            print(f"{sym:>10} | 데이터 없음")
            continue
        if df_sym.empty:
            print(f"{sym:>10} | 데이터 없음")
            continue
        r3 = backtest_detailed(df_sym, LOOKBACK, ADX_THRESHOLD, VOL_MULT, TP, SL)
        sh = f"{r3['sharpe']:+.3f}" if not np.isnan(r3["sharpe"]) else "  nan"
        print(
            f"{sym:>10} | {sh:>7} {r3['wr']:>5.1%} "
            f"{r3['avg_ret']*100:>+6.2f}% {r3['max_dd']*100:>+6.1f}% "
            f"{r3['max_consec_loss']:>4} {r3['trades']:>7}"
        )

    print("\n✅ 분석 완료 — 비중 확대 판단 기준:")
    print("   MDD ≤ -15% → 1슬롯 유지")
    print("   MDD ≤ -10% & Sharpe ≥ 12 → 2슬롯 가능")
    print("   멀티심볼 2개+ Sharpe ≥ 5.0 → 범용 momentum 전략 후보")


if __name__ == "__main__":
    main()
