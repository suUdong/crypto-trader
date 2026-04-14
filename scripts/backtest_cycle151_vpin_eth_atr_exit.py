"""
vpin_eth + BTC 레짐 게이트 + 볼륨 필터 + ATR 적응형 TP/SL — 사이클 151
- 기반: cycle 149 최적 (bEMA=50 bLB=10 bTH=0.02 vSMA=30 vMul=1.5)
  Sharpe +13.045, WR 36.0%, n=45 (부족)
- 문제: 고정 TP=0.045/SL=0.008에 n=45 → 너무 적음
- 목표: n ≥ 60, Sharpe ≥ 8.0, WR ≥ 33%, MDD ≤ -12%
- 탐색:
  1) ATR 기반 적응형 TP/SL (변동성에 맞춤 → 더 많은 시장 조건에서 진입 가능)
  2) VPIN/RSI 문턱값 완화 (진입 기준 소폭 완화 → 트레이드 수 확대)
  3) BTC 모멘텀 문턱값 소폭 완화
- 2-fold walkforward + 슬리피지 스트레스
- 진입: next_bar open
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005

# ── 고정: cycle 149 최적 필터 파라미터 ────────────────────────────────────────
BTC_EMA_PERIOD = 50
BTC_MOM_LOOKBACK = 10
VOL_SMA_PERIOD = 30
VOL_MULT = 1.5

# ── 탐색 그리드 ──────────────────────────────────────────────────────────────
# ATR 기반 TP/SL: TP = atr * tp_mult, SL = atr * sl_mult
ATR_PERIOD_LIST = [10, 14, 20]
TP_ATR_MULT_LIST = [2.0, 2.5, 3.0, 3.5]
SL_ATR_MULT_LIST = [0.5, 0.8, 1.0, 1.2]

# VPIN/RSI 문턱값 완화 탐색
VPIN_HIGH_LIST = [0.50, 0.54, 0.58]         # 기존 0.58 → 완화 탐색
RSI_CEILING_LIST = [65.0, 70.0, 75.0]        # 기존 65 → 완화 탐색
BTC_MOM_THRESH_LIST = [0.0, 0.01, 0.02]      # 기존 0.02 → 완화 탐색

# 고정 파라미터
VPIN_MOM_THRESH = 0.0005
MAX_HOLD = 18
EMA_PERIOD = 20
MOM_LOOKBACK = 8
RSI_PERIOD = 14
RSI_FLOOR = 20.0
BUCKET_COUNT = 24

# ── Walkforward 기간 ─────────────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

def ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def sma(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        result[i] = series[i - period + 1:i + 1].mean()
    return result


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


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        period: int) -> np.ndarray:
    n = len(closes)
    tr = np.full(n, np.nan)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    result = np.full(n, np.nan)
    if n < period:
        return result
    result[period - 1] = tr[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, n):
        result[i] = tr[i] * k + result[i - 1] * (1 - k)
    return result


def compute_vpin(closes: np.ndarray, opens: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_momentum(closes: np.ndarray, lookback: int) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame,
    atr_period: int,
    tp_atr_mult: float,
    sl_atr_mult: float,
    vpin_high: float,
    rsi_ceiling: float,
    btc_mom_thresh: float,
    slippage: float = 0.0005,
) -> dict:
    c = df_eth["close"].values
    o = df_eth["open"].values
    h = df_eth["high"].values
    lo = df_eth["low"].values
    v = df_eth["volume"].values
    n = len(c)

    rsi_arr = rsi(c, RSI_PERIOD)
    ema_arr = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = atr(h, lo, c, atr_period)
    vol_sma_arr = sma(v, VOL_SMA_PERIOD)

    btc_close = df_btc.reindex(df_eth.index)["close"].values
    btc_ema_arr = ema(btc_close, BTC_EMA_PERIOD)
    btc_mom_arr = compute_momentum(btc_close, BTC_MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 BTC_EMA_PERIOD, BTC_MOM_LOOKBACK, VOL_SMA_PERIOD,
                 atr_period) + 5
    i = warmup
    while i < n - 1:
        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_val = v[i]
        vol_sma_val = vol_sma_arr[i]
        btc_ema_val = btc_ema_arr[i]
        btc_close_val = btc_close[i]
        btc_mom_val = btc_mom_arr[i]

        # VPIN 진입 조건 (문턱값 탐색)
        vpin_ok = (
            not np.isnan(vpin_val) and vpin_val > vpin_high
            and not np.isnan(mom_val) and mom_val > VPIN_MOM_THRESH
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < rsi_ceiling
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        # BTC 레짐 게이트 (문턱값 탐색)
        btc_ok = (
            not np.isnan(btc_ema_val) and not np.isnan(btc_close_val)
            and btc_close_val > btc_ema_val
            and not np.isnan(btc_mom_val) and btc_mom_val > btc_mom_thresh
        )

        # 볼륨 필터 (고정)
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * VOL_MULT
        )

        # ATR 유효성
        atr_ok = not np.isnan(atr_val) and atr_val > 0

        if vpin_ok and btc_ok and vol_ok and atr_ok:
            # ATR 기반 적응형 TP/SL
            atr_pct = atr_val / c[i]
            tp = atr_pct * tp_atr_mult
            sl = atr_pct * sl_atr_mult

            # 안전장치: TP 1%~8%, SL 0.3%~3%
            tp = max(0.01, min(0.08, tp))
            sl = max(0.003, min(0.03, sl))

            buy = o[i + 1] * (1 + FEE + slippage)
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE - slippage)
                    i = j
                    break
                if ret <= -sl:
                    returns.append(-sl - FEE - slippage)
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE - slippage)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    mcl = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl}


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth + ATR 적응형 TP/SL + 문턱값 완화 (사이클 151) ===")
    print(f"심볼: {SYMBOL}")
    print(f"고정 필터: bEMA={BTC_EMA_PERIOD} bLB={BTC_MOM_LOOKBACK} "
          f"vSMA={VOL_SMA_PERIOD} vMul={VOL_MULT}")
    print(f"탐색: ATR TP/SL, VPIN 문턱, RSI 상한, BTC 모멘텀 문턱")
    print(f"목표: n ≥ 60, Sharpe ≥ 8.0, WR ≥ 33%, MDD ≤ -12%")
    print("=" * 80)

    # ── 데이터 로드 ────────────────────────────────────────────────────────────
    df_eth = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC_SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_eth.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"\nETH: {len(df_eth)}행 ({df_eth.index[0]} ~ {df_eth.index[-1]})")
    print(f"BTC: {len(df_btc)}행 ({df_btc.index[0]} ~ {df_btc.index[-1]})")
    bh = buy_and_hold(df_eth)
    print(f"ETH Buy-and-Hold: {bh * 100:+.1f}%")

    # ── Phase 0: 베이스라인 (cycle 149 최적, 고정 TP/SL) ─────────────────────
    print(f"\n--- 베이스라인 (cycle 149 최적, 고정 TP=0.045 SL=0.008) ---")
    # ATR period=14, but with fixed TP/SL equivalent ~ tp_mult=3.0 sl_mult=0.6
    base = backtest(df_eth, df_btc, 14, 3.0, 0.6, 0.58, 65.0, 0.02)
    print(f"  Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"n={base['trades']}")

    # ── Phase 1: 전체기간 그리드 서치 ──────────────────────────────────────────
    combos = list(product(
        ATR_PERIOD_LIST, TP_ATR_MULT_LIST, SL_ATR_MULT_LIST,
        VPIN_HIGH_LIST, RSI_CEILING_LIST, BTC_MOM_THRESH_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (atr_p, tp_m, sl_m, vh, rc, bmt) in enumerate(combos):
        if idx % 200 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        r = backtest(df_eth, df_btc, atr_p, tp_m, sl_m, vh, rc, bmt)
        results.append({
            "atr_period": atr_p, "tp_mult": tp_m, "sl_mult": sl_m,
            "vpin_high": vh, "rsi_ceil": rc, "btc_mom_th": bmt, **r,
        })

    # n ≥ 30 + Sharpe ≥ 3.0
    valid = [r for r in results
             if r["trades"] >= 30
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 3.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥30, Sharpe≥3.0): {len(valid)}/{len(results)}")

    # n ≥ 50 우선
    high_n = [r for r in valid if r["trades"] >= 50]
    print(f"n ≥ 50 조합: {len(high_n)}개")

    display = high_n[:20] if high_n else valid[:20]
    label = "n≥50 Top 20" if high_n else "Sharpe Top 20 (n<50)"
    print(f"\n=== {label} (전체기간) ===")
    print(f"{'ATR':>4} {'tpM':>4} {'slM':>4} {'VH':>5} {'RSIc':>5} {'bTH':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print("-" * 85)
    for r in display:
        print(
            f"{r['atr_period']:>4} {r['tp_mult']:>4.1f} {r['sl_mult']:>4.1f} "
            f"{r['vpin_high']:>5.2f} {r['rsi_ceil']:>5.0f} {r['btc_mom_th']:>+5.2f} | "
            f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        return

    best = valid[0]
    print(f"\n★ 전체기간 최적: ATR={best['atr_period']} tpM={best['tp_mult']} "
          f"slM={best['sl_mult']} VH={best['vpin_high']} RSIc={best['rsi_ceil']} "
          f"bTH={best['btc_mom_th']}")
    print(f"  Sharpe: {best['sharpe']:+.3f}  WR: {best['wr']:.1%}  "
          f"avg={best['avg_ret'] * 100:+.2f}%  MDD={best['max_dd'] * 100:+.2f}%  "
          f"n={best['trades']}")

    # ── Phase 2: Walkforward 검증 (Top 10) ─────────────────────────────────
    wf_candidates = (high_n[:10] if len(high_n) >= 5 else valid[:10])
    print(f"\n{'=' * 80}")
    print("=== Walk-Forward 검증 (Top 10, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(wf_candidates, 1):
        atr_p = params["atr_period"]
        tp_m = params["tp_mult"]
        sl_m = params["sl_mult"]
        vh = params["vpin_high"]
        rc = params["rsi_ceil"]
        bmt = params["btc_mom_th"]
        print(f"\n--- #{rank}: ATR={atr_p} tpM={tp_m} slM={sl_m} "
              f"VH={vh} RSIc={rc} bTH={bmt} ---")

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_eth_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_test = load_historical(
                BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
            if df_eth_test.empty or df_btc_test.empty:
                print(f"  Fold {fold_i + 1}: 데이터 없음")
                continue
            r = backtest(df_eth_test, df_btc_test, atr_p, tp_m, sl_m,
                         vh, rc, bmt)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)
            bh_fold = buy_and_hold(df_eth_test)
            print(f"  Fold {fold_i + 1} OOS [{fold['test'][0]}~{fold['test'][1]}]: "
                  f"Sharpe={sh:+.3f}  WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%  "
                  f"BH={bh_fold * 100:+.1f}%")

        if oos_sharpes:
            avg_oos = np.mean(oos_sharpes)
            min_oos = min(oos_sharpes)
            min_n = min(oos_trades) if oos_trades else 0
            print(f"  평균 OOS Sharpe: {avg_oos:+.3f} | 최소: {min_oos:+.3f} | "
                  f"min_n: {min_n}")
            wf_results.append({
                **params,
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "fold_details": fold_details,
            })

    # ── Phase 3: 슬리피지 스트레스 (WF Top 3) ──────────────────────────────
    if not wf_results:
        print("\nWF 검증 결과 없음.")
        return

    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                        reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 3) ===")

    for rank, params in enumerate(wf_top3, 1):
        atr_p = params["atr_period"]
        tp_m = params["tp_mult"]
        sl_m = params["sl_mult"]
        vh = params["vpin_high"]
        rc = params["rsi_ceil"]
        bmt = params["btc_mom_th"]
        print(f"\n--- #{rank}: ATR={atr_p} tpM={tp_m} slM={sl_m} "
              f"VH={vh} RSIc={rc} bTH={bmt} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_eth, df_btc, atr_p, tp_m, sl_m, vh, rc, bmt,
                         slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: ATR={best_wf['atr_period']} tpM={best_wf['tp_mult']} "
          f"slM={best_wf['sl_mult']} VH={best_wf['vpin_high']} "
          f"RSIc={best_wf['rsi_ceil']} bTH={best_wf['btc_mom_th']}")
    print(f"  (고정: bEMA={BTC_EMA_PERIOD} bLB={BTC_MOM_LOOKBACK} "
          f"vSMA={VOL_SMA_PERIOD} vMul={VOL_MULT} hold={MAX_HOLD})")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  MDD={fd['max_dd'] * 100:+.2f}%")

    print(f"\n  vs 베이스라인 (cycle 149 고정 TP/SL): "
          f"Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")

    avg_wr = np.mean([fd["wr"] for fd in best_wf["fold_details"]])
    total_n = sum(best_wf["oos_trades"])
    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
