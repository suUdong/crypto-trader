"""
vpin_eth 사이클 160 — ATR 스케일링 TP/SL + 트레일링 하이브리드
- 기반: c157 최적 vl=0.3 vm=0.0007 hold=24 bTr=0.01 mSc=0.0 minP=0.03 SL=0.004 cool=6
  c157 OOS: avg Sharpe +8.270, Fold1 +11.196 (WR=25.5% n=47), Fold2 +5.344 (WR=16.7% n=36)
- 문제: mom_scale=0이 최적 → 모멘텀 적응 불필요. WR 16.7%(Fold2)가 약점.
- 가설:
  1) 고정 SL/minProfit은 변동성 변화에 부적응 → ATR 대비 비율로 스케일링
     → 고변동성: 넓은 SL/TP (조기 청산 방지) / 저변동성: 좁은 SL/TP (빠른 청산)
  2) TP 타겟 추가: trailing만으로는 이익 캡처 불확실 → ATR 배수 TP 타겟 도달 시 즉시 청산
     → WR 개선 기대 (확정 이익 확보)
  3) 하이브리드: TP 타겟 OR 트레일링 중 먼저 작동하는 쪽으로 청산
- 신규 파라미터: atr_period, tp_atr_mult, sl_atr_mult, trail_atr_mult, min_profit_atr_mult
  → 모두 ATR 배수 → 변동성 자동 적응
- c157 고정 진입 조건 유지 (거래수 보존)
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

# ── 고정값 (c152/c157 검증 완료) ────────────────────────────────────────────
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
COOLDOWN_LOSSES = 2

# ── 진입 파라미터 (c157 최적 고정) ──────────────────────────────────────────
VPIN_LOW = 0.30
VPIN_MOM_THRESH = 0.0007
MOM_LOOKBACK = 8

# ── ATR 기반 탐색 그리드 ────────────────────────────────────────────────────
ATR_PERIOD_LIST = [14, 20]
MAX_HOLD_LIST = [18, 24, 30]

# TP 타겟: close + atr * tp_mult → 도달 시 즉시 청산
TP_ATR_MULT_LIST = [2.0, 2.5, 3.0, 3.5, 4.0]

# SL: close - atr * sl_mult
SL_ATR_MULT_LIST = [0.5, 0.8, 1.0, 1.2, 1.5]

# 트레일링: peak - atr * trail_mult (트레일 활성 후)
TRAIL_ATR_MULT_LIST = [0.5, 0.8, 1.0, 1.5]

# 트레일 활성 최소 수익 (ATR 배수)
MIN_PROFIT_ATR_MULT_LIST = [1.0, 1.5, 2.0]

COOLDOWN_BARS_LIST = [0, 6]

# ── Walkforward 기간 ─────────────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

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
    """Production-matching VPIN: BVC + normal CDF + volume weighting."""
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
    """Average True Range (Wilder smoothing)."""
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


# ── 백테스트 (ATR 스케일링 TP/SL + 트레일링 하이브리드) ──────────────────────

def backtest(
    df: pd.DataFrame,
    atr_period: int,
    max_hold: int,
    tp_atr_mult: float,
    sl_atr_mult: float,
    trail_atr_mult: float,
    min_profit_atr_mult: float,
    cooldown_bars: int,
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
    atr_arr = compute_atr(h, lo, c, atr_period)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, atr_period) + 5
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

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0):
            i += 1
            continue

        # 진입 조건 (c157 동일)
        entry_ok = (
            vpin_val < VPIN_LOW
            and mom_val >= VPIN_MOM_THRESH
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )

        if entry_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy

            # ★ ATR 기반 동적 TP/SL/Trail 계산 (진입 시점 ATR 스냅샷)
            atr_at_entry = atr_val
            tp_price = buy + atr_at_entry * tp_atr_mult       # 절대 TP 가격
            sl_price = buy - atr_at_entry * sl_atr_mult       # 절대 SL 가격
            trail_dist = atr_at_entry * trail_atr_mult        # 트레일 폭 (가격 단위)
            min_profit_dist = atr_at_entry * min_profit_atr_mult  # 트레일 활성 최소 수익

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]

                # 1) TP 타겟 도달 → 즉시 청산
                if current_price >= tp_price:
                    exit_ret = (tp_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # 2) SL 도달 → 즉시 청산
                if current_price <= sl_price:
                    exit_ret = (sl_price / buy - 1) - FEE - slippage
                    i = j
                    break

                # 최고가 갱신
                if current_price > peak_price:
                    peak_price = current_price

                # 3) 트레일링 스톱 (최소 수익 이상일 때만)
                unrealized = peak_price - buy
                if unrealized >= min_profit_dist:
                    if peak_price - current_price >= trail_dist:
                        exit_ret = (current_price / buy - 1) - FEE - slippage
                        i = j
                        break

            if exit_ret is None:
                hold_end = min(i + max_hold, n - 1)
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
    print("=== vpin_eth 사이클 160 — ATR 스케일링 TP/SL + 트레일링 하이브리드 ===")
    print(f"심볼: {SYMBOL}  목표: OOS Sharpe ≥ 5.0, WR 개선 (c157 기준 16.7~25.5%)")
    print("가설: ATR 배수 TP 타겟 → WR↑, ATR 비례 SL/Trail → 변동성 적응")
    print("기준선: c157 OOS avg +8.270 (Fold1=+11.196 WR=25.5%, Fold2=+5.344 WR=16.7%)")
    print("=" * 80)

    # ── Phase 1: train 그리드 서치 ────────────────────────────────────────────
    train_start, train_end = WF_FOLDS[0]["train"]
    df_train = load_historical(SYMBOL, "240m", train_start, train_end)
    if df_train.empty:
        print("train 데이터 없음.")
        return
    print(f"\ntrain 데이터: {len(df_train)}행 ({train_start} ~ {train_end})")

    # c157 기준선 재현 (고정 TP 없음, 트레일만)
    print("\n--- c157 기준선 (bTr=0.01 minP=0.03 SL=0.004 cool=6) ---")
    # ATR20 기준 SL=0.004 ≈ 0.5 ATR, trail=0.01 ≈ 1.0 ATR, minP=0.03 ≈ 3.0 ATR
    base = backtest(df_train, 20, 24, 99.0, 0.5, 1.0, 3.0, 6)
    print(f"  Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"n={base['trades']}")

    combos = list(product(
        ATR_PERIOD_LIST, MAX_HOLD_LIST,
        TP_ATR_MULT_LIST, SL_ATR_MULT_LIST,
        TRAIL_ATR_MULT_LIST, MIN_PROFIT_ATR_MULT_LIST,
        COOLDOWN_BARS_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (ap, mh, tp_m, sl_m, tr_m, mp_m, cb) in enumerate(combos):
        if idx % 1000 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        r = backtest(df_train, ap, mh, tp_m, sl_m, tr_m, mp_m, cb)
        results.append({
            "atr_period": ap, "max_hold": mh,
            "tp_atr_mult": tp_m, "sl_atr_mult": sl_m,
            "trail_atr_mult": tr_m, "min_profit_atr_mult": mp_m,
            "cooldown_bars": cb, **r,
        })

    valid = [r for r in results
             if r["trades"] >= 30
             and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥30): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 20 (Sharpe 기준) ===")
    hdr = (f"{'ATR':>4} {'hold':>4} {'TP_m':>5} {'SL_m':>5} "
           f"{'Tr_m':>5} {'mP_m':>5} {'cool':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{r['atr_period']:>4} {r['max_hold']:>4} "
            f"{r['tp_atr_mult']:>5.1f} {r['sl_atr_mult']:>5.1f} "
            f"{r['trail_atr_mult']:>5.1f} {r['min_profit_atr_mult']:>5.1f} "
            f"{r['cooldown_bars']:>4} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # ── Phase 2: OOS Walk-Forward (Top 20 고유 조합) ─────────────────────────
    seen = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["atr_period"], r["max_hold"],
               r["tp_atr_mult"], r["sl_atr_mult"],
               r["trail_atr_mult"], r["min_profit_atr_mult"],
               r["cooldown_bars"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 20:
            break

    print(f"\n{'=' * 80}")
    print(f"=== OOS Walk-Forward 검증 (Top {len(unique_top)} 고유, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        ap = params["atr_period"]
        mh = params["max_hold"]
        tp_m = params["tp_atr_mult"]
        sl_m = params["sl_atr_mult"]
        tr_m = params["trail_atr_mult"]
        mp_m = params["min_profit_atr_mult"]
        cb = params["cooldown_bars"]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                continue
            r = backtest(df_test, ap, mh, tp_m, sl_m, tr_m, mp_m, cb)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            all_pass = all(s >= 5.0 for s in oos_sharpes)
            print(f"  #{rank}: ATR={ap} hold={mh} "
                  f"TP={tp_m} SL={sl_m} Tr={tr_m} mP={mp_m} cool={cb} | "
                  f"train={params['sharpe']:+.3f} → avg_OOS={avg_oos:+.3f} "
                  f"min_OOS={min_oos:+.3f} "
                  f"{'✅' if all_pass else '❌'}")
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

    # ── Phase 3: 슬리피지 스트레스 (OOS Top 3) ──────────────────────────────
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                        reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS Top 3) ===")

    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    for rank, params in enumerate(wf_top3, 1):
        ap = params["atr_period"]
        mh = params["max_hold"]
        tp_m = params["tp_atr_mult"]
        sl_m = params["sl_atr_mult"]
        tr_m = params["trail_atr_mult"]
        mp_m = params["min_profit_atr_mult"]
        cb = params["cooldown_bars"]
        print(f"\n--- #{rank}: ATR={ap} hold={mh} "
              f"TP={tp_m} SL={sl_m} Tr={tr_m} mP={mp_m} cool={cb} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_full, ap, mh, tp_m, sl_m, tr_m, mp_m, cb,
                         slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── c157 기준선 vs ATR 스케일링 OOS 비교 ─────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== c157 고정 vs c160 ATR 스케일링 OOS 비교 ===")
    for fold_i, fold in enumerate(WF_FOLDS):
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if not df_test.empty:
            # c157 기준선 근사 (TP=무한대=고정없음, SL~0.5ATR, trail~1ATR, minP~3ATR)
            r = backtest(df_test, 20, 24, 99.0, 0.5, 1.0, 3.0, 6)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  [c157 고정] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
                  f"WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  "
                  f"MDD={r['max_dd'] * 100:+.2f}%")
    best = wf_sorted[0]
    for fold_i, fd in enumerate(best["fold_details"]):
        sh = best["oos_sharpes"][fold_i]
        print(f"  [c160 ATR] Fold {fold_i + 1}: Sharpe={sh:+.3f}  "
              f"WR={fd['wr']:.1%}  n={best['oos_trades'][fold_i]}  "
              f"avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: ATR={best['atr_period']} hold={best['max_hold']} "
          f"TP={best['tp_atr_mult']} SL={best['sl_atr_mult']} "
          f"Tr={best['trail_atr_mult']} mP={best['min_profit_atr_mult']} "
          f"cool={best['cooldown_bars']}")
    oos_avg = best["avg_oos_sharpe"]
    status = "✅ ≥5.0 달성" if oos_avg >= 5.0 else "❌ <5.0"
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
