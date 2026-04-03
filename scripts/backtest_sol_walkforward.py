"""
momentum_sol 워크포워드 검증 (과적합 판단)
- Train: 2022-01-01 ~ 2024-12-31
- Test:  2025-01-01 ~ 2026-04-03
- 최적 파라미터 + 인접 파라미터 robust 체크
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-SOL"
FEE    = 0.0005

TRAIN_START = "2022-01-01"
TRAIN_END   = "2024-12-31"
TEST_START  = "2025-01-01"
TEST_END    = "2026-04-03"

# 최적 + 인접 파라미터
LOOKBACK_LIST = [16, 20, 24]
ADX_LIST      = [20.0, 25.0, 30.0]
VOL_LIST      = [1.5, 2.0, 2.5]
TP_LIST       = [0.10, 0.12, 0.15]
SL_LIST       = [0.03, 0.04, 0.05]

ENTRY_THRESHOLD = 0.005
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 75.0
MAX_HOLD        = 48


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


def adx_calc(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def backtest(df: pd.DataFrame, lookback: int, adx_thresh: float,
             vol_mult: float, tp: float, sl: float) -> dict:
    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n-lookback] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_calc(h, lo, c, 14)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > vol_mult * vol_ma

    returns: list[float] = []
    equity = [1.0]
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
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    r = tp - FEE
                    returns.append(r)
                    equity.append(equity[-1] * (1 + r))
                    i = j
                    break
                if ret <= -sl:
                    r = -sl - FEE
                    returns.append(r)
                    equity.append(equity[-1] * (1 + r))
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                r = c[hold_end] / buy - 1 - FEE
                returns.append(r)
                equity.append(equity[-1] * (1 + r))
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0, "mdd": 0.0}

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())

    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / (peak + 1e-9)).min())

    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr), "mdd": mdd}


def main() -> None:
    print("=== momentum_sol 워크포워드 검증 (과적합 판단) ===")
    print(f"Train: {TRAIN_START} ~ {TRAIN_END}")
    print(f"Test:  {TEST_START} ~ {TEST_END}")

    df_train = load_historical(SYMBOL, "240m", TRAIN_START, TRAIN_END)
    df_test  = load_historical(SYMBOL, "240m", TEST_START, TEST_END)

    if df_train.empty or df_test.empty:
        print(f"데이터 없음: train={len(df_train)} test={len(df_test)}")
        return

    print(f"Train {len(df_train)}봉 / Test {len(df_test)}봉\n")

    combos = list(product(LOOKBACK_LIST, ADX_LIST, VOL_LIST, TP_LIST, SL_LIST))
    print(f"총 {len(combos)}개 조합 실행 중...")

    results = []
    for lb, adx_t, vm, tp, sl in combos:
        tr = backtest(df_train, lb, adx_t, vm, tp, sl)
        te = backtest(df_test,  lb, adx_t, vm, tp, sl)
        # robust: OOS Sharpe >= IS Sharpe * 0.5 (50% 이상 유지)
        is_robust = (
            not np.isnan(tr["sharpe"]) and tr["sharpe"] > 0
            and not np.isnan(te["sharpe"]) and te["sharpe"] > 0
            and te["sharpe"] >= tr["sharpe"] * 0.5
        )
        results.append({
            "lb": lb, "adx": adx_t, "vol": vm, "tp": tp, "sl": sl,
            "is_sh": tr["sharpe"], "is_wr": tr["wr"], "is_trades": tr["trades"],
            "oos_sh": te["sharpe"], "oos_wr": te["wr"], "oos_trades": te["trades"],
            "oos_mdd": te["mdd"], "robust": is_robust,
        })

    # 최적 파라미터 결과
    optimal = next(
        (r for r in results if r["lb"] == 20 and r["adx"] == 25.0
         and r["vol"] == 2.0 and r["tp"] == 0.12 and r["sl"] == 0.04),
        None
    )

    print("\n" + "="*80)
    print("최적 파라미터 (lb=20 adx=25 vol=2.0 TP=12% SL=4%) 워크포워드 결과:")
    if optimal:
        print(f"  IS  (2022-2024): Sharpe={optimal['is_sh']:+.3f}  WR={optimal['is_wr']:.1%}  trades={optimal['is_trades']}")
        print(f"  OOS (2025-2026): Sharpe={optimal['oos_sh']:+.3f}  WR={optimal['oos_wr']:.1%}  trades={optimal['oos_trades']}  MDD={optimal['oos_mdd']:.1%}")
        print(f"  Robust: {'✓ PASS' if optimal['robust'] else '✗ FAIL'}")
    print("="*80)

    robust_results = [r for r in results if r["robust"]]
    print(f"\nRobust 조합: {len(robust_results)}/{len(results)}")

    if robust_results:
        robust_results.sort(key=lambda x: x["oos_sh"], reverse=True)
        print("\nTop-5 Robust (OOS Sharpe 기준):")
        print(f"{'lb':>4} {'adx':>5} {'vol':>5} {'TP':>5} {'SL':>5} | {'IS Sh':>7} {'OOS Sh':>7} {'OOS WR':>7} {'OOS tr':>7}")
        print("-"*65)
        for r in robust_results[:5]:
            print(f"{r['lb']:>4} {r['adx']:>5.0f} {r['vol']:>5.1f} {r['tp']:>5.2f} {r['sl']:>5.2f} | "
                  f"{r['is_sh']:>+7.3f} {r['oos_sh']:>+7.3f} {r['oos_wr']:>6.1%} {r['oos_trades']:>7}")
        best = robust_results[0]
        print(f"\n★ Best Robust: lb={best['lb']} adx={best['adx']} vol={best['vol']} "
              f"TP={best['tp']} SL={best['sl']}")
        print(f"  OOS Sharpe={best['oos_sh']:+.3f}  WR={best['oos_wr']:.1%}  MDD={best['oos_mdd']:.1%}")
    else:
        print("Robust 조합 없음 — 현재 파라미터 과적합 의심")

    # docs/backtest_history.md 기록
    hist_path = Path(__file__).resolve().parent.parent / "docs" / "backtest_history.md"
    entry = _format_history(optimal, robust_results)
    with open(hist_path, "a") as f:
        f.write(entry)
    print(f"\n결과 저장 → {hist_path}")


def _format_history(optimal: dict | None, robust: list[dict]) -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n## {now} — momentum_sol 워크포워드 검증\n"]
    lines.append(f"**기간**: Train 2022~2024 / Test 2025~2026-04-03  \n")
    lines.append(f"**그리드**: lookback×adx×vol×TP×SL = {3**5}조합  \n\n")

    if optimal:
        lines.append("### 최적 파라미터 (lb=20 adx=25 vol=2.0 TP=12% SL=4%)\n\n")
        lines.append("| 구간 | Sharpe | WR | trades |\n|---|:---:|:---:|:---:|\n")
        lines.append(f"| IS (2022-2024) | {optimal['is_sh']:+.3f} | {optimal['is_wr']:.1%} | {optimal['is_trades']} |\n")
        lines.append(f"| OOS (2025-2026) | {optimal['oos_sh']:+.3f} | {optimal['oos_wr']:.1%} | {optimal['oos_trades']} |\n\n")
        status = "PASS" if optimal["robust"] else "FAIL"
        lines.append(f"**Robust 판정**: {status} (OOS Sharpe >= IS Sharpe × 50%)\n\n")

    if robust:
        best = robust[0]
        lines.append(f"### Best Robust 파라미터\n\n")
        lines.append(f"lb={best['lb']}, adx={best['adx']}, vol={best['vol']}, "
                     f"TP={best['tp']:.0%}, SL={best['sl']:.0%}  \n")
        lines.append(f"OOS: Sharpe={best['oos_sh']:+.3f}, WR={best['oos_wr']:.1%}, "
                     f"MDD={best['oos_mdd']:.1%}, trades={best['oos_trades']}\n\n")

    if not robust:
        lines.append("**결론**: Robust 조합 없음. 전 파라미터 OOS 성능 저하 → 과적합. daemon 반영 보류.\n")
    elif optimal and optimal["robust"]:
        lines.append("**결론**: 현재 최적 파라미터 Robust PASS. daemon.toml 파라미터 유효.\n")
    else:
        best = robust[0]
        lines.append(f"**결론**: 현재 최적 파라미터 Robust FAIL. "
                     f"Best robust lb={best['lb']} adx={best['adx']} vol={best['vol']} "
                     f"TP={best['tp']:.0%} SL={best['sl']:.0%} 로 교체 검토.\n")

    lines.append("\n---\n")
    return "".join(lines)


if __name__ == "__main__":
    main()
