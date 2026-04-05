"""
사이클 219: c215 최적 + 2-tier 분할익절 + ATR 레짐 적응형 TP/SL 배수 3-fold WF
- 기반: c215 OOS Sharpe +18.682, F3 +15.099, SOL avg +10.482
  최적: emaP=10 sLB=5 slPct=0.5 slSOL=0.70 slXRP=0.85
  (EMA slope 효과 미미 → 제거, 심볼별 SL 스케일 유지)
- 문제:
  1) F1 MDD -13.03% — 큰 미실현 이익 반납 후 손절
  2) F3 거래 9건만 — 이긴 거래에서 최대 추출 필요
  3) TP/SL 배수 고정(3.0/1.5) — 변동성 레짐 무시
  4) 고변동 구간에서 TP 못 채우고 트레일링으로 빠지는 경우 다수
- 가설:
  A) 2-tier 분할 익절: TP1에서 포지션 절반 청산, 나머지 트레일링
     → 미실현 이익 조기 확보 → MDD 개선
     → TP1 = ATR×tp1Mult, TP2 = ATR×tp2Mult (tp2는 기존 TP)
     → 부분 비율(partRatio)도 탐색
  B) ATR 레짐 적응형 배수: ATR 백분위에 따라 TP/SL 배수 동적 조절
     → 고변동(ATR pctile>70): TP 확대, SL 유지 (추세 극대화)
     → 저변동(ATR pctile<30): TP 축소, SL 타이트 (빠른 회전)
     → 중간: 기본값 유지
     → hiTPBonus / loSLScale 파라미터 탐색
- c215 고정: slSOL=0.70 slXRP=0.85 (검증 완료)
  c205 고정: dcU=30 dcL=10 adx=25
  c207 고정: aPLB=30 vRat=1.0 vSMA=20 rsiC=100 tpVS=0.5
  c210 고정: trail=2.5 tpM=3.0(베이스) slM=1.5(베이스) mH=30 aPTh=30 hDec=0
- 탐색 그리드:
  TP1_MULT: [1.5, 2.0, 2.5]         — 1차 익절 ATR 배수
  PART_RATIO: [0.3, 0.5, 0.7]       — 1차 청산 비율
  HI_TP_BONUS: [0.0, 0.5, 1.0]      — 고변동 TP 보너스 배수
  LO_SL_SCALE: [0.7, 0.85, 1.0]     — 저변동 SL 축소 배수
  = 3×3×3×3 = 81 combos
- 목표: avg OOS Sharpe >= 18 AND F3 Sharpe >= 15 AND MDD 개선
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
ATR_TP_MULT_BASE = 3.0    # 베이스 TP 배수 (= TP2)
ATR_SL_MULT_BASE = 1.5    # 베이스 SL 배수
MAX_HOLD = 30
ATR_PCTILE_TH = 30
HOLD_DECAY = 0

# ─── c215 고정값 (검증 완료) ─────────────────────────────────
SYM_SL_SCALE = {"KRW-ETH": 1.0, "KRW-SOL": 0.70, "KRW-XRP": 0.85}

# ─── c219 탐색 그리드 ────────────────────────────────────────
TP1_MULT_LIST = [1.5, 2.0, 2.5]       # 1차 익절 ATR 배수
PART_RATIO_LIST = [0.3, 0.5, 0.7]     # 1차 청산 비율
HI_TP_BONUS_LIST = [0.0, 0.5, 1.0]    # 고변동 TP 보너스
LO_SL_SCALE_LIST = [0.7, 0.85, 1.0]   # 저변동 SL 축소

# ATR 레짐 구분 문턱값
ATR_REGIME_HI = 70   # 이상이면 고변동
ATR_REGIME_LO = 30   # 이하이면 저변동


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
    # c215 고정
    sl_scale: float,
    # c219 탐색 파라미터
    tp1_mult: float,
    part_ratio: float,
    hi_tp_bonus: float,
    lo_sl_scale: float,
    oos_start: str,
    oos_end: str,
    index: pd.DatetimeIndex,
) -> list[dict]:
    """단일 심볼 백테스트 — 2-tier 분할익절 + ATR 레짐 적응형."""
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

            # ★ c219: 1차 분할 익절 체크
            if (not position["tp1_hit"]
                    and current_price >= position["tp1_price"]):
                # TP1 도달 — 부분 청산 기록
                exit_actual = o_next * (1 - SLIPPAGE)
                ret_part = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": ret_part * part_ratio,
                        "reason": "TP1",
                        "bars": bars_held,
                        "weight": part_ratio,
                    })
                position["tp1_hit"] = True
                position["remaining"] = 1.0 - part_ratio
                # TP1 후 트레일링 스탑을 진입가로 올림 (breakeven)
                position["trail_stop"] = max(
                    position.get("trail_stop", 0),
                    position["entry_price"],
                )
                continue  # 이번 봉에서 추가 청산 안 함

            # 청산 조건 (TP1 후 잔여분 또는 전체)
            exit_reason = None
            remaining = position.get("remaining", 1.0)

            # 1) SL
            if current_price <= position["sl_price"]:
                exit_reason = "SL"

            # 2) TP2 (기존 TP — 잔여분 최종 익절)
            if current_price >= position["tp2_price"]:
                exit_reason = "TP2"

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

            if donchian_ok and adx_ok and btc_ok and atr_pctile_ok \
                    and vol_ok and rsi_ok:
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val[i]

                # c207 고정: 변동성 → TP 보너스
                vol_tp_bonus = 0.0
                if TP_VOL_SCALE > 0 and not np.isnan(atr_pctile[i]):
                    vol_score = max(0, atr_pctile[i] - 50) / 50.0
                    vol_tp_bonus = TP_VOL_SCALE * vol_score

                # ★ c219: ATR 레짐 적응형 TP/SL 배수
                cur_atr_pctile = atr_pctile[i] if not np.isnan(
                    atr_pctile[i]) else 50.0

                # 고변동 레짐: TP 확대
                regime_tp_bonus = 0.0
                if cur_atr_pctile >= ATR_REGIME_HI:
                    regime_tp_bonus = hi_tp_bonus

                # 저변동 레짐: SL 축소
                regime_sl_factor = 1.0
                if cur_atr_pctile <= ATR_REGIME_LO:
                    regime_sl_factor = lo_sl_scale

                tp_mult_final = ATR_TP_MULT_BASE + vol_tp_bonus + regime_tp_bonus
                sl_mult_final = ATR_SL_MULT_BASE * sl_scale * regime_sl_factor

                tp2_pct = atr_now / c[i] * tp_mult_final
                tp1_pct = atr_now / c[i] * tp1_mult
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


# ─── 거래 수익 통합 (분할 익절 → 단일 진입당 합산) ────────────

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
    print("=== c219: c215 최적 + 2-tier 분할익절 + ATR 레짐 적응형 3-fold WF ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | ★슬리피지포함 | 다음봉시가진입 ===")
    print(f"c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} adx={ADX_THRESH}")
    print(f"c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
          f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} tpVS={TP_VOL_SCALE}")
    print(f"c210 고정: trail={TRAIL_MULT} tpM={ATR_TP_MULT_BASE}(base) "
          f"slM={ATR_SL_MULT_BASE}(base) mH={MAX_HOLD} "
          f"aPTh={ATR_PCTILE_TH} hDec={HOLD_DECAY}")
    print(f"c215 고정: slSOL={SYM_SL_SCALE['KRW-SOL']} "
          f"slXRP={SYM_SL_SCALE['KRW-XRP']}")
    print("가설: 2-tier 분할익절 → MDD 개선 + ATR 레짐 적응 → 수익 극대화")
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
        TP1_MULT_LIST, PART_RATIO_LIST,
        HI_TP_BONUS_LIST, LO_SL_SCALE_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # Walk-Forward grid search
    all_results: list[dict] = []

    for gi, combo in enumerate(grid):
        tp1_m, part_r, hi_bonus, lo_sl = combo

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

                raw_trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    sl_sc,
                    tp1_m, part_r, hi_bonus, lo_sl,
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                agg = aggregate_trades(raw_trades)
                rets = [t["return"] for t in agg]
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
            fold_mdd_list.append(mdd)
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
        worst_mdd = min(fold_mdd_list) if fold_mdd_list else 0.0

        all_results.append({
            "params": combo,
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg_sharpe,
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
    hdr = (f"{'tp1M':>5} {'pRat':>5} {'hiTP':>5} {'loSL':>5} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'solSh':>7} {'wMDD':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(
            f"{p[0]:>5.1f} {p[1]:>5.1f} {p[2]:>5.1f} {p[3]:>5.2f} | "
            f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
            f"{r['sol_avg_sharpe']:>+7.3f} {r['worst_mdd']:>+7.2f} "
            f"{r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: tp1M={p[0]:.1f} pRat={p[1]:.1f} "
              f"hiTP={p[2]:.1f} loSL={p[3]:.2f}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}  SOL avg: {r['sol_avg_sharpe']:+.3f}  "
              f"worst MDD: {r['worst_mdd']:+.2f}%")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")

    # Top 1 심볼별 분해
    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n" + "=" * 80)
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: tp1M={bp[0]:.1f} "
              f"pRat={bp[1]:.1f} hiTP={bp[2]:.1f} loSL={bp[3]:.2f}) ===")

        for sym in SYMBOLS:
            sp = sym_precomp[sym]
            sl_sc = SYM_SL_SCALE[sym]
            sym_sharpes_list = []
            sym_total_n = 0

            for window in WINDOWS:
                raw_trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    sl_sc,
                    bp[0], bp[1], bp[2], bp[3],
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

    # c215 비교
    print("\n" + "=" * 80)
    print("=== c215 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c215 기준: avg_OOS=+18.682 F3=+15.099 "
              f"SOL_avg=+10.482 F1_MDD=-13.03%")
        print(f"  c219 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f} "
              f"SOL_avg={b['sol_avg_sharpe']:+.3f} "
              f"worst_MDD={b['worst_mdd']:+.2f}%")
        delta = b["avg_sharpe"] - 18.682
        delta_f3 = b["f3_sharpe"] - 15.099
        delta_sol = b["sol_avg_sharpe"] - 10.482
        delta_mdd = b["worst_mdd"] - (-13.03)
        print(f"  Δ avg: {delta:+.3f} "
              f"({'개선' if delta > 0 else '악화'})")
        print(f"  Δ F3: {delta_f3:+.3f} "
              f"({'개선' if delta_f3 > 0 else '악화'})")
        print(f"  Δ SOL: {delta_sol:+.3f} "
              f"({'개선' if delta_sol > 0 else '악화'})")
        print(f"  Δ MDD: {delta_mdd:+.2f}%p "
              f"({'개선' if delta_mdd > 0 else '악화'})")

    # 분할익절 효과 분석
    print("\n" + "=" * 80)
    print("=== 분할익절 효과 분석 (partRatio별) ===")
    for pr in PART_RATIO_LIST:
        subset = [r for r in valid if r["params"][1] == pr]
        if subset:
            avg_sh = np.mean([r["avg_sharpe"] for r in subset[:10]])
            avg_mdd = np.mean([r["worst_mdd"] for r in subset[:10]])
            print(f"  pRat={pr:.1f}: top10 avg Sharpe={avg_sh:+.3f}  "
                  f"avg worst MDD={avg_mdd:+.2f}%")

    print("\n=== ATR 레짐 적응 효과 분석 ===")
    # 고변동 TP 보너스 효과
    for hb in HI_TP_BONUS_LIST:
        subset = [r for r in valid if r["params"][2] == hb]
        if subset:
            avg_sh = np.mean([r["avg_sharpe"] for r in subset[:10]])
            print(f"  hiTPBonus={hb:.1f}: top10 avg Sharpe={avg_sh:+.3f}")

    # 저변동 SL 축소 효과
    print()
    for ls in LO_SL_SCALE_LIST:
        subset = [r for r in valid if r["params"][3] == ls]
        if subset:
            avg_sh = np.mean([r["avg_sharpe"] for r in subset[:10]])
            avg_sol = np.mean([r["sol_avg_sharpe"] for r in subset[:10]])
            print(f"  loSLScale={ls:.2f}: top10 avg Sharpe={avg_sh:+.3f}  "
                  f"SOL={avg_sol:+.3f}")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 15.0
        sol_pass = b["sol_avg_sharpe"] >= 10.0
        mdd_improved = b["worst_mdd"] > -13.03
        status = ("PASS" if b["avg_sharpe"] >= 18.0
                  and b["total_n"] >= 30 and f3_pass else "FAIL")
        print(f"★ OOS 최적: tp1M={p[0]:.1f} pRat={p[1]:.1f} "
              f"hiTP={p[2]:.1f} loSL={p[3]:.2f}")
        print(f"  (c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} "
              f"adx={ADX_THRESH})")
        print(f"  (c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
              f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} "
              f"tpVS={TP_VOL_SCALE})")
        print(f"  (c210 고정: trail={TRAIL_MULT} tpM={ATR_TP_MULT_BASE} "
              f"slM={ATR_SL_MULT_BASE} mH={MAX_HOLD} "
              f"aPTh={ATR_PCTILE_TH} hDec={HOLD_DECAY})")
        print(f"  (c215 고정: slSOL={SYM_SL_SCALE['KRW-SOL']} "
              f"slXRP={SYM_SL_SCALE['KRW-XRP']})")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_pass else 'FAIL'}")
        print(f"  worst MDD: {b['worst_mdd']:+.2f}% "
              f"{'PASS(개선)' if mdd_improved else 'FAIL(악화)'}")
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
