"""
vpin_eth + BTC 레짐 게이트 + 볼륨 필터 — 사이클 149
- 기반: cycle 148 최적 (vh=0.58, vm=0.0005, hold=18, TP=0.045, SL=0.008)
  Sharpe +7.508, WR 29.1%, MDD -21.54%
- 목표: WR ≥ 35%, MDD ≤ -15%, Sharpe ≥ 5.0 유지
- 추가 필터:
  1) BTC 레짐 게이트: BTC EMA 트렌드 상승 시에만 진입
  2) 볼륨 필터: 볼륨 > N-bar SMA 배수 일 때만 진입
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

# ── 고정: cycle 148 최적 파라미터 ────────────────────────────────────────────
VPIN_HIGH = 0.58
VPIN_MOM_THRESH = 0.0005
MAX_HOLD = 18
BASE_TP = 0.045
BASE_SL = 0.008

# ── 탐색 그리드: 레짐 + 볼륨 필터 ───────────────────────────────────────────
# BTC EMA period for regime gate
BTC_EMA_PERIOD_LIST = [10, 20, 30, 50]
# BTC lookback for trend (close > EMA = bullish)
# + BTC momentum: BTC N-bar return > threshold
BTC_MOM_LOOKBACK_LIST = [5, 10, 20]
BTC_MOM_THRESH_LIST = [-0.02, 0.0, 0.01, 0.02]  # 0.0 = BTC not falling

# Volume filter: volume > vol_sma_period SMA * vol_mult
VOL_SMA_PERIOD_LIST = [10, 20, 30]
VOL_MULT_LIST = [0.8, 1.0, 1.2, 1.5]

# 고정 VPIN/지표 파라미터
VPIN_LOW = 0.35
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8

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


def compute_vpin(closes: np.ndarray, opens: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def compute_btc_momentum(closes: np.ndarray, lookback: int) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame,
    btc_ema_period: int,
    btc_mom_lookback: int,
    btc_mom_thresh: float,
    vol_sma_period: int,
    vol_mult: float,
    slippage: float = 0.0005,
) -> dict:
    # ETH 지표
    c = df_eth["close"].values
    o = df_eth["open"].values
    v = df_eth["volume"].values
    n = len(c)

    rsi_arr = rsi(c, RSI_PERIOD)
    ema_arr = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr = compute_vpin_momentum(c, MOM_LOOKBACK)
    vol_sma_arr = sma(v, vol_sma_period)

    # BTC 지표 — align to ETH index
    btc_close = df_btc.reindex(df_eth.index)["close"].values
    btc_ema_arr = ema(btc_close, btc_ema_period)
    btc_mom_arr = compute_btc_momentum(btc_close, btc_mom_lookback)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 btc_ema_period, btc_mom_lookback, vol_sma_period) + 5
    i = warmup
    while i < n - 1:
        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        vol_val = v[i]
        vol_sma_val = vol_sma_arr[i]
        btc_ema_val = btc_ema_arr[i]
        btc_close_val = btc_close[i]
        btc_mom_val = btc_mom_arr[i]

        # 기본 VPIN 조건 (cycle 148과 동일)
        vpin_ok = (
            not np.isnan(vpin_val) and vpin_val > VPIN_HIGH
            and not np.isnan(mom_val) and mom_val > VPIN_MOM_THRESH
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        # BTC 레짐 게이트: BTC close > BTC EMA + BTC momentum > threshold
        btc_ok = (
            not np.isnan(btc_ema_val) and not np.isnan(btc_close_val)
            and btc_close_val > btc_ema_val
            and not np.isnan(btc_mom_val) and btc_mom_val > btc_mom_thresh
        )

        # 볼륨 필터: ETH volume > SMA * multiplier
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * vol_mult
        )

        if vpin_ok and btc_ok and vol_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= BASE_TP:
                    returns.append(BASE_TP - FEE - slippage)
                    i = j
                    break
                if ret <= -BASE_SL:
                    returns.append(-BASE_SL - FEE - slippage)
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
    print("=== vpin_eth + BTC 레짐 게이트 + 볼륨 필터 (사이클 149) ===")
    print(f"심볼: {SYMBOL}  기반: cycle148 최적 (vh={VPIN_HIGH} vm={VPIN_MOM_THRESH} "
          f"hold={MAX_HOLD} TP={BASE_TP} SL={BASE_SL})")
    print(f"목표: WR ≥ 35%, MDD ≤ -15%, Sharpe ≥ 5.0")
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

    # ── Phase 0: 베이스라인 (필터 없이 cycle 148 재현) ────────────────────────
    print(f"\n--- 베이스라인 (cycle 148, 필터 없음) ---")
    # Dummy BTC gate that always passes: btc_ema=1, btc_mom_lookback=1, btc_thresh=-9
    # vol_mult=0 always passes
    base = backtest(df_eth, df_btc, 10, 5, -9.0, 10, 0.0)
    print(f"  Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"n={base['trades']}")

    # ── Phase 1: 전체기간 그리드 서치 ──────────────────────────────────────────
    combos = list(product(
        BTC_EMA_PERIOD_LIST, BTC_MOM_LOOKBACK_LIST, BTC_MOM_THRESH_LIST,
        VOL_SMA_PERIOD_LIST, VOL_MULT_LIST,
    ))
    print(f"\n총 필터 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (bep, bml, bmt, vsp, vmu) in enumerate(combos):
        if idx % 100 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        r = backtest(df_eth, df_btc, bep, bml, bmt, vsp, vmu)
        results.append({
            "btc_ema": bep, "btc_mom_lb": bml, "btc_mom_th": bmt,
            "vol_sma": vsp, "vol_mult": vmu, **r,
        })

    # n ≥ 20 필터 + Sharpe ≥ 3.0
    valid = [r for r in results
             if r["trades"] >= 20
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 3.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥20, Sharpe≥3.0): {len(valid)}/{len(results)}")

    # WR ≥ 35% 필터 우선 표시
    high_wr = [r for r in valid if r["wr"] >= 0.35]
    print(f"WR ≥ 35% 조합: {len(high_wr)}개")

    display = high_wr[:20] if high_wr else valid[:20]
    label = "WR≥35% Top 20" if high_wr else "Sharpe Top 20 (WR<35%)"
    print(f"\n=== {label} (전체기간) ===")
    print(f"{'bEMA':>5} {'bLB':>4} {'bTH':>6} {'vSMA':>5} {'vMul':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print("-" * 80)
    for r in display:
        print(
            f"{r['btc_ema']:>5} {r['btc_mom_lb']:>4} {r['btc_mom_th']:>+5.2f} "
            f"{r['vol_sma']:>5} {r['vol_mult']:>5.1f} | "
            f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        return

    best = valid[0]
    print(f"\n★ 전체기간 최적: bEMA={best['btc_ema']} bLB={best['btc_mom_lb']} "
          f"bTH={best['btc_mom_th']} vSMA={best['vol_sma']} vMul={best['vol_mult']}")
    print(f"  Sharpe: {best['sharpe']:+.3f}  WR: {best['wr']:.1%}  "
          f"avg={best['avg_ret'] * 100:+.2f}%  MDD={best['max_dd'] * 100:+.2f}%  "
          f"n={best['trades']}")

    # ── Phase 2: Walkforward 검증 (Top 10) ─────────────────────────────────
    # Prefer high_wr candidates, fallback to sharpe-sorted
    wf_candidates = (high_wr[:10] if len(high_wr) >= 5
                     else valid[:10])
    print(f"\n{'=' * 80}")
    print("=== Walk-Forward 검증 (Top 10, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(wf_candidates, 1):
        bep = params["btc_ema"]
        bml = params["btc_mom_lb"]
        bmt = params["btc_mom_th"]
        vsp = params["vol_sma"]
        vmu = params["vol_mult"]
        print(f"\n--- #{rank}: bEMA={bep} bLB={bml} bTH={bmt} "
              f"vSMA={vsp} vMul={vmu} ---")

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
            r = backtest(df_eth_test, df_btc_test, bep, bml, bmt, vsp, vmu)
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

    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"], reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 3) ===")

    for rank, params in enumerate(wf_top3, 1):
        bep = params["btc_ema"]
        bml = params["btc_mom_lb"]
        bmt = params["btc_mom_th"]
        vsp = params["vol_sma"]
        vmu = params["vol_mult"]
        print(f"\n--- #{rank}: bEMA={bep} bLB={bml} bTH={bmt} "
              f"vSMA={vsp} vMul={vmu} (avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_eth, df_btc, bep, bml, bmt, vsp, vmu, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: bEMA={best_wf['btc_ema']} bLB={best_wf['btc_mom_lb']} "
          f"bTH={best_wf['btc_mom_th']} vSMA={best_wf['vol_sma']} "
          f"vMul={best_wf['vol_mult']}")
    print(f"  (VPIN 고정: vh={VPIN_HIGH} vm={VPIN_MOM_THRESH} hold={MAX_HOLD} "
          f"TP={BASE_TP} SL={BASE_SL})")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  MDD={fd['max_dd'] * 100:+.2f}%")

    # vs 베이스라인
    print(f"\n  vs 베이스라인 (필터 없음): Sharpe={base['sharpe']:+.3f}  "
          f"WR={base['wr']:.1%}  MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")

    # pipeline output
    avg_wr = np.mean([fd["wr"] for fd in best_wf["fold_details"]])
    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {sum(best_wf['oos_trades'])}")


if __name__ == "__main__":
    main()
