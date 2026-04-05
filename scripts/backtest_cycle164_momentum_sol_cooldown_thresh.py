"""
사이클 164 (ralph c159): momentum_sol cooldown 축소 + entry_threshold 완화
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: c162(ralph c158) 최적 ADX=20 vol=1.5 → avg OOS +11.413, 4/72 WF 통과
      F2 n=15 경계값 — cooldown/threshold 완화로 n 확대 필요

가설:
  1) cooldown 축소(24→6,12,18): 연패 후 빠른 재진입으로 거래수 증가
  2) entry_threshold 완화(0.005→0.002,0.003): 약한 모멘텀도 포착하여 n 확대
  3) max_hold 확장(48→60): 더 긴 보유로 TP 도달 확률 증가
  ADX=20, vol_mult=1.5, lb=20, SMA200 고정 (c158 최적)

그리드:
  - cooldown_bars: [6, 12, 18, 24]
  - entry_thresh: [0.002, 0.003, 0.005]
  - tp: [0.08, 0.10, 0.12]
  - sl: [0.03, 0.04]
  = 4 × 3 × 3 × 2 = 72 조합

WF: 2-fold (새 OOS 윈도우)
  F1: IS=2022-01-01~2024-06-30 → OOS=2024-07-01~2025-06-30
  F2: IS=2023-07-01~2025-09-30 → OOS=2025-10-01~2026-04-05
판정: avg OOS Sharpe≥5.0, 양 Fold n≥15, 2026 n>0
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
FEE = 0.0005
SLIPPAGE_BASE = 0.001
SLIPPAGE_STRESS = [0.0005, 0.001, 0.0015, 0.002]

# 고정 파라미터 (c158 최적)
LOOKBACK = 20
ADX_THRESH = 20.0
VOL_MULT = 1.5
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
BTC_SMA_PERIOD = 200
COOLDOWN_TRIGGER = 3

TIMEFRAME = "240m"

WF_FOLDS = [
    {
        "name": "F1",
        "is_start": "2022-01-01", "is_end": "2024-06-30",
        "oos_start": "2024-07-01", "oos_end": "2025-06-30",
    },
    {
        "name": "F2",
        "is_start": "2023-07-01", "is_end": "2025-09-30",
        "oos_start": "2025-10-01", "oos_end": "2026-04-05",
    },
]

# 그리드
COOLDOWN_LIST = [6, 12, 18, 24]
ENTRY_THRESH_LIST = [0.002, 0.003, 0.005]
TP_LIST = [0.08, 0.10, 0.12]
SL_LIST = [0.03, 0.04]
MAX_HOLD_LIST = [48, 60]

# 4 × 3 × 3 × 2 × 2 = 144 조합

ANNUAL_FACTOR = np.sqrt(6 * 252)
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
    entry_thresh: float,
    tp: float,
    sl: float,
    cooldown_bars: int,
    max_hold: int,
    slippage: float = SLIPPAGE_BASE,
) -> dict:
    c = sol_df["close"].values.astype(float)
    h = sol_df["high"].values.astype(float)
    lo = sol_df["low"].values.astype(float)
    o = sol_df["open"].values.astype(float)
    v = sol_df["volume"].values.astype(float)
    n = len(c)
    idx = sol_df.index

    mom = np.full(n, np.nan)
    if LOOKBACK < n:
        mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0

    rsi_arr = compute_rsi(c, RSI_PERIOD)
    adx_arr = compute_adx(h, lo, c, 14)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values

    btc_regime = pd.Series(btc_closes > btc_sma, index=btc_index)

    trades: list[float] = []
    trade_dates: list[str] = []
    warmup = max(LOOKBACK, RSI_PERIOD + 28, BTC_SMA_PERIOD + 5)

    consec_loss = 0
    cooldown_until = 0

    i = warmup
    while i < n - 1:
        # Cooldown check
        if i < cooldown_until:
            i += 1
            continue

        # BTC BULL regime check
        ts = idx[i]
        loc = btc_regime.index.get_indexer([ts], method="ffill")[0]
        if loc < 0 or not btc_regime.iloc[loc]:
            i += 1
            continue

        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > entry_thresh
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > ADX_THRESH
            and not np.isnan(vol_ma[i]) and v[i] > VOL_MULT * vol_ma[i]
        )

        if entry_ok:
            buy = o[i + 1] * (1 + slippage + FEE)
            trade_dates.append(str(idx[i + 1])[:10])

            exited = False
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                if h[j] >= buy * (1 + tp):
                    exit_price = buy * (1 + tp) * (1 - slippage - FEE)
                    ret = (exit_price - buy) / buy
                    trades.append(ret)
                    if ret < 0:
                        consec_loss += 1
                    else:
                        consec_loss = 0
                    if consec_loss >= COOLDOWN_TRIGGER:
                        cooldown_until = j + cooldown_bars
                        consec_loss = 0
                    i = j + 1
                    exited = True
                    break
                if lo[j] <= buy * (1 - sl):
                    exit_price = buy * (1 - sl) * (1 - slippage - FEE)
                    ret = (exit_price - buy) / buy
                    trades.append(ret)
                    consec_loss += 1
                    if consec_loss >= COOLDOWN_TRIGGER:
                        cooldown_until = j + cooldown_bars
                        consec_loss = 0
                    i = j + 1
                    exited = True
                    break
            if not exited:
                hold_end = min(i + max_hold, n - 1)
                exit_price = c[hold_end] * (1 - slippage - FEE)
                ret = (exit_price - buy) / buy
                trades.append(ret)
                if ret < 0:
                    consec_loss += 1
                else:
                    consec_loss = 0
                if consec_loss >= COOLDOWN_TRIGGER:
                    cooldown_until = hold_end + cooldown_bars
                    consec_loss = 0
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

    equity = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    mdd = float(dd.min()) if len(dd) > 0 else 0.0

    mcl = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0

    t2026 = sum(1 for d in trade_dates if d.startswith("2026"))

    return {
        "sharpe": sh, "wr": wr, "avg": avg_ret, "mdd": mdd,
        "n": len(arr), "mcl": mcl, "trades_2026": t2026,
        "trade_dates": trade_dates,
    }


# ── 메인 ──────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== 사이클 164 (ralph c159): momentum_sol cooldown+threshold 완화 ===")
    print(f"심볼: {SYMBOL}  고정: ADX={ADX_THRESH} vol={VOL_MULT} lb={LOOKBACK} "
          f"BTC_SMA={BTC_SMA_PERIOD}")
    print(f"그리드: cool∈{COOLDOWN_LIST} × thresh∈{ENTRY_THRESH_LIST}"
          f" × TP∈{TP_LIST} × SL∈{SL_LIST} × hold∈{MAX_HOLD_LIST}")
    total = (len(COOLDOWN_LIST) * len(ENTRY_THRESH_LIST)
             * len(TP_LIST) * len(SL_LIST) * len(MAX_HOLD_LIST))
    print(f"총 조합: {total}")
    print("=" * 80)

    sol_full = load_historical(SYMBOL, TIMEFRAME, "2022-01-01", "2026-12-31")
    btc_full = load_historical(BTC_SYMBOL, TIMEFRAME, "2022-01-01", "2026-12-31")
    if sol_full.empty or btc_full.empty:
        print("데이터 로드 실패")
        return
    print(f"SOL 데이터: {len(sol_full)}행 ({sol_full.index[0]} ~ {sol_full.index[-1]})")
    print(f"BTC 데이터: {len(btc_full)}행")

    btc_closes_full = btc_full["close"].values.astype(float)
    btc_sma_full = compute_sma(btc_closes_full, BTC_SMA_PERIOD)

    # ── Phase 1: WF 그리드 탐색 ──────────────────────────────────────
    print("\n=== Phase 1: Walk-Forward 그리드 탐색 ===")
    results: list[dict] = []

    grid = list(product(COOLDOWN_LIST, ENTRY_THRESH_LIST, TP_LIST, SL_LIST, MAX_HOLD_LIST))
    print(f"조합 수: {len(grid)}\n")

    for cool, et, tp, sl, mh in grid:
        fold_results = []
        all_passed = True
        trades_2026_total = 0

        for fold in WF_FOLDS:
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
                et, tp, sl, cool, mh,
            )

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
                et, tp, sl, cool, mh,
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
            "cool": cool, "et": et, "tp": tp, "sl": sl, "mh": mh,
            "avg_oos": avg_oos, "passed": all_passed,
            "trades_2026": trades_2026_total,
            "folds": fold_results,
        })

    results.sort(key=lambda x: x["avg_oos"], reverse=True)

    print(f"\n{'cool':>4} {'thresh':>6} {'TP%':>5} {'SL%':>5} {'hold':>4} "
          f"{'avgOOS':>8} {'F1_Sh':>7} {'F1_n':>5} {'F2_Sh':>7} {'F2_n':>5} "
          f"{'2026n':>5} {'pass':>5}")
    print("-" * 90)

    passed_results = []
    for r in results[:40]:  # top 40
        f1 = r["folds"][0] if len(r["folds"]) > 0 else {}
        f2 = r["folds"][1] if len(r["folds"]) > 1 else {}
        tag = "✅" if r["passed"] else "❌"
        print(
            f"{r['cool']:>4} {r['et']:>6.3f} "
            f"{r['tp']*100:>4.0f}% {r['sl']*100:>4.0f}% {r['mh']:>4} "
            f"{r['avg_oos']:>+8.3f} "
            f"{f1.get('sharpe', -999):>+7.3f} {f1.get('n', 0):>5} "
            f"{f2.get('sharpe', -999):>+7.3f} {f2.get('n', 0):>5} "
            f"{r['trades_2026']:>5} {tag:>5}"
        )
        if r["passed"]:
            passed_results.append(r)

    # ── c158 기준선 vs c159 비교 ──────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== c158 기준선 (cool=24 thresh=0.005) 재현 on 새 윈도우 ===")
    baseline_found = [r for r in results
                      if r["cool"] == 24 and abs(r["et"] - 0.005) < 1e-6
                      and abs(r["tp"] - 0.10) < 1e-6 and abs(r["sl"] - 0.04) < 1e-6
                      and r["mh"] == 48]
    if baseline_found:
        bl = baseline_found[0]
        for i, f in enumerate(bl["folds"]):
            print(f"  [c158 기준] Fold {i+1}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1%}  n={f['n']}  avg={f['avg']*100:+.2f}%  "
                  f"MDD={f['mdd']*100:+.2f}%")

    # ── 2026 거래 리포트 ─────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 2026 거래 발생 조합 ===")
    has_2026 = [r for r in results if r["trades_2026"] > 0]
    if has_2026:
        for r in has_2026[:10]:
            print(f"  cool={r['cool']} thresh={r['et']:.3f} "
                  f"TP={r['tp']*100:.0f}% SL={r['sl']*100:.0f}% hold={r['mh']} → "
                  f"2026 trades: {r['trades_2026']}, avg OOS: {r['avg_oos']:+.3f}")
    else:
        print("  ❌ 모든 조합에서 2026=0거래")

    # ── 통과 조합 슬리피지 스트레스 ──────────────────────────────────
    if passed_results:
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 (상위 3개) ===")
        for r in passed_results[:3]:
            cool, et, tp, sl, mh = r["cool"], r["et"], r["tp"], r["sl"], r["mh"]
            print(f"\n--- cool={cool} thresh={et:.3f} "
                  f"TP={tp*100:.0f}% SL={sl*100:.0f}% hold={mh} "
                  f"(avg OOS: {r['avg_oos']:+.3f}) ---")
            print(f"  {'slip':>6} {'Sharpe':>8} {'WR':>6} {'avg%':>7} {'MDD%':>8} "
                  f"{'MCL':>4} {'n':>5}")
            print(f"  {'-' * 55}")
            for slip in SLIPPAGE_STRESS:
                stress_res = backtest(
                    sol_full, btc_closes_full, btc_sma_full, btc_full.index,
                    et, tp, sl, cool, mh, slippage=slip,
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
    best = passed_results[0] if passed_results else (results[0] if results else None)
    if best:
        label = "★ OOS 최적" if best.get("passed") else "★ 최선 (미통과)"
        print(f"{label}: cool={best['cool']} thresh={best['et']:.3f} "
              f"TP={best['tp']*100:.0f}% SL={best['sl']*100:.0f}% hold={best['mh']}")
        print(f"  (고정: ADX={ADX_THRESH} vol={VOL_MULT} lb={LOOKBACK} "
              f"BTC_SMA={BTC_SMA_PERIOD})")
        print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} "
              f"{'✅ ≥5.0 달성' if best['avg_oos'] >= 5.0 else '❌ <5.0'}")
        is_sharpes = [f.get("is_sharpe", 0) for f in best["folds"]]
        if any(s != 0 for s in is_sharpes):
            print(f"  train Sharpe: {np.mean(is_sharpes):+.3f}")
        for i, f in enumerate(best["folds"]):
            print(f"  Fold {i+1}: Sharpe={f['sharpe']:+.3f}  WR={f['wr']:.1%}  "
                  f"trades={f['n']}  avg={f['avg']*100:+.2f}%  MDD={f['mdd']*100:+.2f}%")
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
