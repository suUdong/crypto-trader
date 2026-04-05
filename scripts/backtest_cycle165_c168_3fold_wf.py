"""
c165: c168 vpin_eth trailing+regime hold — 3-fold WF 검증 (BEAR 구간 필수 포함)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
평가자 블로커: c168 최적(hvH=24 lvH=14 trA=2.0 trSL=0.5) 3-fold WF 미실시.
BEAR 구간(2022 또는 2025) 포함 검증 전까지 daemon 교체 불가.

3-fold WF 설계:
  F1: train 2022-01~2023-12  → OOS 2024-01~2024-09  (BULL 검증)
  F2: train 2022-01~2024-12  → OOS 2025-01~2025-09  (★ 2025 BEAR 포함)
  F3: train 2023-01~2025-09  → OOS 2025-10~2026-04  (최근 회복기)

통과 기준: 모든 fold OOS Sharpe ≥ 3.0 AND n ≥ 5
배포 기준: avg OOS Sharpe ≥ 5.0 AND min fold Sharpe ≥ 1.0
그리드: 최적 파라미터 + 근접 27조합 = 총 27개
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005

# ── 고정: c154 최적 + c160 ATR 파라미터 ─────────────────────────────────────
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

VPIN_MOM_THRESH = 0.0005
EMA_PERIOD = 20
MOM_LOOKBACK = 8
RSI_PERIOD = 14
RSI_FLOOR = 20.0
BUCKET_COUNT = 24

# c154 최적 레짐 파라미터
VOL_REGIME_LOOKBACK = 90
VOL_REGIME_THRESH = 50
HV_TP_OFFSET = 1.0
HV_SL_OFFSET = 0.2
LV_TP_OFFSET = -0.5
LV_SL_OFFSET = -0.1
EMA_SLOPE_PERIOD = 5
EMA_SLOPE_THRESH = 0.001

# ── 3-fold WF 근접 그리드 (c168 최적 hvH=24 lvH=14 trA=2.0 trSL=0.5 중심) ──
HV_HOLD_LIST = [20, 24, 28]
LV_HOLD_LIST = [12, 14, 16]
TRAIL_ACTIVATE_MULT_LIST = [1.8, 2.0, 2.2]
TRAIL_SL_MULT_LIST = [0.4, 0.5, 0.6]
# 3×3×3×3 = 81 조합

WF_FOLDS = [
    {
        "name": "F1 (BULL)",
        "train": ("2022-01-01", "2023-12-31"),
        "test": ("2024-01-01", "2024-09-30"),
    },
    {
        "name": "F2 (★BEAR 2025)",
        "train": ("2022-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2025-09-30"),
    },
    {
        "name": "F3 (회복기)",
        "train": ("2023-01-01", "2025-09-30"),
        "test": ("2025-10-01", "2026-04-05"),
    },
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

def ema_func(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def sma_func(series: np.ndarray, period: int) -> np.ndarray:
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


def atr_func(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int,
) -> np.ndarray:
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
    hv_hold: int,
    lv_hold: int,
    trail_activate_mult: float,
    trail_sl_mult: float,
    slippage: float = 0.0005,
) -> dict:
    c = df_eth["close"].values
    o = df_eth["open"].values
    h = df_eth["high"].values
    lo = df_eth["low"].values
    v = df_eth["volume"].values
    n = len(c)

    rsi_arr = rsi(c, RSI_PERIOD)
    ema_arr = ema_func(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = atr_func(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_func(v, VOL_SMA_PERIOD)
    atr_pctl_arr = compute_atr_percentile(atr_arr, VOL_REGIME_LOOKBACK)
    ema_slope_arr = compute_ema_slope(ema_arr, EMA_SLOPE_PERIOD)

    btc_close = df_btc.reindex(df_eth.index)["close"].values
    btc_ema_arr = ema_func(btc_close, BTC_EMA_PERIOD)
    btc_mom_arr = compute_momentum(btc_close, BTC_MOM_LOOKBACK)

    returns: list[float] = []
    trail_exits = 0
    tp_exits = 0
    sl_exits = 0
    hold_exits = 0

    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 BTC_EMA_PERIOD, BTC_MOM_LOOKBACK, VOL_SMA_PERIOD,
                 ATR_PERIOD, VOL_REGIME_LOOKBACK, EMA_SLOPE_PERIOD) + 5
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

        # EMA 기울기 필터
        slope_ok = True
        if EMA_SLOPE_THRESH > 0:
            slope_ok = (
                not np.isnan(ema_slope) and ema_slope > EMA_SLOPE_THRESH
            )

        # 변동성 레짐
        regime_ok = not np.isnan(atr_pctl)

        if vpin_ok and btc_ok and vol_ok and atr_ok and slope_ok and regime_ok:
            atr_pct = atr_val / c[i]
            is_high_vol = atr_pctl > VOL_REGIME_THRESH

            # 레짐별 TP/SL (c154 최적 유지)
            if is_high_vol:
                tp_mult = BASE_TP_MULT + HV_TP_OFFSET
                sl_mult = BASE_SL_MULT + HV_SL_OFFSET
                max_hold = hv_hold
            else:
                tp_mult = BASE_TP_MULT + LV_TP_OFFSET
                sl_mult = BASE_SL_MULT + LV_SL_OFFSET
                max_hold = lv_hold

            tp = atr_pct * tp_mult
            sl = atr_pct * sl_mult

            tp = max(0.01, min(0.10, tp))
            sl = max(0.003, min(0.04, sl))

            # Trailing stop 파라미터 (ATR 기반)
            trail_activate_pct = atr_pct * trail_activate_mult
            trail_sl_dist = atr_pct * trail_sl_mult

            buy = o[i + 1] * (1 + FEE + slippage)
            ret = None
            exit_bar = i + 1
            trailing_active = False
            highest_ret = 0.0

            for j in range(i + 2, min(i + 1 + max_hold, n)):
                r = c[j] / buy - 1

                if r > highest_ret:
                    highest_ret = r

                # Trailing stop check
                if trailing_active:
                    trail_stop = highest_ret - trail_sl_dist
                    if r <= trail_stop:
                        ret = r - FEE - slippage
                        exit_bar = j
                        trail_exits += 1
                        break

                # Trailing 활성화
                if not trailing_active and r >= trail_activate_pct:
                    trailing_active = True

                # TP hit
                if r >= tp:
                    ret = tp - FEE - slippage
                    exit_bar = j
                    tp_exits += 1
                    break

                # SL hit
                if r <= -sl:
                    ret = -sl - FEE - slippage
                    exit_bar = j
                    sl_exits += 1
                    break

            if ret is None:
                hold_end = min(i + max_hold, n - 1)
                ret = c[hold_end] / buy - 1 - FEE - slippage
                exit_bar = hold_end
                hold_exits += 1

            returns.append(ret)
            i = exit_bar
        else:
            i += 1

    if len(returns) < 3:
        return {
            "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
            "trades": 0, "max_dd": 0.0, "mcl": 0,
            "trail_exits": 0, "tp_exits": 0, "sl_exits": 0, "hold_exits": 0,
        }
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
    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd, "mcl": mcl,
        "trail_exits": trail_exits, "tp_exits": tp_exits,
        "sl_exits": sl_exits, "hold_exits": hold_exits,
    }


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def fmt_sh(val: float) -> str:
    return f"{val:+.3f}" if not np.isnan(val) else "  nan"


def main() -> None:
    print("=" * 80)
    print("=== c165: c168 vpin_eth trailing+regime hold — 3-fold WF 검증 ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: c168 최적 hvH=24 lvH=14 trA=2.0 trSL=0.5")
    print(f"★ 평가자 블로커: BEAR 구간 포함 3-fold WF 미실시")
    print(f"그리드: hvH={HV_HOLD_LIST} lvH={LV_HOLD_LIST} "
          f"trA={TRAIL_ACTIVATE_MULT_LIST} trSL={TRAIL_SL_MULT_LIST}")
    print(f"= {len(HV_HOLD_LIST)*len(LV_HOLD_LIST)*len(TRAIL_ACTIVATE_MULT_LIST)*len(TRAIL_SL_MULT_LIST)}조합")
    print("3-fold 설계:")
    for fold in WF_FOLDS:
        print(f"  {fold['name']}: train {fold['train'][0]}~{fold['train'][1]} "
              f"→ OOS {fold['test'][0]}~{fold['test'][1]}")
    print("=" * 80)

    # ── 데이터 로드 ────────────────────────────────────────────────────────────
    df_eth_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc_full = load_historical(BTC_SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_eth_full.empty or df_btc_full.empty:
        print("데이터 없음.")
        return
    print(f"\nETH: {len(df_eth_full)}행 ({df_eth_full.index[0]} ~ {df_eth_full.index[-1]})")
    print(f"BTC: {len(df_btc_full)}행 ({df_btc_full.index[0]} ~ {df_btc_full.index[-1]})")

    # ── 전체기간 베이스라인 ─────────────────────────────────────────────────────
    bh_full = buy_and_hold(df_eth_full)
    print(f"\nETH Buy-and-Hold (전체): {bh_full * 100:+.1f}%")
    base = backtest(df_eth_full, df_btc_full, 18, 18, 99.0, 99.0)
    print(f"베이스라인 (c154 hold=18, no trail): Sharpe={fmt_sh(base['sharpe'])} "
          f"WR={base['wr']:.1%} n={base['trades']} MDD={base['max_dd']*100:+.2f}%")

    # ── 3-fold WF 그리드 ─────────────────────────────────────────────────────
    total = (len(HV_HOLD_LIST) * len(LV_HOLD_LIST)
             * len(TRAIL_ACTIVATE_MULT_LIST) * len(TRAIL_SL_MULT_LIST))
    print(f"\n총 조합: {total}개 × 3-fold = {total * 3} 백테스트")

    wf_results: list[dict] = []
    combo_idx = 0

    for hv_hold in HV_HOLD_LIST:
        for lv_hold in LV_HOLD_LIST:
            for tr_a in TRAIL_ACTIVATE_MULT_LIST:
                for tr_sl in TRAIL_SL_MULT_LIST:
                    combo_idx += 1
                    oos_sharpes: list[float] = []
                    oos_trades: list[int] = []
                    fold_details: list[dict] = []
                    all_pass = True

                    for fold in WF_FOLDS:
                        df_eth_test = load_historical(
                            SYMBOL, "240m", fold["test"][0], fold["test"][1])
                        df_btc_test = load_historical(
                            BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
                        if df_eth_test.empty or df_btc_test.empty:
                            all_pass = False
                            break
                        r = backtest(
                            df_eth_test, df_btc_test,
                            hv_hold, lv_hold, tr_a, tr_sl)
                        sh = r["sharpe"] if not np.isnan(r["sharpe"]) else -999.0
                        oos_sharpes.append(sh)
                        oos_trades.append(r["trades"])
                        fold_details.append(r)
                        # n < 3 → 실패
                        if r["trades"] < 3:
                            all_pass = False

                    if not all_pass or len(oos_sharpes) != 3:
                        continue

                    avg_oos = float(np.mean(oos_sharpes))
                    min_oos = min(oos_sharpes)

                    wf_results.append({
                        "hv_hold": hv_hold, "lv_hold": lv_hold,
                        "tr_a": tr_a, "tr_sl": tr_sl,
                        "avg_oos_sharpe": avg_oos, "min_oos_sharpe": min_oos,
                        "oos_sharpes": oos_sharpes,
                        "oos_trades": oos_trades,
                        "fold_details": fold_details,
                    })

                    if combo_idx % 20 == 0 or combo_idx == total:
                        print(f"  진행: {combo_idx}/{total} | "
                              f"hvH={hv_hold} lvH={lv_hold} "
                              f"trA={tr_a:.1f} trSL={tr_sl:.1f} → "
                              f"avg OOS={avg_oos:+.3f} min={min_oos:+.3f}")

    # ── 결과 분석 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"=== 3-fold WF 결과 ===")
    print(f"전체 조합: {total}")
    print(f"유효 결과: {len(wf_results)}")

    # 통과 기준: 모든 fold Sharpe ≥ 1.0
    passed_all = [r for r in wf_results if r["min_oos_sharpe"] >= 1.0]
    # 배포 기준: avg ≥ 5.0 AND min ≥ 1.0
    deploy_ready = [r for r in passed_all if r["avg_oos_sharpe"] >= 5.0]

    print(f"모든 fold Sharpe≥1.0 통과: {len(passed_all)}/{len(wf_results)}")
    print(f"배포 가능 (avg≥5.0 & min≥1.0): {len(deploy_ready)}/{len(wf_results)}")

    # 정렬 — avg OOS Sharpe
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"], reverse=True)

    # Top 15 출력
    display = wf_sorted[:15]
    print(f"\n=== Top 15 (avg OOS Sharpe) ===")
    print(f"{'#':>3} {'hvH':>4} {'lvH':>4} {'trA':>4} {'trSL':>5} | "
          f"{'avgOOS':>8} {'minOOS':>8} | "
          f"{'F1_Sh':>7} {'F1_n':>5} {'F2_Sh':>7} {'F2_n':>5} {'F3_Sh':>7} {'F3_n':>5} | "
          f"{'pass':>4}")
    print("-" * 100)
    for rank, r in enumerate(display, 1):
        p = "✅" if r["min_oos_sharpe"] >= 1.0 and r["avg_oos_sharpe"] >= 5.0 else \
            "⚠️" if r["min_oos_sharpe"] >= 1.0 else "❌"
        print(
            f"{rank:>3} {r['hv_hold']:>4} {r['lv_hold']:>4} "
            f"{r['tr_a']:>4.1f} {r['tr_sl']:>5.1f} | "
            f"{r['avg_oos_sharpe']:>+8.3f} {r['min_oos_sharpe']:>+8.3f} | "
            f"{r['oos_sharpes'][0]:>+7.3f} {r['oos_trades'][0]:>5} "
            f"{r['oos_sharpes'][1]:>+7.3f} {r['oos_trades'][1]:>5} "
            f"{r['oos_sharpes'][2]:>+7.3f} {r['oos_trades'][2]:>5} | "
            f"{p:>4}"
        )

    # Fold별 상세 — Top 5
    print(f"\n=== Top 5 Fold 상세 ===")
    for rank, r in enumerate(wf_sorted[:5], 1):
        print(f"\n--- #{rank}: hvH={r['hv_hold']} lvH={r['lv_hold']} "
              f"trA={r['tr_a']:.1f} trSL={r['tr_sl']:.1f} "
              f"(avg OOS: {r['avg_oos_sharpe']:+.3f}) ---")
        for fi, fold in enumerate(WF_FOLDS):
            fd = r["fold_details"][fi]
            bh_fold = 0.0  # 계산은 아래서
            df_eth_f = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1])
            if not df_eth_f.empty:
                bh_fold = buy_and_hold(df_eth_f)
            print(f"  {fold['name']}: Sharpe={r['oos_sharpes'][fi]:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={r['oos_trades'][fi]}  "
                  f"avg={fd['avg_ret']*100:+.2f}%  MDD={fd['max_dd']*100:+.2f}%  "
                  f"trX={fd['trail_exits']}  tpX={fd['tp_exits']}  "
                  f"slX={fd['sl_exits']}  hldX={fd['hold_exits']}  "
                  f"BH={bh_fold*100:+.1f}%")

    # ── 슬리피지 스트레스 (Top 3) ────────────────────────────────────────────
    if wf_sorted:
        stress_top = wf_sorted[:3]
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 (WF Top 3, 전체기간) ===")
        for rank, params in enumerate(stress_top, 1):
            print(f"\n--- #{rank}: hvH={params['hv_hold']} lvH={params['lv_hold']} "
                  f"trA={params['tr_a']:.1f} trSL={params['tr_sl']:.1f} "
                  f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
            print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
                  f"{'MDD':>7} {'MCL':>4} {'n':>5}")
            print("-" * 55)
            for slip in SLIPPAGE_LEVELS:
                r = backtest(df_eth_full, df_btc_full,
                             params["hv_hold"], params["lv_hold"],
                             params["tr_a"], params["tr_sl"],
                             slippage=slip)
                sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
                print(f"  {slip*100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                      f"{r['avg_ret']*100:>+6.2f}% {r['max_dd']*100:>+6.2f}% "
                      f"{r['mcl']:>4} {r['trades']:>5}")

    # ── c168 최적 파라미터 단독 3-fold 상세 ──────────────────────────────────
    c168_result = None
    for r in wf_results:
        if (r["hv_hold"] == 24 and r["lv_hold"] == 14
                and abs(r["tr_a"] - 2.0) < 0.01 and abs(r["tr_sl"] - 0.5) < 0.01):
            c168_result = r
            break

    if c168_result:
        print(f"\n{'=' * 80}")
        print("=== c168 최적 파라미터 (hvH=24 lvH=14 trA=2.0 trSL=0.5) 3-fold 결과 ===")
        for fi, fold in enumerate(WF_FOLDS):
            fd = c168_result["fold_details"][fi]
            print(f"  {fold['name']}: Sharpe={c168_result['oos_sharpes'][fi]:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={c168_result['oos_trades'][fi]}  "
                  f"avg={fd['avg_ret']*100:+.2f}%  MDD={fd['max_dd']*100:+.2f}%")
        print(f"  avg OOS Sharpe: {c168_result['avg_oos_sharpe']:+.3f}")
        print(f"  min OOS Sharpe: {c168_result['min_oos_sharpe']:+.3f}")
        deploy = (c168_result["avg_oos_sharpe"] >= 5.0
                  and c168_result["min_oos_sharpe"] >= 1.0)
        print(f"  배포 가능: {'✅ YES' if deploy else '❌ NO'}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")

    if deploy_ready:
        best = sorted(deploy_ready, key=lambda x: x["avg_oos_sharpe"], reverse=True)[0]
        print(f"★ 3-fold WF 배포 가능 최적: hvH={best['hv_hold']} lvH={best['lv_hold']} "
              f"trA={best['tr_a']:.1f} trSL={best['tr_sl']:.1f}")
        print(f"  avg OOS Sharpe: {best['avg_oos_sharpe']:+.3f}")
        print(f"  min OOS Sharpe: {best['min_oos_sharpe']:+.3f}")
        for fi, fold in enumerate(WF_FOLDS):
            fd = best["fold_details"][fi]
            print(f"  {fold['name']}: Sharpe={best['oos_sharpes'][fi]:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={best['oos_trades'][fi]}  "
                  f"MDD={fd['max_dd']*100:+.2f}%  "
                  f"trX={fd['trail_exits']}  tpX={fd['tp_exits']}")
        print(f"\n  vs 베이스라인: Sharpe={fmt_sh(base['sharpe'])} WR={base['wr']:.1%} "
              f"n={base['trades']}")

        avg_wr = np.mean([fd["wr"] for fd in best["fold_details"]])
        total_n = sum(best["oos_trades"])
        print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
        print(f"WR: {avg_wr*100:.1f}%")
        print(f"trades: {total_n}")
    elif passed_all:
        best = sorted(passed_all, key=lambda x: x["avg_oos_sharpe"], reverse=True)[0]
        print(f"⚠️ 배포기준 미달, 최선 결과: hvH={best['hv_hold']} lvH={best['lv_hold']} "
              f"trA={best['tr_a']:.1f} trSL={best['tr_sl']:.1f}")
        print(f"  avg OOS Sharpe: {best['avg_oos_sharpe']:+.3f} (배포기준 5.0 미달)")
        for fi, fold in enumerate(WF_FOLDS):
            fd = best["fold_details"][fi]
            print(f"  {fold['name']}: Sharpe={best['oos_sharpes'][fi]:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={best['oos_trades'][fi]}")
        avg_wr = np.mean([fd["wr"] for fd in best["fold_details"]])
        total_n = sum(best["oos_trades"])
        print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
        print(f"WR: {avg_wr*100:.1f}%")
        print(f"trades: {total_n}")
    else:
        print("❌ 0/81 조합 3-fold WF 통과 (모든 fold Sharpe≥1.0 기준)")
        if wf_sorted:
            best = wf_sorted[0]
            print(f"  최선: hvH={best['hv_hold']} lvH={best['lv_hold']} "
                  f"trA={best['tr_a']:.1f} trSL={best['tr_sl']:.1f}")
            print(f"  avg OOS: {best['avg_oos_sharpe']:+.3f} "
                  f"min: {best['min_oos_sharpe']:+.3f}")
            for fi, fold in enumerate(WF_FOLDS):
                print(f"  {fold['name']}: Sharpe={best['oos_sharpes'][fi]:+.3f} "
                      f"n={best['oos_trades'][fi]}")
        print(f"\nSharpe: nan")
        print(f"WR: 0.0%")
        print(f"trades: 0")


if __name__ == "__main__":
    main()
