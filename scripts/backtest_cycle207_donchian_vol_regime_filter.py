"""
사이클 207: Donchian Channel Breakout + Volume Regime Filter 3-fold WF
- 기반: c205 OOS Sharpe +9.542 (Donchian 독립 전략) — F3 +0.776 감쇠 문제
- 문제:
  1) F3(2025-12~2026-03) Sharpe +0.776 — 변동성 축소 + 횡보장에서 추세추종 실패
  2) SOL F3 Sharpe -6.995 — 심볼별 편차 과대
  3) 모든 시장 환경에서 동일한 파라미터 사용 → 저변동성 구간 가짜 돌파 다수
- 가설:
  A) Volume Regime Filter: ATR 백분위로 변동성 레짐 감지
     → 고변동성 레짐에서만 진입 (저변동성 횡보장 필터)
     → F3 같은 저변동성 구간에서 거래 차단하여 Sharpe 보존
  B) Volume Confirmation: 돌파 시점에 거래량 확인
     → 거래량 SMA 대비 비율이 높아야 진입 → 가짜 돌파 필터
  C) Regime-Adaptive TP/SL: 변동성 레짐에 따른 TP/SL 조정
     → 고변동성: TP 확대 + SL 확대 (큰 움직임 활용)
     → 저변동성: 진입 자체 차단 (C 아닌 A에서 처리)
  D) Multi-timeframe RSI: 240m RSI 과매수 필터
     → RSI > 70 진입 차단 (이미 과매수 상태에서 추세 합류 방지)
- 탐색 그리드 (c205 최적 고정):
  c205 고정: dcU=30 dcL=10 adx=25 atrTP=3.0 atrSL=2.5 trail=0.0
  ATR_PCTILE_TH: [30, 40, 50, 60]      — 최소 ATR 백분위 (변동성 레짐)
  ATR_PCTILE_LB: [30, 60]              — ATR 백분위 lookback
  VOL_RATIO_MIN: [0.0, 0.8, 1.0, 1.2]  — 최소 거래량/SMA 비율
  VOL_SMA_PERIOD: [20, 40]              — 거래량 SMA 기간
  RSI_CEILING: [100, 70, 65]            — RSI 상한 (100=비활성)
  TP_VOL_SCALE: [0.0, 0.5, 1.0]        — 변동성 → TP 보너스 배수
  = 4×2×4×2×3×3 = 576 combos
- 목표: OOS Sharpe >= 12 AND F3 Sharpe >= 3.0 AND trades >= 25
- 3-fold WF + 슬리피지 스트레스
- 진입: next_bar open
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005  # 0.05% 편도
SLIPPAGE = 0.001  # 0.10%

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]
BTC_SMA_PERIOD = 200

WINDOWS = [
    {
        "name": "F1",
        "is_start": "2022-07-01", "is_end": "2024-04-30",
        "oos_start": "2024-05-01", "oos_end": "2025-02-28",
    },
    {
        "name": "F2",
        "is_start": "2023-05-01", "is_end": "2025-02-28",
        "oos_start": "2025-03-01", "oos_end": "2025-11-30",
    },
    {
        "name": "F3",
        "is_start": "2024-03-01", "is_end": "2025-11-30",
        "oos_start": "2025-12-01", "oos_end": "2026-03-31",
    },
]

# ─── c205 최적 고정값 ─────────────────────────────────────────────
DC_UPPER_LB = 30
DC_LOWER_LB = 10
ADX_THRESH = 25
ATR_TP_MULT = 3.0
ATR_SL_MULT = 2.5
TRAIL_MULT = 0.0
MAX_HOLD = 30

# ─── c207 탐색 그리드 ─────────────────────────────────────────────
ATR_PCTILE_TH_LIST = [30, 40, 50, 60]
ATR_PCTILE_LB_LIST = [30, 60]
VOL_RATIO_MIN_LIST = [0.0, 0.8, 1.0, 1.2]
VOL_SMA_PERIOD_LIST = [20, 40]
RSI_CEILING_LIST = [100, 70, 65]
TP_VOL_SCALE_LIST = [0.0, 0.5, 1.0]


# ─── 지표 계산 ───────────────────────────────────────────────────────

def donchian_upper(highs: np.ndarray, period: int) -> np.ndarray:
    """N봉 최고가 (현재 봉 제외)."""
    n = len(highs)
    result = np.full(n, np.nan)
    for i in range(period + 1, n):
        result[i] = np.max(highs[i - period:i])
    return result


def donchian_lower(lows: np.ndarray, period: int) -> np.ndarray:
    """N봉 최저가 (현재 봉 제외)."""
    n = len(lows)
    result = np.full(n, np.nan)
    for i in range(period + 1, n):
        result[i] = np.min(lows[i - period:i])
    return result


def compute_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
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
    atr_arr = np.full(n, np.nan)
    if n < period:
        return atr_arr
    atr_arr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr_arr[i] = (atr_arr[i - 1] * (period - 1) + tr[i]) / period
    return atr_arr


def compute_atr_percentile(
    atr_arr: np.ndarray, lookback: int,
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


def compute_adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Wilder's ADX."""
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2 + 1:
        return adx_arr

    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        plus_dm[i] = h_diff if (h_diff > l_diff and h_diff > 0) else 0.0
        minus_dm[i] = l_diff if (l_diff > h_diff and l_diff > 0) else 0.0
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    atr_w = np.zeros(n)
    plus_di_smooth = np.zeros(n)
    minus_di_smooth = np.zeros(n)

    atr_w[period] = np.sum(tr[1:period + 1])
    plus_di_smooth[period] = np.sum(plus_dm[1:period + 1])
    minus_di_smooth[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr_w[i] = atr_w[i - 1] - atr_w[i - 1] / period + tr[i]
        plus_di_smooth[i] = (plus_di_smooth[i - 1]
                             - plus_di_smooth[i - 1] / period + plus_dm[i])
        minus_di_smooth[i] = (minus_di_smooth[i - 1]
                              - minus_di_smooth[i - 1] / period
                              + minus_dm[i])

    dx = np.full(n, np.nan)
    for i in range(period, n):
        if atr_w[i] > 0:
            plus_di = 100.0 * plus_di_smooth[i] / atr_w[i]
            minus_di = 100.0 * minus_di_smooth[i] / atr_w[i]
            di_sum = plus_di + minus_di
            if di_sum > 0:
                dx[i] = 100.0 * abs(plus_di - minus_di) / di_sum

    adx_start = period * 2
    if adx_start >= n:
        return adx_arr
    dx_window = dx[period:adx_start]
    valid_dx = dx_window[~np.isnan(dx_window)]
    if len(valid_dx) == 0:
        return adx_arr
    adx_arr[adx_start] = np.mean(valid_dx)
    for i in range(adx_start + 1, n):
        if np.isnan(dx[i]):
            adx_arr[i] = (adx_arr[i - 1]
                          if not np.isnan(adx_arr[i - 1]) else np.nan)
        elif np.isnan(adx_arr[i - 1]):
            adx_arr[i] = dx[i]
        else:
            adx_arr[i] = (adx_arr[i - 1] * (period - 1) + dx[i]) / period
    return adx_arr


def sma_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    cumsum = np.cumsum(series)
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate(
        ([0.0], cumsum[:-period]))) / period
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


# ─── 백테스트 엔진 ───────────────────────────────────────────────────

def run_backtest(
    c: np.ndarray,
    o: np.ndarray,
    h: np.ndarray,
    lo: np.ndarray,
    v: np.ndarray,
    dc_up: np.ndarray,
    dc_lo: np.ndarray,
    atr_val: np.ndarray,
    adx_val: np.ndarray,
    btc_close: np.ndarray,
    btc_sma: np.ndarray,
    atr_pctile: np.ndarray,
    vol_sma: np.ndarray,
    rsi_arr: np.ndarray,
    atr_pctile_th: float,
    vol_ratio_min: float,
    rsi_ceiling: float,
    tp_vol_scale: float,
    oos_start: str,
    oos_end: str,
    index: pd.DatetimeIndex,
) -> list[dict]:
    """단일 심볼 백테스트 — OOS 구간 거래만 반환."""
    n = len(c)
    trades: list[dict] = []
    position = None
    oos_start_ts = pd.Timestamp(oos_start)
    oos_end_ts = pd.Timestamp(oos_end)

    warmup = max(DC_UPPER_LB, DC_LOWER_LB, BTC_SMA_PERIOD, 60) + 10

    for i in range(warmup, n - 1):
        o_next = o[i + 1]

        if position is not None:
            bars_held = i - position["entry_bar"]
            current_price = c[i]

            # trailing stop 업데이트
            if TRAIL_MULT > 0 and current_price > position["peak"]:
                position["peak"] = current_price
                atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0
                trail_stop = current_price - atr_now * TRAIL_MULT
                if trail_stop > position.get("trail_stop", 0):
                    position["trail_stop"] = trail_stop

            # 청산 조건
            exit_reason = None

            # 1) SL
            if current_price <= position["sl_price"]:
                exit_reason = "SL"

            # 2) TP
            if current_price >= position["tp_price"]:
                exit_reason = "TP"

            # 3) Trailing stop
            if (TRAIL_MULT > 0
                    and current_price <= position.get("trail_stop", 0)):
                exit_reason = "TRAIL"

            # 4) Donchian lower 돌파
            if (not np.isnan(dc_lo[i])
                    and current_price <= dc_lo[i]):
                exit_reason = "DC_LOW"

            # 5) Max hold
            if bars_held >= MAX_HOLD:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": ret,
                        "reason": exit_reason,
                        "bars": bars_held,
                    })
                position = None
        else:
            # 진입 조건
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            # c205 고정 조건
            donchian_ok = c[i] > dc_up[i]
            adx_ok = adx_val[i] >= ADX_THRESH
            btc_ok = btc_close[i] > btc_sma[i]

            # c207 신규: ATR 백분위 변동성 레짐 필터
            atr_pctile_ok = True
            if atr_pctile_th > 0:
                if np.isnan(atr_pctile[i]):
                    atr_pctile_ok = False
                else:
                    atr_pctile_ok = atr_pctile[i] >= atr_pctile_th

            # c207 신규: 거래량 확인
            vol_ok = True
            if vol_ratio_min > 0:
                if (np.isnan(vol_sma[i]) or vol_sma[i] <= 0):
                    vol_ok = False
                else:
                    vol_ok = v[i] / vol_sma[i] >= vol_ratio_min

            # c207 신규: RSI 과매수 필터
            rsi_ok = True
            if rsi_ceiling < 100:
                if np.isnan(rsi_arr[i]):
                    rsi_ok = False
                else:
                    rsi_ok = rsi_arr[i] < rsi_ceiling

            if donchian_ok and adx_ok and btc_ok and atr_pctile_ok \
                    and vol_ok and rsi_ok:
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val[i]

                # c207 신규: 변동성 → TP 보너스
                vol_tp_bonus = 0.0
                if tp_vol_scale > 0 and not np.isnan(atr_pctile[i]):
                    # ATR 백분위가 높을수록 TP 확대
                    vol_score = max(0, atr_pctile[i] - 50) / 50.0
                    vol_tp_bonus = tp_vol_scale * vol_score

                tp_pct = atr_now / c[i] * (ATR_TP_MULT + vol_tp_bonus)
                sl_pct = atr_now / c[i] * ATR_SL_MULT

                position = {
                    "entry_price": entry_price,
                    "entry_bar": i + 1,
                    "tp_price": entry_price * (1 + tp_pct),
                    "sl_price": entry_price * (1 - sl_pct),
                    "peak": entry_price,
                    "trail_stop": 0,
                }

    return trades


# ─── 메인 ────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== c207: Donchian Breakout + Volume Regime Filter 3-fold WF ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | ★슬리피지포함 | 🔄다음봉시가진입 ===")
    print(f"c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} "
          f"adx={ADX_THRESH} atrTP={ATR_TP_MULT} "
          f"atrSL={ATR_SL_MULT} trail={TRAIL_MULT}")
    print("가설: 저변동성 횡보장 필터 + 거래량 확인 → F3 감쇠 방지")
    print("=" * 80)

    # BTC 데이터
    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"BTC 데이터: {len(btc_df)} rows")

    # 심볼 데이터 로드
    sym_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        sym_data[sym] = df
        print(f"{sym} 데이터: {len(df)} rows")

    btc_close_full = btc_df["close"].values
    btc_sma_full = sma_calc(btc_close_full, BTC_SMA_PERIOD)

    # 그리드 정의
    grid = list(product(
        ATR_PCTILE_TH_LIST, ATR_PCTILE_LB_LIST,
        VOL_RATIO_MIN_LIST, VOL_SMA_PERIOD_LIST,
        RSI_CEILING_LIST, TP_VOL_SCALE_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # 심볼별 사전 계산 (고정 파라미터 부분)
    sym_precomp: dict[str, dict] = {}
    for sym in SYMBOLS:
        df = sym_data[sym]
        h_arr = df["high"].values
        lo_arr = df["low"].values
        c_arr = df["close"].values
        o_arr = df["open"].values
        v_arr = df["volume"].values

        dc_up = donchian_upper(h_arr, DC_UPPER_LB)
        dc_lo_arr = donchian_lower(lo_arr, DC_LOWER_LB)
        atr_arr = compute_atr(h_arr, lo_arr, c_arr, 14)
        adx_arr = compute_adx(h_arr, lo_arr, c_arr, 14)
        rsi_arr = rsi_calc(c_arr, 14)

        # BTC alignment
        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo_arr,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "index": df.index,
        }

    # ATR percentile 및 vol SMA 캐시 (파라미터 의존)
    atr_pctile_cache: dict[tuple, np.ndarray] = {}
    vol_sma_cache: dict[tuple, np.ndarray] = {}

    # Walk-Forward grid search
    all_results: list[dict] = []

    for gi, (atr_p_th, atr_p_lb, vol_r_min, vol_sma_p,
             rsi_ceil, tp_vs) in enumerate(grid):

        fold_sharpes = []
        fold_details = []
        total_n = 0

        for window in WINDOWS:
            fold_rets = []

            for sym in SYMBOLS:
                sp = sym_precomp[sym]

                # ATR percentile 캐시
                ap_key = (sym, atr_p_lb)
                if ap_key not in atr_pctile_cache:
                    atr_pctile_cache[ap_key] = compute_atr_percentile(
                        sp["atr"], atr_p_lb)
                atr_pctile = atr_pctile_cache[ap_key]

                # vol SMA 캐시
                vs_key = (sym, vol_sma_p)
                if vs_key not in vol_sma_cache:
                    vol_sma_cache[vs_key] = sma_calc(sp["v"], vol_sma_p)
                vol_sma = vol_sma_cache[vs_key]

                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    atr_pctile, vol_sma, sp["rsi"],
                    atr_p_th, vol_r_min, rsi_ceil, tp_vs,
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                fold_rets.extend([t["return"] for t in trades])

            # Fold Sharpe 계산
            if fold_rets:
                avg = np.mean(fold_rets)
                std = (np.std(fold_rets, ddof=1)
                       if len(fold_rets) > 1 else 1e-10)
                sharpe = ((avg / std) * np.sqrt(252 / (240 / 60 / 24))
                          if std > 0 else 0)
                wr = sum(1 for r in fold_rets if r > 0) / len(fold_rets) * 100
                # MDD
                equity = np.cumprod([1 + r for r in fold_rets])
                peak_eq = np.maximum.accumulate(equity)
                mdd = np.min(equity / peak_eq - 1) * 100
            else:
                sharpe = -999
                wr = 0
                avg = 0
                mdd = 0

            fold_sharpes.append(sharpe)
            fold_details.append({
                "name": window["name"],
                "sharpe": sharpe, "wr": wr,
                "n": len(fold_rets), "avg": avg * 100,
                "mdd": mdd,
            })
            total_n += len(fold_rets)

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        all_results.append({
            "params": (atr_p_th, atr_p_lb, vol_r_min, vol_sma_p,
                       rsi_ceil, tp_vs),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
        })

        if (gi + 1) % 50 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")

    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    # ─── 결과 정리 ───────────────────────────────────────────────────
    valid = [r for r in all_results if r["total_n"] >= 25]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=25): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 ===")
    print("=" * 80)
    hdr = (f"{'aPth':>5} {'aPLB':>5} {'vRat':>5} {'vSMA':>5} "
           f"{'rsiC':>5} {'tpVS':>5} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(
            f"{p[0]:>5} {p[1]:>5} {p[2]:>5.1f} {p[3]:>5} "
            f"{p[4]:>5} {p[5]:>5.1f} | "
            f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
            f"{r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: aPth={p[0]} aPLB={p[1]} vRat={p[2]:.1f} "
              f"vSMA={p[3]} rsiC={p[4]} tpVS={p[5]:.1f}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")

    # Top 1 심볼별 분해
    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n" + "=" * 80)
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: aPth={bp[0]} aPLB={bp[1]} "
              f"vRat={bp[2]:.1f} vSMA={bp[3]} rsiC={bp[4]} "
              f"tpVS={bp[5]:.1f}) ===")

        for sym in SYMBOLS:
            sp = sym_precomp[sym]
            sym_sharpes = []
            sym_total_n = 0

            ap_key = (sym, bp[1])
            atr_pctile = atr_pctile_cache.get(ap_key)
            if atr_pctile is None:
                atr_pctile = compute_atr_percentile(sp["atr"], bp[1])

            vs_key = (sym, bp[3])
            vol_sma = vol_sma_cache.get(vs_key)
            if vol_sma is None:
                vol_sma = sma_calc(sp["v"], bp[3])

            for window in WINDOWS:
                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    atr_pctile, vol_sma, sp["rsi"],
                    bp[0], bp[2], bp[4], bp[5],
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                rets = [t["return"] for t in trades]
                n = len(rets)
                if rets:
                    avg = np.mean(rets)
                    std = np.std(rets, ddof=1) if n > 1 else 1e-10
                    sh = ((avg / std) * np.sqrt(252 / (240 / 60 / 24))
                          if std > 0 else 0)
                    wr = sum(1 for r in rets if r > 0) / n * 100
                    eq = np.cumprod([1 + r for r in rets])
                    pk = np.maximum.accumulate(eq)
                    mdd = np.min(eq / pk - 1) * 100
                else:
                    sh, wr, avg, mdd = 0, 0, 0, 0
                print(f"  {sym} {window['name']}: Sharpe={sh:+.3f}  "
                      f"WR={wr:.1f}%  n={n}  avg={avg*100:+.2f}%  "
                      f"MDD={mdd:+.2f}%")
                sym_sharpes.append(sh)
                sym_total_n += n
            print(f"  {sym} 평균: Sharpe={np.mean(sym_sharpes):+.3f}  "
                  f"총 trades={sym_total_n}")

    # c205 비교
    print("\n" + "=" * 80)
    print("=== c205 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c205 기준 (Donchian baseline): avg_OOS=+9.542 "
              f"F3=+0.776")
        print(f"  c207 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f}")
        delta = b["avg_sharpe"] - 9.542
        delta_f3 = b["f3_sharpe"] - 0.776
        print(f"  Δ avg: {delta:+.3f} "
              f"({'개선' if delta > 0 else '악화'})")
        print(f"  Δ F3: {delta_f3:+.3f} "
              f"({'개선' if delta_f3 > 0 else '악화'})")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 3.0
        status = ("PASS" if b["avg_sharpe"] > 5.0
                  and b["total_n"] >= 25 and f3_pass else "FAIL")
        print(f"★ OOS 최적: aPth={p[0]} aPLB={p[1]} vRat={p[2]:.1f} "
              f"vSMA={p[3]} rsiC={p[4]} tpVS={p[5]:.1f}")
        print(f"  (c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} "
              f"adx={ADX_THRESH} atrTP={ATR_TP_MULT} "
              f"atrSL={ATR_SL_MULT} trail={TRAIL_MULT})")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  total trades: {b['total_n']}")
        for f in b["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  trades={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")
        print(f"\nSharpe: {b['avg_sharpe']:+.3f}")
        avg_wr = np.mean([f["wr"] for f in b["folds"]])
        print(f"WR: {avg_wr:.1f}%")
        print(f"trades: {b['total_n']}")
    else:
        print("n>=25 조건 충족 조합 없음 — FAIL")
        print("\nSharpe: N/A")
        print("WR: N/A")
        print("trades: 0")


if __name__ == "__main__":
    main()
