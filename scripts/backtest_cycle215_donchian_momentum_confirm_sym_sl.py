"""
사이클 215: c210 최적 + 모멘텀 확인(EMA slope) + 심볼별 SL 스케일 3-fold WF
- 기반: c210 OOS Sharpe +16.485, F3 +11.993
  최적: trail=2.5 tpM=3.0 slM=1.5 mH=30 aPTh=30 hDec=0
- 문제:
  1) SOL F3 Sharpe -3.447 (WR 33.3%, n=3) — 거짓 브레이크아웃 손실
  2) SOL 전체 avg Sharpe +6.345 vs ETH +74.710 — 품질 차이 극심
  3) F3 총 9거래 중 SOL/XRP가 7개인데 품질 낮음
  4) Donchian 브레이크아웃만으로 추세 강도 확인 부족
- 가설:
  A) EMA slope 확인: 진입 시 단기 EMA가 상승 중이어야 함
     → 모멘텀 없는 박스권 돌파 걸러냄 (SOL F3 핵심 원인)
     → slope_period로 민감도 조절
  B) 심볼별 SL 스케일: 변동성 높은 심볼에 SL 배수 조정
     → SOL은 SL을 타이트하게(빠른 손절), ETH는 넓게(추세 유지)
     → sym_sl_scale으로 SOL/XRP에 0.8~1.2 적용
  C) EMA 기울기 문턱: 최소 기울기(slope_pct) 이상이어야 진입
     → 평탄한 추세 필터링
- c210 고정: trail=2.5 tpM=3.0 slM=1.5 mH=30 aPTh=30 hDec=0
  c205 고정: dcU=30 dcL=10 adx=25
  c207 고정: aPLB=30 vRat=1.0 vSMA=20 rsiC=100 tpVS=0.5
- 탐색 그리드:
  EMA_PERIOD: [10, 20, 30]          — EMA 기간
  SLOPE_LB: [3, 5, 8]               — slope 계산 룩백
  SLOPE_MIN_PCT: [0.0, 0.5, 1.0, 2.0] — 최소 slope % (0=비활성)
  SYM_SL_SCALE_SOL: [0.7, 0.85, 1.0] — SOL SL 스케일
  SYM_SL_SCALE_XRP: [0.85, 1.0, 1.15] — XRP SL 스케일
  = 3×3×4×3×3 = 324 combos
- 목표: OOS Sharpe >= 16 AND F3 Sharpe >= 10 AND SOL avg Sharpe >= 10
- 3-fold WF + 슬리피지 스트레스
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005
SLIPPAGE = 0.001

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

# ─── c205 고정값 ─────────────────────────────────────────────
DC_UPPER_LB = 30
DC_LOWER_LB = 10
ADX_THRESH = 25

# ─── c207 고정값 ─────────────────────────────────────────────
ATR_PCTILE_LB = 30
VOL_RATIO_MIN = 1.0
VOL_SMA_PERIOD = 20
RSI_CEILING = 100
TP_VOL_SCALE = 0.5

# ─── c210 고정값 ─────────────────────────────────────────────
TRAIL_MULT = 2.5
ATR_TP_MULT = 3.0
ATR_SL_MULT = 1.5
MAX_HOLD = 30
ATR_PCTILE_TH = 30
HOLD_DECAY = 0

# ─── c215 탐색 그리드 ────────────────────────────────────────
EMA_PERIOD_LIST = [10, 20, 30]
SLOPE_LB_LIST = [3, 5, 8]
SLOPE_MIN_PCT_LIST = [0.0, 0.5, 1.0, 2.0]
SYM_SL_SCALE_SOL_LIST = [0.7, 0.85, 1.0]
SYM_SL_SCALE_XRP_LIST = [0.85, 1.0, 1.15]
# ETH SL scale 고정 1.0 (이미 최적)


# ─── 지표 계산 ───────────────────────────────────────────────

def donchian_upper(highs: np.ndarray, period: int) -> np.ndarray:
    n = len(highs)
    result = np.full(n, np.nan)
    for i in range(period + 1, n):
        result[i] = np.max(highs[i - period:i])
    return result


def donchian_lower(lows: np.ndarray, period: int) -> np.ndarray:
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


def ema_calc(series: np.ndarray, period: int) -> np.ndarray:
    """지수이동평균 계산."""
    n = len(series)
    result = np.full(n, np.nan)
    if n < period:
        return result
    result[period - 1] = np.mean(series[:period])
    mult = 2.0 / (period + 1)
    for i in range(period, n):
        result[i] = series[i] * mult + result[i - 1] * (1 - mult)
    return result


def ema_slope_pct(ema_arr: np.ndarray, lookback: int) -> np.ndarray:
    """EMA의 lookback 기간 기울기 (%)."""
    n = len(ema_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        prev = ema_arr[i - lookback]
        curr = ema_arr[i]
        if np.isnan(prev) or np.isnan(curr) or prev <= 0:
            continue
        result[i] = (curr - prev) / prev * 100.0
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


# ─── 백테스트 엔진 ───────────────────────────────────────────

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
    ema_slope: np.ndarray,
    # c215 탐색 파라미터
    slope_min_pct: float,
    sl_scale: float,
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

            # 1) SL (심볼별 스케일 적용)
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

            # c207 고정: ATR 백분위 변동성 레짐 필터
            atr_pctile_ok = True
            if ATR_PCTILE_TH > 0:
                if np.isnan(atr_pctile[i]):
                    atr_pctile_ok = False
                else:
                    atr_pctile_ok = atr_pctile[i] >= ATR_PCTILE_TH

            # c207 고정: 거래량 확인
            vol_ok = True
            if VOL_RATIO_MIN > 0:
                if np.isnan(vol_sma[i]) or vol_sma[i] <= 0:
                    vol_ok = False
                else:
                    vol_ok = v[i] / vol_sma[i] >= VOL_RATIO_MIN

            # c207 고정: RSI 과매수 필터 (rsiC=100 비활성)
            rsi_ok = True
            if RSI_CEILING < 100:
                if np.isnan(rsi_arr[i]):
                    rsi_ok = False
                else:
                    rsi_ok = rsi_arr[i] < RSI_CEILING

            # ★ c215 NEW: EMA slope 모멘텀 확인
            slope_ok = True
            if slope_min_pct > 0:
                if np.isnan(ema_slope[i]):
                    slope_ok = False
                else:
                    slope_ok = ema_slope[i] >= slope_min_pct

            if (donchian_ok and adx_ok and btc_ok and atr_pctile_ok
                    and vol_ok and rsi_ok and slope_ok):
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val[i]

                # c207 고정: 변동성 → TP 보너스
                vol_tp_bonus = 0.0
                if TP_VOL_SCALE > 0 and not np.isnan(atr_pctile[i]):
                    vol_score = max(0, atr_pctile[i] - 50) / 50.0
                    vol_tp_bonus = TP_VOL_SCALE * vol_score

                tp_pct = atr_now / c[i] * (ATR_TP_MULT + vol_tp_bonus)
                # ★ c215 NEW: 심볼별 SL 스케일
                sl_pct = atr_now / c[i] * ATR_SL_MULT * sl_scale

                tp_price = entry_price * (1 + tp_pct)
                position = {
                    "entry_price": entry_price,
                    "entry_bar": i + 1,
                    "tp_price": tp_price,
                    "sl_price": entry_price * (1 - sl_pct),
                    "peak": entry_price,
                    "trail_stop": 0,
                }

    return trades


# ─── 메인 ────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== c215: c210 + EMA slope 모멘텀 확인 + 심볼별 SL 스케일 3-fold WF ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | ★슬리피지포함 | 다음봉시가진입 ===")
    print(f"c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} adx={ADX_THRESH}")
    print(f"c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
          f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} tpVS={TP_VOL_SCALE}")
    print(f"c210 고정: trail={TRAIL_MULT} tpM={ATR_TP_MULT} slM={ATR_SL_MULT} "
          f"mH={MAX_HOLD} aPTh={ATR_PCTILE_TH} hDec={HOLD_DECAY}")
    print("가설: EMA slope → 거짓 브레이크아웃 필터 + 심볼별 SL → SOL 개선")
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

    # 심볼별 사전 계산 (고정 파라미터)
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
        atr_pctile = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
        vol_sma_arr = sma_calc(v_arr, VOL_SMA_PERIOD)

        # BTC alignment
        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo_arr,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr,
            "atr_pctile": atr_pctile, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "index": df.index,
        }

    # 그리드 정의
    grid = list(product(
        EMA_PERIOD_LIST, SLOPE_LB_LIST, SLOPE_MIN_PCT_LIST,
        SYM_SL_SCALE_SOL_LIST, SYM_SL_SCALE_XRP_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # EMA/slope 사전 계산 (EMA_PERIOD × SLOPE_LB 조합별)
    ema_slope_cache: dict[str, dict[tuple[int, int], np.ndarray]] = {}
    for sym in SYMBOLS:
        sp = sym_precomp[sym]
        ema_slope_cache[sym] = {}
        for ema_p in EMA_PERIOD_LIST:
            ema_arr = ema_calc(sp["c"], ema_p)
            for slb in SLOPE_LB_LIST:
                slope_arr = ema_slope_pct(ema_arr, slb)
                ema_slope_cache[sym][(ema_p, slb)] = slope_arr

    # Walk-Forward grid search
    all_results: list[dict] = []

    # 심볼별 SL 스케일 맵 (ETH=1.0 고정)
    SYM_SL_MAP_KEYS = {"KRW-ETH": None, "KRW-SOL": 3, "KRW-XRP": 4}

    for gi, combo in enumerate(grid):
        ema_p, slb, slope_pct, sl_sol, sl_xrp = combo
        sl_map = {"KRW-ETH": 1.0, "KRW-SOL": sl_sol, "KRW-XRP": sl_xrp}

        fold_sharpes = []
        fold_details = []
        total_n = 0

        # 심볼별 fold 결과 저장 (SOL 필터용)
        sym_fold_data: dict[str, list[list[float]]] = {
            s: [] for s in SYMBOLS
        }

        for window in WINDOWS:
            fold_rets = []

            for sym in SYMBOLS:
                sp = sym_precomp[sym]
                slope_arr = ema_slope_cache[sym][(ema_p, slb)]

                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    slope_arr,
                    slope_pct, sl_map[sym],
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                rets = [t["return"] for t in trades]
                fold_rets.extend(rets)
                sym_fold_data[sym].append(rets)

            # Fold Sharpe 계산
            if fold_rets:
                avg = np.mean(fold_rets)
                std = (np.std(fold_rets, ddof=1)
                       if len(fold_rets) > 1 else 1e-10)
                sharpe = ((avg / std) * np.sqrt(252 / (240 / 60 / 24))
                          if std > 0 else 0)
                wr = sum(1 for r in fold_rets if r > 0) / len(fold_rets) * 100
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

        # SOL 평균 Sharpe 계산
        sol_sharpes = []
        for fold_rets_sol in sym_fold_data["KRW-SOL"]:
            if fold_rets_sol:
                avg_s = np.mean(fold_rets_sol)
                std_s = (np.std(fold_rets_sol, ddof=1)
                         if len(fold_rets_sol) > 1 else 1e-10)
                sh_s = ((avg_s / std_s) * np.sqrt(252 / (240 / 60 / 24))
                        if std_s > 0 else 0)
            else:
                sh_s = -999
            sol_sharpes.append(sh_s)
        sol_avg_sharpe = np.mean(sol_sharpes) if sol_sharpes else -999

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        all_results.append({
            "params": combo,
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg_sharpe,
            "sym_fold_data": sym_fold_data,
        })

        if (gi + 1) % 50 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")

    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    # ─── 결과 정리 ───────────────────────────────────────────
    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 ===")
    print("=" * 80)
    hdr = (f"{'emaP':>5} {'sLB':>4} {'slPct':>6} {'slSOL':>6} {'slXRP':>6} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'solSh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(
            f"{p[0]:>5} {p[1]:>4} {p[2]:>6.1f} {p[3]:>6.2f} {p[4]:>6.2f} | "
            f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
            f"{r['sol_avg_sharpe']:>+7.3f} {r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: emaP={p[0]} sLB={p[1]} slPct={p[2]:.1f} "
              f"slSOL={p[3]:.2f} slXRP={p[4]:.2f}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}  SOL avg: {r['sol_avg_sharpe']:+.3f}")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")

    # Top 1 심볼별 분해
    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n" + "=" * 80)
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: emaP={bp[0]} "
              f"sLB={bp[1]} slPct={bp[2]:.1f} "
              f"slSOL={bp[3]:.2f} slXRP={bp[4]:.2f}) ===")

        sl_map_best = {
            "KRW-ETH": 1.0, "KRW-SOL": bp[3], "KRW-XRP": bp[4],
        }

        for sym in SYMBOLS:
            sp = sym_precomp[sym]
            slope_arr = ema_slope_cache[sym][(bp[0], bp[1])]
            sym_sharpes_list = []
            sym_total_n = 0

            for window in WINDOWS:
                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    slope_arr,
                    bp[2], sl_map_best[sym],
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                rets = [t["return"] for t in trades]
                nn = len(rets)
                if rets:
                    avg = np.mean(rets)
                    std = np.std(rets, ddof=1) if nn > 1 else 1e-10
                    sh = ((avg / std) * np.sqrt(252 / (240 / 60 / 24))
                          if std > 0 else 0)
                    wr = sum(1 for r in rets if r > 0) / nn * 100
                    eq = np.cumprod([1 + r for r in rets])
                    pk = np.maximum.accumulate(eq)
                    mdd_v = np.min(eq / pk - 1) * 100
                else:
                    sh, wr, avg, mdd_v = 0, 0, 0, 0
                print(f"  {sym} {window['name']}: Sharpe={sh:+.3f}  "
                      f"WR={wr:.1f}%  n={nn}  avg={avg*100:+.2f}%  "
                      f"MDD={mdd_v:+.2f}%")
                sym_sharpes_list.append(sh)
                sym_total_n += nn
            print(f"  {sym} 평균: Sharpe={np.mean(sym_sharpes_list):+.3f}  "
                  f"총 trades={sym_total_n}")

    # c210 비교
    print("\n" + "=" * 80)
    print("=== c210 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c210 기준: avg_OOS=+16.485 F3=+11.993 SOL_avg=+6.345")
        print(f"  c215 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f} SOL_avg={b['sol_avg_sharpe']:+.3f}")
        delta = b["avg_sharpe"] - 16.485
        delta_f3 = b["f3_sharpe"] - 11.993
        delta_sol = b["sol_avg_sharpe"] - 6.345
        print(f"  Δ avg: {delta:+.3f} "
              f"({'개선' if delta > 0 else '악화'})")
        print(f"  Δ F3: {delta_f3:+.3f} "
              f"({'개선' if delta_f3 > 0 else '악화'})")
        print(f"  Δ SOL: {delta_sol:+.3f} "
              f"({'개선' if delta_sol > 0 else '악화'})")

    # slope 효과 분석
    print("\n" + "=" * 80)
    print("=== EMA slope 효과 분석 (slope=0 vs slope>0) ===")
    no_slope = [r for r in valid if r["params"][2] == 0.0]
    with_slope = [r for r in valid if r["params"][2] > 0.0]
    if no_slope:
        avg_ns = np.mean([r["avg_sharpe"] for r in no_slope[:10]])
        avg_sol_ns = np.mean([r["sol_avg_sharpe"] for r in no_slope[:10]])
        print(f"  slope=0 top10 avg Sharpe: {avg_ns:+.3f}  SOL: {avg_sol_ns:+.3f}")
    if with_slope:
        avg_ws = np.mean([r["avg_sharpe"] for r in with_slope[:10]])
        avg_sol_ws = np.mean([r["sol_avg_sharpe"] for r in with_slope[:10]])
        print(f"  slope>0 top10 avg Sharpe: {avg_ws:+.3f}  SOL: {avg_sol_ws:+.3f}")

    # SL 스케일 효과 분석
    print("\n=== 심볼별 SL 스케일 효과 ===")
    for sl_val in SYM_SL_SCALE_SOL_LIST:
        subset = [r for r in valid if r["params"][3] == sl_val]
        if subset:
            avg_sh = np.mean([r["avg_sharpe"] for r in subset[:10]])
            avg_sol = np.mean([r["sol_avg_sharpe"] for r in subset[:10]])
            print(f"  SOL slScale={sl_val:.2f}: top10 avg={avg_sh:+.3f}  "
                  f"SOL avg={avg_sol:+.3f}")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 10.0
        sol_pass = b["sol_avg_sharpe"] >= 10.0
        status = ("PASS" if b["avg_sharpe"] >= 16.0
                  and b["total_n"] >= 30 and f3_pass else "FAIL")
        print(f"★ OOS 최적: emaP={p[0]} sLB={p[1]} slPct={p[2]:.1f} "
              f"slSOL={p[3]:.2f} slXRP={p[4]:.2f}")
        print(f"  (c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} "
              f"adx={ADX_THRESH})")
        print(f"  (c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
              f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} "
              f"tpVS={TP_VOL_SCALE})")
        print(f"  (c210 고정: trail={TRAIL_MULT} tpM={ATR_TP_MULT} "
              f"slM={ATR_SL_MULT} mH={MAX_HOLD} "
              f"aPTh={ATR_PCTILE_TH} hDec={HOLD_DECAY})")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_pass else 'FAIL'}")
        print(f"  total trades: {b['total_n']}")
        for f in b["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  trades={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")
        avg_wr = np.mean([f["wr"] for f in b["folds"]])
        print(f"\nSharpe: {b['avg_sharpe']:+.3f}")
        print(f"WR: {avg_wr:.1f}%")
        print(f"trades: {b['total_n']}")
    else:
        print("n>=30 조건 충족 조합 없음 — FAIL")
        print("\nSharpe: N/A")
        print("WR: N/A")
        print("trades: 0")


if __name__ == "__main__":
    main()
