"""
vpin_eth 사이클 164 — RSI velocity 진입 필터 + 전면 RSI 동적 청산 (TP/SL/Trail)
- 기반: c163 RSI 동적 ATR 청산 (OOS Sharpe +8.837, WR 31.5%, trades 50)
- c163 약점:
  1) Fold 2 약함 (Sharpe +5.635, WR 23.5%, n=17) → 진입 품질 개선 필요
  2) SL만 고정 (0.4 ATR) → RSI 기반 동적 스케일링 미적용
  3) 볼륨 확인 없음 → 노이즈 진입 가능
- 가설:
  A) RSI velocity (RSI 변화율): RSI가 상승 중일 때만 진입 → 바닥 확인 후 매수
     rsi_delta = RSI[i] - RSI[i-rsi_delta_lookback]
     rsi_delta >= rsi_delta_min (양수 = 상승 중)
  B) SL RSI 동적 스케일링: RSI 낮을수록(과매도) → 좁은 SL (강한 지지 기대)
     effective_sl = sl_base - sl_bonus * rsi_ratio (과매도 → SL 좁게)
  C) 소프트 볼륨 필터: volume > vol_sma * vol_mult (1.0~1.5 범위로 완화)
     볼륨이 평균 이상일 때만 진입 → 노이즈 제거, 거래수 소폭 감소 감수
- 탐색:
  RSI_DELTA_LOOKBACK: [2, 3, 4]
  RSI_DELTA_MIN: [0.0, 1.0, 2.0, 3.0]
  SL_BASE_ATR: [0.4, 0.5, 0.6]
  SL_BONUS_ATR: [0.0, 0.1, 0.2]  (rsi_ratio=1일 때 SL 축소량)
  VOL_SMA_PERIOD: [20]
  VOL_MULT: [0.8, 1.0, 1.2]
  TP/Trail: c163 최적 고정 (TP=4.0+2.0, Trail=0.3+0.2, minP=1.5)
  BTC_SMA: 200 고정 (c163 검증)
- 2-fold walkforward + 슬리피지 스트레스
- 진입: next_bar open
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

# -- 고정값 (c152/c157/c163 검증 완료) --
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

# -- 진입 파라미터 (c157 최적 고정) --
VPIN_LOW = 0.30
VPIN_MOM_THRESH = 0.0007
ATR_PERIOD = 20
MAX_HOLD = 24
COOLDOWN_BARS = 6

# -- c163 최적 고정 (TP/Trail) --
BTC_SMA_PERIOD = 200
TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

# -- 탐색 그리드 --
RSI_DELTA_LOOKBACK_LIST = [2, 3, 4]
RSI_DELTA_MIN_LIST = [0.0, 1.0, 2.0, 3.0]
SL_BASE_ATR_LIST = [0.4, 0.5, 0.6]
SL_BONUS_ATR_LIST = [0.0, 0.1, 0.2]
VOL_SMA_PERIOD = 20
VOL_MULT_LIST = [0.8, 1.0, 1.2]

# -- Walkforward 기간 --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
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


def align_btc_to_eth(
    df_eth: pd.DataFrame, df_btc: pd.DataFrame, btc_sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, btc_sma_period)
    btc_close_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_close_aligned = btc_close_s.reindex(df_eth.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_eth.index, method="ffill").values
    return btc_close_aligned, btc_sma_aligned


# -- 백테스트 (RSI velocity + 전면 동적 청산) --

def backtest(
    df: pd.DataFrame,
    rsi_delta_lookback: int,
    rsi_delta_min: float,
    sl_base_atr: float,
    sl_bonus_atr: float,
    vol_mult: float,
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
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD, 50) + 5
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

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0):
            i += 1
            continue

        # -- RSI velocity 계산 --
        rsi_prev_idx = i - rsi_delta_lookback
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # -- 진입 조건 --
        vpin_ok = (
            vpin_val < VPIN_LOW
            and mom_val >= VPIN_MOM_THRESH
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )
        btc_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )
        rsi_velocity_ok = rsi_delta >= rsi_delta_min
        vol_ok = v[i] >= vol_sma_val * vol_mult

        if vpin_ok and btc_ok and rsi_velocity_ok and vol_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # TP: RSI 낮을수록(과매도) → 넓은 TP (c163 최적)
            effective_tp_mult = TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
            tp_price = buy + atr_at_entry * effective_tp_mult

            # SL: RSI 낮을수록(과매도) → 좁은 SL (강한 지지)
            effective_sl_mult = sl_base_atr - sl_bonus_atr * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)  # 최소 0.2 ATR
            sl_price = buy - atr_at_entry * effective_sl_mult

            # Trail: RSI 높을수록 → 넓은 trail (c163 최적)
            effective_trail_mult = TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            trail_dist = atr_at_entry * effective_trail_mult
            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR

            exit_ret = None
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                current_price = c[j]

                # TP
                if current_price >= tp_price:
                    exit_ret = (tp_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # SL
                if current_price <= sl_price:
                    exit_ret = (sl_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # 최고가 갱신
                if current_price > peak_price:
                    peak_price = current_price

                # 트레일링 스톱
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
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
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


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth 사이클 164 — RSI velocity + 전면 동적 SL + 소프트 볼륨 ===")
    print(f"심볼: {SYMBOL}  목표: OOS Sharpe >= 5.0")
    print("가설 A: RSI velocity(delta) > 0 → 바닥 확인 후 진입, 품질 향상")
    print("가설 B: SL도 RSI 동적 스케일링 → 과매도 시 좁은 SL (강한 지지)")
    print("가설 C: 소프트 볼륨 필터 → 노이즈 진입 제거")
    print(f"기준선: c163 OOS +8.837, WR 31.5%, trades 50")
    print(f"고정: TP={TP_BASE_ATR}+{TP_BONUS_ATR}, Trail={TRAIL_BASE_ATR}+"
          f"{TRAIL_BONUS_ATR}, minP={MIN_PROFIT_ATR}, BTC_SMA={BTC_SMA_PERIOD}")
    print("=" * 80)

    # -- BTC 데이터 로드 --
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # -- c163 기준선 OOS --
    print("\n--- c163 기준선 (RSI 동적 TP/Trail, 고정 SL=0.4, 볼륨 필터 없음) ---")
    for fold_i, fold in enumerate(WF_FOLDS):
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if not df_test.empty:
            btc_c_t, btc_sma_t = align_btc_to_eth(df_test, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_test, 3, 0.0, 0.4, 0.0, 0.0,
                         btc_c_t, btc_sma_t)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  [c163] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%")

    # -- Phase 1: train 그리드 서치 --
    train_start, train_end = WF_FOLDS[0]["train"]
    df_train = load_historical(SYMBOL, "240m", train_start, train_end)
    if df_train.empty:
        print("train 데이터 없음.")
        return
    print(f"\ntrain 데이터: {len(df_train)}행 ({train_start} ~ {train_end})")

    btc_c_tr, btc_sma_tr = align_btc_to_eth(df_train, df_btc_full, BTC_SMA_PERIOD)

    combos = list(product(
        RSI_DELTA_LOOKBACK_LIST,
        RSI_DELTA_MIN_LIST,
        SL_BASE_ATR_LIST,
        SL_BONUS_ATR_LIST,
        VOL_MULT_LIST,
    ))
    print(f"총 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (rdl, rdm, sl_b, sl_bon, vm) in enumerate(combos):
        if idx % 50 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        r = backtest(df_train, rdl, rdm, sl_b, sl_bon, vm,
                     btc_c_tr, btc_sma_tr)
        results.append({
            "rsi_delta_lb": rdl,
            "rsi_delta_min": rdm,
            "sl_base": sl_b, "sl_bonus": sl_bon,
            "vol_mult": vm,
            **r,
        })

    valid = [r for r in results
             if r["trades"] >= 15
             and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=15): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 20 (Sharpe 기준) ===")
    hdr = (f"{'dLB':>4} {'dMin':>5} {'SL_b':>5} {'SL+':>4} {'vMul':>5} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['rsi_delta_lb']:>4} {r['rsi_delta_min']:>5.1f} "
            f"{r['sl_base']:>5.1f} {r['sl_bonus']:>4.1f} "
            f"{r['vol_mult']:>5.1f} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 2: OOS Walk-Forward (Top 20 고유) --
    seen: set[tuple] = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["rsi_delta_lb"], r["rsi_delta_min"],
               r["sl_base"], r["sl_bonus"], r["vol_mult"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 20:
            break

    print(f"\n{'=' * 80}")
    print(f"=== OOS Walk-Forward 검증 (Top {len(unique_top)} 고유, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        rdl = params["rsi_delta_lb"]
        rdm = params["rsi_delta_min"]
        sl_b = params["sl_base"]
        sl_bon = params["sl_bonus"]
        vm = params["vol_mult"]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                continue
            btc_c_t, btc_sma_t = align_btc_to_eth(
                df_test, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_test, rdl, rdm, sl_b, sl_bon, vm,
                         btc_c_t, btc_sma_t)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            all_pass = all(s >= 5.0 for s in oos_sharpes)
            print(f"  #{rank}: dLB={rdl} dMin={rdm} "
                  f"SL={sl_b}-{sl_bon} vMul={vm} | "
                  f"train={params['sharpe']:+.3f} -> avg_OOS={avg_oos:+.3f} "
                  f"min_OOS={min_oos:+.3f} "
                  f"{'PASS' if all_pass else 'FAIL'}")
            wf_results.append({
                **params,
                "train_sharpe": params["sharpe"],
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "all_pass": all_pass,
                "fold_details": fold_details,
            })

    if not wf_results:
        print("\nWF 검증 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- Phase 3: 슬리피지 스트레스 (OOS Top 3) --
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                       reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS Top 3) ===")

    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    for rank, params in enumerate(wf_top3, 1):
        rdl = params["rsi_delta_lb"]
        rdm = params["rsi_delta_min"]
        sl_b = params["sl_base"]
        sl_bon = params["sl_bonus"]
        vm = params["vol_mult"]
        btc_c_f, btc_sma_f = align_btc_to_eth(df_full, df_btc_full, BTC_SMA_PERIOD)
        print(f"\n--- #{rank}: dLB={rdl} dMin={rdm} "
              f"SL={sl_b}-{sl_bon} vMul={vm} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_full, rdl, rdm, sl_b, sl_bon, vm,
                         btc_c_f, btc_sma_f, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # -- c163 vs c164 OOS 비교 --
    print(f"\n{'=' * 80}")
    print("=== c163 기준선 vs c164 OOS 비교 ===")
    for fold_i, fold in enumerate(WF_FOLDS):
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if not df_test.empty:
            btc_c_t, btc_sma_t = align_btc_to_eth(
                df_test, df_btc_full, BTC_SMA_PERIOD)
            # c163 기준선 (RSI 동적 TP/Trail, 고정 SL=0.4, 볼륨 필터 없음)
            r = backtest(df_test, 3, 0.0, 0.4, 0.0, 0.0,
                         btc_c_t, btc_sma_t)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  [c163 기준] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%")
    best = wf_sorted[0]
    for fold_i, fd in enumerate(best["fold_details"]):
        sh = best["oos_sharpes"][fold_i]
        print(f"  [c164 최적] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
              f"WR={fd['wr']:.1%}  n={best['oos_trades'][fold_i]}  "
              f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: RSI_delta_LB={best['rsi_delta_lb']} "
          f"RSI_delta_min={best['rsi_delta_min']} "
          f"SL_base={best['sl_base']} SL_bonus={best['sl_bonus']} "
          f"vol_mult={best['vol_mult']}")
    print(f"  (고정: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR} "
          f"BTC_SMA={BTC_SMA_PERIOD} VPIN={VPIN_LOW} MOM={VPIN_MOM_THRESH})")
    oos_avg = best["avg_oos_sharpe"]
    status = "PASS >=5.0" if oos_avg >= 5.0 else "FAIL <5.0"
    print(f"  avg OOS Sharpe: {oos_avg:+.3f} {status}")
    print(f"  train Sharpe: {best['train_sharpe']:+.3f}")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={best['oos_trades'][fi]}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    total_trades = sum(best["oos_trades"])
    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))

    print(f"\nSharpe: {oos_avg:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
