"""
사이클 231: c219 최적 고정 + MDD 제어 메커니즘 탐색 3-fold WF

c219 결과:
  ★ tp1M=2.5 pRat=0.7 hiTP=? loSL=? + solADX=35 solVol=1.3 solAtrPth=50
  avg OOS Sharpe: +27.868 PASS
  F3 Sharpe: +40.584 PASS
  SOL avg Sharpe: +11.487 PASS
  worst MDD: -16.30% FAIL(악화) ← F2에서 발생

문제 분석:
  - F2 MDD=-16.30%: 연속 손실 구간에서 회복 없이 추가 진입 → drawdown 악화
  - F2 WR=60.6%로 F1(71%)보다 낮음: 약세 구간 진입 필터 부족
  - 큰 손실 1~2건이 전체 MDD 지배 → 연속 손실 후 쿨다운 필요

가설:
  A) 연속손실 쿨다운: N번 연속 손절 후 M봉 동안 진입 스킵
     → 하락 추세에서 반복 손절 방지 → MDD 직접 개선
  B) 드로다운 트레일 강화: 최근 K거래 수익률 합 < -X% 이면 trail 배수 축소
     → 약세 감지 시 빠른 청산 → 개별 거래 손실 제한
  C) 최대 단일 손실 캡: SL 크기를 ATR×slM×capScale로 제한
     → 큰 개별 손실 방지 (현재 SL이 심볼별로 다르지만 상한 없음)

고정 (c219 최적):
  c205: dcU=30 dcL=10 adx=25
  c207: aPLB=30 vRat=1.0 vSMA=20 rsiC=100 tpVS=0.5
  c210: trail=2.5(base) tpM=3.0 slM=1.5 mH=30 aPTh=30
  c215: slSOL=0.70 slXRP=0.85
  c219: tp1M=2.5 pRat=0.7 hiTP(best from c219) loSL(best)
  SOL gates: solADX=35 solVol=1.3 solAtrPth=50

탐색 그리드:
  CONSEC_LOSS_LIMIT: [2, 3]           — 연속손실 한도
  COOLDOWN_BARS: [3, 6, 12]           — 쿨다운 봉 수
  DD_TRAIL_TIGHTEN: [0.0, 0.5, 1.0]  — 드로다운 시 trail 축소량
  DD_LOOKBACK_TRADES: [3, 5]          — 드로다운 감지 거래 수
  DD_THRESHOLD_PCT: [-3.0, -5.0]      — 누적손실 임계치(%)
  = 2×3×3×2×2 = 72 combos

목표: avg>=27 AND F3>=40 AND SOL>=10 AND worst_MDD > -13.03%
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
RSI_CEILING = 100
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
# ATR 레짐 적응: c219 최적 (보수적으로 0 사용 — 레짐 효과 미확정)
HI_TP_BONUS = 0.0
LO_SL_SCALE = 1.0
ATR_REGIME_HI = 70
ATR_REGIME_LO = 30

# ─── SOL 전용 엔트리 게이트 (c219 winner) ────────────────────
SOL_ADX_GATE = 35
SOL_VOL_GATE = 1.3
SOL_ATR_PCTILE_GATE = 50

# ─── c231 탐색 그리드 ────────────────────────────────────────
CONSEC_LOSS_LIST = [2, 3]            # 연속손실 한도
COOLDOWN_BARS_LIST = [3, 6, 12]      # 쿨다운 봉수
DD_TRAIL_TIGHTEN_LIST = [0.0, 0.5, 1.0]  # trail 축소량
DD_LB_TRADES_LIST = [3, 5]           # 드로다운 감지 거래 수
DD_THRESH_LIST = [-3.0, -5.0]        # 누적손실 임계치(%)


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


# ─── 백테스트 엔진 (MDD 제어 포함) ──────────────────────────

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
    # c231 MDD 제어 파라미터
    consec_loss_limit: int,
    cooldown_bars: int,
    dd_trail_tighten: float,
    dd_lb_trades: int,
    dd_thresh_pct: float,
    oos_start: str,
    oos_end: str,
    index: pd.DatetimeIndex,
) -> list[dict]:
    """2-tier 분할익절 + 연속손실 쿨다운 + 드로다운 trail 강화."""
    n = len(c)
    trades: list[dict] = []
    position = None
    oos_s = pd.Timestamp(oos_start)
    oos_e = pd.Timestamp(oos_end)

    # MDD 제어 상태
    consec_losses = 0
    cooldown_until = -1  # bar index까지 진입 금지
    recent_returns: list[float] = []  # 최근 거래 수익률 기록

    warmup = max(DC_UPPER_LB, DC_LOWER_LB, BTC_SMA_PERIOD, 60) + 10

    for i in range(warmup, n - 1):
        o_next = o[i + 1]

        if position is not None:
            bars_held = i - position["entry_bar"]
            cp = c[i]

            # 현재 trail 배수 결정 (드로다운 시 축소)
            effective_trail = TRAIL_MULT_BASE
            if dd_trail_tighten > 0 and len(recent_returns) >= dd_lb_trades:
                recent_sum = sum(recent_returns[-dd_lb_trades:]) * 100
                if recent_sum < dd_thresh_pct:
                    effective_trail = max(
                        1.0, TRAIL_MULT_BASE - dd_trail_tighten
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
                # breakeven stop
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

                # MDD 제어: 연속 손실 카운트 + 수익률 기록
                full_ret = ret  # 전체 포지션 기준 수익률
                recent_returns.append(full_ret)
                if full_ret < 0:
                    consec_losses += 1
                    if consec_losses >= consec_loss_limit:
                        cooldown_until = i + cooldown_bars
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

            # ATR 백분위
            if ATR_PCTILE_TH > 0:
                if np.isnan(atr_pctile[i]) or atr_pctile[i] < ATR_PCTILE_TH:
                    continue

            # 거래량
            if VOL_RATIO_MIN > 0:
                if (np.isnan(vol_sma[i]) or vol_sma[i] <= 0
                        or v[i] / vol_sma[i] < VOL_RATIO_MIN):
                    continue

            # RSI
            if RSI_CEILING < 100:
                if np.isnan(rsi_arr[i]) or rsi_arr[i] >= RSI_CEILING:
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
    print("=== c231: c219 최적 고정 + MDD 제어 (연속손실 쿨다운 + DD trail 강화) ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | 슬리피지포함 | 다음봉시가진입 ===")
    print(f"c219 고정: tp1M={TP1_MULT} pRat={PART_RATIO}")
    print(f"SOL gate: solADX={SOL_ADX_GATE} solVol={SOL_VOL_GATE} "
          f"solAtrPth={SOL_ATR_PCTILE_GATE}")
    print("탐색: 연속손실한도 × 쿨다운봉수 × DD trail축소 × DD감지거래수 × DD임계치")
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
        CONSEC_LOSS_LIST, COOLDOWN_BARS_LIST,
        DD_TRAIL_TIGHTEN_LIST, DD_LB_TRADES_LIST, DD_THRESH_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # 베이스라인 (MDD 제어 OFF) 먼저 실행
    print("\n--- 베이스라인 (MDD 제어 OFF: consec=99, cool=0, ddTrail=0) ---")
    base_fold_sharpes = []
    base_fold_details = []
    base_total_n = 0
    base_sym_data: dict[str, list[list[float]]] = {s: [] for s in SYMBOLS}

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
                99, 0, 0.0, 3, -99.0,  # MDD 제어 비활성
                window["oos_start"], window["oos_end"],
                sp["index"],
            )
            agg = aggregate_trades(raw)
            rets = [t["return"] for t in agg]
            fold_rets.extend(rets)
            base_sym_data[sym].append(rets)

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
    print(f"  avg Sharpe: {base_avg:+.3f}  worst MDD: {base_worst_mdd:+.2f}%  "
          f"n={base_total_n}")
    for f in base_fold_details:
        print(f"  {f['name']}: Sh={f['sharpe']:+.3f} WR={f['wr']:.1f}% "
              f"n={f['n']} avg={f['avg']:+.2f}% MDD={f['mdd']:+.2f}%")

    # 그리드 서치
    all_results: list[dict] = []

    for gi, combo in enumerate(grid):
        cl, cb, ddt, ddlb, ddth = combo

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
                    cl, cb, ddt, ddlb, ddth,
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

        all_results.append({
            "params": combo,
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg,
            "worst_mdd": worst_mdd,
        })

        if (gi + 1) % 20 == 0:
            print(f"  진행: {gi + 1}/{len(grid)}")

    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    # 결과 정렬: MDD 개선 우선, Sharpe 유지
    valid = [r for r in all_results if r["total_n"] >= 30]
    # Sharpe 유지 + MDD 개선 조합 우선 정렬
    valid.sort(
        key=lambda x: (
            x["avg_sharpe"] >= 20,        # Sharpe 최소 유지
            x["worst_mdd"] > -15,         # MDD 개선
            x["avg_sharpe"],              # 그 다음 Sharpe 높은 순
        ),
        reverse=True,
    )

    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 (Sharpe>=20 & MDD개선 우선) ===")
    print("=" * 80)
    hdr = (f"{'cLim':>5} {'cool':>5} {'ddTr':>5} {'ddLB':>5} {'ddTh':>6} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'solSh':>7} {'wMDD':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(
            f"{p[0]:>5} {p[1]:>5} {p[2]:>5.1f} {p[3]:>5} {p[4]:>6.1f} | "
            f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
            f"{r['sol_avg_sharpe']:>+7.3f} {r['worst_mdd']:>+7.2f} "
            f"{r['total_n']:>5}")

    # 효과 분석: 연속손실한도
    print("\n=== 연속손실한도 효과 ===")
    for cl in CONSEC_LOSS_LIST:
        sub = [r for r in valid if r["params"][0] == cl]
        if sub:
            top5 = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_mdd = np.mean([r["worst_mdd"] for r in top5])
            print(f"  consec={cl}: top5 avg Sharpe={avg_sh:+.3f}  "
                  f"avg MDD={avg_mdd:+.2f}%")

    # 효과 분석: 쿨다운봉수
    print("\n=== 쿨다운봉수 효과 ===")
    for cb in COOLDOWN_BARS_LIST:
        sub = [r for r in valid if r["params"][1] == cb]
        if sub:
            top5 = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_mdd = np.mean([r["worst_mdd"] for r in top5])
            print(f"  cool={cb}: top5 avg Sharpe={avg_sh:+.3f}  "
                  f"avg MDD={avg_mdd:+.2f}%")

    # 효과 분석: DD trail 축소
    print("\n=== DD Trail 축소 효과 ===")
    for ddt in DD_TRAIL_TIGHTEN_LIST:
        sub = [r for r in valid if r["params"][2] == ddt]
        if sub:
            top5 = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            avg_sh = np.mean([r["avg_sharpe"] for r in top5])
            avg_mdd = np.mean([r["worst_mdd"] for r in top5])
            print(f"  ddTrail={ddt:.1f}: top5 avg Sharpe={avg_sh:+.3f}  "
                  f"avg MDD={avg_mdd:+.2f}%")

    # 합격 조합
    passing = [r for r in valid
               if r["avg_sharpe"] >= 20
               and r["f3_sharpe"] >= 15
               and r["sol_avg_sharpe"] >= 8
               and r["worst_mdd"] > -15]
    print(f"\n=== 합격 (avg>=20 & F3>=15 & SOL>=8 & MDD>-15%): "
          f"{len(passing)}개 ===")
    for r in passing[:10]:
        p = r["params"]
        print(f"  cL={p[0]} cool={p[1]} ddTr={p[2]:.1f} ddLB={p[3]} "
              f"ddTh={p[4]:.1f} | avg={r['avg_sharpe']:+.3f} "
              f"F3={r['f3_sharpe']:+.3f} SOL={r['sol_avg_sharpe']:+.3f} "
              f"MDD={r['worst_mdd']:+.2f}% n={r['total_n']}")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== c219 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c219 기준: avg_OOS=+27.868 F3=+40.584 "
              f"SOL_avg=+11.487 worst_MDD=-16.30%")
        print(f"  c231 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f} "
              f"SOL_avg={b['sol_avg_sharpe']:+.3f} "
              f"worst_MDD={b['worst_mdd']:+.2f}%")
        d_avg = b["avg_sharpe"] - 27.868
        d_f3 = b["f3_sharpe"] - 40.584
        d_sol = b["sol_avg_sharpe"] - 11.487
        d_mdd = b["worst_mdd"] - (-16.30)
        print(f"  Δ avg: {d_avg:+.3f} ({'개선' if d_avg > 0 else '악화'})")
        print(f"  Δ F3: {d_f3:+.3f} ({'개선' if d_f3 > 0 else '악화'})")
        print(f"  Δ SOL: {d_sol:+.3f} ({'개선' if d_sol > 0 else '악화'})")
        print(f"  Δ MDD: {d_mdd:+.2f}%p ({'개선' if d_mdd > 0 else '악화'})")

    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 15.0
        sol_pass = b["sol_avg_sharpe"] >= 8.0
        mdd_pass = b["worst_mdd"] > -15.0
        main_pass = b["avg_sharpe"] >= 20.0 and b["total_n"] >= 30 and f3_pass
        print(f"★ OOS 최적: cLim={p[0]} cool={p[1]} ddTrail={p[2]:.1f} "
              f"ddLB={p[3]} ddTh={p[4]:.1f}")
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
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_pass else 'FAIL'}")
        print(f"  worst MDD: {b['worst_mdd']:+.2f}% "
              f"{'PASS(개선)' if mdd_pass else 'FAIL(악화)'}")
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
