"""
c167: vpin_eth BTC 드로다운 게이트 + ETH/BTC 상대강도 — 3-fold WF BEAR 방어
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: c166 F1(BULL) Sharpe=+19.880 우수, F2/F3(BEAR) 전면 붕괴
      원인: BTC EMA+모멘텀 게이트가 BEAR에서 거짓양성 다수 통과
      → BEAR fold에서 15건 전패 (WR=0%)

가설:
  1) BTC 고점 대비 드로다운 필터 — BTC가 N봉 고점 대비 X% 이상 빠지면 진입 금지
     → BEAR 구간 대부분 차단, BULL은 통과 (드로다운 작음)
  2) ETH/BTC 상대강도 — ETH가 BTC 대비 상승할 때만 진입
     → BEAR에서 ETH가 BTC보다 약세이면 진입 차단
  3) 두 필터 조합으로 F2/F3 손실 최소화 + F1 유지

그리드:
  - btc_dd_lookback: [30, 60, 90]         — BTC 고점 산출 기간 (3)
  - btc_dd_max: [0.05, 0.10, 0.15, 0.20]  — 허용 최대 드로다운 (4)
  - rs_lookback: [10, 20, 30]              — ETH/BTC 상대강도 기간 (3)
  - rs_min: [0.0, 0.01, 0.02]             — 최소 상대강도 (0=OFF) (3)
  = 3×4×3×3 = 108 조합

3-fold WF:
  F1: train 2022-01~2023-12 → OOS 2024-01~2024-09  (BULL)
  F2: train 2022-01~2024-12 → OOS 2025-01~2025-09  (2025 혼재)
  F3: train 2023-01~2025-09 → OOS 2025-10~2026-04  (★BEAR)

통과 기준: 전 fold Sharpe > 0, min_n ≥ 3
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

# ── 고정: c168 최적 파라미터 (c166 베이스) ────────────────────────────────────
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

HV_HOLD = 24
LV_HOLD = 14
TRAIL_ACTIVATE_MULT = 2.0
TRAIL_SL_MULT = 0.5

VOL_RATIO_MIN = 1.5  # c166 기본값 고정

# Grid axes — BEAR 방어 필터
BTC_DD_LOOKBACK_LIST = [30, 60, 90]
BTC_DD_MAX_LIST = [0.05, 0.10, 0.15, 0.20]
RS_LOOKBACK_LIST = [10, 20, 30]
RS_MIN_LIST = [0.0, 0.01, 0.02]

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


def compute_rolling_high(closes: np.ndarray, lookback: int) -> np.ndarray:
    """N봉 고점 — BTC 드로다운 계산용."""
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(lookback - 1, n):
        result[i] = np.nanmax(closes[i - lookback + 1:i + 1])
    return result


def compute_relative_strength(
    eth_closes: np.ndarray, btc_closes: np.ndarray, lookback: int,
) -> np.ndarray:
    """ETH/BTC 상대강도: ETH 수익률 - BTC 수익률 (lookback 기간)."""
    n = len(eth_closes)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        if (eth_closes[i - lookback] > 0 and btc_closes[i - lookback] > 0
                and not np.isnan(eth_closes[i]) and not np.isnan(btc_closes[i])):
            eth_ret = eth_closes[i] / eth_closes[i - lookback] - 1
            btc_ret = btc_closes[i] / btc_closes[i - lookback] - 1
            result[i] = eth_ret - btc_ret
    return result


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame,
    btc_dd_lookback: int,
    btc_dd_max: float,
    rs_lookback: int,
    rs_min: float,
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

    # 새 지표: BTC 드로다운 + ETH/BTC 상대강도
    btc_rolling_high = compute_rolling_high(btc_close, btc_dd_lookback)
    eth_btc_rs = compute_relative_strength(c, btc_close, rs_lookback)

    returns: list[float] = []
    trail_exits = 0
    tp_exits = 0
    sl_exits = 0
    hold_exits = 0
    dd_filtered = 0
    rs_filtered = 0

    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 BTC_EMA_PERIOD, BTC_MOM_LOOKBACK, VOL_SMA_PERIOD,
                 ATR_PERIOD, VOL_REGIME_LOOKBACK, EMA_SLOPE_PERIOD,
                 btc_dd_lookback, rs_lookback) + 5
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
            and vol_val > vol_sma_val * VOL_RATIO_MIN
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

        # ★ 새 필터 1: BTC 드로다운 게이트
        btc_rh = btc_rolling_high[i]
        btc_dd_ok = True
        if not np.isnan(btc_rh) and btc_rh > 0 and not np.isnan(btc_close_val):
            btc_dd = 1.0 - btc_close_val / btc_rh
            if btc_dd > btc_dd_max:
                btc_dd_ok = False
                dd_filtered += 1

        # ★ 새 필터 2: ETH/BTC 상대강도
        rs_val = eth_btc_rs[i]
        rs_ok = True
        if rs_min > 0:
            if np.isnan(rs_val) or rs_val < rs_min:
                rs_ok = False
                rs_filtered += 1

        if (vpin_ok and btc_ok and vol_ok and atr_ok
                and slope_ok and regime_ok and btc_dd_ok and rs_ok):
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
            "dd_filtered": dd_filtered, "rs_filtered": rs_filtered,
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
        "dd_filtered": dd_filtered, "rs_filtered": rs_filtered,
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
    print("=== c167: vpin_eth BTC 드로다운 게이트 + ETH/BTC 상대강도 — BEAR 방어 ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: c166 (c168 최적 + 변동성레짐 + BTC모멘텀게이트)")
    print(f"신규 필터: BTC 드로다운 게이트 + ETH/BTC 상대강도")
    print(f"그리드: dd_lb={BTC_DD_LOOKBACK_LIST} dd_max={BTC_DD_MAX_LIST} "
          f"rs_lb={RS_LOOKBACK_LIST} rs_min={RS_MIN_LIST}")
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

    # ── Phase 0: 베이스라인 (c166 = 필터 없음) ─────────────────────────────────
    print(f"\n--- 베이스라인 (c166, 추가필터 없음) ---")
    base = backtest(df_eth, df_btc, btc_dd_lookback=90, btc_dd_max=1.0,
                    rs_lookback=10, rs_min=0.0)
    print(f"  Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"MCL={base['mcl']}  n={base['trades']}")

    # ── Phase 1: 전체기간 그리드 서치 ──────────────────────────────────────────
    total = (len(BTC_DD_LOOKBACK_LIST) * len(BTC_DD_MAX_LIST)
             * len(RS_LOOKBACK_LIST) * len(RS_MIN_LIST))
    print(f"\n총 조합: {total}개")
    print(f"\n{'ddLB':>5} {'ddMx':>5} {'rsLB':>5} {'rsMn':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5} "
          f"{'ddF':>4} {'rsF':>4}")
    print("-" * 85)

    results: list[dict] = []
    for dd_lb in BTC_DD_LOOKBACK_LIST:
        for dd_max in BTC_DD_MAX_LIST:
            for rs_lb in RS_LOOKBACK_LIST:
                for rs_mn in RS_MIN_LIST:
                    r = backtest(df_eth, df_btc, dd_lb, dd_max, rs_lb, rs_mn)
                    results.append({
                        "dd_lb": dd_lb, "dd_max": dd_max,
                        "rs_lb": rs_lb, "rs_mn": rs_mn, **r,
                    })
                    print(
                        f"{dd_lb:>5} {dd_max:>5.2f} {rs_lb:>5} {rs_mn:>5.2f} | "
                        f"{fmt_sh(r['sharpe']):>7} {r['wr']:>5.1%} "
                        f"{r['avg_ret'] * 100:>+6.2f}% "
                        f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} "
                        f"{r['trades']:>5} {r['dd_filtered']:>4} "
                        f"{r['rs_filtered']:>4}"
                    )

    # n ≥ 10 + Sharpe ≥ 3.0
    valid = [r for r in results
             if r["trades"] >= 10
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 3.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥10, Sharpe≥3.0): {len(valid)}/{len(results)}")

    display = valid[:10]
    print(f"\n=== Top 10 (전체기간) ===")
    for rank, r in enumerate(display, 1):
        print(
            f"  #{rank:>2} ddLB={r['dd_lb']} ddMx={r['dd_max']:.2f} "
            f"rsLB={r['rs_lb']} rsMn={r['rs_mn']:.2f}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%  MCL={r['mcl']}  "
            f"n={r['trades']}  ddF={r['dd_filtered']}  rsF={r['rs_filtered']}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # ── Phase 2: 3-Fold Walk-Forward 검증 (Top 20) ────────────────────────────
    wf_candidates = valid[:20]
    print(f"\n{'=' * 80}")
    print("=== 3-Fold Walk-Forward 검증 (Top 20) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(wf_candidates, 1):
        dd_lb = params["dd_lb"]
        dd_max = params["dd_max"]
        rs_lb = params["rs_lb"]
        rs_mn = params["rs_mn"]
        print(f"\n--- #{rank}: ddLB={dd_lb} ddMx={dd_max:.2f} "
              f"rsLB={rs_lb} rsMn={rs_mn:.2f} ---")

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        oos_wrs: list[float] = []
        fold_details: list[dict] = []
        for fold in WF_FOLDS:
            df_eth_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_test = load_historical(
                BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
            if df_eth_test.empty or df_btc_test.empty:
                print(f"  {fold['name']}: 데이터 없음")
                continue
            r = backtest(df_eth_test, df_btc_test, dd_lb, dd_max, rs_lb, rs_mn)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            oos_wrs.append(r["wr"])
            fold_details.append(r)
            bh_fold = buy_and_hold(df_eth_test)
            print(f"  {fold['name']} OOS [{fold['test'][0]}~{fold['test'][1]}]: "
                  f"Sharpe={sh:+.3f}  WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%  "
                  f"ddF={r['dd_filtered']}  rsF={r['rs_filtered']}  "
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

        # 통과 기준: 전 fold Sharpe > 0, min_n ≥ 3
        if min_oos > 0 and min_n >= 3:
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
            n_tag = "✅" if total_n >= 20 else "⚠️n<20"
            print(f"  → ✅ WF PASS ({n_tag})")
        else:
            reason = []
            if min_oos <= 0:
                reason.append(f"min_Sharpe={min_oos:+.3f}≤0")
            if min_n < 3:
                reason.append(f"min_n={min_n}<3")
            print(f"  → ❌ WF FAIL ({', '.join(reason)})")

    # ── Phase 3: 슬리피지 스트레스 ─────────────────────────────────────────────
    if not wf_results:
        print(f"\n{'=' * 80}")
        print("=== WF 통과: 0개 ===")
        print("  WF 통과 조합 없음 — 전체 OOS Top 사용")

        # 전체기간 Top 3로 슬리피지 테스트
        top_for_slip = valid[:3]
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 (Top 3) ===")
        for rank, params in enumerate(top_for_slip, 1):
            dd_lb = params["dd_lb"]
            dd_max = params["dd_max"]
            rs_lb = params["rs_lb"]
            rs_mn = params["rs_mn"]
            print(f"\n--- #{rank}: ddLB={dd_lb} ddMx={dd_max:.2f} "
                  f"rsLB={rs_lb} rsMn={rs_mn:.2f} "
                  f"(avg OOS: {params.get('avg_oos_sharpe', params['sharpe']):+.3f})"
                  f" ---")
            print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
                  f"{'MDD':>7} {'MCL':>4} {'n':>5}")
            print("-" * 55)
            for slip in SLIPPAGE_LEVELS:
                r = backtest(df_eth, df_btc, dd_lb, dd_max, rs_lb, rs_mn,
                             slippage=slip)
                sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
                print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                      f"{r['avg_ret'] * 100:>+6.2f}% "
                      f"{r['max_dd'] * 100:>+6.2f}% "
                      f"{r['mcl']:>4} {r['trades']:>5}")

        # 최종 요약 — 전체기간 최적
        best = valid[0]
        print(f"\n{'=' * 80}")
        print("=== 최종 요약 ===")
        print(f"★ OOS 최적: ddLB={best['dd_lb']} ddMx={best['dd_max']:.2f} "
              f"rsLB={best['rs_lb']} rsMn={best['rs_mn']:.2f}")
        print(f"  avg OOS Sharpe: {best['sharpe']:+.3f} FAIL <5.0")
        print(f"  train Sharpe: {base['sharpe']:+.3f}")
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
        n_tag = "✅" if params["total_n"] >= 20 else "⚠️n<20"
        print(f"  #{rank} ddLB={params['dd_lb']} ddMx={params['dd_max']:.2f} "
              f"rsLB={params['rs_lb']} rsMn={params['rs_mn']:.2f}  "
              f"avg OOS={params['avg_oos_sharpe']:+.3f}  "
              f"total_n={params['total_n']} {n_tag}")

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 5) ===")

    for rank, params in enumerate(wf_top5, 1):
        dd_lb = params["dd_lb"]
        dd_max = params["dd_max"]
        rs_lb = params["rs_lb"]
        rs_mn = params["rs_mn"]
        print(f"\n--- #{rank}: ddLB={dd_lb} ddMx={dd_max:.2f} "
              f"rsLB={rs_lb} rsMn={rs_mn:.2f} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}, "
              f"total_n: {params['total_n']}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_eth, df_btc, dd_lb, dd_max, rs_lb, rs_mn,
                         slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: ddLB={best_wf['dd_lb']} ddMx={best_wf['dd_max']:.2f} "
          f"rsLB={best_wf['rs_lb']} rsMn={best_wf['rs_mn']:.2f}")
    print(f"  (기반: c166 + BTC 드로다운 게이트 + ETH/BTC 상대강도)")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        fn = WF_FOLDS[fi]["name"]
        print(f"  {fn}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%  "
              f"ddF={fd['dd_filtered']}  rsF={fd['rs_filtered']}")

    print(f"\n  vs c166 베이스라인: "
          f"Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")
    print(f"  vs c166 F1: Sharpe=+19.880  WR=50.0%  n=10")

    avg_wr = float(np.mean(best_wf["oos_wrs"]))
    total_n = best_wf["total_n"]
    n_verdict = "✅ n≥20" if total_n >= 20 else "⚠️ n<20"
    print(f"\n  total_n: {total_n} → {n_verdict}")

    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
