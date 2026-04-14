"""
vpin_eth ADX 트렌드 강도 + VPIN 가속도 복합 필터 — 사이클 172
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: 사이클 171 최적 hvRV=7 lvRV=1 slope=0.0010 vRat=2.0
      avg OOS Sharpe=+18.424, WR=58.4%, n=25
      문제:
        1) Fold 2 (2025-07~2026-04 BEAR): Sharpe=+7.598, WR=45.5%, n=11
           → 약세장 진입 품질 저하. 트렌드 없는 구간에 진입
        2) n=25 여전히 부족. Fold 1 n=14, Fold 2 n=11
        3) VPIN > 0.5 조건만으로는 정보 비대칭 '증가 중'인지 판별 불가

가설:
  1) ADX 트렌드 강도 필터:
     ADX > threshold → 명확한 트렌드 존재 시에만 진입
     약세장에서 횡보/무방향 구간 필터 → Fold 2 WR 개선
     그리드: [0 (OFF), 15, 20, 25]
  2) VPIN 가속도 (VPIN rate of change):
     VPIN이 상승 중(VPIN acceleration > 0) = 정보 비대칭 증가 중
     정적 VPIN > 0.5 보다 '흐름' 포착에 유리
     vpin_accel = VPIN[i] - VPIN[i-lookback]
     그리드: accel_lb=[3, 5], accel_th=[0.0 (OFF), 0.02, 0.05]
  3) c171 최적 파라미터 고정 (hvRV=7, lvRV=1, slope=0.001, vRat=2.0)

그리드:
  - adx_th: [0, 15, 20, 25]           — ADX threshold (4) (0=OFF)
  - vpin_accel_lb: [3, 5]             — VPIN accel lookback (2)
  - vpin_accel_th: [0.0, 0.02, 0.05]  — VPIN accel threshold (3) (0=OFF)
  = 4×2×3 = 24 조합

고정 (c171 최적):
  - hvRV=7, lvRV=1, slope=0.001, vRat=2.0
  - rvLB=5, c168 hold/trail, c154 레짐 TP/SL
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

# ── 고정: c171 최적 (c170+c168+c154 계승) ────────────────────────────────────
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

# c168 최적 hold/trail
HV_HOLD = 24
LV_HOLD = 14
TRAIL_ACTIVATE_MULT = 2.0
TRAIL_SL_MULT = 0.5

# c171 최적 적응형 RSI velocity
RSI_VEL_LB = 5
HV_RSI_VEL_TH = 7
LV_RSI_VEL_TH = 1
EMA_SLOPE_TH = 0.001
VOL_RATIO_MIN = 2.0

# c172 그리드 축
ADX_PERIOD = 14
ADX_TH_LIST = [0, 15, 20, 25]
VPIN_ACCEL_LB_LIST = [3, 5]
VPIN_ACCEL_TH_LIST = [0.0, 0.02, 0.05]

WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
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


def adx_func(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int,
) -> np.ndarray:
    """Compute ADX (Average Directional Index)."""
    n = len(closes)
    result = np.full(n, np.nan)
    if n < period * 2 + 1:
        return result

    # True Range
    tr = np.full(n, 0.0)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))

    # +DM, -DM
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    # Smoothed TR, +DM, -DM (Wilder's smoothing)
    smooth_tr = np.full(n, np.nan)
    smooth_plus = np.full(n, np.nan)
    smooth_minus = np.full(n, np.nan)

    smooth_tr[period] = tr[1:period + 1].sum()
    smooth_plus[period] = plus_dm[1:period + 1].sum()
    smooth_minus[period] = minus_dm[1:period + 1].sum()

    for i in range(period + 1, n):
        smooth_tr[i] = smooth_tr[i - 1] - smooth_tr[i - 1] / period + tr[i]
        smooth_plus[i] = smooth_plus[i - 1] - smooth_plus[i - 1] / period + plus_dm[i]
        smooth_minus[i] = (
            smooth_minus[i - 1] - smooth_minus[i - 1] / period + minus_dm[i]
        )

    # +DI, -DI
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    for i in range(period, n):
        if smooth_tr[i] > 0:
            plus_di[i] = 100.0 * smooth_plus[i] / smooth_tr[i]
            minus_di[i] = 100.0 * smooth_minus[i] / smooth_tr[i]

    # DX
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if not np.isnan(plus_di[i]) and not np.isnan(minus_di[i]):
            di_sum = plus_di[i] + minus_di[i]
            if di_sum > 0:
                dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum

    # ADX = smoothed DX
    first_adx_idx = period * 2
    if first_adx_idx >= n:
        return result
    dx_window = []
    for i in range(period, first_adx_idx + 1):
        if not np.isnan(dx[i]):
            dx_window.append(dx[i])
    if len(dx_window) < period:
        return result
    result[first_adx_idx] = np.mean(dx_window[-period:])
    for i in range(first_adx_idx + 1, n):
        if not np.isnan(dx[i]) and not np.isnan(result[i - 1]):
            result[i] = (result[i - 1] * (period - 1) + dx[i]) / period
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
    adx_th: float,
    vpin_accel_lb: int,
    vpin_accel_th: float,
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
    ema_slope_arr = compute_ema_slope(ema_arr, 5)
    adx_arr = adx_func(h, lo, c, ADX_PERIOD)

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
                 ATR_PERIOD, VOL_REGIME_LOOKBACK, RSI_VEL_LB + RSI_PERIOD + 1,
                 ADX_PERIOD * 2 + 1) + 5
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
        adx_val = adx_arr[i]

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

        # 볼륨 서지 필터 (c171 최적 고정)
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * VOL_RATIO_MIN
        )

        # ATR 유효성
        atr_ok = not np.isnan(atr_val) and atr_val > 0

        # 변동성 레짐 판별
        regime_ok = not np.isnan(atr_pctl)
        is_high_vol = regime_ok and atr_pctl > VOL_REGIME_THRESH

        # EMA slope 필터 (c171 최적 고정)
        slope_ok = True
        if EMA_SLOPE_TH > 0:
            slope_ok = not np.isnan(ema_slope) and ema_slope > EMA_SLOPE_TH

        # 적응형 RSI velocity 필터 (c171 최적 고정)
        rsi_vel_ok = True
        prev_idx = i - RSI_VEL_LB
        if (prev_idx >= 0
                and not np.isnan(rsi_arr[i])
                and not np.isnan(rsi_arr[prev_idx])):
            rsi_vel = rsi_arr[i] - rsi_arr[prev_idx]
            vel_thresh = HV_RSI_VEL_TH if is_high_vol else LV_RSI_VEL_TH
            rsi_vel_ok = rsi_vel >= vel_thresh
        else:
            rsi_vel_ok = False

        # ★ NEW: ADX 트렌드 강도 필터 (0 = OFF)
        adx_ok = True
        if adx_th > 0:
            adx_ok = not np.isnan(adx_val) and adx_val >= adx_th

        # ★ NEW: VPIN 가속도 필터 (0.0 = OFF)
        vpin_accel_ok = True
        if vpin_accel_th > 0:
            prev_vpin_idx = i - vpin_accel_lb
            if (prev_vpin_idx >= 0
                    and not np.isnan(vpin_arr[i])
                    and not np.isnan(vpin_arr[prev_vpin_idx])):
                vpin_accel = vpin_arr[i] - vpin_arr[prev_vpin_idx]
                vpin_accel_ok = vpin_accel >= vpin_accel_th
            else:
                vpin_accel_ok = False

        if (vpin_ok and btc_ok and vol_ok and atr_ok
                and slope_ok and rsi_vel_ok and regime_ok
                and adx_ok and vpin_accel_ok):
            atr_pct = atr_val / c[i]

            # 레짐별 TP/SL (c154 최적 유지)
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

            # Trailing stop (c168 최적 고정)
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
    print("=== vpin_eth ADX + VPIN 가속도 필터 (사이클 172) ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: c171 최적 (hvRV=7 lvRV=1 slope=0.001 vRat=2.0)")
    print(f"가설: ADX 트렌드 강도 + VPIN 가속도 → Fold 2 WR 개선 + 진입 품질 향상")
    print(f"그리드: adx_th={ADX_TH_LIST} vpin_accel_lb={VPIN_ACCEL_LB_LIST} "
          f"vpin_accel_th={VPIN_ACCEL_TH_LIST}")
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

    # ── Phase 0: 베이스라인 (c171 최적, 추가 필터 OFF) ─────────────────────────
    print(f"\n--- 베이스라인 (c171 최적, adx=OFF, accel=OFF) ---")
    base = backtest(df_eth, df_btc, adx_th=0, vpin_accel_lb=3, vpin_accel_th=0.0)
    print(f"  Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"MCL={base['mcl']}  n={base['trades']}  "
          f"trailX={base['trail_exits']}  tpX={base['tp_exits']}")

    # ── Phase 1: 전체기간 그리드 서치 ──────────────────────────────────────────
    total = (len(ADX_TH_LIST) * len(VPIN_ACCEL_LB_LIST)
             * len(VPIN_ACCEL_TH_LIST))
    print(f"\n총 조합: {total}개")

    print(f"\n{'adx':>5} {'aLB':>4} {'aTH':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5} "
          f"{'trX':>4} {'tpX':>4}")
    print("-" * 75)

    results: list[dict] = []
    for adx_th in ADX_TH_LIST:
        for accel_lb in VPIN_ACCEL_LB_LIST:
            for accel_th in VPIN_ACCEL_TH_LIST:
                r = backtest(df_eth, df_btc, adx_th, accel_lb, accel_th)
                results.append({
                    "adx_th": adx_th, "accel_lb": accel_lb,
                    "accel_th": accel_th, **r,
                })
                print(
                    f"{adx_th:>5} {accel_lb:>4} {accel_th:>5.2f} | "
                    f"{fmt_sh(r['sharpe']):>7} {r['wr']:>5.1%} "
                    f"{r['avg_ret'] * 100:>+6.2f}% "
                    f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} "
                    f"{r['trades']:>5} {r['trail_exits']:>4} "
                    f"{r['tp_exits']:>4}"
                )

    # n ≥ 15 + Sharpe ≥ 3.0
    valid = [r for r in results
             if r["trades"] >= 15
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 3.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥15, Sharpe≥3.0): {len(valid)}/{len(results)}")

    base_n = base["trades"]
    display = valid[:15]
    print(f"\n=== Top 15 (전체기간) ===")
    for rank, r in enumerate(display, 1):
        n_delta = r["trades"] - base_n
        n_tag = f"Δn={n_delta:+d}" if n_delta != 0 else "=n"
        safe_cl = "✅" if r["mcl"] <= 3 else "❌"
        print(
            f"  #{rank:>2} adx={r['adx_th']} aLB={r['accel_lb']} "
            f"aTH={r['accel_th']:.2f}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%  MCL={r['mcl']}{safe_cl}  "
            f"n={r['trades']}({n_tag})  trX={r['trail_exits']}  tpX={r['tp_exits']}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # ── Phase 2: Walk-Forward 검증 (Top 10) ─────────────────────────────────
    wf_candidates = valid[:10]
    print(f"\n{'=' * 80}")
    print("=== Walk-Forward 검증 (Top 10, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(wf_candidates, 1):
        adx_th = params["adx_th"]
        accel_lb = params["accel_lb"]
        accel_th = params["accel_th"]
        print(f"\n--- #{rank}: adx={adx_th} aLB={accel_lb} "
              f"aTH={accel_th:.2f} ---")

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        oos_wrs: list[float] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_eth_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_test = load_historical(
                BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
            if df_eth_test.empty or df_btc_test.empty:
                print(f"  Fold {fold_i + 1}: 데이터 없음")
                continue
            r = backtest(df_eth_test, df_btc_test, adx_th, accel_lb, accel_th)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            oos_wrs.append(r["wr"])
            fold_details.append(r)
            bh_fold = buy_and_hold(df_eth_test)
            print(f"  Fold {fold_i + 1} OOS [{fold['test'][0]}~{fold['test'][1]}]: "
                  f"Sharpe={sh:+.3f}  WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%  "
                  f"trX={r['trail_exits']}  tpX={r['tp_exits']}  "
                  f"BH={bh_fold * 100:+.1f}%")

        if oos_sharpes:
            avg_oos = np.mean(oos_sharpes)
            min_oos = min(oos_sharpes)
            min_n = min(oos_trades) if oos_trades else 0
            print(f"  평균 OOS Sharpe: {avg_oos:+.3f} | 최소: {min_oos:+.3f} | "
                  f"min_n: {min_n}")

            # WF 통과 기준: 양 Fold Sharpe > 0, min_n ≥ 5
            if min_oos > 0 and min_n >= 5:
                wf_results.append({
                    **params,
                    "avg_oos_sharpe": avg_oos,
                    "min_oos_sharpe": min_oos,
                    "oos_sharpes": oos_sharpes,
                    "oos_trades": oos_trades,
                    "oos_wrs": oos_wrs,
                    "fold_details": fold_details,
                })
                print("  → ✅ WF PASS")
            else:
                reason = []
                if min_oos <= 0:
                    reason.append(f"min_Sharpe={min_oos:+.3f}≤0")
                if min_n < 5:
                    reason.append(f"min_n={min_n}<5")
                print(f"  → ❌ WF FAIL ({', '.join(reason)})")

    # ── Phase 3: 슬리피지 스트레스 (WF Top 3) ──────────────────────────────
    if not wf_results:
        print("\nWF 통과 조합 없음.")
        best = valid[0]
        print(f"\n(참고) 전체기간 최적: adx={best['adx_th']} "
              f"aLB={best['accel_lb']} aTH={best['accel_th']:.2f}")
        print(f"  Sharpe={fmt_sh(best['sharpe'])}  WR={best['wr']:.1%}  "
              f"n={best['trades']}")
        print(f"\nSharpe: {best['sharpe']:+.3f}")
        print(f"WR: {best['wr'] * 100:.1f}%")
        print(f"trades: {best['trades']}")
        return

    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                        reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print(f"=== WF 통과: {len(wf_results)}개 ===")
    for rank, params in enumerate(wf_sorted, 1):
        print(f"  #{rank} adx={params['adx_th']} aLB={params['accel_lb']} "
              f"aTH={params['accel_th']:.2f}  "
              f"avg OOS={params['avg_oos_sharpe']:+.3f}  "
              f"n={sum(params['oos_trades'])}")

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 3) ===")

    for rank, params in enumerate(wf_top3, 1):
        adx_th = params["adx_th"]
        accel_lb = params["accel_lb"]
        accel_th = params["accel_th"]
        print(f"\n--- #{rank}: adx={adx_th} aLB={accel_lb} "
              f"aTH={accel_th:.2f} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_eth, df_btc, adx_th, accel_lb, accel_th,
                         slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: adx={best_wf['adx_th']} aLB={best_wf['accel_lb']} "
          f"aTH={best_wf['accel_th']:.2f}")
    print(f"  (기반: c171 + ADX 트렌드 강도 + VPIN 가속도)")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  MDD={fd['max_dd'] * 100:+.2f}%  "
              f"trX={fd['trail_exits']}  tpX={fd['tp_exits']}")

    print(f"\n  vs c171 최적 (hvRV=7 lvRV=1 slope=0.001 vRat=2.0): "
          f"avg OOS Sharpe=+18.424  WR=58.4%  n=25")
    print(f"  vs 베이스라인 (필터 OFF): "
          f"Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")

    avg_wr = np.mean(best_wf["oos_wrs"])
    total_n = sum(best_wf["oos_trades"])
    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
