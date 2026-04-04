"""
사이클 147: momentum_sol 슬리피지 스트레스 + MDD 분석
- 평가자 지시: walk-forward 3-window + slippage 0.05%→0.15% stress test
- 목적: daemon 2슬롯 확대 전 실전 내성 측정
- 현재 daemon: lb=12, adx=25, vol=2.0, TP=12%, SL=4% (C1)
- 검증 기준: 각 창 Sharpe >5, 슬리피지 0.15%에서 Sharpe >3
- 진입가: 다음 봉 시가(open) 사용 ★슬리피지포함
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-SOL"
BASE_FEE = 0.0005

WINDOWS = [
    {"name": "W1", "is_start": "2022-01-01", "is_end": "2023-12-31",
     "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2023-01-01", "is_end": "2024-12-31",
     "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"name": "W3", "is_start": "2024-01-01", "is_end": "2025-12-31",
     "oos_start": "2026-01-01", "oos_end": "2026-04-05"},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015]  # 0.05%, 0.10%, 0.15%

# daemon 현재 설정 (C1)
PARAMS = {"lookback": 12, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04}

ENTRY_THRESHOLD = 0.005
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
MAX_HOLD = 48


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


def adx_calc(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])
        ),
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


def backtest(
    df: pd.DataFrame,
    lookback: int,
    adx_thresh: float,
    vol_mult: float,
    tp: float,
    sl: float,
    slippage: float = 0.0,
) -> dict:
    c = df["close"].values
    o = df["open"].values if "open" in df.columns else c
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

    total_fee = BASE_FEE + slippage
    returns: list[float] = []
    equity_curve: list[float] = [1.0]
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
            # 다음 봉 시가로 진입 (슬리피지 포함)
            buy = o[i + 1] * (1 + total_fee)
            trade_ret = None
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    trade_ret = tp - total_fee
                    i = j
                    break
                if ret <= -sl:
                    trade_ret = -sl - total_fee
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                trade_ret = c[hold_end] / buy - 1 - total_fee
                i = hold_end
            if trade_ret is not None:
                returns.append(trade_ret)
                equity_curve.append(equity_curve[-1] * (1 + trade_ret))
        else:
            i += 1

    if len(returns) < 3:
        return {
            "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
            "trades": 0, "mdd": 0.0, "max_consec_loss": 0,
        }

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())

    # MDD 계산
    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    mdd = float(dd.min())

    # 최대 연속 손실
    max_cl = 0
    cur_cl = 0
    for r in returns:
        if r < 0:
            cur_cl += 1
            max_cl = max(max_cl, cur_cl)
        else:
            cur_cl = 0

    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "mdd": mdd, "max_consec_loss": max_cl,
    }


def main() -> None:
    print("=" * 85)
    print("사이클 147: momentum_sol 슬리피지 스트레스 + MDD 분석")
    print(f"파라미터: lb={PARAMS['lookback']} adx={PARAMS['adx']:.0f} "
          f"vol={PARAMS['vol_mult']} TP={PARAMS['tp']:.0%} SL={PARAMS['sl']:.0%}")
    print("검증 기준: 각 창 OOS Sharpe >5 (강화), slippage 0.15%에서 Sharpe >3")
    print("=" * 85)

    # 데이터 로드
    data_cache: dict[str, pd.DataFrame] = {}
    for w in WINDOWS:
        df_is = load_historical(SYMBOL, "240m", w["is_start"], w["is_end"])
        df_oos = load_historical(SYMBOL, "240m", w["oos_start"], w["oos_end"])
        data_cache[f"{w['name']}_is"] = df_is
        data_cache[f"{w['name']}_oos"] = df_oos
        print(f"  {w['name']}: IS={len(df_is)}행, OOS={len(df_oos)}행")

    lb = PARAMS["lookback"]
    adx_t = PARAMS["adx"]
    vm = PARAMS["vol_mult"]
    tp = PARAMS["tp"]
    sl_val = PARAMS["sl"]

    # === Part 1: 3-window walk-forward (base slippage 0.05%) ===
    print("\n" + "=" * 85)
    print("Part 1: 3-Window Walk-Forward (slippage=0.05%)")
    print("=" * 85)
    hdr = (f"{'윈도우':<40} | {'IS Sharpe':>10} {'IS WR':>7} {'IS T':>5} | "
           f"{'OOS Sharpe':>10} {'OOS WR':>7} {'OOS T':>5} {'OOS MDD':>8} {'MCL':>4} | {'판정':>4}")
    print(hdr)
    print("-" * len(hdr))

    wf_results = []
    for w in WINDOWS:
        df_is = data_cache[f"{w['name']}_is"]
        df_oos = data_cache[f"{w['name']}_oos"]

        is_r = backtest(df_is, lb, adx_t, vm, tp, sl_val, slippage=0.0005)
        oos_r = backtest(df_oos, lb, adx_t, vm, tp, sl_val, slippage=0.0005)

        oos_ok = (
            not np.isnan(oos_r["sharpe"])
            and oos_r["sharpe"] > 5.0
            and oos_r["wr"] > 0.45
            and oos_r["trades"] >= 6
        )
        verdict = "PASS" if oos_ok else "FAIL"
        wf_results.append({"window": w["name"], "oos": oos_r, "pass": oos_ok})

        is_sh = f"{is_r['sharpe']:+.3f}" if not np.isnan(is_r["sharpe"]) else "   nan"
        oos_sh = f"{oos_r['sharpe']:+.3f}" if not np.isnan(oos_r["sharpe"]) else "   nan"
        wname = f"{w['name']}(OOS:{w['oos_start'][:7]}~{w['oos_end'][:7]})"

        print(
            f"{wname:<40} | "
            f"{is_sh:>10} {is_r['wr']:>6.1%} {is_r['trades']:>5} | "
            f"{oos_sh:>10} {oos_r['wr']:>6.1%} {oos_r['trades']:>5} "
            f"{oos_r['mdd']:>7.2%} {oos_r['max_consec_loss']:>4} | {verdict:>4}"
        )

    pass_count = sum(1 for r in wf_results if r["pass"])
    print(f"\n  → 통과: {pass_count}/{len(WINDOWS)}", end="")
    if pass_count == 3:
        print(" ★★★ 전 구간 통과")
    elif pass_count >= 2:
        print(" ◆◆ 2/3 통과")
    else:
        print(" ✗ 불안정")

    # === Part 2: 슬리피지 스트레스 테스트 ===
    print("\n" + "=" * 85)
    print("Part 2: 슬리피지 스트레스 테스트 (전체 기간 2022-01~2026-04)")
    print("=" * 85)

    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-04-05")
    print(f"  전체 데이터: {len(df_full)}행\n")

    print(f"{'Slippage':>10} | {'Sharpe':>10} {'WR':>7} {'Trades':>7} {'AvgRet':>8} "
          f"{'MDD':>8} {'MCL':>4} | {'판정':>10}")
    print("-" * 80)

    stress_results = []
    for slip in SLIPPAGE_LEVELS:
        r = backtest(df_full, lb, adx_t, vm, tp, sl_val, slippage=slip)
        ok = not np.isnan(r["sharpe"]) and r["sharpe"] > 3.0
        verdict = "PASS" if ok else "FAIL"
        stress_results.append({"slippage": slip, **r, "pass": ok})

        sh_str = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "   nan"
        print(
            f"{slip:>9.2%} | {sh_str:>10} {r['wr']:>6.1%} {r['trades']:>7} "
            f"{r['avg_ret']:>7.3%} {r['mdd']:>7.2%} {r['max_consec_loss']:>4} | {verdict:>10}"
        )

    # === Part 3: Buy-and-Hold 비교 ===
    print("\n" + "=" * 85)
    print("Part 3: Buy-and-Hold 비교 (전체 기간)")
    print("=" * 85)

    c_full = df_full["close"].values
    bh_ret = c_full[-1] / c_full[0] - 1
    bh_peak = np.maximum.accumulate(c_full)
    bh_dd = (c_full - bh_peak) / bh_peak
    bh_mdd = float(bh_dd.min())

    base_r = stress_results[0]  # slippage=0.05%
    strat_cumret = 1.0
    for wr in wf_results:
        strat_cumret *= (1 + wr["oos"]["avg_ret"]) ** wr["oos"]["trades"]

    print(f"  Buy-and-Hold: 수익률={bh_ret:+.2%}, MDD={bh_mdd:.2%}")
    print(f"  momentum_sol (slip=0.05%): 수익률=~{base_r['avg_ret'] * base_r['trades']:+.2%}, "
          f"MDD={base_r['mdd']:.2%}, trades={base_r['trades']}")
    if base_r["avg_ret"] * base_r["trades"] > bh_ret:
        print("  → ★ 전략 > Buy-and-Hold")
    else:
        print("  → Buy-and-Hold 우위")

    # === 종합 판정 ===
    print("\n" + "=" * 85)
    print("종합 판정")
    print("=" * 85)

    all_wf_pass = pass_count == 3
    stress_015_pass = stress_results[-1]["pass"]  # 0.15% slippage
    worst_mdd = min(r["oos"]["mdd"] for r in wf_results if r["oos"]["trades"] > 0) \
        if any(r["oos"]["trades"] > 0 for r in wf_results) else 0.0

    print(f"  WF 3-window: {'PASS' if all_wf_pass else 'FAIL'} ({pass_count}/3)")
    print(f"  Slippage 0.15%: {'PASS' if stress_015_pass else 'FAIL'} "
          f"(Sharpe={stress_results[-1]['sharpe']:+.3f})")
    print(f"  최악 OOS MDD: {worst_mdd:.2%}")
    print(f"  최대 연속 손실: {max(r['oos']['max_consec_loss'] for r in wf_results)}")

    if all_wf_pass and stress_015_pass and worst_mdd > -0.15:
        print("\n  ★★★ 2슬롯 확대 가능 — 모든 검증 통과")
    elif pass_count >= 2 and stress_015_pass:
        print("\n  ◆◆ 현 1슬롯 유지 권장 — WF 일부 미달")
    else:
        print("\n  ✗ daemon 축소/동결 검토 필요")


if __name__ == "__main__":
    main()
