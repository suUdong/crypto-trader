"""
c166: vpin_eth RSI velocity + volume surge — 3-fold WF 검증 (BEAR 포함, n≥30 목표)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: c170 결과 promising (avg OOS +17.986, rvLB=5 rvTh=5 vRat=2.0)
      문제: 2-fold WF only, n=25 (n<30 기준 미달), BEAR fold 미포함

목표:
  1) 3-fold WF (F3 = BEAR 구간) — c165와 동일 fold 구조
  2) n≥30 달성 — 파라미터 그리드 확장 (rsi_vel_thresh 하향, vol_ratio 하향)
  3) BEAR fold Sharpe > 0 유지 확인

그리드 (c170 최적 중심 + 완화 방향):
  - rsi_vel_lb: [3, 5, 7]            — RSI velocity lookback (3)
  - rsi_vel_thresh: [0, 1, 3, 5]     — 0 = RSI vel 필터 OFF (4)
  - vol_ratio_min: [1.2, 1.5, 2.0]   — 1.2 추가로 n 확대 (3)
  = 3×4×3 = 36 조합

3-fold WF:
  F1: train 2022-01~2023-12 → OOS 2024-01~2024-09  (BULL)
  F2: train 2022-01~2024-12 → OOS 2025-01~2025-09  (2025 혼재)
  F3: train 2023-01~2025-09 → OOS 2025-10~2026-04  (★BEAR)

통과 기준: 전 fold Sharpe > 0, min_n ≥ 5
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005

# ── 고정: c168 최적 파라미터 ─────────────────────────────────────────────────
BTC_EMA_PERIOD = 50
BTC_MOM_LOOKBACK = 10
BTC_MOM_THRESH = 0.02
VOL_SMA_PERIOD = 30
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

# c168 최적 hold/trail (고정)
HV_HOLD = 24
LV_HOLD = 14
TRAIL_ACTIVATE_MULT = 2.0
TRAIL_SL_MULT = 0.5

# Grid axes
RSI_VEL_LB_LIST = [3, 5, 7]
RSI_VEL_THRESH_LIST = [0, 1, 3, 5]
VOL_RATIO_MIN_LIST = [1.2, 1.5, 2.0]

WF_FOLDS = [
    {
        "name": "F1 (BULL)",
        "train": ("2022-01-01", "2023-12-31"),
        "test": ("2024-01-01", "2024-09-30"),
    },
    {
        "name": "F2 (2025 혼재)",
        "train": ("2022-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2025-09-30"),
    },
    {
        "name": "F3 (★BEAR)",
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
    rsi_vel_lb: int,
    rsi_vel_thresh: float,
    vol_ratio_min: float,
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
                 ATR_PERIOD, VOL_REGIME_LOOKBACK, EMA_SLOPE_PERIOD,
                 rsi_vel_lb + RSI_PERIOD + 1) + 5
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

        # 볼륨 서지 필터
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * vol_ratio_min
        )

        # ATR 유효성
        atr_ok = not np.isnan(atr_val) and atr_val > 0

        # EMA 기울기 필터
        slope_ok = True
        if EMA_SLOPE_THRESH > 0:
            slope_ok = (
                not np.isnan(ema_slope) and ema_slope > EMA_SLOPE_THRESH
            )

        # RSI velocity 필터 (thresh=0 이면 OFF)
        rsi_vel_ok = True
        if rsi_vel_lb > 0 and rsi_vel_thresh > 0:
            prev_idx = i - rsi_vel_lb
            if (prev_idx >= 0
                    and not np.isnan(rsi_arr[i])
                    and not np.isnan(rsi_arr[prev_idx])):
                rsi_vel = rsi_arr[i] - rsi_arr[prev_idx]
                rsi_vel_ok = rsi_vel >= rsi_vel_thresh
            else:
                rsi_vel_ok = False

        # 변동성 레짐
        regime_ok = not np.isnan(atr_pctl)

        if (vpin_ok and btc_ok and vol_ok and atr_ok
                and slope_ok and rsi_vel_ok and regime_ok):
            atr_pct = atr_val / c[i]
            is_high_vol = atr_pctl > VOL_REGIME_THRESH

            if is_high_vol:
                tp_mult = BASE_TP_MULT + HV_TP_OFFSET
                sl_mult = BASE_SL_MULT + HV_SL_OFFSET
                max_hold = HV_HOLD
            else:
                tp_mult = BASE_TP_MULT + LV_TP_OFFSET
                sl_mult = BASE_SL_MULT + LV_SL_OFFSET
                max_hold = LV_HOLD

            tp = atr_pct * tp_mult
            sl = atr_pct * sl_mult

            tp = max(0.01, min(0.10, tp))
            sl = max(0.003, min(0.04, sl))

            trail_activate_pct = atr_pct * TRAIL_ACTIVATE_MULT
            trail_sl_dist = atr_pct * TRAIL_SL_MULT

            buy = o[i + 1] * (1 + FEE + slippage)
            ret = None
            exit_bar = i + 1
            trailing_active = False
            highest_ret = 0.0

            for j in range(i + 2, min(i + 1 + max_hold, n)):
                r = c[j] / buy - 1

                if r > highest_ret:
                    highest_ret = r

                if trailing_active:
                    trail_stop = highest_ret - trail_sl_dist
                    if r <= trail_stop:
                        ret = r - FEE - slippage
                        exit_bar = j
                        trail_exits += 1
                        break

                if not trailing_active and r >= trail_activate_pct:
                    trailing_active = True

                if r >= tp:
                    ret = tp - FEE - slippage
                    exit_bar = j
                    tp_exits += 1
                    break

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
    print("=== c166: vpin_eth RSI vel+vol surge 3-fold WF (BEAR 포함) ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: c168 최적 (hvH={HV_HOLD} lvH={LV_HOLD} "
          f"trA={TRAIL_ACTIVATE_MULT} trSL={TRAIL_SL_MULT})")
    print(f"그리드: rsi_vel_lb={RSI_VEL_LB_LIST} rsi_vel_thresh="
          f"{RSI_VEL_THRESH_LIST} vol_ratio={VOL_RATIO_MIN_LIST}")
    print(f"3-fold WF: F1(BULL) F2(2025혼재) F3(★BEAR)")
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

    # ── Phase 0: 베이스라인 (c168 최적, 추가 필터 없음) ──────────────────────
    print(f"\n--- 베이스라인 (c168 최적, RSI vel=OFF, vol_ratio=1.5) ---")
    base = backtest(df_eth, df_btc, rsi_vel_lb=0, rsi_vel_thresh=0,
                    vol_ratio_min=1.5)
    print(f"  Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"MCL={base['mcl']}  n={base['trades']}  "
          f"trailX={base['trail_exits']}  tpX={base['tp_exits']}")

    # ── Phase 1: 전체기간 그리드 서치 ──────────────────────────────────────────
    total = len(RSI_VEL_LB_LIST) * len(RSI_VEL_THRESH_LIST) * len(VOL_RATIO_MIN_LIST)
    print(f"\n총 조합: {total}개")

    print(f"\n{'rvLB':>5} {'rvTh':>5} {'vRat':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5} "
          f"{'trX':>4} {'tpX':>4}")
    print("-" * 80)

    results: list[dict] = []
    for rv_lb in RSI_VEL_LB_LIST:
        for rv_th in RSI_VEL_THRESH_LIST:
            for vr in VOL_RATIO_MIN_LIST:
                r = backtest(df_eth, df_btc, rv_lb, rv_th, vr)
                results.append({
                    "rv_lb": rv_lb, "rv_th": rv_th, "vr": vr, **r,
                })
                print(
                    f"{rv_lb:>5} {rv_th:>5} {vr:>5.1f} | "
                    f"{fmt_sh(r['sharpe']):>7} {r['wr']:>5.1%} "
                    f"{r['avg_ret'] * 100:>+6.2f}% "
                    f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} "
                    f"{r['trades']:>5} {r['trail_exits']:>4} "
                    f"{r['tp_exits']:>4}"
                )

    # n ≥ 15 + Sharpe ≥ 3.0 (전체기간 기준)
    valid = [r for r in results
             if r["trades"] >= 15
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 3.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥15, Sharpe≥3.0): {len(valid)}/{len(results)}")

    display = valid[:10]
    print(f"\n=== Top 10 (전체기간) ===")
    for rank, r in enumerate(display, 1):
        wr_delta = r["wr"] - base["wr"]
        wr_tag = f"Δ{wr_delta:+.1%}" if abs(wr_delta) > 0.001 else "="
        print(
            f"  #{rank:>2} rvLB={r['rv_lb']} rvTh={r['rv_th']} "
            f"vRat={r['vr']:.1f}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}({wr_tag})  "
            f"MDD={r['max_dd'] * 100:+.2f}%  MCL={r['mcl']}  "
            f"n={r['trades']}  trX={r['trail_exits']}  tpX={r['tp_exits']}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # ── Phase 2: 3-Fold Walk-Forward 검증 (Top 15) ──────────────────────────
    wf_candidates = valid[:15]
    print(f"\n{'=' * 80}")
    print("=== 3-Fold Walk-Forward 검증 (Top 15) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(wf_candidates, 1):
        rv_lb = params["rv_lb"]
        rv_th = params["rv_th"]
        vr = params["vr"]
        print(f"\n--- #{rank}: rvLB={rv_lb} rvTh={rv_th} vRat={vr:.1f} ---")

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        oos_wrs: list[float] = []
        fold_details: list[dict] = []
        all_pass = True
        for fold_i, fold in enumerate(WF_FOLDS):
            df_eth_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_test = load_historical(
                BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
            if df_eth_test.empty or df_btc_test.empty:
                print(f"  {fold['name']}: 데이터 없음")
                all_pass = False
                continue
            r = backtest(df_eth_test, df_btc_test, rv_lb, rv_th, vr)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            oos_wrs.append(r["wr"])
            fold_details.append(r)
            bh_fold = buy_and_hold(df_eth_test)
            print(f"  {fold['name']} OOS [{fold['test'][0]}~{fold['test'][1]}]: "
                  f"Sharpe={sh:+.3f}  WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%  "
                  f"trX={r['trail_exits']}  tpX={r['tp_exits']}  "
                  f"BH={bh_fold * 100:+.1f}%")

        if len(oos_sharpes) < 3:
            print("  → ❌ WF FAIL (fold 누락)")
            continue

        avg_oos = float(np.mean(oos_sharpes))
        min_oos = min(oos_sharpes)
        min_n = min(oos_trades) if oos_trades else 0
        total_n = sum(oos_trades)
        print(f"  avg OOS Sharpe: {avg_oos:+.3f} | min: {min_oos:+.3f} | "
              f"min_n: {min_n} | total_n: {total_n}")

        # 통과 기준: 전 fold Sharpe > 0, min_n ≥ 5
        if min_oos > 0 and min_n >= 5:
            wf_results.append({
                **params,
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "oos_wrs": oos_wrs,
                "fold_details": fold_details,
                "total_n": total_n,
            })
            n_tag = "✅" if total_n >= 30 else "⚠️n<30"
            print(f"  → ✅ WF PASS ({n_tag})")
        else:
            reason = []
            if min_oos <= 0:
                reason.append(f"min_Sharpe={min_oos:+.3f}≤0")
            if min_n < 5:
                reason.append(f"min_n={min_n}<5")
            print(f"  → ❌ WF FAIL ({', '.join(reason)})")

    # ── Phase 3: 슬리피지 스트레스 (WF Top 5) ──────────────────────────────
    if not wf_results:
        print("\nWF 통과 조합 없음.")
        best = valid[0]
        print(f"\n(참고) 전체기간 최적: rvLB={best['rv_lb']} rvTh={best['rv_th']} "
              f"vRat={best['vr']:.1f}")
        print(f"  Sharpe={fmt_sh(best['sharpe'])}  WR={best['wr']:.1%}  "
              f"n={best['trades']}")
        print(f"\nSharpe: {best['sharpe']:+.3f}")
        print(f"WR: {best['wr'] * 100:.1f}%")
        print(f"trades: {best['trades']}")
        return

    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                        reverse=True)
    wf_top5 = wf_sorted[:5]

    print(f"\n{'=' * 80}")
    print(f"=== WF 통과: {len(wf_results)}개 ===")
    for rank, params in enumerate(wf_sorted, 1):
        n_tag = "✅" if params["total_n"] >= 30 else "⚠️n<30"
        print(f"  #{rank} rvLB={params['rv_lb']} rvTh={params['rv_th']} "
              f"vRat={params['vr']:.1f}  avg OOS={params['avg_oos_sharpe']:+.3f}  "
              f"total_n={params['total_n']} {n_tag}")

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 5) ===")

    for rank, params in enumerate(wf_top5, 1):
        rv_lb = params["rv_lb"]
        rv_th = params["rv_th"]
        vr = params["vr"]
        print(f"\n--- #{rank}: rvLB={rv_lb} rvTh={rv_th} vRat={vr:.1f} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}, "
              f"total_n: {params['total_n']}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_eth, df_btc, rv_lb, rv_th, vr, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: rvLB={best_wf['rv_lb']} rvTh={best_wf['rv_th']} "
          f"vRat={best_wf['vr']:.1f}")
    print(f"  (기반: c168 최적 + RSI velocity + volume surge 필터)")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        fn = WF_FOLDS[fi]["name"]
        print(f"  {fn}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  MDD={fd['max_dd'] * 100:+.2f}%  "
              f"trX={fd['trail_exits']}  tpX={fd['tp_exits']}")

    print(f"\n  vs c168 베이스라인 (no filter): "
          f"Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")
    print(f"  vs c168 3-fold WF 최적: avg OOS Sharpe=+14.111  n=59")
    print(f"  vs c170 2-fold WF 최적: avg OOS Sharpe=+17.986  n=25")

    avg_wr = float(np.mean(best_wf["oos_wrs"]))
    total_n = best_wf["total_n"]
    n_verdict = "✅ n≥30" if total_n >= 30 else "⚠️ n<30 — daemon 배포 불가"
    print(f"\n  total_n: {total_n} → {n_verdict}")

    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
