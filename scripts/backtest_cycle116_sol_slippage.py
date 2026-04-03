"""
사이클 116: momentum_sol 슬리피지 민감도 분석
- 목적: Sharpe +14.37 (IS) / OOS W1=+23.8 W2=+18.0 과적합 의심 해소
         실제 Upbit SOL 슬리피지 0.05~0.20% 구간에서도 엣지 유지 여부
- daemon 파라미터: lb=12, adx=25, vol=2.0, TP=12%, SL=4%, max_hold=48
- 슬리피지 범위: 0.0% ~ 0.30% (편도, 진입+청산 각각 적용)
- WF 3창: W1 OOS=2024, W2 OOS=2025, W3 OOS=2026
- 판정 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-SOL"
FEE    = 0.0005  # 0.05% 수수료 (편도)

WINDOWS = [
    {"name": "W1", "is_start": "2022-01-01", "is_end": "2023-12-31",
     "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2023-01-01", "is_end": "2024-12-31",
     "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"name": "W3", "is_start": "2024-01-01", "is_end": "2025-12-31",
     "oos_start": "2026-01-01", "oos_end": "2026-04-04"},
]

# daemon 파라미터 (사이클 102 확정, 변경 없음)
LOOKBACK    = 12
ADX_THRESH  = 25.0
VOL_MULT    = 2.0
TP          = 0.12
SL          = 0.04
MAX_HOLD    = 48

ENTRY_THRESHOLD = 0.005
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 75.0

# 슬리피지 구간 (편도 %)
SLIPPAGE_LIST = [0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003]

# 판정 기준
PASS_SHARPE = 3.0
PASS_WR     = 0.45
PASS_TRADES = 6


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


def adx_calc(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
             period: int = 14) -> np.ndarray:
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
    atr_s[period-1]  = tr[:period].sum()
    dip_s[period-1]  = dm_p[:period].sum()
    dim_s[period-1]  = dm_m[:period].sum()
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


def backtest(df: pd.DataFrame, slippage: float) -> dict:
    """슬리피지를 편도 비율로 적용.
    - 진입: buy = c[i+1] * (1 + FEE + slippage)
    - TP hit: TP - FEE - slippage
    - SL hit: -SL - FEE - slippage
    - hold_end: c[hold_end] / buy - 1 - FEE - slippage
    """
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    v  = df["volume"].values
    n  = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n-LOOKBACK] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_calc(h, lo, c, 14)
    vol_ma  = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok  = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = LOOKBACK + RSI_PERIOD + 28
    i = warmup
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > ADX_THRESH
            and vol_ok[i]
        )
        if entry_ok:
            buy = c[i + 1] * (1.0 + FEE + slippage)
            exited = False
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= TP:
                    returns.append(TP - FEE - slippage)
                    i = j
                    exited = True
                    break
                if ret <= -SL:
                    returns.append(-SL - FEE - slippage)
                    i = j
                    exited = True
                    break
            if not exited:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE - slippage)
                i = hold_end
        else:
            i += 1

    if len(returns) < PASS_TRADES:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def run_window(w: dict, slippage: float) -> dict:
    df_oos = load_historical(SYMBOL, "240m", w["oos_start"], w["oos_end"])
    oos_r  = backtest(df_oos, slippage)
    passed = (
        not np.isnan(oos_r["sharpe"])
        and oos_r["sharpe"] >= PASS_SHARPE
        and oos_r["wr"] >= PASS_WR
        and oos_r["trades"] >= PASS_TRADES
    )
    return {"name": w["name"], "oos": oos_r, "passed": passed}


def main() -> None:
    print("=" * 70)
    print("사이클 116: momentum_sol 슬리피지 민감도 분석")
    print(f"daemon 파라미터: lb={LOOKBACK} adx={ADX_THRESH:.0f} vol={VOL_MULT} "
          f"TP={TP*100:.0f}% SL={SL*100:.0f}% hold={MAX_HOLD}")
    print(f"슬리피지 범위: {[f'{s*100:.2f}%' for s in SLIPPAGE_LIST]}")
    print(f"판정 기준: OOS Sharpe > {PASS_SHARPE} && WR > {PASS_WR:.0%} && trades >= {PASS_TRADES}")
    print("=" * 70)

    print(f"\n{'Slip%':>6} | {'W1 OOS Sh':>10} {'WR':>6} {'T':>4} | "
          f"{'W2 OOS Sh':>10} {'WR':>6} {'T':>4} | "
          f"{'W3 OOS Sh':>10} {'WR':>6} {'T':>4} | {'통과':>5}")
    print("-" * 85)

    summary_rows = []
    for slip in SLIPPAGE_LIST:
        row_results = []
        pass_count  = 0
        for w in WINDOWS:
            res = run_window(w, slip)
            row_results.append(res)
            if res["passed"]:
                pass_count += 1

        slip_pct = f"{slip*100:.2f}%"
        cols = []
        for res in row_results:
            sh = res["oos"]["sharpe"]
            wr = res["oos"]["wr"]
            t  = res["oos"]["trades"]
            ok = "✅" if res["passed"] else "❌"
            sh_str = f"{sh:+.3f}{ok}" if not np.isnan(sh) else "  nan❌"
            cols.append(f"{sh_str:>10} {wr:>5.1%} {t:>4}")

        print(f"{slip_pct:>6} | {cols[0]} | {cols[1]} | {cols[2]} | {pass_count}/3")
        summary_rows.append({
            "slip": slip,
            "w1_sh": row_results[0]["oos"]["sharpe"],
            "w2_sh": row_results[1]["oos"]["sharpe"],
            "w3_sh": row_results[2]["oos"]["sharpe"],
            "w1_pass": row_results[0]["passed"],
            "w2_pass": row_results[1]["passed"],
            "w3_pass": row_results[2]["passed"],
            "pass_count": pass_count,
        })

    print()

    base = summary_rows[0]
    print(f"★ 기준(슬리피지 0%): W1={base['w1_sh']:+.3f}, W2={base['w2_sh']:+.3f}, "
          f"W3={base['w3_sh'] if not np.isnan(base['w3_sh']) else 'nan'}, "
          f"통과={base['pass_count']}/3")

    print()
    print("=== 슬리피지 임계점 분석 ===")
    first_fail_slip = None
    for row in summary_rows:
        if row["pass_count"] < 2:
            first_fail_slip = row["slip"]
            break
    if first_fail_slip is not None:
        print(f"⚠️  2/3 미달 첫 슬리피지: {first_fail_slip*100:.2f}%")
    else:
        print("✅ 모든 슬리피지 구간에서 2/3+ 통과")

    # W3는 데이터 부족으로 trades < 6 가능 → W1+W2 기준으로도 분석
    print()
    print("=== W1+W2 기준 강건성 (W3 제외) ===")
    for row in summary_rows:
        w12_pass = sum([row["w1_pass"], row["w2_pass"]])
        slip_pct = f"{row['slip']*100:.2f}%"
        print(f"  슬리피지 {slip_pct}: W1={row['w1_sh']:+.3f} W2={row['w2_sh']:+.3f} "
              f"→ W1+W2 {w12_pass}/2 {'✅' if w12_pass == 2 else '❌'}")

    base_avg = np.nanmean([base["w1_sh"], base["w2_sh"]])
    print(f"\n기준(0%) W1+W2 평균 Sharpe: {base_avg:+.3f}")
    print()
    print("=== Sharpe 감쇠율 ===")
    for row in summary_rows[1:]:
        avg_sh = np.nanmean([row["w1_sh"], row["w2_sh"]])
        decay  = (base_avg - avg_sh) / abs(base_avg) * 100 if base_avg != 0 else 0
        status = f"감쇠 {decay:+.1f}%"
        print(f"  슬리피지 {row['slip']*100:.2f}%: W1+W2 평균 Sharpe {avg_sh:+.3f} ({status})")

    print()
    print("=== 결론 ===")
    real_row = next((r for r in summary_rows if abs(r["slip"] - 0.001) < 0.0001), None)
    if real_row:
        real_avg = np.nanmean([real_row["w1_sh"], real_row["w2_sh"]])
        still_ok = real_row["pass_count"] >= 2
        print(f"현실적 슬리피지 0.10%: W1+W2 평균 OOS Sharpe {real_avg:+.3f}, "
              f"통과 {real_row['pass_count']}/3 → {'엣지 유지 ✅' if still_ok else '엣지 소멸 ⚠️'}")

    high_row = next((r for r in summary_rows if abs(r["slip"] - 0.002) < 0.0001), None)
    if high_row:
        high_avg = np.nanmean([high_row["w1_sh"], high_row["w2_sh"]])
        still_ok = high_row["pass_count"] >= 2
        print(f"높은 슬리피지 0.20%: W1+W2 평균 OOS Sharpe {high_avg:+.3f}, "
              f"통과 {high_row['pass_count']}/3 → {'엣지 유지 ✅' if still_ok else '엣지 소멸 ⚠️'}")


if __name__ == "__main__":
    main()
