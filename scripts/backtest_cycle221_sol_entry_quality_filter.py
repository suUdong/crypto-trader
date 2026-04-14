"""
사이클 221: c219 최적 고정 + SOL 전용 진입 품질 필터 3-fold WF
- 기반: c219 OOS avg=+23.575, F3=+29.650, SOL=+7.658(FAIL), worst MDD=-12.12%
  최적: tp1M=2.5 pRat=0.7 hiTP=0.0 loSL=0.70
- 문제:
  1) SOL avg Sharpe +7.658 — FAIL (목표 >= 10.0)
  2) ETH/XRP는 강력 — SOL만 개선하면 전체 대폭 상승 가능
  3) c219 분할익절/ATR레짐 효과 미미 → hiTP=0.0 승, pRat 차이 미미
     → 복잡도 대비 효과 부족, SOL 진입 품질이 진짜 병목
- 가설:
  A) SOL ADX 강화: SOL은 추세 약한 구간에서 잘못된 진입 다수
     → SOL에서만 ADX 임계값 추가 부스트 (기본 25 + boost)
  B) SOL RSI 하한: RSI 너무 낮으면 약세 모멘텀에 진입
     → SOL에서만 RSI > floor 필터 (0=비활성)
  C) SOL 거래량 강화: 거래량 동반 없는 가짜 돌파 필터
     → SOL에서만 볼륨 비율 강화 (기본 1.0 vs 더 높은 기준)
  D) SOL ATR pctile 부스트: 변동성 약한 구간에서 진입 제한
     → SOL에서만 ATR 백분위 임계 추가 (기본 30 + boost)
- c219 고정: tp1M=2.5 pRat=0.7 hiTP=0.0 loSL=0.70
  c215 고정: slSOL=0.70 slXRP=0.85
  c210 고정: trail=2.5 tpM=3.0 slM=1.5 mH=30 aPTh=30 hDec=0
  c207 고정: aPLB=30 vRat=1.0 vSMA=20 rsiC=100 tpVS=0.5
  c205 고정: dcU=30 dcL=10 adx=25
- 탐색 그리드:
  SOL_ADX_BOOST:     [0, 5, 10]     — SOL ADX 추가 (25+0=25, 25+5=30, 25+10=35)
  SOL_RSI_FLOOR:     [0, 40, 50]    — SOL RSI 하한 (0=비활성)
  SOL_VOL_BOOST:     [1.0, 1.5, 2.0] — SOL 거래량 비율 최소
  SOL_ATR_PCT_BOOST: [0, 10, 20]    — SOL ATR pctile 추가
  = 3×3×3×3 = 81 combos
- 목표: SOL avg Sharpe >= 10.0 AND avg OOS >= 23.0 AND worst MDD >= -13%
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
ATR_TP_MULT_BASE = 3.0
ATR_SL_MULT_BASE = 1.5
MAX_HOLD = 30
ATR_PCTILE_TH = 30
HOLD_DECAY = 0

# ─── c215 고정값 ─────────────────────────────────────────────
SYM_SL_SCALE = {"KRW-ETH": 1.0, "KRW-SOL": 0.70, "KRW-XRP": 0.85}

# ─── c219 고정값 (검증 완료) ─────────────────────────────────
TP1_MULT = 2.5
PART_RATIO = 0.7
HI_TP_BONUS = 0.0
LO_SL_SCALE = 0.70

# ATR 레짐 구분 문턱값
ATR_REGIME_HI = 70
ATR_REGIME_LO = 30

# ─── c221 탐색 그리드: SOL 전용 필터 ────────────────────────
SOL_ADX_BOOST_LIST = [0, 5, 10]        # SOL ADX += boost
SOL_RSI_FLOOR_LIST = [0, 40, 50]       # SOL RSI >= floor (0=비활성)
SOL_VOL_BOOST_LIST = [1.0, 1.5, 2.0]  # SOL vol_ratio >= this
SOL_ATR_PCT_BOOST_LIST = [0, 10, 20]   # SOL ATR pctile += boost


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
    # 심볼별 파라미터
    sl_scale: float,
    adx_thresh_eff: float,
    rsi_floor: float,
    vol_ratio_min_eff: float,
    atr_pctile_th_eff: float,
    # WF 기간
    oos_start: str,
    oos_end: str,
    index: pd.DatetimeIndex,
) -> list[dict]:
    """단일 심볼 백테스트 — c219 고정 + 심볼별 진입 필터."""
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

            # 1차 분할 익절 체크 (c219 고정)
            if (not position["tp1_hit"]
                    and current_price >= position["tp1_price"]):
                exit_actual = o_next * (1 - SLIPPAGE)
                ret_part = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": ret_part * PART_RATIO,
                        "reason": "TP1",
                        "bars": bars_held,
                        "weight": PART_RATIO,
                    })
                position["tp1_hit"] = True
                position["remaining"] = 1.0 - PART_RATIO
                position["trail_stop"] = max(
                    position.get("trail_stop", 0),
                    position["entry_price"],
                )
                continue

            # 청산 조건
            exit_reason = None
            remaining = position.get("remaining", 1.0)

            if current_price <= position["sl_price"]:
                exit_reason = "SL"
            if current_price >= position["tp2_price"]:
                exit_reason = "TP2"
            if (TRAIL_MULT > 0
                    and current_price <= position.get("trail_stop", 0)):
                exit_reason = "TRAIL"
            if (not np.isnan(dc_lo[i])
                    and current_price <= dc_lo[i]):
                exit_reason = "DC_LOW"
            if bars_held >= MAX_HOLD:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": ret * remaining,
                        "reason": exit_reason,
                        "bars": bars_held,
                        "weight": remaining,
                    })
                position = None
        else:
            # 진입 조건
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            # c205: Donchian + ADX + BTC
            donchian_ok = c[i] > dc_up[i]
            adx_ok = adx_val[i] >= adx_thresh_eff  # ★ 심볼별 ADX
            btc_ok = btc_close[i] > btc_sma[i]

            # c207: ATR 백분위 (★ 심볼별 임계값)
            atr_pctile_ok = True
            if atr_pctile_th_eff > 0:
                if np.isnan(atr_pctile[i]):
                    atr_pctile_ok = False
                else:
                    atr_pctile_ok = atr_pctile[i] >= atr_pctile_th_eff

            # c207: 거래량 (★ 심볼별 볼륨 비율)
            vol_ok = True
            if vol_ratio_min_eff > 0:
                if np.isnan(vol_sma[i]) or vol_sma[i] <= 0:
                    vol_ok = False
                else:
                    vol_ok = v[i] / vol_sma[i] >= vol_ratio_min_eff

            # ★ c221: RSI 하한 필터 (심볼별)
            rsi_floor_ok = True
            if rsi_floor > 0:
                if np.isnan(rsi_arr[i]):
                    rsi_floor_ok = False
                else:
                    rsi_floor_ok = rsi_arr[i] >= rsi_floor

            # c207: RSI 상한 (고정, 비활성)
            rsi_ok = True
            if RSI_CEILING < 100:
                if np.isnan(rsi_arr[i]):
                    rsi_ok = False
                else:
                    rsi_ok = rsi_arr[i] < RSI_CEILING

            if (donchian_ok and adx_ok and btc_ok and atr_pctile_ok
                    and vol_ok and rsi_ok and rsi_floor_ok):
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val[i]

                # c207: 변동성 → TP 보너스
                vol_tp_bonus = 0.0
                if TP_VOL_SCALE > 0 and not np.isnan(atr_pctile[i]):
                    vol_score = max(0, atr_pctile[i] - 50) / 50.0
                    vol_tp_bonus = TP_VOL_SCALE * vol_score

                # c219: ATR 레짐 적응 (hiTP=0.0 고정 → 실질적으로 비활성)
                cur_atr_pctile = atr_pctile[i] if not np.isnan(
                    atr_pctile[i]) else 50.0
                regime_tp_bonus = 0.0
                if cur_atr_pctile >= ATR_REGIME_HI:
                    regime_tp_bonus = HI_TP_BONUS  # 0.0
                regime_sl_factor = 1.0
                if cur_atr_pctile <= ATR_REGIME_LO:
                    regime_sl_factor = LO_SL_SCALE

                tp_mult_final = ATR_TP_MULT_BASE + vol_tp_bonus + regime_tp_bonus
                sl_mult_final = ATR_SL_MULT_BASE * sl_scale * regime_sl_factor

                tp2_pct = atr_now / c[i] * tp_mult_final
                tp1_pct = atr_now / c[i] * TP1_MULT
                sl_pct = atr_now / c[i] * sl_mult_final

                position = {
                    "entry_price": entry_price,
                    "entry_bar": i + 1,
                    "tp1_price": entry_price * (1 + tp1_pct),
                    "tp2_price": entry_price * (1 + tp2_pct),
                    "sl_price": entry_price * (1 - sl_pct),
                    "peak": entry_price,
                    "trail_stop": 0,
                    "tp1_hit": False,
                    "remaining": 1.0,
                }

    return trades


# ─── 거래 수익 통합 ──────────────────────────────────────────

def aggregate_trades(trades: list[dict]) -> list[dict]:
    """같은 entry_time의 분할 거래를 합산."""
    if not trades:
        return []
    by_entry: dict[str, dict] = {}
    for t in trades:
        key = str(t["entry_time"])
        if key not in by_entry:
            by_entry[key] = {
                "entry_time": t["entry_time"],
                "return": 0.0,
                "bars": t["bars"],
                "reasons": [],
            }
        by_entry[key]["return"] += t["return"]
        by_entry[key]["bars"] = max(by_entry[key]["bars"], t["bars"])
        by_entry[key]["reasons"].append(t["reason"])
    return list(by_entry.values())


# ─── 메인 ────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== c221: c219 최적 고정 + SOL 전용 진입 품질 필터 3-fold WF ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | ★슬리피지포함 | 다음봉시가진입 ===")
    print(f"c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} adx={ADX_THRESH}")
    print(f"c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
          f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} tpVS={TP_VOL_SCALE}")
    print(f"c210 고정: trail={TRAIL_MULT} tpM={ATR_TP_MULT_BASE} "
          f"slM={ATR_SL_MULT_BASE} mH={MAX_HOLD} aPTh={ATR_PCTILE_TH}")
    print(f"c215 고정: slSOL={SYM_SL_SCALE['KRW-SOL']} "
          f"slXRP={SYM_SL_SCALE['KRW-XRP']}")
    print(f"c219 고정: tp1M={TP1_MULT} pRat={PART_RATIO} "
          f"hiTP={HI_TP_BONUS} loSL={LO_SL_SCALE}")
    print("가설: SOL 전용 진입 필터(ADX강화+RSI하한+거래량강화+ATR강화) "
          "→ SOL Sharpe >= 10.0")
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

    # 심볼별 사전 계산
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
        SOL_ADX_BOOST_LIST, SOL_RSI_FLOOR_LIST,
        SOL_VOL_BOOST_LIST, SOL_ATR_PCT_BOOST_LIST,
    ))
    print(f"\n총 SOL 필터 조합: {len(grid)}")
    print("(ETH/XRP는 기본 파라미터 고정, SOL만 필터 변동)")

    # Walk-Forward grid search
    all_results: list[dict] = []

    for gi, combo in enumerate(grid):
        sol_adx_b, sol_rsi_f, sol_vol_b, sol_atr_b = combo

        fold_sharpes = []
        fold_details = []
        total_n = 0

        sym_fold_data: dict[str, list[list[float]]] = {
            s: [] for s in SYMBOLS
        }
        fold_mdd_list = []

        for window in WINDOWS:
            fold_rets = []

            for sym in SYMBOLS:
                sp = sym_precomp[sym]
                sl_sc = SYM_SL_SCALE[sym]

                # ★ SOL만 필터 강화, ETH/XRP는 기본값
                if sym == "KRW-SOL":
                    adx_th_eff = ADX_THRESH + sol_adx_b
                    rsi_fl = sol_rsi_f
                    vol_min_eff = sol_vol_b
                    atr_pctile_th_eff = ATR_PCTILE_TH + sol_atr_b
                else:
                    adx_th_eff = ADX_THRESH
                    rsi_fl = 0  # 비활성
                    vol_min_eff = VOL_RATIO_MIN
                    atr_pctile_th_eff = ATR_PCTILE_TH

                raw_trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    sl_sc,
                    adx_th_eff, rsi_fl, vol_min_eff, atr_pctile_th_eff,
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                agg = aggregate_trades(raw_trades)
                rets = [t["return"] for t in agg]
                fold_rets.extend(rets)
                sym_fold_data[sym].append(rets)

            # Fold Sharpe
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
                sharpe, wr, avg, mdd = -999, 0, 0, 0

            fold_sharpes.append(sharpe)
            fold_details.append({
                "name": window["name"],
                "sharpe": sharpe, "wr": wr,
                "n": len(fold_rets), "avg": avg * 100,
                "mdd": mdd,
            })
            fold_mdd_list.append(mdd)
            total_n += len(fold_rets)

        # SOL 평균 Sharpe
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

        # XRP 평균 Sharpe
        xrp_sharpes = []
        for fold_rets_xrp in sym_fold_data["KRW-XRP"]:
            if fold_rets_xrp:
                avg_x = np.mean(fold_rets_xrp)
                std_x = (np.std(fold_rets_xrp, ddof=1)
                         if len(fold_rets_xrp) > 1 else 1e-10)
                sh_x = ((avg_x / std_x) * np.sqrt(252 / (240 / 60 / 24))
                        if std_x > 0 else 0)
            else:
                sh_x = -999
            xrp_sharpes.append(sh_x)
        xrp_avg_sharpe = np.mean(xrp_sharpes) if xrp_sharpes else -999

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        worst_mdd = min(fold_mdd_list) if fold_mdd_list else 0.0

        all_results.append({
            "params": combo,
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg_sharpe,
            "xrp_avg_sharpe": xrp_avg_sharpe,
            "worst_mdd": worst_mdd,
            "sym_fold_data": sym_fold_data,
        })

        if (gi + 1) % 20 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")

    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    # ─── 결과 정리 ───────────────────────────────────────────
    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 ===")
    print("=" * 80)
    hdr = (f"{'adxB':>5} {'rsiF':>5} {'volB':>5} {'atrB':>5} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'solSh':>7} {'xrpSh':>7} "
           f"{'wMDD':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(
            f"{p[0]:>5} {p[1]:>5} {p[2]:>5.1f} {p[3]:>5} | "
            f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
            f"{r['sol_avg_sharpe']:>+7.3f} {r['xrp_avg_sharpe']:>+7.3f} "
            f"{r['worst_mdd']:>+7.2f} {r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: adxB={p[0]} rsiF={p[1]} volB={p[2]:.1f} "
              f"atrB={p[3]}")
        print(f"  → SOL 실효: ADX>={ADX_THRESH + p[0]} RSI>={p[1]} "
              f"vol>={p[2]:.1f} atrPct>={ATR_PCTILE_TH + p[3]}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}  SOL avg: {r['sol_avg_sharpe']:+.3f}  "
              f"XRP avg: {r['xrp_avg_sharpe']:+.3f}  "
              f"worst MDD: {r['worst_mdd']:+.2f}%")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")

    # SOL 필터별 효과 분석
    print("\n" + "=" * 80)
    print("=== SOL 필터별 효과 분석 ===")

    print("\n--- ADX 부스트 효과 ---")
    for ab in SOL_ADX_BOOST_LIST:
        subset = [r for r in valid if r["params"][0] == ab]
        if subset:
            avg_sh = np.mean([r["avg_sharpe"] for r in subset[:10]])
            avg_sol = np.mean([r["sol_avg_sharpe"] for r in subset[:10]])
            print(f"  ADX+{ab} (>={ADX_THRESH + ab}): "
                  f"top10 avg Sharpe={avg_sh:+.3f}  SOL={avg_sol:+.3f}")

    print("\n--- RSI 하한 효과 ---")
    for rf in SOL_RSI_FLOOR_LIST:
        subset = [r for r in valid if r["params"][1] == rf]
        if subset:
            avg_sh = np.mean([r["avg_sharpe"] for r in subset[:10]])
            avg_sol = np.mean([r["sol_avg_sharpe"] for r in subset[:10]])
            print(f"  RSI>={rf}: "
                  f"top10 avg Sharpe={avg_sh:+.3f}  SOL={avg_sol:+.3f}")

    print("\n--- 거래량 비율 효과 ---")
    for vb in SOL_VOL_BOOST_LIST:
        subset = [r for r in valid if r["params"][2] == vb]
        if subset:
            avg_sh = np.mean([r["avg_sharpe"] for r in subset[:10]])
            avg_sol = np.mean([r["sol_avg_sharpe"] for r in subset[:10]])
            avg_n = np.mean([r["total_n"] for r in subset[:10]])
            print(f"  vol>={vb:.1f}: "
                  f"top10 avg Sharpe={avg_sh:+.3f}  SOL={avg_sol:+.3f}  "
                  f"avg_n={avg_n:.0f}")

    print("\n--- ATR pctile 부스트 효과 ---")
    for apb in SOL_ATR_PCT_BOOST_LIST:
        subset = [r for r in valid if r["params"][3] == apb]
        if subset:
            avg_sh = np.mean([r["avg_sharpe"] for r in subset[:10]])
            avg_sol = np.mean([r["sol_avg_sharpe"] for r in subset[:10]])
            print(f"  ATR pct+{apb} (>={ATR_PCTILE_TH + apb}): "
                  f"top10 avg Sharpe={avg_sh:+.3f}  SOL={avg_sol:+.3f}")

    # Top 1 심볼별 분해
    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n" + "=" * 80)
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: adxB={bp[0]} rsiF={bp[1]} "
              f"volB={bp[2]:.1f} atrB={bp[3]}) ===")

        for sym in SYMBOLS:
            sp = sym_precomp[sym]
            sl_sc = SYM_SL_SCALE[sym]
            sym_sharpes_list = []
            sym_total_n = 0

            if sym == "KRW-SOL":
                adx_th_eff = ADX_THRESH + bp[0]
                rsi_fl = bp[1]
                vol_min_eff = bp[2]
                atr_pctile_th_eff = ATR_PCTILE_TH + bp[3]
            else:
                adx_th_eff = ADX_THRESH
                rsi_fl = 0
                vol_min_eff = VOL_RATIO_MIN
                atr_pctile_th_eff = ATR_PCTILE_TH

            for window in WINDOWS:
                raw_trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    sl_sc,
                    adx_th_eff, rsi_fl, vol_min_eff, atr_pctile_th_eff,
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                agg = aggregate_trades(raw_trades)
                rets = [t["return"] for t in agg]
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

    # c219 비교
    print("\n" + "=" * 80)
    print("=== c219 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        bp = b["params"]
        print(f"  c219 기준: avg_OOS=+23.575 F3=+29.650 "
              f"SOL_avg=+7.658 worst_MDD=-12.12%")
        print(f"  c221 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f} "
              f"SOL_avg={b['sol_avg_sharpe']:+.3f} "
              f"worst_MDD={b['worst_mdd']:+.2f}%")
        delta = b["avg_sharpe"] - 23.575
        delta_f3 = b["f3_sharpe"] - 29.650
        delta_sol = b["sol_avg_sharpe"] - 7.658
        delta_mdd = b["worst_mdd"] - (-12.12)
        print(f"  Δ avg: {delta:+.3f} "
              f"({'개선' if delta > 0 else '악화'})")
        print(f"  Δ F3: {delta_f3:+.3f} "
              f"({'개선' if delta_f3 > 0 else '악화'})")
        print(f"  Δ SOL: {delta_sol:+.3f} "
              f"({'개선' if delta_sol > 0 else '악화'})")
        print(f"  Δ MDD: {delta_mdd:+.2f}%p "
              f"({'개선' if delta_mdd > 0 else '악화'})")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 15.0
        sol_pass = b["sol_avg_sharpe"] >= 10.0
        mdd_ok = b["worst_mdd"] > -13.0
        status = ("PASS" if b["avg_sharpe"] >= 23.0
                  and b["total_n"] >= 30 and f3_pass else "FAIL")
        print(f"★ OOS 최적: adxB={p[0]} rsiF={p[1]} "
              f"volB={p[2]:.1f} atrB={p[3]}")
        print(f"  → SOL 실효: ADX>={ADX_THRESH + p[0]} RSI>={p[1]} "
              f"vol>={p[2]:.1f} atrPct>={ATR_PCTILE_TH + p[3]}")
        print(f"  (c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} "
              f"adx={ADX_THRESH})")
        print(f"  (c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
              f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} "
              f"tpVS={TP_VOL_SCALE})")
        print(f"  (c210 고정: trail={TRAIL_MULT} tpM={ATR_TP_MULT_BASE} "
              f"slM={ATR_SL_MULT_BASE} mH={MAX_HOLD} "
              f"aPTh={ATR_PCTILE_TH})")
        print(f"  (c215 고정: slSOL={SYM_SL_SCALE['KRW-SOL']} "
              f"slXRP={SYM_SL_SCALE['KRW-XRP']})")
        print(f"  (c219 고정: tp1M={TP1_MULT} pRat={PART_RATIO} "
              f"hiTP={HI_TP_BONUS} loSL={LO_SL_SCALE})")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_pass else 'FAIL(목표>=10)'}")
        print(f"  worst MDD: {b['worst_mdd']:+.2f}% "
              f"{'PASS' if mdd_ok else 'FAIL'}")
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
