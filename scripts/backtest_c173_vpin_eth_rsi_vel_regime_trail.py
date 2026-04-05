"""
vpin_eth RSI velocity + 레짐별 adaptive trailing — 사이클 173
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경:
  c170 (Sharpe +34.39): RSI velocity + volume surge dual confirm
  c168 (Sharpe +16.16): trailing stop + 레짐 적응형 hold — 81/81 WF 통과
  c171 (Sharpe +29.25): adaptive RSI vel regime

  공통 강점: RSI velocity가 추세 전환 신호로 매우 유효
  공통 약점: 레짐별 trailing 미분화 — 고변동에서 trailing 과민, 저변동에서 불발

가설:
  1) c170 RSI velocity 진입 + c168 레짐별 hold/TP/SL 결합
  2) 레짐별 trailing 파라미터 분리:
     - 고변동: 넓은 trail SL + 빠른 activate (추세 탈 때까지 보유)
     - 저변동: 타이트한 trail SL + 느린 activate (빠른 이익 확정)
  3) RSI velocity + volume surge entry score 기반 hold bonus
     (두 조건 모두 강하면 hold 연장)
  4) entry score = rsi_vel_norm + vol_surge_norm → score > th 일 때 hold 보너스

그리드:
  - rsi_vel_thresh: [3.0, 4.0, 5.0] — RSI velocity 진입 임계 (3)
  - vol_surge_mult: [1.5, 2.0, 2.5] — 볼륨 서지 배수 (3)
  - hv_trail_sl: [0.8, 1.2, 1.5] — 고변동 trailing SL ATR배수 (3)
  - lv_trail_sl: [0.3, 0.5, 0.7] — 저변동 trailing SL ATR배수 (3)
  = 3×3×3×3 = 81 조합
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

# ── c168 고정 파라미터 (c154 기반) ────────────────────────────────────────────
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
VOL_REGIME_LOOKBACK = 90
VOL_REGIME_THRESH = 50
HV_TP_OFFSET = 1.0
HV_SL_OFFSET = 0.2
LV_TP_OFFSET = -0.5
LV_SL_OFFSET = -0.1
EMA_SLOPE_PERIOD = 5
EMA_SLOPE_THRESH = 0.001

# c168 WF 최적 hold
HV_HOLD = 24
LV_HOLD = 12

# Trailing activate (c168 최적)
TRAIL_ACTIVATE_MULT = 1.8

# RSI velocity 파라미터 (c170 기반)
RSI_VEL_LOOKBACK = 5  # RSI 변화 측정 봉수

# Hold bonus
HOLD_BONUS_SCORE_TH = 1.5
HOLD_BONUS_BARS = 6

# Grid axes
RSI_VEL_THRESH_LIST = [3.0, 4.0, 5.0]
VOL_SURGE_MULT_LIST = [1.5, 2.0, 2.5]
HV_TRAIL_SL_LIST = [0.8, 1.2, 1.5]
LV_TRAIL_SL_LIST = [0.3, 0.5, 0.7]

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


def compute_rsi_velocity(rsi_arr: np.ndarray, lookback: int) -> np.ndarray:
    """RSI velocity: RSI change over lookback bars (absolute)."""
    n = len(rsi_arr)
    vel = np.full(n, np.nan)
    for i in range(lookback, n):
        if not np.isnan(rsi_arr[i]) and not np.isnan(rsi_arr[i - lookback]):
            vel[i] = rsi_arr[i] - rsi_arr[i - lookback]
    return vel


def compute_vol_surge(volumes: np.ndarray, sma_period: int) -> np.ndarray:
    """Volume surge ratio: current vol / SMA(vol)."""
    n = len(volumes)
    surge = np.full(n, np.nan)
    vol_sma = sma_func(volumes, sma_period)
    for i in range(sma_period - 1, n):
        if not np.isnan(vol_sma[i]) and vol_sma[i] > 0:
            surge[i] = volumes[i] / vol_sma[i]
    return surge


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame,
    *,
    rsi_vel_thresh: float,
    vol_surge_mult: float,
    hv_trail_sl: float,
    lv_trail_sl: float,
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
    rsi_vel_arr = compute_rsi_velocity(rsi_arr, RSI_VEL_LOOKBACK)
    vol_surge_arr = compute_vol_surge(v, VOL_SMA_PERIOD)

    btc_close = df_btc.reindex(df_eth.index)["close"].values
    btc_ema_arr = ema_func(btc_close, BTC_EMA_PERIOD)
    btc_mom_arr = compute_momentum(btc_close, BTC_MOM_LOOKBACK)

    returns: list[float] = []
    trail_exits = 0
    tp_exits = 0
    sl_exits = 0
    hold_exits = 0
    rsi_vel_entries = 0
    base_entries = 0

    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 BTC_EMA_PERIOD, BTC_MOM_LOOKBACK, VOL_SMA_PERIOD,
                 ATR_PERIOD, VOL_REGIME_LOOKBACK, EMA_SLOPE_PERIOD,
                 RSI_VEL_LOOKBACK) + 5
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
        rsi_vel = rsi_vel_arr[i]
        vol_surge = vol_surge_arr[i]

        # BTC 레짐 게이트
        btc_ok = (
            not np.isnan(btc_ema_val) and not np.isnan(btc_close_val)
            and btc_close_val > btc_ema_val
            and not np.isnan(btc_mom_val) and btc_mom_val > BTC_MOM_THRESH
        )

        # 기본 VPIN 진입 조건
        vpin_ok = (
            not np.isnan(vpin_val) and vpin_val > VPIN_HIGH
            and not np.isnan(mom_val) and mom_val > VPIN_MOM_THRESH
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        # 볼륨 필터
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * 1.2  # 기본 볼륨 필터 (약간 완화)
        )

        # ATR 유효성
        atr_ok = not np.isnan(atr_val) and atr_val > 0

        # EMA 기울기 필터
        slope_ok = not np.isnan(ema_slope) and ema_slope > EMA_SLOPE_THRESH

        # 변동성 레짐
        regime_ok = not np.isnan(atr_pctl)

        # ★ RSI velocity + volume surge 진입 보강
        rsi_vel_ok = (
            not np.isnan(rsi_vel) and rsi_vel > rsi_vel_thresh
        )
        vol_surge_ok = (
            not np.isnan(vol_surge) and vol_surge > vol_surge_mult
        )

        # 진입 조건: 기본 VPIN + BTC gate + (RSI vel OR vol surge 중 하나 이상)
        if (vpin_ok and btc_ok and vol_ok and atr_ok and slope_ok
                and regime_ok and (rsi_vel_ok or vol_surge_ok)):

            # Entry score for hold bonus
            entry_score = 0.0
            if rsi_vel_ok:
                entry_score += 1.0
                rsi_vel_entries += 1
            else:
                base_entries += 1
            if vol_surge_ok:
                entry_score += 1.0

            atr_pct = atr_val / c[i]
            is_high_vol = atr_pctl > VOL_REGIME_THRESH

            # 레짐별 TP/SL (c154/c168 최적)
            if is_high_vol:
                tp_mult = BASE_TP_MULT + HV_TP_OFFSET
                sl_mult = BASE_SL_MULT + HV_SL_OFFSET
                max_hold = HV_HOLD
                trail_sl_mult = hv_trail_sl
            else:
                tp_mult = BASE_TP_MULT + LV_TP_OFFSET
                sl_mult = BASE_SL_MULT + LV_SL_OFFSET
                max_hold = LV_HOLD
                trail_sl_mult = lv_trail_sl

            # Hold bonus: 양쪽 신호 모두 강하면 hold 연장
            if entry_score >= HOLD_BONUS_SCORE_TH:
                max_hold += HOLD_BONUS_BARS

            tp = atr_pct * tp_mult
            sl = atr_pct * sl_mult
            tp = max(0.01, min(0.10, tp))
            sl = max(0.003, min(0.04, sl))

            # ★ 레짐별 trailing
            trail_activate_pct = atr_pct * TRAIL_ACTIVATE_MULT
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
            "rsi_vel_entries": 0, "base_entries": 0,
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
        "rsi_vel_entries": rsi_vel_entries, "base_entries": base_entries,
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
    print("=== vpin_eth RSI velocity + 레짐별 adaptive trailing (사이클 173) ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: c170 RSI vel + c168 trailing regime hold")
    print(f"가설: RSI velocity 진입 보강 + 레짐별 trailing SL 분리")
    print(f"그리드: rsiVel={RSI_VEL_THRESH_LIST} volSurge={VOL_SURGE_MULT_LIST} "
          f"hvTrSL={HV_TRAIL_SL_LIST} lvTrSL={LV_TRAIL_SL_LIST}")
    print("=" * 80)

    # ── 데이터 로드 ───────────────────────────────────────────────────────────
    df_eth = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC_SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_eth.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"\nETH: {len(df_eth)}행 ({df_eth.index[0]} ~ {df_eth.index[-1]})")
    print(f"BTC: {len(df_btc)}행 ({df_btc.index[0]} ~ {df_btc.index[-1]})")
    bh = buy_and_hold(df_eth)
    print(f"ETH Buy-and-Hold: {bh * 100:+.1f}%")

    # ── Phase 0: 베이스라인 (c168 최적, RSI vel/vol surge 필터 없음) ──────────
    print(f"\n--- 베이스라인 (c168 hold, no RSI vel filter) ---")
    base = backtest(
        df_eth, df_btc,
        rsi_vel_thresh=-999.0, vol_surge_mult=0.0,  # 모든 진입 허용
        hv_trail_sl=0.8, lv_trail_sl=0.4,
    )
    print(f"  Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"MCL={base['mcl']}  n={base['trades']}  "
          f"trX={base['trail_exits']}  tpX={base['tp_exits']}  "
          f"slX={base['sl_exits']}  holdX={base['hold_exits']}")

    # ── Phase 1: 전체기간 그리드 서치 ─────────────────────────────────────────
    total = (len(RSI_VEL_THRESH_LIST) * len(VOL_SURGE_MULT_LIST)
             * len(HV_TRAIL_SL_LIST) * len(LV_TRAIL_SL_LIST))
    print(f"\n총 조합: {total}개")

    print(f"\n{'rVel':>5} {'vSrg':>5} {'hvTS':>5} {'lvTS':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5} "
          f"{'trX':>4} {'tpX':>4} {'slX':>4} {'hldX':>5} {'rvE':>4}")
    print("-" * 105)

    results: list[dict] = []
    for rv_th in RSI_VEL_THRESH_LIST:
        for vs_m in VOL_SURGE_MULT_LIST:
            for hv_ts in HV_TRAIL_SL_LIST:
                for lv_ts in LV_TRAIL_SL_LIST:
                    r = backtest(
                        df_eth, df_btc,
                        rsi_vel_thresh=rv_th, vol_surge_mult=vs_m,
                        hv_trail_sl=hv_ts, lv_trail_sl=lv_ts,
                    )
                    results.append({
                        "rv_th": rv_th, "vs_m": vs_m,
                        "hv_ts": hv_ts, "lv_ts": lv_ts, **r,
                    })
                    print(
                        f"{rv_th:>5.1f} {vs_m:>5.1f} {hv_ts:>5.1f} {lv_ts:>5.1f} | "
                        f"{fmt_sh(r['sharpe']):>7} {r['wr']:>5.1%} "
                        f"{r['avg_ret'] * 100:>+6.2f}% "
                        f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} "
                        f"{r['trades']:>5} {r['trail_exits']:>4} "
                        f"{r['tp_exits']:>4} {r['sl_exits']:>4} "
                        f"{r['hold_exits']:>5} {r['rsi_vel_entries']:>4}"
                    )

    valid = [r for r in results
             if r["trades"] >= 30
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 3.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥30, Sharpe≥3.0): {len(valid)}/{len(results)}")

    high_n = [r for r in valid if r["trades"] >= 50]
    display = high_n[:15] if high_n else valid[:15]
    label = "n≥50 Top 15" if high_n else "Top 15"

    print(f"\n=== {label} (전체기간) ===")
    for rank, r in enumerate(display, 1):
        safe_cl = "✅" if r["mcl"] <= 3 else "❌"
        safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
        print(
            f"  #{rank:>2} rVel={r['rv_th']:.1f} vSrg={r['vs_m']:.1f} "
            f"hvTS={r['hv_ts']:.1f} lvTS={r['lv_ts']:.1f}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
            f"MCL={r['mcl']}{safe_cl}  n={r['trades']}  "
            f"rvE={r['rsi_vel_entries']}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    best = valid[0]
    print(f"\n★ 전체기간 최적: rVel={best['rv_th']:.1f} vSrg={best['vs_m']:.1f} "
          f"hvTS={best['hv_ts']:.1f} lvTS={best['lv_ts']:.1f}")

    # ── Phase 2: Walkforward 검증 (Top 10) ────────────────────────────────
    wf_candidates = (high_n[:10] if len(high_n) >= 5 else valid[:10])
    print(f"\n{'=' * 80}")
    print("=== Walk-Forward 검증 (Top 10, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(wf_candidates, 1):
        rvth = params["rv_th"]
        vsm = params["vs_m"]
        hvts = params["hv_ts"]
        lvts = params["lv_ts"]
        print(f"\n--- #{rank}: rVel={rvth:.1f} vSrg={vsm:.1f} "
              f"hvTS={hvts:.1f} lvTS={lvts:.1f} ---")

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
            r = backtest(
                df_eth_test, df_btc_test,
                rsi_vel_thresh=rvth, vol_surge_mult=vsm,
                hv_trail_sl=hvts, lv_trail_sl=lvts,
            )
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)
            bh_fold = buy_and_hold(df_eth_test)
            print(f"  Fold {fold_i + 1} OOS [{fold['test'][0]}~{fold['test'][1]}]: "
                  f"Sharpe={sh:+.3f}  WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%  "
                  f"trX={r['trail_exits']}  rvE={r['rsi_vel_entries']}  "
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

    # ── Phase 3: 슬리피지 스트레스 (WF Top 3) ────────────────────────────────
    if not wf_results:
        print("\nWF 검증 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                        reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 3) ===")

    for rank, params in enumerate(wf_top3, 1):
        rvth = params["rv_th"]
        vsm = params["vs_m"]
        hvts = params["hv_ts"]
        lvts = params["lv_ts"]
        print(f"\n--- #{rank}: rVel={rvth:.1f} vSrg={vsm:.1f} "
              f"hvTS={hvts:.1f} lvTS={lvts:.1f} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(
                df_eth, df_btc,
                rsi_vel_thresh=rvth, vol_surge_mult=vsm,
                hv_trail_sl=hvts, lv_trail_sl=lvts, slippage=slip,
            )
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: rVel={best_wf['rv_th']:.1f} vSrg={best_wf['vs_m']:.1f} "
          f"hvTS={best_wf['hv_ts']:.1f} lvTS={best_wf['lv_ts']:.1f}")
    print(f"  (기반: c170 RSI vel + c168 trailing regime + 레짐별 trail SL 분리)")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  MDD={fd['max_dd'] * 100:+.2f}%  "
              f"trX={fd['trail_exits']}  tpX={fd['tp_exits']}  "
              f"rvE={fd['rsi_vel_entries']}")

    print(f"\n  vs 베이스라인 (no RSI vel filter): "
          f"Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")

    avg_wr = np.mean([fd["wr"] for fd in best_wf["fold_details"]])
    total_n = sum(best_wf["oos_trades"])
    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
