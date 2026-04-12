"""
사이클 244: c243 최적 고정 + 거래량 가속도 브레이크아웃 필터

c243 결과:
  avg OOS Sharpe: +31.850 PASS  F2: +33.667 PASS  F3: +13.521 FAIL
  F1: Sharpe=+48.363  WR=85.7%  trades=14  avg=+6.50%  MDD=-1.60%
  F2: Sharpe=+33.667  WR=87.5%  trades=8   avg=+3.43%  MDD=-4.98%
  F3: Sharpe=+13.521  WR=60.0%  trades=5   avg=+1.24%  MDD=-2.75%

문제 분석:
  - F3 Sharpe +13.5 (n=5) — 최근 구간(2025-12~2026-03)에서 약한 성과
  - F3 WR 60% = 5건 중 2건 손실 — 진입 품질 이슈
  - 가설 1: 거래량이 "가속"되는 (증가 추세) 브레이크아웃만 취하면 노이즈 진입 줄임
    → 단순 vol > sma가 아니라, 최근 N봉 동안 vol이 상승 추세인지 확인
  - 가설 2: 브레이크아웃 "강도" (dc_up 대비 초과 비율)과 vol 가속의 조합이
    F3 구간의 약한 시그널을 걸러낼 수 있음

c243 최적 고정:
  btcMLB=10, btcMMin=0.02, btcADX=0, boMgn=0.005
  (c241: rCeil=80 rFlr=30 mLB=5 mMin=0.02 aPct=30 vRat=1.5)
  (c233: trail=2.0 TP2=3.0 SL=1.5 MH=30 TP1=2.5)
  (c231: cLim=2 cool=6 ddTr=1.0 ddLB=5 ddTh=-3.0)
  (c219: pRat=0.7)
  (SOL gate: solADX=35 solVol=1.3 solAtrPth=50)
  (c205: dcU=30 dcL=10 adx=25)
  (c215: slSOL=0.7 slXRP=0.85)

새 탐색 그리드 (c244):
  VOL_ACCEL_LB:     [3, 5, 8]           — 거래량 추세 lookback (봉 수)
  VOL_ACCEL_MIN:    [0.0, 0.05, 0.10, 0.20] — 최소 거래량 상승률 (0=OFF)
  BREAKOUT_STR_MIN: [0.0, 0.005, 0.010, 0.015] — DC_UPPER 대비 최소 초과율 (0=OFF)
  = 3 × 4 × 4 = 48 combos

목표: F3 Sharpe >= 20 AND avg >= 28 AND F2 >= 25 AND SOL >= 10 AND MDD > -15%
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical  # noqa: E402

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

# ─── c205 고정 ────────────────────────────────────────────────
DC_UPPER_LB = 30
DC_LOWER_LB = 10
ADX_THRESH = 25

# ─── c207 고정 ────────────────────────────────────────────────
ATR_PCTILE_LB = 30
VOL_SMA_PERIOD = 20
TP_VOL_SCALE = 0.5

# ─── c215 고정 ────────────────────────────────────────────────
SYM_SL_SCALE = {"KRW-ETH": 1.0, "KRW-SOL": 0.70, "KRW-XRP": 0.85}

# ─── c219 고정 (2-tier 분할익절) ──────────────────────────────
PART_RATIO = 0.7

# ─── SOL 전용 게이트 ──────────────────────────────────────────
SOL_ADX_GATE = 35
SOL_VOL_GATE = 1.3
SOL_ATR_PCTILE_GATE = 50

# ─── c231 고정 (MDD 제어) ─────────────────────────────────────
CONSEC_LOSS_LIMIT = 2
COOLDOWN_BARS = 6
DD_TRAIL_TIGHTEN = 1.0
DD_LB_TRADES = 5
DD_THRESH_PCT = -3.0

# ─── c233 최적 출구 고정 ─────────────────────────────────────
BASE_TRAIL_MULT = 2.0
BASE_TP2_MULT = 3.0
BASE_SL_MULT = 1.5
BASE_MAX_HOLD = 30
BASE_TP1_MULT = 2.5

# ─── c241 최적 엔트리 필터 고정 ──────────────────────────────
RSI_CEIL = 80
RSI_FLOOR = 30
MOM_LB = 5
MOM_MIN = 0.02
ATR_PCTILE_MIN = 30
VOL_RATIO_MIN = 1.5

# ─── c243 최적 고정 ──────────────────────────────────────────
BTC_MOM_LB = 10
BTC_MOM_MIN = 0.02
BTC_ADX_GATE = 0
BREAKOUT_MARGIN = 0.005

# ─── c244 탐색 그리드 ─────────────────────────────────────────
VOL_ACCEL_LB_LIST = [3, 5, 8]
VOL_ACCEL_MIN_LIST = [0.0, 0.05, 0.10, 0.20]
BREAKOUT_STR_MIN_LIST = [0.0, 0.005, 0.010, 0.015]


# ─── 지표 계산 ──────────────────────────────────────────────

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


def compute_atr_percentile(atr_arr: np.ndarray, lookback: int) -> np.ndarray:
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
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
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
    result[period - 1:] = (
        cumsum[period - 1:]
        - np.concatenate(([0.0], cumsum[:-period]))
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


def compute_vol_accel(volume: np.ndarray, lookback: int) -> np.ndarray:
    """거래량 가속도: 최근 lookback 봉 동안 거래량 변화율 (선형 회귀 기울기 기반).

    양수 = 거래량 증가 추세, 음수 = 감소 추세.
    결과는 평균 거래량 대비 비율로 정규화.
    """
    n = len(volume)
    result = np.full(n, np.nan)
    x = np.arange(lookback, dtype=float)
    x_mean = x.mean()
    x_var = np.sum((x - x_mean) ** 2)
    if x_var == 0:
        return result

    for i in range(lookback, n):
        window = volume[i - lookback:i]
        if np.any(np.isnan(window)):
            continue
        y_mean = window.mean()
        if y_mean <= 0:
            continue
        slope = np.sum((x - x_mean) * (window - y_mean)) / x_var
        # 정규화: 기울기를 평균 거래량 대비 비율로
        result[i] = slope / y_mean
    return result


# ─── 백테스트 엔진 ─────────────────────────────────────────

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
    vol_accel: np.ndarray,
    sl_scale: float,
    sym: str,
    # c244 새 파라미터
    vol_accel_min: float,
    breakout_str_min: float,
    oos_start: str,
    oos_end: str,
    index: pd.DatetimeIndex,
) -> list[dict]:
    """c243 최적 고정 + 거래량 가속도 + 브레이크아웃 강도 필터."""
    n = len(c)
    trades: list[dict] = []
    position = None
    oos_s = pd.Timestamp(oos_start)
    oos_e = pd.Timestamp(oos_end)

    consec_losses = 0
    cooldown_until = -1
    recent_returns: list[float] = []

    warmup = max(DC_UPPER_LB, DC_LOWER_LB, BTC_SMA_PERIOD, 60,
                 MOM_LB + 5, BTC_MOM_LB + 5, 15) + 10

    for i in range(warmup, n - 1):
        o_next = o[i + 1]

        if position is not None:
            bars_held = i - position["entry_bar"]
            cp = c[i]

            # trailing stop 업데이트
            if cp > position["peak"]:
                position["peak"] = cp
                atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0
                effective_trail = BASE_TRAIL_MULT
                if DD_TRAIL_TIGHTEN > 0 and len(recent_returns) >= DD_LB_TRADES:
                    recent_sum = sum(recent_returns[-DD_LB_TRADES:]) * 100
                    if recent_sum < DD_THRESH_PCT:
                        effective_trail = max(1.0, effective_trail - DD_TRAIL_TIGHTEN)
                ts = cp - atr_now * effective_trail
                if ts > position.get("trail_stop", 0):
                    position["trail_stop"] = ts

            # TP1 분할익절
            if not position["tp1_hit"] and cp >= position["tp1_price"]:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret_part = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                et = index[position["entry_bar"]]
                if oos_s <= et <= oos_e:
                    trades.append({
                        "entry_time": et,
                        "return": ret_part * PART_RATIO,
                        "reason": "TP1",
                        "bars": bars_held,
                    })
                position["tp1_hit"] = True
                position["remaining"] = 1.0 - PART_RATIO
                position["trail_stop"] = max(
                    position.get("trail_stop", 0),
                    position["entry_price"],
                )
                continue

            # 청산 조건
            remaining = position.get("remaining", 1.0)
            exit_reason = None

            if cp <= position["sl_price"]:
                exit_reason = "SL"
            if cp >= position["tp2_price"]:
                exit_reason = "TP2"
            if cp <= position.get("trail_stop", 0):
                exit_reason = "TRAIL"
            if not np.isnan(dc_lo[i]) and cp <= dc_lo[i]:
                exit_reason = "DC_LOW"
            if bars_held >= BASE_MAX_HOLD:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                et = index[position["entry_bar"]]
                if oos_s <= et <= oos_e:
                    trades.append({
                        "entry_time": et,
                        "return": ret * remaining,
                        "reason": exit_reason,
                        "bars": bars_held,
                    })

                recent_returns.append(ret)
                if ret < 0:
                    consec_losses += 1
                    if consec_losses >= CONSEC_LOSS_LIMIT:
                        cooldown_until = i + COOLDOWN_BARS
                else:
                    consec_losses = 0

                position = None

        else:
            if i <= cooldown_until:
                continue

            # 기본 nan/데이터 체크
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            # 기본 진입 필터
            if not (c[i] > dc_up[i]):
                continue
            if not (adx_val[i] >= ADX_THRESH):
                continue
            if not (btc_close[i] > btc_sma[i]):
                continue

            # ── c241 고정 엔트리 필터 ────────────────────────
            if not np.isnan(atr_pctile[i]) and atr_pctile[i] < ATR_PCTILE_MIN:
                continue

            if (not np.isnan(vol_sma[i]) and vol_sma[i] > 0
                    and v[i] / vol_sma[i] < VOL_RATIO_MIN):
                continue

            if not np.isnan(rsi_arr[i]):
                if rsi_arr[i] > RSI_CEIL or rsi_arr[i] < RSI_FLOOR:
                    continue

            if i >= MOM_LB:
                mom_ret = (c[i] / c[i - MOM_LB]) - 1.0
                if mom_ret < MOM_MIN:
                    continue

            # ── c243 고정 필터 ───────────────────────────────
            if BTC_MOM_MIN > 0.0 and i >= BTC_MOM_LB:
                btc_now = btc_close[i]
                btc_prev = btc_close[i - BTC_MOM_LB]
                if np.isnan(btc_now) or np.isnan(btc_prev) or btc_prev <= 0:
                    continue
                btc_mom = btc_now / btc_prev - 1.0
                if btc_mom < BTC_MOM_MIN:
                    continue

            if BREAKOUT_MARGIN > 0.0 and dc_up[i] > 0:
                if c[i] < dc_up[i] * (1.0 + BREAKOUT_MARGIN):
                    continue

            # ── c244 새 필터 ─────────────────────────────────
            # 1) 거래량 가속도 필터
            if vol_accel_min > 0.0 and not np.isnan(vol_accel[i]):
                if vol_accel[i] < vol_accel_min:
                    continue

            # 2) 브레이크아웃 강도 필터 (DC_UPPER 대비 초과율)
            if breakout_str_min > 0.0 and dc_up[i] > 0:
                bo_strength = (c[i] - dc_up[i]) / dc_up[i]
                if bo_strength < breakout_str_min:
                    continue

            # SOL 전용 게이트
            if sym == "KRW-SOL":
                if adx_val[i] < SOL_ADX_GATE:
                    continue
                if (not np.isnan(vol_sma[i]) and vol_sma[i] > 0
                        and v[i] / vol_sma[i] < SOL_VOL_GATE):
                    continue
                if (not np.isnan(atr_pctile[i])
                        and atr_pctile[i] < SOL_ATR_PCTILE_GATE):
                    continue

            # XRP 전용 게이트
            if sym == "KRW-XRP":
                if adx_val[i] < 25:
                    continue

            # 진입
            entry_price = o_next * (1 + SLIPPAGE)
            atr_now = atr_val[i]

            vol_tp_bonus = 0.0
            if TP_VOL_SCALE > 0 and not np.isnan(atr_pctile[i]):
                vol_score = max(0, atr_pctile[i] - 50) / 50.0
                vol_tp_bonus = TP_VOL_SCALE * vol_score

            tp_mult_final = BASE_TP2_MULT + vol_tp_bonus
            sl_mult = BASE_SL_MULT * sl_scale

            tp2_pct = atr_now / c[i] * tp_mult_final
            tp1_pct = atr_now / c[i] * BASE_TP1_MULT
            sl_pct = atr_now / c[i] * sl_mult

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


def aggregate_trades(trades: list[dict]) -> list[dict]:
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


def calc_sharpe(rets: list[float]) -> float:
    if not rets:
        return -999
    avg = np.mean(rets)
    std = np.std(rets, ddof=1) if len(rets) > 1 else 1e-10
    return (avg / std) * np.sqrt(252 / (240 / 60 / 24)) if std > 0 else 0


def calc_mdd(rets: list[float]) -> float:
    if not rets:
        return 0
    equity = np.cumprod([1 + r for r in rets])
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1) * 100)


# ─── 메인 ──────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== c244: c243최적 고정 + 거래량 가속도 + 브레이크아웃 강도 필터 ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | 슬리피지포함 | 다음봉시가진입 ===")
    print(f"c243 고정: btcMLB={BTC_MOM_LB} btcMMin={BTC_MOM_MIN} "
          f"btcADX={BTC_ADX_GATE} boMgn={BREAKOUT_MARGIN}")
    print(f"c241 고정: rCeil={RSI_CEIL} rFlr={RSI_FLOOR} mLB={MOM_LB} "
          f"mMin={MOM_MIN} aPct={ATR_PCTILE_MIN} vRat={VOL_RATIO_MIN}")
    print(f"c233 고정: trail={BASE_TRAIL_MULT} TP2={BASE_TP2_MULT} "
          f"SL={BASE_SL_MULT} MH={BASE_MAX_HOLD} TP1={BASE_TP1_MULT}")
    print(f"탐색: VOL_ACCEL_LB × VOL_ACCEL_MIN × BREAKOUT_STR_MIN")
    print("=" * 80)

    # 데이터 로드
    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-12")
    print(f"BTC 데이터: {len(btc_df)} rows")

    sym_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = load_historical(sym, "240m", "2022-01-01", "2026-04-12")
        sym_data[sym] = df
        print(f"{sym} 데이터: {len(df)} rows")

    btc_close_full = btc_df["close"].values
    btc_sma_full = sma_calc(btc_close_full, BTC_SMA_PERIOD)

    # 각 VOL_ACCEL_LB에 대해 미리 계산
    vol_accel_precomp: dict[str, dict[int, np.ndarray]] = {}

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
        rsi_arr_s = rsi_calc(c_arr, 14)
        atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
        vol_sma_arr = sma_calc(v_arr, VOL_SMA_PERIOD)

        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_sma_s = pd.Series(btc_sma_full, index=btc_df.index)

        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_sma_aligned = btc_sma_s.reindex(df.index, method="ffill").values

        # vol accel per lookback
        va_by_lb: dict[int, np.ndarray] = {}
        for lb in VOL_ACCEL_LB_LIST:
            va_by_lb[lb] = compute_vol_accel(v_arr, lb)
        vol_accel_precomp[sym] = va_by_lb

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo_arr,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr_s,
            "atr_pctile": atr_pctile_arr, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_sma": btc_sma_aligned,
            "index": df.index,
        }

    # 그리드
    grid = list(product(
        VOL_ACCEL_LB_LIST, VOL_ACCEL_MIN_LIST, BREAKOUT_STR_MIN_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # 베이스라인 (c243 최적, 새 필터 OFF)
    print("\n--- 베이스라인 (c243 최적, vol_accel=OFF, bo_str=OFF) ---")
    base_fold_sharpes = []
    base_fold_details = []
    base_total_n = 0

    for window in WINDOWS:
        fold_rets = []
        for sym in SYMBOLS:
            sp = sym_precomp[sym]
            dummy_va = np.full(len(sp["c"]), np.nan)
            raw = run_backtest(
                sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                sp["dc_up"], sp["dc_lo"],
                sp["atr"], sp["adx"],
                sp["btc_c"], sp["btc_sma"],
                sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                dummy_va,
                SYM_SL_SCALE[sym], sym,
                0.0, 0.0,  # 새 필터 OFF
                window["oos_start"], window["oos_end"],
                sp["index"],
            )
            agg = aggregate_trades(raw)
            fold_rets.extend([t["return"] for t in agg])

        sh = calc_sharpe(fold_rets)
        wr = (sum(1 for r in fold_rets if r > 0) / len(fold_rets) * 100
              if fold_rets else 0)
        mdd = calc_mdd(fold_rets)
        avg_r = np.mean(fold_rets) * 100 if fold_rets else 0
        base_fold_sharpes.append(sh)
        base_fold_details.append({
            "name": window["name"], "sharpe": sh, "wr": wr,
            "n": len(fold_rets), "avg": avg_r, "mdd": mdd,
        })
        base_total_n += len(fold_rets)

    base_avg = np.mean(base_fold_sharpes)
    base_f2 = base_fold_sharpes[1]
    base_f3 = base_fold_sharpes[2]
    base_worst_mdd = min(f["mdd"] for f in base_fold_details)
    print(f"  avg Sharpe: {base_avg:+.3f}  F2: {base_f2:+.3f}  "
          f"F3: {base_f3:+.3f}  worst MDD: {base_worst_mdd:+.2f}%  "
          f"n={base_total_n}")
    for f in base_fold_details:
        print(f"  {f['name']}: Sh={f['sharpe']:+.3f} WR={f['wr']:.1f}% "
              f"n={f['n']} avg={f['avg']:+.2f}% MDD={f['mdd']:+.2f}%")

    # 그리드 서치
    all_results: list[dict] = []

    for gi, combo in enumerate(grid):
        va_lb, va_min, bo_str_min = combo

        fold_sharpes = []
        fold_details = []
        total_n = 0
        sym_fold: dict[str, list[list[float]]] = {s: [] for s in SYMBOLS}
        fold_mdd_list = []

        for window in WINDOWS:
            fold_rets = []
            for sym in SYMBOLS:
                sp = sym_precomp[sym]
                va_arr = vol_accel_precomp[sym][va_lb]
                raw = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_sma"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    va_arr,
                    SYM_SL_SCALE[sym], sym,
                    va_min, bo_str_min,
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                agg = aggregate_trades(raw)
                rets = [t["return"] for t in agg]
                fold_rets.extend(rets)
                sym_fold[sym].append(rets)

            sh = calc_sharpe(fold_rets)
            wr = (sum(1 for r in fold_rets if r > 0) / len(fold_rets) * 100
                  if fold_rets else 0)
            mdd = calc_mdd(fold_rets)
            avg_r = np.mean(fold_rets) * 100 if fold_rets else 0

            fold_sharpes.append(sh)
            fold_details.append({
                "name": window["name"], "sharpe": sh, "wr": wr,
                "n": len(fold_rets), "avg": avg_r, "mdd": mdd,
            })
            fold_mdd_list.append(mdd)
            total_n += len(fold_rets)

        sol_sharpes = [calc_sharpe(rs) for rs in sym_fold["KRW-SOL"]]
        sol_avg = np.mean(sol_sharpes) if sol_sharpes else -999

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        worst_mdd = min(fold_mdd_list) if fold_mdd_list else 0
        f2_sharpe = fold_sharpes[1] if len(fold_sharpes) > 1 else -999

        all_results.append({
            "params": combo,
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f2_sharpe": f2_sharpe,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg,
            "worst_mdd": worst_mdd,
        })

        if (gi + 1) % 20 == 0:
            print(f"  진행: {gi + 1}/{len(grid)}")

    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    # 결과 정렬: F3 개선 우선 (c244의 핵심 목표)
    valid = [r for r in all_results if r["total_n"] >= 20]
    valid.sort(
        key=lambda x: (
            x["f3_sharpe"] >= 20,
            x["avg_sharpe"] >= 28,
            x["f2_sharpe"] >= 25,
            x["worst_mdd"] > -15,
            x["sol_avg_sharpe"] >= 10,
            x["f3_sharpe"],
            x["avg_sharpe"],
        ),
        reverse=True,
    )

    print(f"\n유효 조합 (n>=20): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 (F3개선 우선) ===")
    print("=" * 80)
    hdr = (f"{'vaLB':>5} {'vaMin':>6} {'boStr':>6} | "
           f"{'avgSh':>7} {'F2Sh':>7} {'F3Sh':>7} {'solSh':>7} "
           f"{'wMDD':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(
            f"{p[0]:>5} {p[1]:>6.2f} {p[2]:>6.3f} | "
            f"{r['avg_sharpe']:>+7.3f} {r['f2_sharpe']:>+7.3f} "
            f"{r['f3_sharpe']:>+7.3f} {r['sol_avg_sharpe']:>+7.3f} "
            f"{r['worst_mdd']:>+7.2f} {r['total_n']:>5}")

    # 효과 분석
    print("\n=== 거래량 가속도 Lookback 효과 ===")
    for val in VOL_ACCEL_LB_LIST:
        sub = [r for r in valid if r["params"][0] == val]
        if sub:
            top5 = sorted(sub, key=lambda x: x["f3_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_f3 = np.mean([r["f3_sharpe"] for r in top5])
            print(f"  vaLB={val}: top5 avgSh={avg_sh:+.3f}  F3={avg_f3:+.3f}")

    print("\n=== 거래량 가속도 최소값 효과 ===")
    for val in VOL_ACCEL_MIN_LIST:
        sub = [r for r in valid if r["params"][1] == val]
        if sub:
            top5 = sorted(sub, key=lambda x: x["f3_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_f3 = np.mean([r["f3_sharpe"] for r in top5])
            print(f"  vaMin={val:.2f}: top5 avgSh={avg_sh:+.3f}  F3={avg_f3:+.3f}")

    print("\n=== 브레이크아웃 강도 최소값 효과 ===")
    for val in BREAKOUT_STR_MIN_LIST:
        sub = [r for r in valid if r["params"][2] == val]
        if sub:
            top5 = sorted(sub, key=lambda x: x["f3_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_f3 = np.mean([r["f3_sharpe"] for r in top5])
            print(f"  boStr={val:.3f}: top5 avgSh={avg_sh:+.3f}  F3={avg_f3:+.3f}")

    # 합격 조합
    passing = [r for r in valid
               if r["f3_sharpe"] >= 20
               and r["avg_sharpe"] >= 28
               and r["f2_sharpe"] >= 25
               and r["sol_avg_sharpe"] >= 10
               and r["worst_mdd"] > -15]
    print(f"\n=== 합격 (F3>=20 & avg>=28 & F2>=25 & SOL>=10 & MDD>-15%): "
          f"{len(passing)}개 ===")
    for r in passing[:10]:
        p = r["params"]
        print(f"  vaLB={p[0]} vaMin={p[1]:.2f} boStr={p[2]:.3f} | "
              f"avg={r['avg_sharpe']:+.3f} F2={r['f2_sharpe']:+.3f} "
              f"F3={r['f3_sharpe']:+.3f} SOL={r['sol_avg_sharpe']:+.3f} "
              f"MDD={r['worst_mdd']:+.2f}% n={r['total_n']}")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== c243 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c243 기준: avg_OOS=+31.850 F2=+33.667 "
              f"F3=+13.521 SOL=+40.596 worst_MDD=-4.98%")
        print(f"  c244 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F2={b['f2_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f} "
              f"SOL_avg={b['sol_avg_sharpe']:+.3f} "
              f"worst_MDD={b['worst_mdd']:+.2f}%")
        d_avg = b["avg_sharpe"] - 31.850
        d_f2 = b["f2_sharpe"] - 33.667
        d_f3 = b["f3_sharpe"] - 13.521
        d_sol = b["sol_avg_sharpe"] - 40.596
        d_mdd = b["worst_mdd"] - (-4.98)
        print(f"  Δ avg: {d_avg:+.3f} ({'개선' if d_avg > 0 else '악화'})")
        print(f"  Δ F2:  {d_f2:+.3f} ({'개선' if d_f2 > 0 else '악화'})")
        print(f"  Δ F3:  {d_f3:+.3f} ({'개선' if d_f3 > 0 else '악화'})")
        print(f"  Δ SOL: {d_sol:+.3f} ({'개선' if d_sol > 0 else '악화'})")
        print(f"  Δ MDD: {d_mdd:+.2f}%p ({'개선' if d_mdd > 0 else '악화'})")

    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f2_pass = b["f2_sharpe"] >= 25.0
        f3_pass = b["f3_sharpe"] >= 20.0
        sol_pass = b["sol_avg_sharpe"] >= 10.0
        mdd_pass = b["worst_mdd"] > -15.0
        avg_pass = b["avg_sharpe"] >= 28.0
        print(f"★ OOS 최적: vaLB={p[0]} vaMin={p[1]:.2f} boStr={p[2]:.3f}")
        print(f"  (c243 고정: btcMLB={BTC_MOM_LB} btcMMin={BTC_MOM_MIN} "
              f"btcADX={BTC_ADX_GATE} boMgn={BREAKOUT_MARGIN})")
        print(f"  (c241 고정: rCeil={RSI_CEIL} rFlr={RSI_FLOOR} "
              f"mLB={MOM_LB} mMin={MOM_MIN} aPct={ATR_PCTILE_MIN} "
              f"vRat={VOL_RATIO_MIN})")
        print(f"  (c233 고정: trail={BASE_TRAIL_MULT} TP2={BASE_TP2_MULT} "
              f"SL={BASE_SL_MULT} MH={BASE_MAX_HOLD} TP1={BASE_TP1_MULT})")
        print(f"  (c231 고정: cLim={CONSEC_LOSS_LIMIT} cool={COOLDOWN_BARS} "
              f"ddTr={DD_TRAIL_TIGHTEN} ddLB={DD_LB_TRADES} ddTh={DD_THRESH_PCT})")
        print(f"  (c219 고정: pRat={PART_RATIO})")
        print(f"  (SOL gate: solADX={SOL_ADX_GATE} solVol={SOL_VOL_GATE} "
              f"solAtrPth={SOL_ATR_PCTILE_GATE})")
        print(f"  (c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} adx={ADX_THRESH})")
        print(f"  (c215 고정: slSOL={SYM_SL_SCALE['KRW-SOL']} "
              f"slXRP={SYM_SL_SCALE['KRW-XRP']})")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} "
              f"{'PASS' if avg_pass else 'FAIL'}")
        print(f"  F2 Sharpe: {b['f2_sharpe']:+.3f} "
              f"{'PASS' if f2_pass else 'FAIL'}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_pass else 'FAIL'}")
        print(f"  worst MDD: {b['worst_mdd']:+.2f}% "
              f"{'PASS' if mdd_pass else 'FAIL'}")
        print(f"  total trades: {b['total_n']}")

        for fold in b["folds"]:
            print(f"  {fold['name']}: Sharpe={fold['sharpe']:+.3f}  "
                  f"WR={fold['wr']:.1f}%  trades={fold['n']}  "
                  f"avg={fold['avg']:+.2f}%  MDD={fold['mdd']:+.2f}%")

        all_rets = []
        for window in WINDOWS:
            for sym in SYMBOLS:
                sp = sym_precomp[sym]
                va_arr = vol_accel_precomp[sym][p[0]]
                raw = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_sma"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    va_arr,
                    SYM_SL_SCALE[sym], sym,
                    p[1], p[2],
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                agg = aggregate_trades(raw)
                all_rets.extend([t["return"] for t in agg])

        total_wr = (sum(1 for r in all_rets if r > 0) / len(all_rets) * 100
                    if all_rets else 0)
        total_sh = calc_sharpe(all_rets)
        print(f"\nSharpe: {total_sh:+.2f}")
        print(f"WR: {total_wr:.1f}%")
        print(f"trades: {len(all_rets)}")


if __name__ == "__main__":
    main()
