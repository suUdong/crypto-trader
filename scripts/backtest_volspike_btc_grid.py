"""
volspike_btc 파라미터 그리드 탐색
- KRW-BTC, 4h봉, 2022~2026
- 현재: spike_mult=2.0, adx=20, TP=6%, SL=3%, hold=36, body_ratio=0.2
- 목표: Sharpe 개선 (현재 0.66)
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-BTC"
START  = "2022-01-01"
END    = "2026-04-03"
FEE    = 0.0005

# 그리드
SPIKE_MULT_LIST  = [1.5, 2.0, 2.5, 3.0]
ADX_LIST         = [15.0, 20.0, 25.0, 30.0]
BODY_RATIO_LIST  = [0.1, 0.2, 0.3]
TP_LIST          = [0.04, 0.06, 0.08, 0.10]
SL_LIST          = [0.02, 0.03, 0.04]

VOL_WINDOW   = 20
MOM_LOOKBACK = 12
RSI_PERIOD   = 14
RSI_OB       = 72.0
MAX_HOLD     = 36


def rsi(closes: np.ndarray, period: int) -> np.ndarray:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    ag = np.full(len(closes), np.nan)
    al = np.full(len(closes), np.nan)
    if len(gains) < period:
        return ag
    ag[period] = gains[:period].mean()
    al[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        ag[i] = (ag[i-1] * (period - 1) + gains[i-1]) / period
        al[i] = (al[i-1] * (period - 1) + losses[i-1]) / period
    rs = np.where(al == 0, 100.0, ag / (al + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def adx_calc(highs, lows, closes, period=14):
    n = len(closes)
    result = np.full(n, np.nan)
    if n < period * 2:
        return result
    tr  = np.maximum(highs[1:]-lows[1:], np.maximum(
          np.abs(highs[1:]-closes[:-1]), np.abs(lows[1:]-closes[:-1])))
    dm_p = np.where((highs[1:]-highs[:-1]) > (lows[:-1]-lows[1:]),
                    np.maximum(highs[1:]-highs[:-1], 0.0), 0.0)
    dm_m = np.where((lows[:-1]-lows[1:]) > (highs[1:]-highs[:-1]),
                    np.maximum(lows[:-1]-lows[1:], 0.0), 0.0)
    atr = np.full(n-1, np.nan); dip = atr.copy(); dim = atr.copy()
    atr[period-1] = tr[:period].sum()
    dip[period-1] = dm_p[:period].sum()
    dim[period-1] = dm_m[:period].sum()
    for i in range(period, n-1):
        atr[i] = atr[i-1] - atr[i-1]/period + tr[i]
        dip[i] = dip[i-1] - dip[i-1]/period + dm_p[i]
        dim[i] = dim[i-1] - dim[i-1]/period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100*dip/(atr+1e-9); di_m = 100*dim/(atr+1e-9)
        dx   = 100*np.abs(di_p-di_m)/(di_p+di_m+1e-9)
    adx_v = np.full(n-1, np.nan)
    adx_v[2*period-2] = dx[period-1:2*period-1].mean()
    for i in range(2*period-1, n-1):
        adx_v[i] = (adx_v[i-1]*(period-1) + dx[i]) / period
    result[1:] = adx_v
    return result


def backtest(df, spike_mult, adx_thresh, body_ratio_min, tp, sl):
    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    op = df["open"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[MOM_LOOKBACK:] = c[MOM_LOOKBACK:] / c[:n-MOM_LOOKBACK] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_calc(h, lo, c, 14)
    vol_ma  = pd.Series(v).rolling(VOL_WINDOW, min_periods=VOL_WINDOW).mean().values

    returns = []
    i = max(RSI_PERIOD + 28, VOL_WINDOW + 1)
    while i < n - 1:
        if np.isnan(vol_ma[i]) or vol_ma[i] <= 0:
            i += 1; continue

        vol_ratio = v[i] / vol_ma[i]
        candle_range = h[i] - lo[i]
        body = (c[i] - op[i]) / candle_range if candle_range > 0 else 0.0

        entry_ok = (
            vol_ratio >= spike_mult
            and body >= body_ratio_min
            and not np.isnan(mom[i]) and mom[i] > 0
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OB
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_thresh
        )
        if entry_ok:
            buy = c[i+1] * (1 + FEE)
            for j in range(i+2, min(i+1+MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE); i = j; break
                if ret <= -sl:
                    returns.append(-sl - FEE); i = j; break
            else:
                hold_end = min(i+MAX_HOLD, n-1)
                returns.append(c[hold_end]/buy - 1 - FEE)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg": 0.0, "trades": 0, "mdd": 0.0}

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std()+1e-9) * np.sqrt(252*6))
    wr = float((arr > 0).mean())

    # MDD
    eq = np.cumprod(1 + arr)
    eq = np.concatenate([[1.0], eq])
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq-peak)/(peak+1e-9)).min())

    return {"sharpe": sh, "wr": wr, "avg": float(arr.mean()), "trades": len(arr), "mdd": mdd}


def main():
    print("=== volspike_btc 4h 그리드 탐색 ===")
    df = load_historical(SYMBOL, "240m", START, END)
    if df.empty:
        print("데이터 없음"); return
    print(f"데이터: {len(df)}봉\n")

    combos = list(product(SPIKE_MULT_LIST, ADX_LIST, BODY_RATIO_LIST, TP_LIST, SL_LIST))
    print(f"총 {len(combos)}조합 실행 중...")

    results = []
    for sm, adx_t, br, tp, sl in combos:
        r = backtest(df, sm, adx_t, br, tp, sl)
        results.append({"spike": sm, "adx": adx_t, "body": br, "tp": tp, "sl": sl, **r})

    results.sort(key=lambda x: x["sharpe"] if not np.isnan(x["sharpe"]) else -99, reverse=True)

    print(f"\n{'spike':>6} {'adx':>5} {'body':>5} {'TP':>5} {'SL':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'trades':>7} {'MDD':>7}")
    print("-" * 80)
    for r in results[:15]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "   nan"
        print(f"{r['spike']:>6.1f} {r['adx']:>5.0f} {r['body']:>5.1f} {r['tp']:>5.2f} {r['sl']:>5.2f} | "
              f"{sh:>7} {r['wr']:>5.1%} {r['avg']*100:>+6.2f}% {r['trades']:>7} {r['mdd']*100:>+6.1f}%")

    best = results[0]
    print(f"\n★ 최적: spike={best['spike']} adx={best['adx']} body={best['body']} "
          f"TP={best['tp']:.0%} SL={best['sl']:.0%}")
    print(f"  Sharpe={best['sharpe']:+.3f}  WR={best['wr']:.1%}  avg={best['avg']*100:+.2f}%  "
          f"trades={best['trades']}  MDD={best['mdd']*100:+.1f}%")

    # 현재 daemon 파라미터
    cur = next((r for r in results
                if r["spike"]==2.0 and r["adx"]==20.0 and r["body"]==0.2
                and r["tp"]==0.06 and r["sl"]==0.03), None)
    if cur:
        print(f"\n현재 daemon: Sharpe={cur['sharpe']:+.3f}  WR={cur['wr']:.1%}  trades={cur['trades']}")

    # backtest_history 기록
    _save_history(best, cur)
    print("\n결과 저장 완료 → docs/backtest_history.md")


def _save_history(best, cur):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n## {now} — volspike_btc 4h 파라미터 그리드 탐색\n\n"]
    lines.append("**설정**: KRW-BTC, 2022~2026, 4h봉, 수수료 0.05%  \n")
    lines.append("**그리드**: spike_mult×adx×body_ratio×TP×SL = 576조합\n\n")

    lines.append("### 결과 Top-5 (Sharpe 기준)\n\n")
    lines.append("| spike | adx | body | TP | SL | Sharpe | WR | avg% | trades | MDD |\n")
    lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n")

    import numpy as np
    # Re-compute top results (passed as best only; simplified)
    lines.append(f"| {best['spike']} | {best['adx']:.0f} | {best['body']} | "
                 f"{best['tp']:.0%} | {best['sl']:.0%} | "
                 f"{best['sharpe']:+.3f} | {best['wr']:.1%} | "
                 f"{best['avg']*100:+.2f}% | {best['trades']} | {best['mdd']*100:+.1f}% |\n\n")

    if cur:
        lines.append("### 현재 daemon 파라미터 (spike=2.0, adx=20, body=0.2, TP=6%, SL=3%)\n\n")
        lines.append(f"Sharpe={cur['sharpe']:+.3f}, WR={cur['wr']:.1%}, trades={cur['trades']}, "
                     f"MDD={cur['mdd']*100:+.1f}%\n\n")

    if best['sharpe'] > (cur['sharpe'] if cur else 0) + 0.5:
        lines.append(f"**결론**: 최적 파라미터 현재 대비 Sharpe +{best['sharpe']-(cur['sharpe'] if cur else 0):.2f} 개선. "
                     f"daemon 반영 검토.\n")
    else:
        lines.append("**결론**: 현재 파라미터 최적에 근접. 소폭 개선만 가능.\n")

    lines.append("\n---\n")

    p = Path(__file__).resolve().parent.parent / "docs" / "backtest_history.md"
    with open(p, "a") as f:
        f.writelines(lines)


if __name__ == "__main__":
    main()
