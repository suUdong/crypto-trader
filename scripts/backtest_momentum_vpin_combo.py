"""
momentum_vpin_combo 4h 그리드 탐색
- 가설: momentum 진입 시 VPIN 급등 필터 추가 → 노이즈 진입 감소
- SOL 최적(Sharpe +14.37) 파라미터를 베이스로 VPIN 임계값 탐색
- 심볼: SOL, ETH, APT, LINK, SUI (btc_dip_alt_entry 양수 심볼)
- 기간: 2022-01-01 ~ 2026-04-03
- 그리드: vpin_threshold × momentum_lookback × TP × SL
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

START  = "2022-01-01"
END    = "2026-04-03"
FEE    = 0.0005

SYMBOLS = ["KRW-SOL", "KRW-ETH", "KRW-APT", "KRW-LINK", "KRW-SUI"]

# ── 고정값 (momentum_sol 최적 기반) ───────────────────────────────────────────
ADX_THRESH      = 25.0
VOL_MULT        = 2.0
ENTRY_THRESHOLD = 0.005
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 75.0
MAX_HOLD        = 48
VPIN_BUCKET     = 24

# ── 그리드 ─────────────────────────────────────────────────────────────────────
VPIN_THRESH_LIST  = [0.55, 0.60, 0.65, 0.70, 0.75]
LOOKBACK_LIST     = [12, 16, 20]
TP_LIST           = [0.08, 0.10, 0.12]
SL_LIST           = [0.03, 0.04]


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
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr  = np.maximum(highs[1:] - lows[1:],
          np.maximum(np.abs(highs[1:] - closes[:-1]),
                     np.abs(lows[1:]  - closes[:-1])))
    dm_p = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
                    np.maximum(highs[1:] - highs[:-1], 0.0), 0.0)
    dm_m = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
                    np.maximum(lows[:-1] - lows[1:], 0.0), 0.0)
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period-1] = tr[:period].sum()
    dip_s[period-1] = dm_p[:period].sum()
    dim_s[period-1] = dm_m[:period].sum()
    for i in range(period, n - 1):
        atr_s[i] = atr_s[i-1] - atr_s[i-1] / period + tr[i]
        dip_s[i] = dip_s[i-1] - dip_s[i-1] / period + dm_p[i]
        dim_s[i] = dim_s[i-1] - dim_s[i-1] / period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dip_s / (atr_s + 1e-9)
        di_m = 100 * dim_s / (atr_s + 1e-9)
        dx   = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2*period-2] = dx[period-1:2*period-1].mean()
    for i in range(2*period-1, n-1):
        adx_vals[i] = (adx_vals[i-1] * (period-1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


def compute_vpin(closes: np.ndarray, opens: np.ndarray, bucket_count: int = 24) -> np.ndarray:
    """Simplified VPIN: |close-open| / (high-low) proxy, rolling average."""
    price_range = np.abs(closes - opens) + 1e-9
    candle_move = np.abs(closes - opens)
    vpin_proxy  = candle_move / price_range
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i-bucket_count:i].mean()
    return result


def backtest(
    df: pd.DataFrame,
    vpin_thresh: float,
    lookback: int,
    tp: float,
    sl: float,
) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    o  = df["open"].values
    v  = df["volume"].values
    n  = len(c)

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n-lookback] - 1.0

    rsi_arr  = rsi(c, RSI_PERIOD)
    adx_arr  = adx(h, lo, c, 14)
    vpin_arr = compute_vpin(c, o, VPIN_BUCKET)

    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = max(VPIN_BUCKET, lookback, RSI_PERIOD + 1) + 28
    i = warmup
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > ADX_THRESH
            and vol_ok[i]
            and not np.isnan(vpin_arr[i]) and vpin_arr[i] > vpin_thresh  # VPIN 필터
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
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def main() -> None:
    print("=== momentum_vpin_combo 4h 그리드 탐색 ===")
    print(f"기간: {START} ~ {END}  |  ADX≥{ADX_THRESH}  VOL×{VOL_MULT}  MAX_HOLD={MAX_HOLD}")
    print(f"심볼: {', '.join(SYMBOLS)}\n")

    combos = list(product(VPIN_THRESH_LIST, LOOKBACK_LIST, TP_LIST, SL_LIST))
    print(f"파라미터 조합: {len(combos)}개 × {len(SYMBOLS)}심볼 = {len(combos)*len(SYMBOLS)}회\n")

    all_results: list[dict] = []

    for symbol in SYMBOLS:
        df = load_historical(symbol, "240m", START, END)
        if df.empty:
            print(f"[SKIP] {symbol}: 데이터 없음")
            continue
        print(f"{symbol}: {len(df)}행 로드")

        for vt, lb, tp, sl in combos:
            r = backtest(df, vt, lb, tp, sl)
            all_results.append({
                "symbol": symbol,
                "vpin_thresh": vt,
                "lookback": lb,
                "tp": tp,
                "sl": sl,
                **r,
            })

    # ── 전체 Top 20 (Sharpe) ──────────────────────────────────────────────────
    all_results.sort(
        key=lambda x: (x["sharpe"] if not np.isnan(x["sharpe"]) else -99),
        reverse=True,
    )

    print("\n=== Top 20 (전체 Sharpe 기준) ===")
    hdr = f"{'symbol':<12} {'vpin':>5} {'lb':>3} {'TP':>5} {'SL':>5} | {'Sharpe':>7} {'WR':>6} {'avg%':>7} {'N':>5}"
    print(hdr)
    print("-" * len(hdr))
    for r in all_results[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "   nan"
        print(
            f"{r['symbol']:<12} {r['vpin_thresh']:>5.2f} {r['lookback']:>3} "
            f"{r['tp']:>5.2f} {r['sl']:>5.2f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret']*100:>+6.2f}% {r['trades']:>5}"
        )

    # ── 심볼별 최고 ───────────────────────────────────────────────────────────
    print("\n=== 심볼별 최고 Sharpe ===")
    for symbol in SYMBOLS:
        sym_res = [r for r in all_results if r["symbol"] == symbol]
        if not sym_res:
            print(f"  {symbol}: 결과 없음")
            continue
        best = sym_res[0]  # already sorted
        sh = f"{best['sharpe']:+.3f}" if not np.isnan(best["sharpe"]) else "nan"
        print(
            f"  {symbol}: Sharpe={sh}  WR={best['wr']:.1%}  avg={best['avg_ret']*100:+.2f}%  "
            f"N={best['trades']}  (vpin={best['vpin_thresh']} lb={best['lookback']} "
            f"TP={best['tp']} SL={best['sl']})"
        )

    # ── VPIN 임계값별 효과 분석 ───────────────────────────────────────────────
    print("\n=== VPIN 임계값별 평균 Sharpe (모든 심볼·파라미터 평균) ===")
    for vt in VPIN_THRESH_LIST:
        subset = [r["sharpe"] for r in all_results if r["vpin_thresh"] == vt and not np.isnan(r["sharpe"])]
        if subset:
            print(f"  vpin≥{vt:.2f}: avg_sharpe={np.mean(subset):+.3f}  n={len(subset)}")

    if all_results and not np.isnan(all_results[0]["sharpe"]):
        best = all_results[0]
        print(f"\n★ 전체 최적: {best['symbol']}  "
              f"vpin≥{best['vpin_thresh']}  lookback={best['lookback']}  "
              f"TP={best['tp']}  SL={best['sl']}")
        print(f"  Sharpe={best['sharpe']:+.3f}  WR={best['wr']:.1%}  "
              f"avg={best['avg_ret']*100:+.2f}%  trades={best['trades']}")


if __name__ == "__main__":
    main()
