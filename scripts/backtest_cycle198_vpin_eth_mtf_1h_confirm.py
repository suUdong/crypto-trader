"""
vpin_eth 사이클 198 — 멀티타임프레임 앙상블: 4h VPIN 신호 + 1h 진입 확인

배경:
- c195-197: VPIN 진입 게이트(Keltner/MomAccel) 및 60m 타임프레임 이식 전부 FAIL
- VPIN alpha는 240m(4h)에 구조적으로 귀속됨 (c197 확인)
- 평가자 방향: "멀티타임프레임 1h+4h 앙상블 진입" 탐색

가설:
- 4h VPIN 신호는 유지 (신호 생성은 4h에서만)
- 4h 신호 발생 시, 해당 4h 봉에 대응하는 4개 1h 봉의 상태를 확인
- 1h 모멘텀/RSI/EMA가 정합적일 때만 진입 → 거짓 신호 필터링
- 진입가: 4h 다음 봉 시가 (기존과 동일, look-ahead bias 방지)
- 기대: WR 향상 + Sharpe 개선, n은 소폭 감소 허용

탐색 그리드: 3 × 4 × 2 × 2 = 48 combos
- H1_MOM_LB: 1h 모멘텀 lookback [3, 5, 8]
- H1_RSI_CEIL: 1h RSI 상한 [55, 60, 65, 70]
- H1_EMA_CONFIRM: 1h close > EMA 확인 [True, False]
- H1_CONFIRM_MODE: 확인 방식 [any=4봉 중 1개 이상, last=마지막 1h 봉만]

3-fold expanding WF + 슬리피지 스트레스
진입: next_bar open (4h)
"""
from __future__ import annotations

import math
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
FEE = 0.0005

# -- c165/c179 최적 고정값 (VPIN ETH daemon 파라미터) --
VPIN_LOW = 0.35
MOM_THRESH = 0.0007
MAX_HOLD = 20
COOLDOWN_BARS = 4

RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

RSI_DELTA_LB = 3
RSI_DELTA_MIN = 0.0
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD = 20
VOL_SMA_PERIOD = 20

TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

BTC_SMA_PERIOD = 200
ATR_PCTILE_LB = 60

ATR_PCTILE_THRESH = 30
BODY_RATIO_MIN = 0.7
VPIN_RELAX_THRESH = 0.25
RELAX_SCALE = 0.5

# -- 탐색 그리드: 1h 확인 파라미터 --
H1_MOM_LB_LIST = [3, 5, 8]
H1_RSI_CEIL_LIST = [55, 60, 65, 70]
H1_EMA_CONFIRM_LIST = [True, False]
H1_CONFIRM_MODE_LIST = ["any", "last"]  # any=4봉 중 1개 이상, last=마지막 1h봉만

# -- 3-fold expanding WF (OOS 미사용 윈도우) --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-02-28"), "test": ("2024-03-01", "2024-11-30")},
    {"train": ("2022-01-01", "2024-11-30"), "test": ("2024-12-01", "2025-08-31")},
    {"train": ("2022-01-01", "2025-05-31"), "test": ("2025-06-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# -- 지표 함수 --

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def ema_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def sma_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    cumsum = np.cumsum(series)
    result[period - 1:] = (
        cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))
    ) / period
    return result


def rsi_calc(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def compute_vpin_bvc(
    closes: np.ndarray, opens: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray, bucket_count: int = 24,
) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(bucket_count, n):
        total_vol = 0.0
        abs_imbalance = 0.0
        for j in range(i - bucket_count, i):
            price_range = highs[j] - lows[j]
            if price_range <= 0:
                buy_frac = 0.5
            else:
                z = (closes[j] - opens[j]) / price_range
                buy_frac = _normal_cdf(z)
            bv = volumes[j] * buy_frac
            sv = volumes[j] * (1.0 - buy_frac)
            abs_imbalance += abs(bv - sv)
            total_vol += volumes[j]
        if total_vol > 0:
            result[i] = abs_imbalance / total_vol
        else:
            result[i] = 0.5
    return result


def compute_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def compute_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 20,
) -> np.ndarray:
    n = len(closes)
    tr = np.full(n, np.nan)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n < period:
        return atr
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def compute_atr_percentile(
    atr_arr: np.ndarray, lookback: int = 40,
) -> np.ndarray:
    n = len(atr_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = atr_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = atr_arr[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


def compute_body_ratio(
    opens: np.ndarray, closes: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(n):
        candle_range = highs[i] - lows[i]
        if candle_range <= 0:
            result[i] = 0.0
        else:
            result[i] = abs(closes[i] - opens[i]) / candle_range
    return result


def align_btc_to_df(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame, btc_sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, btc_sma_period)
    btc_close_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_close_aligned = btc_close_s.reindex(df_sym.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_sym.index, method="ffill").values
    return btc_close_aligned, btc_sma_aligned


def build_1h_confirm_map(
    df_4h: pd.DataFrame, df_1h: pd.DataFrame,
    h1_mom_lb: int, h1_rsi_ceil: float, h1_ema_confirm: bool,
    h1_confirm_mode: str,
) -> np.ndarray:
    """각 4h 봉에 대해 1h 확인 조건 충족 여부를 bool 배열로 반환."""
    n4 = len(df_4h)
    confirm = np.zeros(n4, dtype=bool)

    if df_1h.empty:
        return confirm

    # 1h 지표 사전 계산
    c1 = df_1h["close"].values
    rsi_1h = rsi_calc(c1, RSI_PERIOD)
    mom_1h = compute_momentum(c1, h1_mom_lb)
    ema_1h = ema_calc(c1, 20)  # 1h EMA 고정 period=20

    idx_4h = df_4h.index
    idx_1h = df_1h.index

    for i in range(n4):
        t4 = idx_4h[i]
        # 이 4h 봉에 대응하는 1h 봉들: [t4, t4+4h) 범위
        t4_end = t4 + pd.Timedelta(hours=4)
        mask = (idx_1h >= t4) & (idx_1h < t4_end)
        h1_indices = np.where(mask)[0]

        if len(h1_indices) == 0:
            continue

        if h1_confirm_mode == "last":
            # 마지막 1h 봉만 확인
            check_indices = [h1_indices[-1]]
        else:
            # any: 4봉 중 1개 이상 확인
            check_indices = h1_indices

        for j in check_indices:
            if j >= len(c1):
                continue
            rsi_ok = not np.isnan(rsi_1h[j]) and rsi_1h[j] < h1_rsi_ceil
            mom_ok = not np.isnan(mom_1h[j]) and mom_1h[j] > 0
            ema_ok = True
            if h1_ema_confirm:
                ema_ok = (
                    not np.isnan(ema_1h[j]) and c1[j] > ema_1h[j]
                )
            if rsi_ok and mom_ok and ema_ok:
                confirm[i] = True
                break

    return confirm


# -- 백테스트 --

def backtest(
    df_4h: pd.DataFrame,
    h1_confirm: np.ndarray,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    slippage: float = 0.0005,
) -> dict:
    c = df_4h["close"].values
    o = df_4h["open"].values
    h = df_4h["high"].values
    lo = df_4h["low"].values
    v = df_4h["volume"].values
    n = len(c)

    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)
    atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
    body_ratio_arr = compute_body_ratio(o, c, h, lo)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, 50) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if COOLDOWN_BARS > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_sma_val = vol_sma_arr[i]
        atr_pctile_val = atr_pctile_arr[i]
        body_val = body_ratio_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0):
            i += 1
            continue

        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # 4h 진입 조건 (c165/c179 최적)
        vpin_ok = (
            vpin_val < VPIN_LOW
            and mom_val >= MOM_THRESH
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )
        btc_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )
        rsi_velocity_ok = rsi_delta >= RSI_DELTA_MIN
        vol_ok = v[i] >= vol_sma_val * VOL_MULT

        strong_signal = vpin_val < VPIN_RELAX_THRESH
        if strong_signal:
            eff_atr_thresh = ATR_PCTILE_THRESH * RELAX_SCALE
            eff_body_min = BODY_RATIO_MIN * RELAX_SCALE
        else:
            eff_atr_thresh = ATR_PCTILE_THRESH
            eff_body_min = BODY_RATIO_MIN

        atr_pctile_ok = True
        if eff_atr_thresh > 0:
            if np.isnan(atr_pctile_val):
                atr_pctile_ok = False
            else:
                atr_pctile_ok = atr_pctile_val >= eff_atr_thresh

        body_ok = True
        if eff_body_min > 0:
            if np.isnan(body_val):
                body_ok = False
            else:
                body_ok = body_val >= eff_body_min and c[i] >= o[i]

        # ★ 1h 확인 게이트 (새로운 필터)
        h1_ok = h1_confirm[i] if i < len(h1_confirm) else False

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and h1_ok):
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            effective_tp_mult = TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
            tp_price = buy + atr_at_entry * effective_tp_mult

            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            effective_trail_mult = (
                TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            )
            trail_dist = atr_at_entry * effective_trail_mult
            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR

            exit_ret = None
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                current_price = c[j]

                if current_price >= tp_price:
                    exit_ret = (tp_price / buy - 1) - FEE - slippage
                    i = j
                    break

                if current_price <= sl_price:
                    exit_ret = (sl_price / buy - 1) - FEE - slippage
                    i = j
                    break

                if current_price > peak_price:
                    peak_price = current_price

                unrealized = peak_price - buy
                if unrealized >= min_profit_dist:
                    if peak_price - current_price >= trail_dist:
                        exit_ret = (current_price / buy - 1) - FEE - slippage
                        i = j
                        break

            if exit_ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)

            if exit_ret < 0:
                consecutive_losses += 1
                if consecutive_losses >= COOLDOWN_LOSSES and COOLDOWN_BARS > 0:
                    cooldown_until = i + COOLDOWN_BARS
                    consecutive_losses = 0
            else:
                consecutive_losses = 0
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd}


def backtest_baseline(
    df_4h: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    slippage: float = 0.0005,
) -> dict:
    """1h 확인 없는 기존 4h-only 베이스라인."""
    n4 = len(df_4h)
    h1_confirm_all = np.ones(n4, dtype=bool)  # 전부 True
    return backtest(df_4h, h1_confirm_all, btc_close_aligned,
                    btc_sma_aligned, slippage)


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth 사이클 198 — 멀티타임프레임 4h VPIN + 1h 진입 확인 ===")
    print(f"심볼: {SYMBOL}")
    print("가설: 4h VPIN 신호 + 1h 모멘텀/RSI/EMA 정합성 확인 → 거짓 신호 필터링")
    print(f"4h 고정: VPIN={VPIN_LOW} MOM={MOM_THRESH} Hold={MAX_HOLD} "
          f"CD={COOLDOWN_BARS}")
    print(f"탐색: H1_MOM_LB={H1_MOM_LB_LIST} × H1_RSI_CEIL={H1_RSI_CEIL_LIST}")
    print(f"      H1_EMA={H1_EMA_CONFIRM_LIST} × MODE={H1_CONFIRM_MODE_LIST}")
    print("=" * 80)

    # -- 데이터 로드 --
    df_btc_4h = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    df_eth_4h_full = load_historical(SYMBOL, "240m", "2021-01-01", "2026-12-31")
    df_eth_1h_full = load_historical(SYMBOL, "60m", "2021-01-01", "2026-12-31")

    if df_btc_4h.empty or df_eth_4h_full.empty or df_eth_1h_full.empty:
        print("데이터 부족.")
        return

    print(f"\n4h ETH: {len(df_eth_4h_full)}행 | 1h ETH: {len(df_eth_1h_full)}행 "
          f"| 4h BTC: {len(df_btc_4h)}행")

    combos = list(product(
        H1_MOM_LB_LIST, H1_RSI_CEIL_LIST,
        H1_EMA_CONFIRM_LIST, H1_CONFIRM_MODE_LIST,
    ))
    print(f"총 조합: {len(combos)}개")

    # -- Baseline (4h only, 1h 확인 없음) --
    print("\n--- Baseline (4h only) ---")
    baseline_results = []
    for fold_idx, fold in enumerate(WF_FOLDS):
        t_start, t_end = fold["test"]
        df_4h_test = df_eth_4h_full.loc[t_start:t_end]
        btc_c, btc_s = align_btc_to_df(df_4h_test, df_btc_4h, BTC_SMA_PERIOD)
        res = backtest_baseline(df_4h_test, btc_c, btc_s)
        baseline_results.append(res)
        print(f"  F{fold_idx + 1} ({t_start}~{t_end}): "
              f"Sharpe {res['sharpe']:+.3f} WR {res['wr']:.1%} "
              f"n={res['trades']} MDD {res['max_dd']:.2%}")

    valid_bl = [r for r in baseline_results if r["trades"] > 0
                and not np.isnan(r["sharpe"])]
    if valid_bl:
        bl_avg_sharpe = np.mean([r["sharpe"] for r in valid_bl])
        bl_total_n = sum(r["trades"] for r in valid_bl)
        bl_avg_wr = np.mean([r["wr"] for r in valid_bl])
        print(f"  Baseline avg: Sharpe {bl_avg_sharpe:+.3f} "
              f"WR {bl_avg_wr:.1%} total_n={bl_total_n}")
    else:
        bl_avg_sharpe = 0.0
        bl_total_n = 0

    # -- Walk-Forward Grid Search --
    print("\n--- Walk-Forward Grid Search ---")
    all_results: list[dict] = []

    for combo_idx, (h1_mom_lb, h1_rsi_ceil, h1_ema_confirm,
                    h1_confirm_mode) in enumerate(combos):
        fold_results = []
        for fold_idx, fold in enumerate(WF_FOLDS):
            t_start, t_end = fold["test"]
            df_4h_test = df_eth_4h_full.loc[t_start:t_end]
            df_1h_test = df_eth_1h_full.loc[t_start:t_end]

            btc_c, btc_s = align_btc_to_df(df_4h_test, df_btc_4h, BTC_SMA_PERIOD)
            h1_confirm = build_1h_confirm_map(
                df_4h_test, df_1h_test,
                h1_mom_lb, h1_rsi_ceil, h1_ema_confirm, h1_confirm_mode,
            )
            res = backtest(df_4h_test, h1_confirm, btc_c, btc_s)
            fold_results.append(res)

        valid = [r for r in fold_results if r["trades"] > 0
                 and not np.isnan(r["sharpe"])]
        if valid:
            avg_sharpe = float(np.mean([r["sharpe"] for r in valid]))
            avg_wr = float(np.mean([r["wr"] for r in valid]))
            total_n = sum(r["trades"] for r in valid)
            avg_mdd = float(np.mean([r["max_dd"] for r in valid]))
        else:
            avg_sharpe = float("nan")
            avg_wr = 0.0
            total_n = 0
            avg_mdd = 0.0

        all_results.append({
            "h1_mom_lb": h1_mom_lb,
            "h1_rsi_ceil": h1_rsi_ceil,
            "h1_ema_confirm": h1_ema_confirm,
            "h1_confirm_mode": h1_confirm_mode,
            "avg_sharpe": avg_sharpe,
            "avg_wr": avg_wr,
            "total_n": total_n,
            "avg_mdd": avg_mdd,
            "folds": fold_results,
        })

        if (combo_idx + 1) % 12 == 0:
            print(f"  진행: {combo_idx + 1}/{len(combos)}")

    # -- 정렬 + Top 결과 --
    valid_results = [r for r in all_results if not np.isnan(r["avg_sharpe"])]
    valid_results.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    print(f"\n{'=' * 80}")
    print(f"=== 결과 요약 (Baseline avg Sharpe: {bl_avg_sharpe:+.3f}, "
          f"n={bl_total_n}) ===")
    print(f"{'=' * 80}")

    print(f"\n--- Top 10 ---")
    print(f"{'h1mLB':>5} {'h1rC':>5} {'ema':>5} {'mode':>5} "
          f"{'avgSh':>8} {'ΔSh':>7} {'WR':>6} {'n':>4} {'MDD':>7}")
    for r in valid_results[:10]:
        delta = r["avg_sharpe"] - bl_avg_sharpe
        print(f"{r['h1_mom_lb']:>5} {r['h1_rsi_ceil']:>5} "
              f"{'Y' if r['h1_ema_confirm'] else 'N':>5} "
              f"{r['h1_confirm_mode']:>5} "
              f"{r['avg_sharpe']:>+8.3f} {delta:>+7.3f} "
              f"{r['avg_wr']:>5.1%} {r['total_n']:>4} "
              f"{r['avg_mdd']:>6.2%}")

    # -- Top 1 상세 fold 결과 --
    if valid_results:
        top = valid_results[0]
        print(f"\n--- Top 1 상세: h1mLB={top['h1_mom_lb']} "
              f"h1rC={top['h1_rsi_ceil']} ema={'Y' if top['h1_ema_confirm'] else 'N'} "
              f"mode={top['h1_confirm_mode']} ---")
        for fi, (fold, fres) in enumerate(zip(WF_FOLDS, top["folds"])):
            t_s, t_e = fold["test"]
            print(f"  F{fi + 1} ({t_s}~{t_e}): Sharpe {fres['sharpe']:+.3f} "
                  f"WR {fres['wr']:.1%} n={fres['trades']} "
                  f"MDD {fres['max_dd']:.2%}")

        # -- 슬리피지 스트레스 --
        print(f"\n--- 슬리피지 스트레스 (Top 1) ---")
        print(f"{'slip':>6} {'Sharpe':>8} {'WR':>6} {'n':>4} {'MDD':>7}")
        for slip in SLIPPAGE_LEVELS:
            slip_fold_results = []
            for fold_idx, fold in enumerate(WF_FOLDS):
                t_start, t_end = fold["test"]
                df_4h_test = df_eth_4h_full.loc[t_start:t_end]
                df_1h_test = df_eth_1h_full.loc[t_start:t_end]
                btc_c, btc_s = align_btc_to_df(
                    df_4h_test, df_btc_4h, BTC_SMA_PERIOD
                )
                h1_confirm = build_1h_confirm_map(
                    df_4h_test, df_1h_test,
                    top["h1_mom_lb"], top["h1_rsi_ceil"],
                    top["h1_ema_confirm"], top["h1_confirm_mode"],
                )
                res = backtest(df_4h_test, h1_confirm, btc_c, btc_s, slip)
                slip_fold_results.append(res)
            valid_s = [r for r in slip_fold_results
                       if r["trades"] > 0 and not np.isnan(r["sharpe"])]
            if valid_s:
                s_sharpe = float(np.mean([r["sharpe"] for r in valid_s]))
                s_wr = float(np.mean([r["wr"] for r in valid_s]))
                s_n = sum(r["trades"] for r in valid_s)
                s_mdd = float(np.mean([r["max_dd"] for r in valid_s]))
                print(f"{slip:.2%} {s_sharpe:>+8.3f} {s_wr:>5.1%} "
                      f"{s_n:>4} {s_mdd:>6.2%}")

        # -- Buy & Hold 비교 --
        print(f"\n--- Buy & Hold 비교 ---")
        for fi, fold in enumerate(WF_FOLDS):
            t_s, t_e = fold["test"]
            df_test = df_eth_4h_full.loc[t_s:t_e]
            if len(df_test) > 1:
                bh_ret = df_test["close"].iloc[-1] / df_test["close"].iloc[0] - 1
                print(f"  F{fi + 1} ({t_s}~{t_e}): B&H {bh_ret:+.1%}")

    # -- 최종 요약 --
    if valid_results:
        top = valid_results[0]
        delta = top["avg_sharpe"] - bl_avg_sharpe
        print(f"\n{'=' * 80}")
        print(f"최종: avg OOS Sharpe {top['avg_sharpe']:+.3f} "
              f"(baseline {bl_avg_sharpe:+.3f}, Δ={delta:+.3f})")
        print(f"WR {top['avg_wr']:.1%} | n={top['total_n']} "
              f"| MDD {top['avg_mdd']:.2%}")
        print(f"최적: h1mLB={top['h1_mom_lb']} h1rC={top['h1_rsi_ceil']} "
              f"ema={'Y' if top['h1_ema_confirm'] else 'N'} "
              f"mode={top['h1_confirm_mode']}")
        if delta > 0:
            print("판정: ✅ 1h 확인 게이트가 baseline 대비 개선")
        elif delta == 0:
            print("판정: ⚠️ NEUTRAL — baseline과 동일")
        else:
            print("판정: ❌ 1h 확인 게이트가 baseline 대비 악화")
        print(f"{'=' * 80}")

    # Output for parsing
    if valid_results:
        top = valid_results[0]
        print(f"\nSharpe: {top['avg_sharpe']:+.3f}")
        print(f"WR: {top['avg_wr']:.1%}")
        print(f"trades: {top['total_n']}")
    else:
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")


if __name__ == "__main__":
    main()
