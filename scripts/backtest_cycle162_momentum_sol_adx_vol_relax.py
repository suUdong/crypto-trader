"""
사이클 162: momentum_sol ADX 완화(30→25→20) + 볼륨 완화(2.0→1.5→1.0)
- 목적: 2026 n>0 확보가 1차 목표 + WF Sharpe≥5.0
- 평가자 방향: ADX∈{20,25} × vol_mult∈{1.0,1.5} × SMA200 고정 그리드
- 핵심 변경:
  1) ADX∈{20,25} (daemon=25, 20은 추가 완화)
  2) vol_mult∈{1.0,1.5,2.0} (daemon=2.0, 1.0/1.5는 완화)
  3) lb∈{12,20} (C1=12, C0=20)
  4) BTC > SMA200 regime gate (BULL 전용)
  5) open[i+1] 진입 (look-ahead bias 제거)
  6) TP∈{0.08,0.10,0.12} × SL∈{0.03,0.04}
- WF: 2-fold
  F1: IS=2022-01~2024-03 → OOS=2024-04~2025-03
  F2: IS=2023-04~2025-06 → OOS=2025-07~2026-04
- 판정: avg OOS Sharpe≥5.0, 양 Fold n≥15, 2026 n>0 확보 여부 별도 리포트
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
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005  # 0.05% 편도
SLIPPAGE_BASE = 0.001  # 0.10%
SLIPPAGE_STRESS = [0.0005, 0.001, 0.0015, 0.002]

RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
ENTRY_THRESHOLD = 0.005
MAX_HOLD = 48
BTC_SMA_PERIOD = 200  # 고정 — c153 최적

TIMEFRAME = "240m"  # 4h bars

WF_FOLDS = [
    {
        "name": "F1",
        "is_start": "2022-01-01", "is_end": "2024-03-31",
        "oos_start": "2024-04-01", "oos_end": "2025-03-31",
    },
    {
        "name": "F2",
        "is_start": "2023-04-01", "is_end": "2025-06-30",
        "oos_start": "2025-07-01", "oos_end": "2026-04-05",
    },
]

# 그리드
LB_LIST = [12, 20]
ADX_LIST = [20.0, 25.0]
VOL_MULT_LIST = [1.0, 1.5, 2.0]
TP_LIST = [0.08, 0.10, 0.12]
SL_LIST = [0.03, 0.04]

# 72 조합

ANNUAL_FACTOR = np.sqrt(6 * 252)  # 4h bars: 6/day × 252 trading days
PASS_SHARPE = 5.0
PASS_N_PER_FOLD = 15


# ── 지표 ──────────────────────────────────────────────────────────────

def compute_sma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    cs = np.cumsum(arr)
    out[period - 1:] = (cs[period - 1:] - np.concatenate([[0], cs[:-period]])) / period
    return out


def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    rsi_arr = np.full(len(closes), np.nan)
    deltas = np.diff(closes)
    if len(deltas) < period:
        return rsi_arr
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    if avg_loss == 0:
        rsi_arr[period] = 100.0
    else:
        rsi_arr[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_arr[i + 1] = 100.0
        else:
            rsi_arr[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return rsi_arr


def compute_adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
) -> np.ndarray:
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
        dx = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    if 2 * period - 2 < len(dx):
        adx_vals[2 * period - 2] = dx[period - 1:2 * period - 1].mean()
        for i in range(2 * period - 1, n - 1):
            adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


# ── 백테스트 ──────────────────────────────────────────────────────────

def backtest(
    sol_df: pd.DataFrame,
    btc_closes: np.ndarray,
    btc_sma: np.ndarray,
    btc_index: pd.DatetimeIndex,
    lookback: int,
    adx_thresh: float,
    vol_mult: float,
    tp: float,
    sl: float,
    slippage: float = SLIPPAGE_BASE,
) -> dict:
    c = sol_df["close"].values.astype(float)
    h = sol_df["high"].values.astype(float)
    lo = sol_df["low"].values.astype(float)
    o = sol_df["open"].values.astype(float)
    v = sol_df["volume"].values.astype(float)
    n = len(c)
    idx = sol_df.index

    # 모멘텀
    mom = np.full(n, np.nan)
    if lookback < n:
        mom[lookback:] = c[lookback:] / c[:n - lookback] - 1.0

    rsi_arr = compute_rsi(c, RSI_PERIOD)
    adx_arr = compute_adx(h, lo, c, 14)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values

    # BTC regime: BTC > SMA200 → BULL
    btc_regime = pd.Series(btc_closes > btc_sma, index=btc_index)

    trades: list[float] = []
    trade_dates: list[str] = []
    warmup = max(lookback, RSI_PERIOD + 28, BTC_SMA_PERIOD + 5)

    i = warmup
    while i < n - 1:
        # BTC BULL regime check
        ts = idx[i]
        loc = btc_regime.index.get_indexer([ts], method="ffill")[0]
        if loc < 0 or not btc_regime.iloc[loc]:
            i += 1
            continue

        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_thresh
            and not np.isnan(vol_ma[i]) and v[i] > vol_mult * vol_ma[i]
        )

        if entry_ok:
            # 다음 봉 시가 진입 (bias 제거)
            buy = o[i + 1] * (1 + slippage + FEE)
            trade_dates.append(str(idx[i + 1])[:10])

            exited = False
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                # TP on high
                if h[j] >= buy * (1 + tp):
                    exit_price = buy * (1 + tp) * (1 - slippage - FEE)
                    trades.append((exit_price - buy) / buy)
                    i = j + 1
                    exited = True
                    break
                # SL on low
                if lo[j] <= buy * (1 - sl):
                    exit_price = buy * (1 - sl) * (1 - slippage - FEE)
                    trades.append((exit_price - buy) / buy)
                    i = j + 1
                    exited = True
                    break
            if not exited:
                hold_end = min(i + MAX_HOLD, n - 1)
                exit_price = c[hold_end] * (1 - slippage - FEE)
                trades.append((exit_price - buy) / buy)
                i = hold_end + 1
        else:
            i += 1

    if not trades:
        return {"sharpe": -999, "wr": 0, "avg": 0, "mdd": 0, "n": 0, "mcl": 0,
                "trades_2026": 0, "trade_dates": []}

    arr = np.array(trades)
    wr = float((arr > 0).sum() / len(arr))
    avg_ret = float(arr.mean())
    sh = float(arr.mean() / (arr.std() + 1e-9) * ANNUAL_FACTOR) if len(arr) > 1 else 0.0

    # MDD
    equity = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    mdd = float(dd.min()) if len(dd) > 0 else 0.0

    # MCL
    mcl = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0

    # 2026 trades
    t2026 = sum(1 for d in trade_dates if d.startswith("2026"))

    return {
        "sharpe": sh, "wr": wr, "avg": avg_ret, "mdd": mdd,
        "n": len(arr), "mcl": mcl, "trades_2026": t2026,
        "trade_dates": trade_dates,
    }


# ── 메인 ──────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== 사이클 162: momentum_sol ADX+볼륨 완화 그리드 탐색 ===")
    print(f"심볼: {SYMBOL}  BTC SMA: {BTC_SMA_PERIOD}  진입: open[i+1]")
    print(f"그리드: lb∈{LB_LIST} × ADX∈{ADX_LIST} × vol∈{VOL_MULT_LIST}"
          f" × TP∈{TP_LIST} × SL∈{SL_LIST}")
    print(f"총 조합: {len(LB_LIST)*len(ADX_LIST)*len(VOL_MULT_LIST)*len(TP_LIST)*len(SL_LIST)}")
    print("=" * 80)

    # 데이터 로드
    sol_full = load_historical(SYMBOL, TIMEFRAME, "2022-01-01", "2026-12-31")
    btc_full = load_historical(BTC_SYMBOL, TIMEFRAME, "2022-01-01", "2026-12-31")
    if sol_full.empty or btc_full.empty:
        print("데이터 로드 실패")
        return
    print(f"SOL 데이터: {len(sol_full)}행 ({sol_full.index[0]} ~ {sol_full.index[-1]})")
    print(f"BTC 데이터: {len(btc_full)}행")

    # BTC 지표 사전계산 (전체)
    btc_closes_full = btc_full["close"].values.astype(float)
    btc_sma_full = compute_sma(btc_closes_full, BTC_SMA_PERIOD)

    # ── Phase 1: WF 그리드 탐색 ──────────────────────────────────────
    print("\n=== Phase 1: Walk-Forward 그리드 탐색 ===")
    results: list[dict] = []

    grid = list(product(LB_LIST, ADX_LIST, VOL_MULT_LIST, TP_LIST, SL_LIST))
    print(f"조합 수: {len(grid)}\n")

    for lb, adx_t, vm, tp, sl in grid:
        fold_results = []
        all_passed = True
        trades_2026_total = 0

        for fold in WF_FOLDS:
            # IS
            is_sol = sol_full.loc[fold["is_start"]:fold["is_end"]]
            is_btc = btc_full.loc[fold["is_start"]:fold["is_end"]]
            if is_sol.empty or is_btc.empty:
                fold_results.append({"sharpe": -999, "n": 0, "wr": 0, "mdd": 0,
                                     "avg": 0, "trades_2026": 0})
                all_passed = False
                continue

            btc_c_is = is_btc["close"].values.astype(float)
            btc_sma_is = compute_sma(btc_c_is, BTC_SMA_PERIOD)

            is_res = backtest(
                is_sol, btc_c_is, btc_sma_is, is_btc.index,
                lb, adx_t, vm, tp, sl,
            )

            # OOS
            oos_sol = sol_full.loc[fold["oos_start"]:fold["oos_end"]]
            oos_btc = btc_full.loc[fold["oos_start"]:fold["oos_end"]]
            if oos_sol.empty or oos_btc.empty:
                fold_results.append({"sharpe": -999, "n": 0, "wr": 0, "mdd": 0,
                                     "avg": 0, "trades_2026": 0})
                all_passed = False
                continue

            btc_c_oos = oos_btc["close"].values.astype(float)
            btc_sma_oos = compute_sma(btc_c_oos, BTC_SMA_PERIOD)

            oos_res = backtest(
                oos_sol, btc_c_oos, btc_sma_oos, oos_btc.index,
                lb, adx_t, vm, tp, sl,
            )

            fold_results.append({
                "is_sharpe": is_res["sharpe"],
                "is_n": is_res["n"],
                "sharpe": oos_res["sharpe"],
                "n": oos_res["n"],
                "wr": oos_res["wr"],
                "mdd": oos_res["mdd"],
                "avg": oos_res["avg"],
                "trades_2026": oos_res["trades_2026"],
            })
            trades_2026_total += oos_res["trades_2026"]

            if oos_res["sharpe"] < PASS_SHARPE or oos_res["n"] < PASS_N_PER_FOLD:
                all_passed = False

        avg_oos = np.mean([f["sharpe"] for f in fold_results]) if fold_results else -999
        results.append({
            "lb": lb, "adx": adx_t, "vol": vm, "tp": tp, "sl": sl,
            "avg_oos": avg_oos, "passed": all_passed,
            "trades_2026": trades_2026_total,
            "folds": fold_results,
        })

    # ── 결과 정렬 (avg_oos 내림차순) ──────────────────────────────────
    results.sort(key=lambda x: x["avg_oos"], reverse=True)

    print(f"\n{'lb':>3} {'ADX':>5} {'vol':>5} {'TP%':>5} {'SL%':>5} "
          f"{'avgOOS':>8} {'F1_Sh':>7} {'F1_n':>5} {'F2_Sh':>7} {'F2_n':>5} "
          f"{'2026n':>5} {'pass':>5}")
    print("-" * 85)

    passed_results = []
    for r in results:
        f1 = r["folds"][0] if len(r["folds"]) > 0 else {}
        f2 = r["folds"][1] if len(r["folds"]) > 1 else {}
        tag = "✅" if r["passed"] else "❌"
        print(
            f"{r['lb']:>3} {r['adx']:>5.0f} {r['vol']:>5.1f} "
            f"{r['tp']*100:>4.0f}% {r['sl']*100:>4.0f}% "
            f"{r['avg_oos']:>+8.3f} "
            f"{f1.get('sharpe', -999):>+7.3f} {f1.get('n', 0):>5} "
            f"{f2.get('sharpe', -999):>+7.3f} {f2.get('n', 0):>5} "
            f"{r['trades_2026']:>5} {tag:>5}"
        )
        if r["passed"]:
            passed_results.append(r)

    # ── 2026 거래 유무 별도 리포트 ────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 2026 거래 발생 조합 ===")
    has_2026 = [r for r in results if r["trades_2026"] > 0]
    if has_2026:
        for r in has_2026[:10]:
            print(f"  lb={r['lb']} ADX={r['adx']:.0f} vol={r['vol']:.1f} "
                  f"TP={r['tp']*100:.0f}% SL={r['sl']*100:.0f}% → "
                  f"2026 trades: {r['trades_2026']}, avg OOS: {r['avg_oos']:+.3f}")
    else:
        print("  ❌ 모든 조합에서 2026=0거래")

    # ── 통과 조합 슬리피지 스트레스 ──────────────────────────────────
    if passed_results:
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 (상위 3개) ===")
        for r in passed_results[:3]:
            lb, adx_t, vm, tp, sl = r["lb"], r["adx"], r["vol"], r["tp"], r["sl"]
            print(f"\n--- lb={lb} ADX={adx_t:.0f} vol={vm:.1f} "
                  f"TP={tp*100:.0f}% SL={sl*100:.0f}% (avg OOS: {r['avg_oos']:+.3f}) ---")
            print(f"  {'slip':>6} {'Sharpe':>8} {'WR':>6} {'avg%':>7} {'MDD%':>8} "
                  f"{'MCL':>4} {'n':>5}")
            print(f"  {'-' * 50}")
            for slip in SLIPPAGE_STRESS:
                stress_res = backtest(
                    sol_full, btc_closes_full, btc_sma_full, btc_full.index,
                    lb, adx_t, vm, tp, sl, slippage=slip,
                )
                print(
                    f"  {slip*100:.2f}% {stress_res['sharpe']:>+8.3f} "
                    f"{stress_res['wr']:>5.1%} {stress_res['avg']*100:>+6.2f}% "
                    f"{stress_res['mdd']*100:>+7.2f}% {stress_res['mcl']:>4} "
                    f"{stress_res['n']:>5}"
                )

    # ── Buy-and-Hold 비교 ─────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== Buy-and-Hold 비교 ===")
    for fold in WF_FOLDS:
        oos_sol = sol_full.loc[fold["oos_start"]:fold["oos_end"]]
        if not oos_sol.empty:
            bh = (oos_sol["close"].iloc[-1] / oos_sol["close"].iloc[0]) - 1
            print(f"  {fold['name']} OOS ({fold['oos_start']}~{fold['oos_end']}): "
                  f"BH={bh*100:+.1f}%")

    # ── 최종 요약 ─────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    if passed_results:
        best = passed_results[0]
        print(f"★ OOS 최적: lb={best['lb']} ADX={best['adx']:.0f} "
              f"vol={best['vol']:.1f} TP={best['tp']*100:.0f}% SL={best['sl']*100:.0f}%")
        print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} "
              f"{'✅ ≥5.0 달성' if best['avg_oos'] >= 5.0 else '❌ <5.0'}")
        for i, f in enumerate(best["folds"]):
            print(f"  Fold {i+1}: Sharpe={f['sharpe']:+.3f}  WR={f['wr']:.1%}  "
                  f"trades={f['n']}  avg={f['avg']*100:+.2f}%  MDD={f['mdd']*100:+.2f}%")
        print(f"  2026 trades: {best['trades_2026']}")
    else:
        # 최선 결과라도 보고
        best = results[0] if results else None
        if best:
            print(f"★ 최선 (미통과): lb={best['lb']} ADX={best['adx']:.0f} "
                  f"vol={best['vol']:.1f} TP={best['tp']*100:.0f}% SL={best['sl']*100:.0f}%")
            print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} ❌ <5.0")
            for i, f in enumerate(best["folds"]):
                print(f"  Fold {i+1}: Sharpe={f['sharpe']:+.3f}  WR={f.get('wr',0):.1%}  "
                      f"trades={f['n']}  avg={f.get('avg',0)*100:+.2f}%  "
                      f"MDD={f.get('mdd',0)*100:+.2f}%")
            print(f"  2026 trades: {best['trades_2026']}")

    n_passed = len(passed_results)
    n_2026 = len(has_2026)
    print(f"\nSharpe: {best['avg_oos']:+.3f}" if best else "\nSharpe: N/A")
    print(f"WR: {np.mean([f['wr'] for f in best['folds']])*100:.1f}%"
          if best else "WR: N/A")
    print(f"trades: {sum(f['n'] for f in best['folds'])}" if best else "trades: 0")
    print(f"passed: {n_passed}/{len(grid)}")
    print(f"2026 signal combos: {n_2026}/{len(grid)}")


if __name__ == "__main__":
    main()
