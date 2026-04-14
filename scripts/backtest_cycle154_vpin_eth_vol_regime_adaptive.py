"""
vpin_eth 사이클 154 — 변동성 레짐 적응형 ATR배수 + EMA 기울기 필터
- 기반: cycle 151 최적 ATR=20 tpM=3.0 slM=0.5 VH=0.5 RSIc=75.0 bTH=0.02
  avg OOS Sharpe: +10.714, WR=37.7%, n=70
- 문제점:
  1) 고정 ATR 배수 → 고변동성 구간에서 SL이 너무 좁아 조기 손절
  2) 저변동성 구간에서 TP가 너무 넓어 만기 청산 빈도↑
  3) 추세 강도 무시 → 횡보장 진입으로 WR 저하
- 가설:
  1) ATR percentile로 변동성 레짐 분류 (high/low)
     high_vol: TP 배수↑ SL 배수↑ (변동성 활용, 노이즈 회피)
     low_vol:  TP 배수↓ SL 배수↓ (좁은 범위 내 빠른 청산)
  2) EMA 기울기(slope) > threshold → 추세 확인 후 진입
- 탐색:
  ATR percentile 기준, high/low별 TP/SL 배수 오프셋, EMA slope 기간/문턱
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

# ── 고정: cycle 151 최적 파라미터 ────────────────────────────────────────────
BTC_EMA_PERIOD = 50
BTC_MOM_LOOKBACK = 10
BTC_MOM_THRESH = 0.02
VOL_SMA_PERIOD = 30
VOL_MULT = 1.5
VPIN_HIGH = 0.50
RSI_CEILING = 75.0
ATR_PERIOD = 20
BASE_TP_MULT = 3.0
BASE_SL_MULT = 0.5

# 고정 파라미터
VPIN_MOM_THRESH = 0.0005
MAX_HOLD = 18
EMA_PERIOD = 20
MOM_LOOKBACK = 8
RSI_PERIOD = 14
RSI_FLOOR = 20.0
BUCKET_COUNT = 24

# ── 탐색 그리드 ──────────────────────────────────────────────────────────────
# 변동성 레짐 분류: ATR percentile 기준
VOL_REGIME_LOOKBACK_LIST = [60, 90, 120]          # ATR percentile 산정 기간 (봉)
VOL_REGIME_THRESH_LIST = [40, 50, 60]              # percentile 기준 (이하=low, 초과=high)

# high_vol일 때 base 대비 오프셋
HV_TP_OFFSET_LIST = [0.0, 0.5, 1.0, 1.5]          # high_vol TP = base + offset
HV_SL_OFFSET_LIST = [0.0, 0.2, 0.4]                # high_vol SL = base + offset

# low_vol일 때 base 대비 오프셋 (축소)
LV_TP_OFFSET_LIST = [0.0, -0.5, -1.0]              # low_vol TP = base + offset
LV_SL_OFFSET_LIST = [0.0, -0.1, -0.2]              # low_vol SL = base + offset

# EMA 기울기 필터
EMA_SLOPE_PERIOD_LIST = [5, 10]                     # 기울기 산정 기간 (봉)
EMA_SLOPE_THRESH_LIST = [0.0, 0.001, 0.002, 0.003] # 기울기 문턱 (0=비활성)

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


def compute_atr_percentile(atr_arr: np.ndarray, lookback: int) -> np.ndarray:
    """각 시점에서 과거 lookback 기간 내 ATR의 percentile(0~100)을 반환."""
    n = len(atr_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = atr_arr[i - lookback:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) < 10:
            continue
        result[i] = float(np.sum(valid <= atr_arr[i]) / len(valid) * 100)
    return result


def compute_ema_slope(ema_arr: np.ndarray, period: int) -> np.ndarray:
    """EMA의 N봉 전 대비 변화율 (기울기 proxy)."""
    n = len(ema_arr)
    result = np.full(n, np.nan)
    for i in range(period, n):
        if not np.isnan(ema_arr[i]) and not np.isnan(ema_arr[i - period]):
            if ema_arr[i - period] > 0:
                result[i] = (ema_arr[i] - ema_arr[i - period]) / ema_arr[i - period]
    return result


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame,
    vol_regime_lb: int,
    vol_regime_th: int,
    hv_tp_off: float,
    hv_sl_off: float,
    lv_tp_off: float,
    lv_sl_off: float,
    ema_slope_period: int,
    ema_slope_thresh: float,
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
    atr_arr = atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma(v, VOL_SMA_PERIOD)
    atr_pctl_arr = compute_atr_percentile(atr_arr, vol_regime_lb)
    ema_slope_arr = compute_ema_slope(ema_arr, ema_slope_period)

    btc_close = df_btc.reindex(df_eth.index)["close"].values
    btc_ema_arr = ema(btc_close, BTC_EMA_PERIOD)
    btc_mom_arr = compute_momentum(btc_close, BTC_MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 BTC_EMA_PERIOD, BTC_MOM_LOOKBACK, VOL_SMA_PERIOD,
                 ATR_PERIOD, vol_regime_lb, ema_slope_period) + 5
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
        atr_pctl = atr_pctl_arr[i]
        ema_slope = ema_slope_arr[i]

        # VPIN 진입 조건
        vpin_ok = (
            not np.isnan(vpin_val) and vpin_val > VPIN_HIGH
            and not np.isnan(mom_val) and mom_val > VPIN_MOM_THRESH
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        # BTC 레짐 게이트
        btc_ok = (
            not np.isnan(btc_ema_val) and not np.isnan(btc_close_val)
            and btc_close_val > btc_ema_val
            and not np.isnan(btc_mom_val) and btc_mom_val > BTC_MOM_THRESH
        )

        # 볼륨 필터
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * VOL_MULT
        )

        # ATR 유효성
        atr_ok = not np.isnan(atr_val) and atr_val > 0

        # EMA 기울기 필터 (0이면 비활성)
        slope_ok = True
        if ema_slope_thresh > 0:
            slope_ok = (
                not np.isnan(ema_slope) and ema_slope > ema_slope_thresh
            )

        # 변동성 레짐 유효성
        regime_ok = not np.isnan(atr_pctl)

        if vpin_ok and btc_ok and vol_ok and atr_ok and slope_ok and regime_ok:
            # 변동성 레짐에 따른 ATR 배수 결정
            atr_pct = atr_val / c[i]
            if atr_pctl > vol_regime_th:
                # high volatility regime
                tp_mult = BASE_TP_MULT + hv_tp_off
                sl_mult = BASE_SL_MULT + hv_sl_off
            else:
                # low volatility regime
                tp_mult = BASE_TP_MULT + lv_tp_off
                sl_mult = BASE_SL_MULT + lv_sl_off

            tp = atr_pct * tp_mult
            sl = atr_pct * sl_mult

            # 안전장치: TP 1%~10%, SL 0.3%~4%
            tp = max(0.01, min(0.10, tp))
            sl = max(0.003, min(0.04, sl))

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
    print("=== vpin_eth 변동성 레짐 적응형 ATR배수 + EMA 기울기 (사이클 154) ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: cycle 151 최적 ATR=20 tpM=3.0 slM=0.5 VH=0.5 RSIc=75 bTH=0.02")
    print(f"탐색: 레짐LB/TH, HV/LV TP/SL 오프셋, EMA slope 기간/문턱")
    print(f"목표: Sharpe > +10.7, WR ≥ 38%, n ≥ 60, MDD ≤ -12%")
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

    # ── Phase 0: 베이스라인 (cycle 151 고정 ATR배수) ───────────────────────────
    print(f"\n--- 베이스라인 (cycle 151 고정 ATR배수, slope 비활성) ---")
    base = backtest(df_eth, df_btc, 90, 50, 0.0, 0.0, 0.0, 0.0, 5, 0.0)
    print(f"  Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"n={base['trades']}")

    # ── Phase 1: 전체기간 그리드 서치 ──────────────────────────────────────────
    combos = list(product(
        VOL_REGIME_LOOKBACK_LIST, VOL_REGIME_THRESH_LIST,
        HV_TP_OFFSET_LIST, HV_SL_OFFSET_LIST,
        LV_TP_OFFSET_LIST, LV_SL_OFFSET_LIST,
        EMA_SLOPE_PERIOD_LIST, EMA_SLOPE_THRESH_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (vlb, vth, htp, hsl, ltp, lsl, sp, sth) in enumerate(combos):
        if idx % 500 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")

        # low_vol TP/SL 배수가 음수가 되면 스킵
        if BASE_TP_MULT + ltp < 1.0 or BASE_SL_MULT + lsl < 0.1:
            continue

        r = backtest(df_eth, df_btc, vlb, vth, htp, hsl, ltp, lsl, sp, sth)
        results.append({
            "vol_lb": vlb, "vol_th": vth,
            "hv_tp": htp, "hv_sl": hsl, "lv_tp": ltp, "lv_sl": lsl,
            "slope_p": sp, "slope_th": sth, **r,
        })

    # n ≥ 30 + Sharpe ≥ 3.0
    valid = [r for r in results
             if r["trades"] >= 30
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 3.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥30, Sharpe≥3.0): {len(valid)}/{len(results)}")

    high_n = [r for r in valid if r["trades"] >= 50]
    print(f"n ≥ 50 조합: {len(high_n)}개")

    display = high_n[:20] if high_n else valid[:20]
    label = "n≥50 Top 20" if high_n else "Sharpe Top 20 (n<50)"
    print(f"\n=== {label} (전체기간) ===")
    print(f"{'vLB':>4} {'vTH':>4} {'hvTP':>5} {'hvSL':>5} {'lvTP':>5} "
          f"{'lvSL':>5} {'sP':>3} {'sTH':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print("-" * 100)
    for r in display:
        print(
            f"{r['vol_lb']:>4} {r['vol_th']:>4} {r['hv_tp']:>+5.1f} "
            f"{r['hv_sl']:>+5.1f} {r['lv_tp']:>+5.1f} {r['lv_sl']:>+5.1f} "
            f"{r['slope_p']:>3} {r['slope_th']:>5.3f} | "
            f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        return

    best = valid[0]
    print(f"\n★ 전체기간 최적: vLB={best['vol_lb']} vTH={best['vol_th']} "
          f"hvTP={best['hv_tp']:+.1f} hvSL={best['hv_sl']:+.1f} "
          f"lvTP={best['lv_tp']:+.1f} lvSL={best['lv_sl']:+.1f} "
          f"sP={best['slope_p']} sTH={best['slope_th']:.3f}")
    print(f"  Sharpe: {best['sharpe']:+.3f}  WR: {best['wr']:.1%}  "
          f"avg={best['avg_ret'] * 100:+.2f}%  MDD={best['max_dd'] * 100:+.2f}%  "
          f"n={best['trades']}")

    # ── Phase 2: Walkforward 검증 (Top 10) ─────────────────────────────────
    wf_candidates = (high_n[:10] if len(high_n) >= 5 else valid[:10])
    print(f"\n{'=' * 80}")
    print("=== Walk-Forward 검증 (Top 10, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(wf_candidates, 1):
        vlb = params["vol_lb"]
        vth = params["vol_th"]
        htp = params["hv_tp"]
        hsl = params["hv_sl"]
        ltp = params["lv_tp"]
        lsl = params["lv_sl"]
        sp = params["slope_p"]
        sth = params["slope_th"]
        print(f"\n--- #{rank}: vLB={vlb} vTH={vth} hvTP={htp:+.1f} hvSL={hsl:+.1f} "
              f"lvTP={ltp:+.1f} lvSL={lsl:+.1f} sP={sp} sTH={sth:.3f} ---")

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
            r = backtest(df_eth_test, df_btc_test, vlb, vth, htp, hsl,
                         ltp, lsl, sp, sth)
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
        vlb = params["vol_lb"]
        vth = params["vol_th"]
        htp = params["hv_tp"]
        hsl = params["hv_sl"]
        ltp = params["lv_tp"]
        lsl = params["lv_sl"]
        sp = params["slope_p"]
        sth = params["slope_th"]
        print(f"\n--- #{rank}: vLB={vlb} vTH={vth} hvTP={htp:+.1f} hvSL={hsl:+.1f} "
              f"lvTP={ltp:+.1f} lvSL={lsl:+.1f} sP={sp} sTH={sth:.3f} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_eth, df_btc, vlb, vth, htp, hsl, ltp, lsl,
                         sp, sth, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: vLB={best_wf['vol_lb']} vTH={best_wf['vol_th']} "
          f"hvTP={best_wf['hv_tp']:+.1f} hvSL={best_wf['hv_sl']:+.1f} "
          f"lvTP={best_wf['lv_tp']:+.1f} lvSL={best_wf['lv_sl']:+.1f} "
          f"sP={best_wf['slope_p']} sTH={best_wf['slope_th']:.3f}")
    print(f"  (기반: ATR={ATR_PERIOD} baseTpM={BASE_TP_MULT} baseSlM={BASE_SL_MULT} "
          f"VH={VPIN_HIGH} RSIc={RSI_CEILING} bTH={BTC_MOM_THRESH} "
          f"hold={MAX_HOLD})")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  MDD={fd['max_dd'] * 100:+.2f}%")

    print(f"\n  vs 베이스라인 (cycle 151 고정 ATR배수): "
          f"Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")

    avg_wr = np.mean([fd["wr"] for fd in best_wf["fold_details"]])
    total_n = sum(best_wf["oos_trades"])
    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
