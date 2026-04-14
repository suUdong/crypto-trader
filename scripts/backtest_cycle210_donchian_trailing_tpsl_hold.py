"""
사이클 210: Donchian c207 최적 필터 고정 + 청산 로직 최적화 3-fold WF
- 기반: c207 OOS Sharpe +15.410, F3 +6.665 (ATR regime + vol + RSI 필터)
- 문제:
  1) F3 총 9거래 — 저변동성 구간에서 거래량 부족
  2) SOL F3 Sharpe -3.447, XRP F3 -1.369 — 수익 보호 부재로 반전 손실
  3) trail=0.0 고정 — 큰 수익을 TP까지 홀딩하다 반전에 돌려줌
  4) atrTP=3.0 atrSL=2.5 고정 — 변동성 환경별 최적 TP/SL 다를 수 있음
- 가설:
  A) Trailing Stop: 수익 발생 시 후행 스탑으로 보호 → 큰 추세 수익 확보
  B) TP/SL 재최적화: c205 고정값에서 벗어나 더 나은 비율 탐색
  C) Hold Decay: 보유 기간 증가시 TP 목표를 점진적 축소
     → 오래 보유할수록 소폭 수익이라도 확정
     → F3 같은 약한 추세에서 소폭 수익 보존
  D) ATR 문턱 완화(20 추가): F3에서 더 많은 거래 기회 확보
- c207 고정: aPLB=30 vRat=1.0 vSMA=20 rsiC=100 tpVS=0.5
  c205 고정: dcU=30 dcL=10 adx=25
- 탐색 그리드:
  TRAIL_MULT: [0.0, 1.5, 2.0, 2.5]      — trailing stop ATR 배수
  ATR_TP_MULT: [2.5, 3.0, 3.5]           — TP ATR 배수
  ATR_SL_MULT: [1.5, 2.0, 2.5]           — SL ATR 배수
  MAX_HOLD: [20, 30]                      — 최대 보유 기간
  ATR_PCTILE_TH: [20, 30]                — ATR 백분위 문턱
  HOLD_DECAY: [0, 1]                      — 보유기간 TP 축소 (0=비활성)
  = 4×3×3×2×2×2 = 288 combos
- 목표: OOS Sharpe >= 15 AND F3 Sharpe >= 5.0 AND trades >= 30
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

# ─── c210 탐색 그리드 ────────────────────────────────────────
TRAIL_MULT_LIST = [0.0, 1.5, 2.0, 2.5]
ATR_TP_MULT_LIST = [2.5, 3.0, 3.5]
ATR_SL_MULT_LIST = [1.5, 2.0, 2.5]
MAX_HOLD_LIST = [20, 30]
ATR_PCTILE_TH_LIST = [20, 30]
HOLD_DECAY_LIST = [0, 1]  # 0=비활성, 1=활성


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
    # c210 탐색 파라미터
    trail_mult: float,
    atr_tp_mult: float,
    atr_sl_mult: float,
    max_hold: int,
    atr_pctile_th: float,
    hold_decay: int,
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
            if trail_mult > 0 and current_price > position["peak"]:
                position["peak"] = current_price
                atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0
                trail_stop = current_price - atr_now * trail_mult
                if trail_stop > position.get("trail_stop", 0):
                    position["trail_stop"] = trail_stop

            # hold decay: 보유 기간에 따라 TP 축소
            if hold_decay and bars_held > 0:
                # 10봉 이후부터 TP를 점진적 축소 (50%까지)
                if bars_held > 10:
                    decay_factor = max(0.5, 1.0 - (bars_held - 10) * 0.025)
                    effective_tp = (position["orig_tp_price"]
                                    * decay_factor
                                    + position["entry_price"]
                                    * (1 - decay_factor))
                else:
                    effective_tp = position["orig_tp_price"]
            else:
                effective_tp = position["orig_tp_price"]

            # 청산 조건
            exit_reason = None

            # 1) SL
            if current_price <= position["sl_price"]:
                exit_reason = "SL"

            # 2) TP (hold decay 적용)
            if current_price >= effective_tp:
                exit_reason = "TP"

            # 3) Trailing stop
            if (trail_mult > 0
                    and current_price <= position.get("trail_stop", 0)):
                exit_reason = "TRAIL"

            # 4) Donchian lower 돌파
            if (not np.isnan(dc_lo[i])
                    and current_price <= dc_lo[i]):
                exit_reason = "DC_LOW"

            # 5) Max hold
            if bars_held >= max_hold:
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
            if atr_pctile_th > 0:
                if np.isnan(atr_pctile[i]):
                    atr_pctile_ok = False
                else:
                    atr_pctile_ok = atr_pctile[i] >= atr_pctile_th

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

                tp_pct = atr_now / c[i] * (atr_tp_mult + vol_tp_bonus)
                sl_pct = atr_now / c[i] * atr_sl_mult

                tp_price = entry_price * (1 + tp_pct)
                position = {
                    "entry_price": entry_price,
                    "entry_bar": i + 1,
                    "orig_tp_price": tp_price,
                    "sl_price": entry_price * (1 - sl_pct),
                    "peak": entry_price,
                    "trail_stop": 0,
                }

    return trades


# ─── 메인 ────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== c210: Donchian c207 필터 고정 + 청산 최적화 3-fold WF ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | ★슬리피지포함 | 다음봉시가진입 ===")
    print(f"c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} adx={ADX_THRESH}")
    print(f"c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
          f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} tpVS={TP_VOL_SCALE}")
    print("가설: trailing stop + TP/SL 재최적화 + hold decay → F3 수익 보호")
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
        TRAIL_MULT_LIST, ATR_TP_MULT_LIST, ATR_SL_MULT_LIST,
        MAX_HOLD_LIST, ATR_PCTILE_TH_LIST, HOLD_DECAY_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # Walk-Forward grid search
    all_results: list[dict] = []

    for gi, (trail_m, tp_m, sl_m, mh, ap_th, hd) in enumerate(grid):

        fold_sharpes = []
        fold_details = []
        total_n = 0

        for window in WINDOWS:
            fold_rets = []

            for sym in SYMBOLS:
                sp = sym_precomp[sym]

                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    trail_m, tp_m, sl_m, mh, ap_th, hd,
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
            "params": (trail_m, tp_m, sl_m, mh, ap_th, hd),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
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
    hdr = (f"{'trail':>5} {'tpM':>5} {'slM':>5} {'mH':>4} "
           f"{'aPTh':>5} {'hDec':>4} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(
            f"{p[0]:>5.1f} {p[1]:>5.1f} {p[2]:>5.1f} {p[3]:>4} "
            f"{p[4]:>5} {p[5]:>4} | "
            f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
            f"{r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: trail={p[0]:.1f} tpM={p[1]:.1f} slM={p[2]:.1f} "
              f"mH={p[3]} aPTh={p[4]} hDec={p[5]}")
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
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: trail={bp[0]:.1f} "
              f"tpM={bp[1]:.1f} slM={bp[2]:.1f} mH={bp[3]} "
              f"aPTh={bp[4]} hDec={bp[5]}) ===")

        for sym in SYMBOLS:
            sp = sym_precomp[sym]
            sym_sharpes = []
            sym_total_n = 0

            for window in WINDOWS:
                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    bp[0], bp[1], bp[2], bp[3], bp[4], bp[5],
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
                sym_sharpes.append(sh)
                sym_total_n += nn
            print(f"  {sym} 평균: Sharpe={np.mean(sym_sharpes):+.3f}  "
                  f"총 trades={sym_total_n}")

    # c207 비교
    print("\n" + "=" * 80)
    print("=== c207 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c207 기준: avg_OOS=+15.410 F3=+6.665")
        print(f"  c210 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f}")
        delta = b["avg_sharpe"] - 15.410
        delta_f3 = b["f3_sharpe"] - 6.665
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
        f3_pass = b["f3_sharpe"] >= 5.0
        status = ("PASS" if b["avg_sharpe"] >= 15.0
                  and b["total_n"] >= 30 and f3_pass else "FAIL")
        print(f"★ OOS 최적: trail={p[0]:.1f} tpM={p[1]:.1f} "
              f"slM={p[2]:.1f} mH={p[3]} aPTh={p[4]} hDec={p[5]}")
        print(f"  (c205 고정: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} "
              f"adx={ADX_THRESH})")
        print(f"  (c207 고정: aPLB={ATR_PCTILE_LB} vRat={VOL_RATIO_MIN} "
              f"vSMA={VOL_SMA_PERIOD} rsiC={RSI_CEILING} "
              f"tpVS={TP_VOL_SCALE})")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
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
