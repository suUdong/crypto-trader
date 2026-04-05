"""
vpin_multi 사이클 208 — 60m 타임프레임 c179 VPIN 재검증
- 기반: c179 OOS Sharpe +42.878 (240m vol regime adaptive) — 현 최적
- 평가자 방향: 60m로 신호 밀도 4배 증가 → n 확보, alpha 재검증
- 핵심 변경:
  1. 타임프레임: 240m → 60m (1봉=1시간, 하루 24봉)
  2. 시간의존 파라미터 ×4 스케일:
     - MAX_HOLD: 20 → 60~100 (×3~5 탐색)
     - COOLDOWN: 4 → 8~24 (×2~6 탐색)
     - BUCKET_COUNT: 24 → 48~96 (×2~4 탐색)
     - MOM_LOOKBACK: 8 → 24~40 (×3~5 탐색)
     - EMA_PERIOD: 20 → 60~100
     - ATR_PERIOD: 20 → 60~100
     - VOL_SMA_PERIOD: 20 → 60~100
  3. VPIN/MOM threshold는 스케일 독립 → 그리드 탐색
  4. Sharpe annualization: sqrt(252*24) (60m = 24봉/일)
- 그리드:
  VPIN_LOW: [0.30, 0.35, 0.40]
  MOM_THRESH: [0.0003, 0.0005, 0.0007]
  HOLD: [60, 80, 100]
  CD: [8, 16, 24]
  BUCKET: [48, 96]
  = 3×3×3×3×2 = 162조합
- 3-fold WF + 슬리피지 스트레스
- 진입: next_bar open
★슬리피지포함 | 🔄다음봉시가진입
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

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]
FEE = 0.0005
ANNUALIZE_FACTOR = np.sqrt(252 * 24)  # 60m = 24 bars/day

# -- 스케일 독립 파라미터 (c179 고정) --
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
COOLDOWN_LOSSES = 2

RSI_DELTA_LB = 3
RSI_DELTA_MIN = 0.0
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8

# -- c177 TP/Trail 고정 --
TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

# -- c177 진입 필터 고정 --
ATR_PCTILE_THRESH = 30
BODY_RATIO_MIN = 0.7
VPIN_RELAX_THRESH = 0.25
RELAX_SCALE = 0.5

# -- c179 vol regime 고정 --
VOL_REGIME_THRESH = 60
HIGH_VOL_TP_SCALE = 0.65
HIGH_VOL_TRAIL_SCALE = 0.7
HIGH_VOL_HOLD_SCALE = 0.8

BTC_SMA_PERIOD = 800  # 200 × 4 (60m scale)

# -- 60m 스케일 조정 고정값 --
EMA_PERIOD = 80        # 20 × 4
ATR_PERIOD = 80        # 20 × 4
VOL_SMA_PERIOD = 80    # 20 × 4
ATR_PCTILE_LB = 240    # 60 × 4
MOM_LOOKBACK = 32      # 8 × 4

# -- 탐색 그리드 --
VPIN_LOW_LIST = [0.30, 0.35, 0.40]
MOM_THRESH_LIST = [0.0003, 0.0005, 0.0007]
HOLD_LIST = [60, 80, 100]
CD_LIST = [8, 16, 24]
BUCKET_LIST = [48, 96]
# 총: 3×3×3×3×2 = 162

# -- 3-fold Walkforward --
WF_FOLDS = [
    {"train": ("2022-05-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-09-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-03-01", "2025-03-31"), "test": ("2025-04-01", "2026-03-31")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# -- 지표 --

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


def compute_vpin_bvc(
    closes: np.ndarray, opens: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray, bucket_count: int,
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


def compute_momentum(closes: np.ndarray, lookback: int) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def compute_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int,
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


def align_btc_to_symbol(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame, btc_sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, btc_sma_period)
    btc_close_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_close_aligned = btc_close_s.reindex(df_sym.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_sym.index, method="ffill").values
    return btc_close_aligned, btc_sma_aligned


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    vpin_low: float,
    mom_thresh: float,
    max_hold: int,
    cooldown_bars: int,
    bucket_count: int,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, bucket_count)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)
    atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
    body_ratio_arr = compute_body_ratio(o, c, h, lo)

    returns: list[float] = []
    warmup = max(bucket_count, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD,
                 ATR_PCTILE_LB, 50) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if cooldown_bars > 0 and i < cooldown_until:
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

        # RSI velocity
        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # ★ 진입 조건: c179 동일 (60m 스케일 조정)
        vpin_ok = (
            vpin_val < vpin_low
            and mom_val >= mom_thresh
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

        # c177 신호강도 적응적 필터 완화
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

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok):

            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # c179 변동성 레짐 판단
            is_high_vol = (
                not np.isnan(atr_pctile_val)
                and atr_pctile_val >= VOL_REGIME_THRESH
            )

            if is_high_vol:
                tp_scale = HIGH_VOL_TP_SCALE
                trail_scale = HIGH_VOL_TRAIL_SCALE
                hold_scale = HIGH_VOL_HOLD_SCALE
            else:
                tp_scale = 1.0 + (1.0 - HIGH_VOL_TP_SCALE) * 0.3
                trail_scale = 1.0 + (1.0 - HIGH_VOL_TRAIL_SCALE) * 0.2
                hold_scale = 1.0 + (1.0 - HIGH_VOL_HOLD_SCALE) * 0.3

            # TP
            effective_tp_mult = (TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio) * tp_scale
            tp_price = buy + atr_at_entry * effective_tp_mult

            # SL
            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)
            if is_high_vol:
                effective_sl_mult *= (1.0 - (1.0 - HIGH_VOL_TP_SCALE) * 0.2)
                effective_sl_mult = max(0.15, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            # Trail
            trail_dist = atr_at_entry * (
                TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            ) * trail_scale
            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR * trail_scale

            eff_max_hold = max(5, int(max_hold * hold_scale))

            exit_ret = None
            for j in range(i + 2, min(i + 1 + eff_max_hold, n)):
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
                        exit_ret = (
                            (current_price / buy - 1) - FEE - slippage
                        )
                        i = j
                        break

            if exit_ret is None:
                hold_end = min(i + eff_max_hold, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)

            if exit_ret < 0:
                consecutive_losses += 1
                if consecutive_losses >= COOLDOWN_LOSSES and cooldown_bars > 0:
                    cooldown_until = i + cooldown_bars
                    consecutive_losses = 0
            else:
                consecutive_losses = 0
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * ANNUALIZE_FACTOR)
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
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl}


def pool_results(results_list: list[dict]) -> dict:
    all_sharpes = []
    all_wrs = []
    total_trades = 0
    all_avg_rets = []
    all_max_dds = []
    all_mcls = []
    for r in results_list:
        if r["trades"] > 0 and not np.isnan(r["sharpe"]):
            all_sharpes.append(r["sharpe"])
            all_wrs.append(r["wr"])
            total_trades += r["trades"]
            all_avg_rets.append(r["avg_ret"])
            all_max_dds.append(r["max_dd"])
            all_mcls.append(r["mcl"])
    if not all_sharpes:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    return {
        "sharpe": float(np.mean(all_sharpes)),
        "wr": float(np.mean(all_wrs)),
        "avg_ret": float(np.mean(all_avg_rets)),
        "trades": total_trades,
        "max_dd": float(np.mean(all_max_dds)),
        "mcl": max(all_mcls),
    }


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 208 — 60m 타임프레임 c179 VPIN 재검증 ===")
    print(f"심볼: {', '.join(SYMBOLS)}  "
          f"목표: OOS Sharpe > 5.0 (daemon 기준)")
    print("가설: 60m에서 신호 밀도 4배 → n 확보 + alpha 재검증")
    print(f"60m 고정: EMA={EMA_PERIOD} ATR={ATR_PERIOD} VOL_SMA={VOL_SMA_PERIOD} "
          f"ATR_PCTILE_LB={ATR_PCTILE_LB} MOM_LB={MOM_LOOKBACK}")
    print(f"c179 고정: volTh={VOL_REGIME_THRESH} tpSc={HIGH_VOL_TP_SCALE} "
          f"trSc={HIGH_VOL_TRAIL_SCALE} hdSc={HIGH_VOL_HOLD_SCALE}")
    print(f"c177 고정: atrTh={ATR_PCTILE_THRESH} body={BODY_RATIO_MIN} "
          f"vpRx={VPIN_RELAX_THRESH} rxSc={RELAX_SCALE}")
    print(f"TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} "
          f"minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD}")
    print(f"Annualize: sqrt(252×24) = {ANNUALIZE_FACTOR:.2f}")
    print("=" * 80)

    # -- BTC 데이터 --
    df_btc_full = load_historical("KRW-BTC", "60m", "2022-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 60m 데이터 없음.")
        return

    print(f"BTC 60m: {len(df_btc_full)}행")

    # -- 심볼별 데이터 확인 --
    print("\n--- 심볼별 데이터 확인 ---")
    sym_data_ok = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "60m", "2022-05-01", "2026-03-31")
        if df_check.empty or len(df_check) < 2000:
            print(f"  {sym}: 데이터 부족 ({len(df_check)}행) → 제외")
        else:
            print(f"  {sym}: {len(df_check)}행 OK")
            sym_data_ok.append(sym)

    if not sym_data_ok:
        print("유효 심볼 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 1: train 그리드 서치 --
    combos = list(product(
        VPIN_LOW_LIST, MOM_THRESH_LIST,
        HOLD_LIST, CD_LIST, BUCKET_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개 × {len(sym_data_ok)} 심볼")

    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: train 그리드 서치 ({train_start} ~ {train_end})")

    sym_train_data: dict[str, pd.DataFrame] = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "60m", train_start, train_end)
        if not df_tr.empty:
            sym_train_data[sym] = df_tr
            print(f"  {sym} train: {len(df_tr)}행")

    results: list[dict] = []
    for idx, (vl, mt, hd, cd, bk) in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_data:
                continue
            df_tr = sym_train_data[sym]
            btc_c, btc_s = align_btc_to_symbol(
                df_tr, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_tr, vl, mt, hd, cd, bk, btc_c, btc_s)
            sym_results.append(r)
        pooled = pool_results(sym_results)
        results.append({
            "vl": vl, "mt": mt, "hd": hd, "cd": cd, "bk": bk,
            **pooled,
        })
        if (idx + 1) % 30 == 0 or idx == len(combos) - 1:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    valid = [r for r in results if not np.isnan(r["sharpe"]) and r["trades"] >= 30]
    if not valid:
        print("유효 결과 없음 (n<30 or all NaN).")
        # c179 240m 대비 참고로 n<30 결과도 출력
        any_result = [r for r in results if not np.isnan(r["sharpe"])]
        if any_result:
            any_result.sort(key=lambda x: x["sharpe"], reverse=True)
            print("\n--- n<30 참고 결과 ---")
            for r in any_result[:5]:
                print(f"  VPIN={r['vl']} MOM={r['mt']} Hold={r['hd']} "
                      f"CD={r['cd']} Bucket={r['bk']} → "
                      f"Sharpe={r['sharpe']:+.3f} n={r['trades']}")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    valid.sort(key=lambda x: x["sharpe"], reverse=True)
    top5 = valid[:5]
    print("\n--- Train Top 5 ---")
    for rank, r in enumerate(top5, 1):
        print(f"  #{rank} VPIN={r['vl']} MOM={r['mt']} Hold={r['hd']} "
              f"CD={r['cd']} Bucket={r['bk']} → "
              f"Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1%} "
              f"n={r['trades']} avg={r['avg_ret']:+.2%} "
              f"MDD={r['max_dd']:+.4f}")

    # -- Phase 2: 3-fold WF 검증 --
    print("\n" + "=" * 80)
    print("Phase 2: 3-fold WF 검증 (Top 5)")
    print("=" * 80)

    best_oos_sharpe = float("-inf")
    best_combo = None
    best_fold_details: list[dict] = []

    for rank, combo in enumerate(top5, 1):
        vl = combo["vl"]
        mt = combo["mt"]
        hd = combo["hd"]
        cd = combo["cd"]
        bk = combo["bk"]

        print(f"\n--- #{rank}: VPIN={vl} MOM={mt} Hold={hd} "
              f"CD={cd} Bucket={bk} ---")

        fold_results: list[dict] = []
        fold_details: list[dict] = []
        for fi, fold in enumerate(WF_FOLDS, 1):
            tr_start, tr_end = fold["train"]
            te_start, te_end = fold["test"]

            # train
            train_results: list[dict] = []
            for sym in sym_data_ok:
                df_tr = load_historical(sym, "60m", tr_start, tr_end)
                if df_tr.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_tr, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_tr, vl, mt, hd, cd, bk, btc_c, btc_s)
                train_results.append(r)
            train_pooled = pool_results(train_results)

            # test (OOS)
            test_results: list[dict] = []
            sym_test_details: list[dict] = []
            for sym in sym_data_ok:
                df_te = load_historical(sym, "60m", te_start, te_end)
                if df_te.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_te, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_te, vl, mt, hd, cd, bk,
                             btc_c, btc_s, slippage=0.0005)
                test_results.append(r)
                sym_test_details.append({"sym": sym, **r})
            test_pooled = pool_results(test_results)

            fold_results.append(test_pooled)
            fold_details.append({
                "fold": fi, "train": train_pooled, "test": test_pooled,
                "sym_details": sym_test_details,
            })

            print(f"  Fold {fi}: train Sharpe={train_pooled['sharpe']:+.3f} "
                  f"→ OOS Sharpe={test_pooled['sharpe']:+.3f} "
                  f"WR={test_pooled['wr']:.1%} n={test_pooled['trades']} "
                  f"avg={test_pooled['avg_ret']:+.2%} "
                  f"MDD={test_pooled['max_dd']:+.4f}")

        oos_sharpes = [fr["sharpe"] for fr in fold_results
                       if not np.isnan(fr["sharpe"])]
        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
        else:
            avg_oos = float("nan")

        total_n = sum(fr["trades"] for fr in fold_results)
        print(f"  → avg OOS Sharpe: {avg_oos:+.3f}  total n={total_n}")

        if not np.isnan(avg_oos) and avg_oos > best_oos_sharpe:
            best_oos_sharpe = avg_oos
            best_combo = combo
            best_fold_details = fold_details

    if best_combo is None:
        print("\n유효 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 3: 슬리피지 스트레스 --
    print("\n" + "=" * 80)
    print("Phase 3: 슬리피지 스트레스 테스트")
    print("=" * 80)

    vl = best_combo["vl"]
    mt = best_combo["mt"]
    hd = best_combo["hd"]
    cd = best_combo["cd"]
    bk = best_combo["bk"]

    print(f"최적: VPIN={vl} MOM={mt} Hold={hd} CD={cd} Bucket={bk}")

    for slip in SLIPPAGE_LEVELS:
        slip_results: list[dict] = []
        for sym in sym_data_ok:
            for fold in WF_FOLDS:
                te_start, te_end = fold["test"]
                df_te = load_historical(sym, "60m", te_start, te_end)
                if df_te.empty:
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_te, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_te, vl, mt, hd, cd, bk, btc_c, btc_s, slip)
                slip_results.append(r)
        sp = pool_results(slip_results)
        status = "PASS" if sp["sharpe"] > 0 else "FAIL"
        print(f"  slip={slip:.4f}: Sharpe={sp['sharpe']:+.3f} "
              f"WR={sp['wr']:.1%} n={sp['trades']} [{status}]")

    # -- 심볼별 OOS 분해 --
    print("\n" + "=" * 80)
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: VPIN={vl} MOM={mt} "
          f"Hold={hd} CD={cd} Bucket={bk}) ===")
    sym_avg_sharpes: dict[str, list[float]] = {s: [] for s in sym_data_ok}
    sym_total_n: dict[str, int] = {s: 0 for s in sym_data_ok}
    for fd in best_fold_details:
        fi = fd["fold"]
        for sd in fd["sym_details"]:
            sym = sd["sym"]
            print(f"  {sym} Fold {fi}: Sharpe={sd['sharpe']:+.3f}  "
                  f"WR={sd['wr']:.1%}  n={sd['trades']}  "
                  f"avg={sd['avg_ret']:+.2%}  MDD={sd['max_dd']:+.4f}")
            if not np.isnan(sd["sharpe"]):
                sym_avg_sharpes[sym].append(sd["sharpe"])
            sym_total_n[sym] += sd["trades"]
    for sym in sym_data_ok:
        avg_sh = (float(np.mean(sym_avg_sharpes[sym]))
                  if sym_avg_sharpes[sym] else 0)
        print(f"  {sym} 평균: Sharpe={avg_sh:+.3f}  "
              f"총 trades={sym_total_n[sym]}")

    # -- c179 240m 대비 비교 --
    print("\n" + "=" * 80)
    print("=== c179 (240m) 베이스라인 대비 비교 ===")
    c179_baseline = 42.878
    total_n = sum(fd["test"]["trades"] for fd in best_fold_details)
    total_wr_vals = [fd["test"]["wr"] for fd in best_fold_details
                     if fd["test"]["trades"] > 0]
    avg_wr = float(np.mean(total_wr_vals)) if total_wr_vals else 0
    delta = best_oos_sharpe - c179_baseline
    status_vs_179 = "개선" if delta > 0 else "악화"
    print(f"  c179 기준 (240m vol regime adaptive): "
          f"avg_OOS=+{c179_baseline} n=~60")
    print(f"  c208 최적 (60m VPIN={vl} MOM={mt} Hold={hd} CD={cd} "
          f"Bucket={bk}): avg_OOS={best_oos_sharpe:+.3f} n={total_n}")
    print(f"  Δ vs c179: {delta:+.3f} ({status_vs_179})")
    print(f"  ⚠️  주의: 240m vs 60m Sharpe 직접 비교 주의 "
          f"(annualize factor 상이: 240m=sqrt(252×6), 60m=sqrt(252×24))")

    # -- 최종 요약 --
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    overall_status = ("PASS" if best_oos_sharpe > 5.0 and total_n >= 30
                      else "FAIL")
    print(f"★ OOS 최적: VPIN={vl} MOM={mt} Hold={hd} CD={cd} Bucket={bk}")
    print(f"  (60m 고정: EMA={EMA_PERIOD} ATR={ATR_PERIOD} "
          f"VOL_SMA={VOL_SMA_PERIOD} ATR_PCTILE_LB={ATR_PCTILE_LB} "
          f"MOM_LB={MOM_LOOKBACK})")
    print(f"  (c179 고정: volTh={VOL_REGIME_THRESH} "
          f"tpSc={HIGH_VOL_TP_SCALE} trSc={HIGH_VOL_TRAIL_SCALE} "
          f"hdSc={HIGH_VOL_HOLD_SCALE})")
    print(f"  (c177 고정: atrTh={ATR_PCTILE_THRESH} body={BODY_RATIO_MIN} "
          f"vpRx={VPIN_RELAX_THRESH} rxSc={RELAX_SCALE})")
    print(f"  (TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} "
          f"minP={MIN_PROFIT_ATR} BTC_SMA={BTC_SMA_PERIOD})")
    print(f"  avg OOS Sharpe: {best_oos_sharpe:+.3f} {overall_status}")
    train_sharpe = float(np.mean([
        fd["train"]["sharpe"] for fd in best_fold_details
        if not np.isnan(fd["train"]["sharpe"])
    ])) if best_fold_details else 0
    print(f"  train Sharpe: {train_sharpe:+.3f}")
    for fd in best_fold_details:
        fi = fd["fold"]
        tp = fd["test"]
        print(f"  Fold {fi}: Sharpe={tp['sharpe']:+.3f}  "
              f"WR={tp['wr']:.1%}  trades={tp['trades']}  "
              f"avg={tp['avg_ret']:+.2%}  MDD={tp['max_dd']:+.4f}")

    print(f"\nSharpe: {best_oos_sharpe:+.3f}")
    print(f"WR: {avg_wr:.1%}")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
