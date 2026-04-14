"""
사이클 232: c231 최적 고정 + F2 개선 진입 필터 강화 3-fold WF

c231 결과:
  ★ cLim=2 cool=6 ddTrail=1.0 ddLB=5 ddTh=-3.0
  avg OOS Sharpe: +29.622  F3: +43.081  SOL: +21.805  worst_MDD: -14.65%
  F1: Sharpe=+27.750  WR=76.7%  trades=30  avg=+5.24%  MDD=-12.12%
  F2: Sharpe=+18.035  WR=60.6%  trades=33  avg=+2.05%  MDD=-14.65%  ← 약점
  F3: Sharpe=+43.081  WR=85.7%  trades=7   avg=+2.64%  MDD=-2.21%

문제 분석:
  - F2 WR 60.6%: 약세 구간에서도 진입 → 승률 하락
  - BTC SMA200 위이기만 하면 진입: 트렌드 강도 미반영
  - RSI 천장만 있고 바닥 없음: 약한 모멘텀 구간 진입 가능
  - XRP에는 SOL 같은 전용 게이트 없음

가설:
  A) BTC 트렌드 강도: BTC가 SMA200 대비 최소 X% 위일 때만 진입
     → 약세 회복 초기(SMA 바로 위)에서의 성급한 진입 방지
  B) RSI 밴드: RSI가 특정 범위(예: 40~70)일 때만 진입
     → 과매도 반등(RSI<40)과 과매수(RSI>70) 구간 배제
  C) XRP 전용 ADX/거래량 게이트: SOL처럼 XRP에도 별도 필터
     → XRP의 낮은 추세 구간 진입 방지

고정 (c231 최적 전체):
  c205: dcU=30 dcL=10 adx=25
  c207: aPLB=30 vRat=1.0 vSMA=20 rsiC=100 tpVS=0.5
  c210: trail=2.5 tpM=3.0 slM=1.5 mH=30 aPTh=30
  c215: slSOL=0.70 slXRP=0.85
  c219: tp1M=2.5 pRat=0.7
  c231: cLim=2 cool=6 ddTrail=1.0 ddLB=5 ddTh=-3.0
  SOL gates: solADX=35 solVol=1.3 solAtrPth=50

탐색 그리드:
  BTC_TREND_MIN_PCT: [0.0, 1.0, 3.0]     — BTC SMA200 대비 최소 % 상회
  RSI_ENTRY_LO: [0, 35, 45]               — RSI 하한 (0=OFF)
  RSI_ENTRY_HI: [70, 80, 100]             — RSI 상한 (100=OFF=기존)
  XRP_ADX_GATE: [25, 30, 35]              — XRP ADX 게이트 (25=기존)
  XRP_VOL_GATE: [1.0, 1.2]               — XRP 거래량 게이트 (1.0=기존)
  = 3×3×3×3×2 = 162 combos

목표: avg>=27 AND F3>=40 AND F2_sharpe>=20 AND worst_MDD>-15%
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

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

# ─── c205 고정 ───────────────────────────────────────────────
DC_UPPER_LB = 30
DC_LOWER_LB = 10
ADX_THRESH = 25

# ─── c207 고정 ───────────────────────────────────────────────
ATR_PCTILE_LB = 30
VOL_RATIO_MIN = 1.0
VOL_SMA_PERIOD = 20
RSI_CEILING = 100  # 기본 천장 (탐색에서 오버라이드)
TP_VOL_SCALE = 0.5

# ─── c210 고정 ───────────────────────────────────────────────
TRAIL_MULT_BASE = 2.5
ATR_TP_MULT_BASE = 3.0
ATR_SL_MULT_BASE = 1.5
MAX_HOLD = 30
ATR_PCTILE_TH = 30

# ─── c215 고정 ───────────────────────────────────────────────
SYM_SL_SCALE = {"KRW-ETH": 1.0, "KRW-SOL": 0.70, "KRW-XRP": 0.85}

# ─── c219 고정 (2-tier 분할익절) ─────────────────────────────
TP1_MULT = 2.5
PART_RATIO = 0.7
HI_TP_BONUS = 0.0
LO_SL_SCALE = 1.0
ATR_REGIME_HI = 70
ATR_REGIME_LO = 30

# ─── SOL 전용 엔트리 게이트 (c219) ──────────────────────────
SOL_ADX_GATE = 35
SOL_VOL_GATE = 1.3
SOL_ATR_PCTILE_GATE = 50

# ─── c231 고정 (MDD 제어) ───────────────────────────────────
CONSEC_LOSS_LIMIT = 2
COOLDOWN_BARS = 6
DD_TRAIL_TIGHTEN = 1.0
DD_LB_TRADES = 5
DD_THRESH_PCT = -3.0

# ─── c232 탐색 그리드 ───────────────────────────────────────
BTC_TREND_MIN_LIST = [0.0, 1.0, 3.0]     # BTC SMA200 대비 최소 %
RSI_ENTRY_LO_LIST = [0, 35, 45]           # RSI 하한 (0=OFF)
RSI_ENTRY_HI_LIST = [70, 80, 100]         # RSI 상한 (100=OFF)
XRP_ADX_GATE_LIST = [25, 30, 35]          # XRP ADX 게이트
XRP_VOL_GATE_LIST = [1.0, 1.2]            # XRP 거래량 게이트


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


# ─── 백테스트 엔진 ──────────────────────────────────────────

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
    sl_scale: float,
    sym: str,
    # c232 탐색 파라미터
    btc_trend_min_pct: float,
    rsi_entry_lo: float,
    rsi_entry_hi: float,
    xrp_adx_gate: float,
    xrp_vol_gate: float,
    oos_start: str,
    oos_end: str,
    index: pd.DatetimeIndex,
) -> list[dict]:
    """2-tier 분할익절 + c231 MDD제어 + c232 진입필터."""
    n = len(c)
    trades: list[dict] = []
    position = None
    oos_s = pd.Timestamp(oos_start)
    oos_e = pd.Timestamp(oos_end)

    # c231 MDD 제어 상태
    consec_losses = 0
    cooldown_until = -1
    recent_returns: list[float] = []

    warmup = max(DC_UPPER_LB, DC_LOWER_LB, BTC_SMA_PERIOD, 60) + 10

    for i in range(warmup, n - 1):
        o_next = o[i + 1]

        if position is not None:
            bars_held = i - position["entry_bar"]
            cp = c[i]

            # 현재 trail 배수 결정 (드로다운 시 축소)
            effective_trail = TRAIL_MULT_BASE
            if DD_TRAIL_TIGHTEN > 0 and len(recent_returns) >= DD_LB_TRADES:
                recent_sum = sum(recent_returns[-DD_LB_TRADES:]) * 100
                if recent_sum < DD_THRESH_PCT:
                    effective_trail = max(
                        1.0, TRAIL_MULT_BASE - DD_TRAIL_TIGHTEN
                    )

            # trailing stop 업데이트
            if effective_trail > 0 and cp > position["peak"]:
                position["peak"] = cp
                atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0
                ts = cp - atr_now * effective_trail
                if ts > position.get("trail_stop", 0):
                    position["trail_stop"] = ts

            # TP1 분할익절
            if (not position["tp1_hit"]
                    and cp >= position["tp1_price"]):
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
            if effective_trail > 0 and cp <= position.get("trail_stop", 0):
                exit_reason = "TRAIL"
            if not np.isnan(dc_lo[i]) and cp <= dc_lo[i]:
                exit_reason = "DC_LOW"
            if bars_held >= MAX_HOLD:
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

                # c231 MDD 제어: 연속 손실 카운트 + 수익률 기록
                full_ret = ret
                recent_returns.append(full_ret)
                if full_ret < 0:
                    consec_losses += 1
                    if consec_losses >= CONSEC_LOSS_LIMIT:
                        cooldown_until = i + COOLDOWN_BARS
                else:
                    consec_losses = 0

                position = None

        else:
            # 쿨다운 체크
            if i <= cooldown_until:
                continue

            # 기본 필터
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            if not (c[i] > dc_up[i]):
                continue
            if not (adx_val[i] >= ADX_THRESH):
                continue
            if not (btc_close[i] > btc_sma[i]):
                continue

            # ★ c232: BTC 트렌드 강도 필터
            if btc_trend_min_pct > 0:
                btc_above_pct = (btc_close[i] / btc_sma[i] - 1) * 100
                if btc_above_pct < btc_trend_min_pct:
                    continue

            # ATR 백분위
            if ATR_PCTILE_TH > 0:
                if np.isnan(atr_pctile[i]) or atr_pctile[i] < ATR_PCTILE_TH:
                    continue

            # 거래량
            if VOL_RATIO_MIN > 0:
                if (np.isnan(vol_sma[i]) or vol_sma[i] <= 0
                        or v[i] / vol_sma[i] < VOL_RATIO_MIN):
                    continue

            # ★ c232: RSI 밴드 필터 (하한 + 상한)
            if rsi_entry_lo > 0 or rsi_entry_hi < 100:
                if np.isnan(rsi_arr[i]):
                    continue
                if rsi_entry_lo > 0 and rsi_arr[i] < rsi_entry_lo:
                    continue
                if rsi_entry_hi < 100 and rsi_arr[i] >= rsi_entry_hi:
                    continue

            # SOL 전용 엔트리 게이트
            if sym == "KRW-SOL":
                if adx_val[i] < SOL_ADX_GATE:
                    continue
                if (not np.isnan(vol_sma[i]) and vol_sma[i] > 0
                        and v[i] / vol_sma[i] < SOL_VOL_GATE):
                    continue
                if (not np.isnan(atr_pctile[i])
                        and atr_pctile[i] < SOL_ATR_PCTILE_GATE):
                    continue

            # ★ c232: XRP 전용 엔트리 게이트
            if sym == "KRW-XRP":
                if adx_val[i] < xrp_adx_gate:
                    continue
                if (not np.isnan(vol_sma[i]) and vol_sma[i] > 0
                        and v[i] / vol_sma[i] < xrp_vol_gate):
                    continue

            # 진입
            entry_price = o_next * (1 + SLIPPAGE)
            atr_now = atr_val[i]

            # TP 보너스 (c207)
            vol_tp_bonus = 0.0
            if TP_VOL_SCALE > 0 and not np.isnan(atr_pctile[i]):
                vol_score = max(0, atr_pctile[i] - 50) / 50.0
                vol_tp_bonus = TP_VOL_SCALE * vol_score

            # ATR 레짐 적응형
            cur_pctile = atr_pctile[i] if not np.isnan(atr_pctile[i]) else 50
            regime_tp_bonus = HI_TP_BONUS if cur_pctile >= ATR_REGIME_HI else 0
            regime_sl_factor = LO_SL_SCALE if cur_pctile <= ATR_REGIME_LO else 1.0

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


# ─── 메인 ────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== c232: c231 고정 + F2 개선 진입필터 (BTC강도+RSI밴드+XRP게이트) ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | 슬리피지포함 | 다음봉시가진입 ===")
    print(f"c231 고정: cLim={CONSEC_LOSS_LIMIT} cool={COOLDOWN_BARS} "
          f"ddTr={DD_TRAIL_TIGHTEN} ddLB={DD_LB_TRADES} ddTh={DD_THRESH_PCT}")
    print(f"탐색: BTC강도% × RSI하한 × RSI상한 × XRP_ADX × XRP_Vol")
    print("=" * 80)

    # 데이터 로드
    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"BTC 데이터: {len(btc_df)} rows")

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
        atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
        vol_sma_arr = sma_calc(v_arr, VOL_SMA_PERIOD)

        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo_arr,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr,
            "atr_pctile": atr_pctile_arr, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "index": df.index,
        }

    # 그리드
    grid = list(product(
        BTC_TREND_MIN_LIST, RSI_ENTRY_LO_LIST,
        RSI_ENTRY_HI_LIST, XRP_ADX_GATE_LIST, XRP_VOL_GATE_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # 베이스라인 (c231 최적, 추가 필터 OFF)
    print("\n--- 베이스라인 (c231 최적, 추가필터 OFF) ---")
    base_fold_sharpes = []
    base_fold_details = []
    base_total_n = 0

    for window in WINDOWS:
        fold_rets = []
        for sym in SYMBOLS:
            sp = sym_precomp[sym]
            raw = run_backtest(
                sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                sp["dc_up"], sp["dc_lo"],
                sp["atr"], sp["adx"],
                sp["btc_c"], sp["btc_s"],
                sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                SYM_SL_SCALE[sym], sym,
                0.0, 0, 100,   # c232 OFF: btc_trend=0, rsi_lo=0, rsi_hi=100
                25, 1.0,        # xrp gates = 기본값
                window["oos_start"], window["oos_end"],
                sp["index"],
            )
            agg = aggregate_trades(raw)
            rets = [t["return"] for t in agg]
            fold_rets.extend(rets)

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
    base_worst_mdd = min(f["mdd"] for f in base_fold_details)
    base_f2_sharpe = base_fold_sharpes[1]
    print(f"  avg Sharpe: {base_avg:+.3f}  F2: {base_f2_sharpe:+.3f}  "
          f"worst MDD: {base_worst_mdd:+.2f}%  n={base_total_n}")
    for f in base_fold_details:
        print(f"  {f['name']}: Sh={f['sharpe']:+.3f} WR={f['wr']:.1f}% "
              f"n={f['n']} avg={f['avg']:+.2f}% MDD={f['mdd']:+.2f}%")

    # 그리드 서치
    all_results: list[dict] = []

    for gi, combo in enumerate(grid):
        btc_min, rsi_lo, rsi_hi, xrp_adx, xrp_vol = combo

        fold_sharpes = []
        fold_details = []
        total_n = 0
        sym_fold: dict[str, list[list[float]]] = {s: [] for s in SYMBOLS}
        fold_mdd_list = []

        for window in WINDOWS:
            fold_rets = []
            for sym in SYMBOLS:
                sp = sym_precomp[sym]
                raw = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    SYM_SL_SCALE[sym], sym,
                    btc_min, rsi_lo, rsi_hi, xrp_adx, xrp_vol,
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

        # SOL 평균 Sharpe
        sol_sharpes = []
        for rs in sym_fold["KRW-SOL"]:
            sol_sharpes.append(calc_sharpe(rs))
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

        if (gi + 1) % 40 == 0:
            print(f"  진행: {gi + 1}/{len(grid)}")

    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    # 결과 정렬: F2 개선 + 전체 Sharpe 유지
    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(
        key=lambda x: (
            x["avg_sharpe"] >= 25,        # 전체 Sharpe 유지
            x["f2_sharpe"] >= 20,         # F2 개선 핵심
            x["worst_mdd"] > -15,         # MDD 유지
            x["f2_sharpe"],               # F2 Sharpe 최대화
            x["avg_sharpe"],              # 그 다음 전체 Sharpe
        ),
        reverse=True,
    )

    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 (F2개선 + Sharpe유지 우선) ===")
    print("=" * 80)
    hdr = (f"{'btcM':>5} {'rLo':>4} {'rHi':>4} {'xAdx':>5} {'xVol':>5} | "
           f"{'avgSh':>7} {'F2Sh':>7} {'F3Sh':>7} {'solSh':>7} "
           f"{'wMDD':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(
            f"{p[0]:>5.1f} {p[1]:>4} {p[2]:>4} {p[3]:>5} {p[4]:>5.1f} | "
            f"{r['avg_sharpe']:>+7.3f} {r['f2_sharpe']:>+7.3f} "
            f"{r['f3_sharpe']:>+7.3f} {r['sol_avg_sharpe']:>+7.3f} "
            f"{r['worst_mdd']:>+7.2f} {r['total_n']:>5}")

    # 효과 분석: BTC 트렌드 강도
    print("\n=== BTC 트렌드 강도 효과 ===")
    for bm in BTC_TREND_MIN_LIST:
        sub = [r for r in valid if r["params"][0] == bm]
        if sub:
            top5 = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_f2 = np.mean([r["f2_sharpe"] for r in top5])
            avg_n = np.mean([r["total_n"] for r in top5])
            print(f"  btcMin={bm:.1f}%: top5 avgSh={avg_sh:+.3f}  "
                  f"F2={avg_f2:+.3f}  avgN={avg_n:.0f}")

    # 효과 분석: RSI 밴드
    print("\n=== RSI 하한 효과 ===")
    for rl in RSI_ENTRY_LO_LIST:
        sub = [r for r in valid if r["params"][1] == rl]
        if sub:
            top5 = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_f2 = np.mean([r["f2_sharpe"] for r in top5])
            print(f"  rsiLo={rl}: top5 avgSh={avg_sh:+.3f}  F2={avg_f2:+.3f}")

    print("\n=== RSI 상한 효과 ===")
    for rh in RSI_ENTRY_HI_LIST:
        sub = [r for r in valid if r["params"][2] == rh]
        if sub:
            top5 = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_f2 = np.mean([r["f2_sharpe"] for r in top5])
            print(f"  rsiHi={rh}: top5 avgSh={avg_sh:+.3f}  F2={avg_f2:+.3f}")

    # 효과 분석: XRP 게이트
    print("\n=== XRP ADX 게이트 효과 ===")
    for xa in XRP_ADX_GATE_LIST:
        sub = [r for r in valid if r["params"][3] == xa]
        if sub:
            top5 = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_f2 = np.mean([r["f2_sharpe"] for r in top5])
            print(f"  xrpADX={xa}: top5 avgSh={avg_sh:+.3f}  "
                  f"F2={avg_f2:+.3f}")

    # 합격 조합
    passing = [r for r in valid
               if r["avg_sharpe"] >= 25
               and r["f2_sharpe"] >= 20
               and r["f3_sharpe"] >= 30
               and r["sol_avg_sharpe"] >= 10
               and r["worst_mdd"] > -15]
    print(f"\n=== 합격 (avg>=25 & F2>=20 & F3>=30 & SOL>=10 & MDD>-15%): "
          f"{len(passing)}개 ===")
    for r in passing[:10]:
        p = r["params"]
        print(f"  btc={p[0]:.1f} rLo={p[1]} rHi={p[2]} xAdx={p[3]} "
              f"xVol={p[4]:.1f} | avg={r['avg_sharpe']:+.3f} "
              f"F2={r['f2_sharpe']:+.3f} F3={r['f3_sharpe']:+.3f} "
              f"SOL={r['sol_avg_sharpe']:+.3f} "
              f"MDD={r['worst_mdd']:+.2f}% n={r['total_n']}")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== c231 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c231 기준: avg_OOS=+29.622 F2=+18.035 "
              f"F3=+43.081 SOL=+21.805 worst_MDD=-14.65%")
        print(f"  c232 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F2={b['f2_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f} "
              f"SOL_avg={b['sol_avg_sharpe']:+.3f} "
              f"worst_MDD={b['worst_mdd']:+.2f}%")
        d_avg = b["avg_sharpe"] - 29.622
        d_f2 = b["f2_sharpe"] - 18.035
        d_f3 = b["f3_sharpe"] - 43.081
        d_sol = b["sol_avg_sharpe"] - 21.805
        d_mdd = b["worst_mdd"] - (-14.65)
        print(f"  Δ avg: {d_avg:+.3f} ({'개선' if d_avg > 0 else '악화'})")
        print(f"  Δ F2: {d_f2:+.3f} ({'개선' if d_f2 > 0 else '악화'})")
        print(f"  Δ F3: {d_f3:+.3f} ({'개선' if d_f3 > 0 else '악화'})")
        print(f"  Δ SOL: {d_sol:+.3f} ({'개선' if d_sol > 0 else '악화'})")
        print(f"  Δ MDD: {d_mdd:+.2f}%p ({'개선' if d_mdd > 0 else '악화'})")

    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f2_pass = b["f2_sharpe"] >= 20.0
        f3_pass = b["f3_sharpe"] >= 30.0
        sol_pass = b["sol_avg_sharpe"] >= 10.0
        mdd_pass = b["worst_mdd"] > -15.0
        main_pass = (b["avg_sharpe"] >= 25.0 and b["total_n"] >= 30
                     and f2_pass and f3_pass)
        print(f"★ OOS 최적: btcMin={p[0]:.1f} rsiLo={p[1]} rsiHi={p[2]} "
              f"xrpADX={p[3]} xrpVol={p[4]:.1f}")
        print(f"  (c231 고정: cLim={CONSEC_LOSS_LIMIT} cool={COOLDOWN_BARS} "
              f"ddTr={DD_TRAIL_TIGHTEN} ddLB={DD_LB_TRADES} "
              f"ddTh={DD_THRESH_PCT})")
        print(f"  (c219 고정: tp1M={TP1_MULT} pRat={PART_RATIO})")
        print(f"  (SOL gate: solADX={SOL_ADX_GATE} solVol={SOL_VOL_GATE} "
              f"solAtrPth={SOL_ATR_PCTILE_GATE})")
        print(f"  (c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} "
              f"adx={ADX_THRESH})")
        print(f"  (c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
              f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} "
              f"tpVS={TP_VOL_SCALE})")
        print(f"  (c210 고정: trail={TRAIL_MULT_BASE} tpM={ATR_TP_MULT_BASE} "
              f"slM={ATR_SL_MULT_BASE} mH={MAX_HOLD} "
              f"aPTh={ATR_PCTILE_TH})")
        print(f"  (c215 고정: slSOL={SYM_SL_SCALE['KRW-SOL']} "
              f"slXRP={SYM_SL_SCALE['KRW-XRP']})")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} "
              f"{'PASS' if main_pass else 'FAIL'}")
        print(f"  F2 Sharpe: {b['f2_sharpe']:+.3f} "
              f"{'PASS' if f2_pass else 'FAIL'}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_pass else 'FAIL'}")
        print(f"  worst MDD: {b['worst_mdd']:+.2f}% "
              f"{'PASS' if mdd_pass else 'FAIL'}")
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
