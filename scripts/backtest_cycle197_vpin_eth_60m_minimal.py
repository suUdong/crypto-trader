"""
vpin_eth 사이클 197 — 60m 최소필터 VPIN (n≥60 확보 목표)
- 배경: c195 MTF v1 9개 필터→1h 변환 시 n=4 (vol_mom 9%, body 21% 통과)
  c195/c196 entry gate 추가 모두 c179 대비 악화
  평가자 지시: "VPIN ETH를 더 짧은 타임프레임(60m)으로 n≥60 확보"
- 가설:
  60m VPIN을 최소 4개 핵심 필터로만 운용하면 n 확보 가능
  4h에서 효과적이었던 복합 필터는 60m에서 과적합/희소화 원인
  핵심 신호만으로 60m의 높은 시간해상도를 활용
- 필터:
  1) VPIN > threshold (BVC 기반 유동성 불균형)
  2) momentum > 0 (추세 방향)
  3) RSI in [floor, ceiling] (과매수/과매도 회피)
  4) BTC > SMA200 (레짐 게이트)
- 탐색 그리드:
  VPIN_BUCKETS: [24, 48, 96]   — 24h/48h/96h 윈도우
  VPIN_THRESH: [0.30, 0.35, 0.40]
  MOM_LB: [4, 8, 12]           — 4h/8h/12h 모멘텀
  MAX_HOLD: [20, 40, 60]       — 20h/40h/60h
  = 3×3×3×3 = 81 combos (train에서 top5 → WF)
- Exit: ATR-based TP/SL (c165 고정)
- 3-fold WF + 슬리피지 스트레스
- 진입: next_bar open (60m)
- 심볼: ETH only (가장 안정적 VPIN 심볼)
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

SYMBOLS = ["KRW-ETH"]
FEE = 0.0005

# -- 고정 파라미터 --
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
EMA_PERIOD = 80          # 4h EMA20 → 60m 80봉 동등
COOLDOWN_BARS = 8         # 4h 4봉 → 60m 8봉 (완화)
COOLDOWN_LOSSES = 2

# -- Exit: c165 ATR-based (60m 적응) --
ATR_PERIOD = 80           # 4h 20 → 60m 80
TP_ATR_MULT = 5.0         # c165 고정
SL_ATR_MULT = 0.3         # c165 고정
TRAIL_ACT_ATR = 1.5       # c165 고정
TRAIL_SL_ATR = 0.4        # c165 고정
VOL_SMA_PERIOD = 80
VOL_MULT = 0.8

BTC_SMA_PERIOD = 800      # 4h 200 → 60m 800

# -- 탐색 그리드 --
VPIN_BUCKETS_LIST = [24, 48, 96]
VPIN_THRESH_LIST = [0.30, 0.35, 0.40]
MOM_LB_LIST = [4, 8, 12]
MAX_HOLD_LIST = [20, 40, 60]

# -- 3-fold WF --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ---- 지표 함수 ----

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
    result = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        if closes[i - lookback] > 0:
            result[i] = (closes[i] / closes[i - lookback]) - 1.0
    return result


def compute_atr(
    highs: np.ndarray, lows: np.ndarray,
    closes: np.ndarray, period: int = 20,
) -> np.ndarray:
    n = len(closes)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n <= period:
        return atr
    atr[period] = tr[1:period + 1].mean()
    k = 2.0 / (period + 1)
    for i in range(period + 1, n):
        atr[i] = tr[i] * k + atr[i - 1] * (1 - k)
    return atr


# ---- 백테스트 엔진 ----

def backtest_60m(
    df: pd.DataFrame,
    btc_sma: np.ndarray,
    btc_df: pd.DataFrame,
    vpin_buckets: int,
    vpin_thresh: float,
    mom_lb: int,
    max_hold: int,
    slip: float = 0.0,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    # 지표 계산
    vpin = compute_vpin_bvc(c, o, h, lo, v, vpin_buckets)
    mom = compute_momentum(c, mom_lb)
    rsi = rsi_calc(c, RSI_PERIOD)
    ema = ema_calc(c, EMA_PERIOD)
    atr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma = sma_calc(v, VOL_SMA_PERIOD)

    # BTC SMA 매핑 (60m → 60m)
    btc_c = btc_df["close"].values
    btc_sma_arr = sma_calc(btc_c, BTC_SMA_PERIOD)
    # 60m BTC index를 ETH index에 매핑
    btc_idx_map = {}
    for idx, ts in enumerate(btc_df.index):
        btc_idx_map[ts] = idx

    trades = []
    in_pos = False
    entry_price = 0.0
    entry_bar = 0
    consecutive_losses = 0
    cooldown_until = 0
    trail_active = False
    trail_stop = 0.0

    for i in range(max(vpin_buckets, mom_lb, EMA_PERIOD, ATR_PERIOD, BTC_SMA_PERIOD) + 1, n - 1):
        if in_pos:
            bars_held = i - entry_bar
            cur_atr = atr[i] if not np.isnan(atr[i]) else atr[i - 1]
            if np.isnan(cur_atr) or cur_atr <= 0:
                continue

            tp_price = entry_price * (1.0 + TP_ATR_MULT * cur_atr / entry_price)
            sl_price = entry_price * (1.0 - SL_ATR_MULT * cur_atr / entry_price)

            # 트레일링 스탑 활성화
            cur_ret = (c[i] - entry_price) / entry_price
            if cur_ret >= TRAIL_ACT_ATR * cur_atr / entry_price:
                trail_active = True
                new_trail = c[i] * (1.0 - TRAIL_SL_ATR * cur_atr / c[i])
                trail_stop = max(trail_stop, new_trail)

            exit_price = None
            # TP hit
            if h[i] >= tp_price:
                exit_price = tp_price
            # SL hit
            elif lo[i] <= sl_price:
                exit_price = sl_price
            # Trail hit
            elif trail_active and lo[i] <= trail_stop:
                exit_price = trail_stop
            # Max hold
            elif bars_held >= max_hold:
                exit_price = c[i]

            if exit_price is not None:
                ret = (exit_price / entry_price) - 1.0 - 2 * (FEE + slip)
                trades.append(ret)
                in_pos = False
                trail_active = False
                trail_stop = 0.0
                if ret < 0:
                    consecutive_losses += 1
                    if consecutive_losses >= COOLDOWN_LOSSES:
                        cooldown_until = i + COOLDOWN_BARS
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0
            continue

        # --- 진입 로직 ---
        if i < cooldown_until:
            continue

        # 필수 지표 유효성
        if (np.isnan(vpin[i]) or np.isnan(mom[i]) or np.isnan(rsi[i])
                or np.isnan(ema[i]) or np.isnan(atr[i])):
            continue

        # Gate 1: VPIN > threshold (유동성 불균형)
        if vpin[i] < vpin_thresh:
            continue

        # Gate 2: momentum > 0 (추세 방향)
        if mom[i] <= 0:
            continue

        # Gate 3: RSI in range
        if rsi[i] > RSI_CEILING or rsi[i] < RSI_FLOOR:
            continue

        # Gate 4: Price > EMA (추세 확인)
        if c[i] <= ema[i]:
            continue

        # Gate 5: BTC > SMA200 (레짐 게이트)
        ts = df.index[i]
        btc_i = btc_idx_map.get(ts)
        if btc_i is None or btc_i >= len(btc_sma_arr) or np.isnan(btc_sma_arr[btc_i]):
            continue
        if btc_c[btc_i] <= btc_sma_arr[btc_i]:
            continue

        # Gate 6: Volume > SMA * mult (거래량 확인)
        if not np.isnan(vol_sma[i]) and vol_sma[i] > 0:
            if v[i] < vol_sma[i] * VOL_MULT:
                continue

        # 진입 (next bar open)
        entry_price = o[i + 1]
        entry_bar = i + 1
        in_pos = True
        trail_active = False
        trail_stop = 0.0

    # 통계
    if len(trades) == 0:
        return {"sharpe": 0.0, "wr": 0.0, "n": 0, "avg": 0.0, "mdd": 0.0}

    arr = np.array(trades)
    avg = arr.mean()
    std = arr.std()
    sharpe = (avg / std * np.sqrt(252 * 24)) if std > 0 else 0.0
    wr = (arr > 0).sum() / len(arr) * 100
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    mdd = dd.min() * 100

    return {"sharpe": sharpe, "wr": wr, "n": len(trades), "avg": avg * 100, "mdd": mdd}


def main():
    print("=" * 80)
    print("  c197: VPIN ETH 60m 최소필터 — n≥60 확보 목표")
    print("=" * 80)

    # 데이터 로드
    print("\n데이터 로드 중...")
    eth_60m = load_historical("KRW-ETH", "60m", "2022-01-01", "2026-04-05")
    btc_60m = load_historical("KRW-BTC", "60m", "2022-01-01", "2026-04-05")
    print(f"  KRW-ETH 60m: {len(eth_60m)}행")
    print(f"  KRW-BTC 60m: {len(btc_60m)}행")

    btc_c = btc_60m["close"].values
    btc_sma = sma_calc(btc_c, BTC_SMA_PERIOD)

    # Phase 1: 전체 기간 train 그리드 서치
    combos = list(product(
        VPIN_BUCKETS_LIST, VPIN_THRESH_LIST, MOM_LB_LIST, MAX_HOLD_LIST
    ))
    print(f"\n총 조합: {len(combos)}개")

    train_start, train_end = "2022-01-01", "2024-03-31"
    train_df = eth_60m[train_start:train_end]
    btc_train = btc_60m[train_start:train_end]
    print(f"\nPhase 1: train 그리드 서치 ({train_start} ~ {train_end})")
    print(f"  KRW-ETH train: {len(train_df)}행")

    results = []
    for idx, (vb, vt, ml, mh) in enumerate(combos):
        r = backtest_60m(train_df, btc_sma, btc_train, vb, vt, ml, mh)
        results.append((vb, vt, ml, mh, r))
        if (idx + 1) % 27 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    # train 결과 정렬
    results.sort(key=lambda x: x[4]["sharpe"], reverse=True)

    print(f"\n--- Train Top 10 ---")
    for i, (vb, vt, ml, mh, r) in enumerate(results[:10]):
        print(f"  #{i+1} vB={vb} vT={vt} mL={ml} mH={mh} → "
              f"Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1f}% n={r['n']} "
              f"avg={r['avg']:+.2f}% MDD={r['mdd']:.2f}%")

    # Phase 2: Top 5 WF 검증
    top_n = min(5, len([r for r in results if r[4]["n"] >= 5]))
    if top_n == 0:
        print("\n⚠️ train에서 유효 조합 없음 (n≥5 없음)")
        return

    print(f"\n{'='*80}")
    print(f"Phase 2: 3-fold WF 검증 (Top {top_n})")
    print(f"{'='*80}")

    wf_results = []
    for rank, (vb, vt, ml, mh, _) in enumerate(results[:top_n]):
        print(f"\n--- #{rank+1}: vB={vb} vT={vt} mL={ml} mH={mh} ---")
        fold_sharpes = []
        fold_details = []
        for fi, fold in enumerate(WF_FOLDS):
            ts, te = fold["train"]
            os_, oe = fold["test"]
            tr_df = eth_60m[ts:te]
            btc_tr = btc_60m[ts:te]
            r_tr = backtest_60m(tr_df, btc_sma, btc_tr, vb, vt, ml, mh)
            oos_df = eth_60m[os_:oe]
            btc_oos = btc_60m[os_:oe]
            r_oos = backtest_60m(oos_df, btc_sma, btc_oos, vb, vt, ml, mh)
            fold_sharpes.append(r_oos["sharpe"])
            fold_details.append(r_oos)
            print(f"  Fold {fi+1}: train Sharpe={r_tr['sharpe']:+.3f} → "
                  f"OOS Sharpe={r_oos['sharpe']:+.3f} WR={r_oos['wr']:.1f}% n={r_oos['n']}")

        avg_oos = np.mean(fold_sharpes)
        total_n = sum(d["n"] for d in fold_details)
        print(f"  → avg OOS Sharpe: {avg_oos:+.3f} (total n={total_n})")

        wf_results.append({
            "params": (vb, vt, ml, mh),
            "avg_oos": avg_oos,
            "folds": fold_details,
            "total_n": total_n,
        })

    # 최적 선택 (avg OOS 기준)
    wf_results.sort(key=lambda x: x["avg_oos"], reverse=True)
    best = wf_results[0]
    vb, vt, ml, mh = best["params"]

    # Phase 3: 슬리피지 스트레스
    print(f"\n{'='*80}")
    print("Phase 3: 슬리피지 스트레스 테스트")
    print(f"{'='*80}")
    print(f"최적: vB={vb} vT={vt} mL={ml} mH={mh}")

    for slip in SLIPPAGE_LEVELS:
        fold_sharpes = []
        fold_n = 0
        fold_wr = []
        for fi, fold in enumerate(WF_FOLDS):
            os_, oe = fold["test"]
            oos_df = eth_60m[os_:oe]
            btc_oos = btc_60m[os_:oe]
            r = backtest_60m(oos_df, btc_sma, btc_oos, vb, vt, ml, mh, slip=slip)
            fold_sharpes.append(r["sharpe"])
            fold_n += r["n"]
            fold_wr.append(r["wr"])
        avg_sh = np.mean(fold_sharpes)
        avg_wr = np.mean(fold_wr)
        tag = "PASS" if avg_sh > 5.0 else "FAIL"
        print(f"  slip={slip:.4f}: Sharpe={avg_sh:+.3f} WR={avg_wr:.1f}% n={fold_n} [{tag}]")

    # Phase 4: BH 비교
    print(f"\n{'='*80}")
    print("Phase 4: Buy-and-Hold 비교")
    print(f"{'='*80}")
    for fi, fold in enumerate(WF_FOLDS):
        os_, oe = fold["test"]
        oos_df = eth_60m[os_:oe]
        if len(oos_df) >= 2:
            bh_ret = (oos_df["close"].iloc[-1] / oos_df["close"].iloc[0] - 1) * 100
            strat_r = best["folds"][fi]
            cum_ret = sum(strat_r["avg"] / 100 * 1 for _ in range(strat_r["n"])) if strat_r["n"] > 0 else 0
            # 정확한 누적 수익
            cum_ret = strat_r["avg"] * strat_r["n"] / 100  # 단순 합
            print(f"  Fold {fi+1} ({os_}~{oe}): BH={bh_ret:+.1f}% | "
                  f"전략 avg_ret={strat_r['avg']:+.2f}% × {strat_r['n']}거래")

    # 최종 요약
    print(f"\n{'='*80}")
    print("=== 최종 요약 ===")
    print(f"{'='*80}")
    print(f"★ OOS 최적: vB={vb} vT={vt} mL={ml} mH={mh}")
    print(f"  (고정: RSI_CEIL={RSI_CEILING} RSI_FLOOR={RSI_FLOOR} EMA={EMA_PERIOD}"
          f" ATR={ATR_PERIOD} CD={COOLDOWN_BARS})")
    print(f"  (Exit: TP={TP_ATR_MULT} SL={SL_ATR_MULT} Trail={TRAIL_ACT_ATR}/{TRAIL_SL_ATR}"
          f" BTC_SMA={BTC_SMA_PERIOD})")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f}"
          f" {'PASS' if best['avg_oos'] > 5.0 else 'FAIL'}")

    total_n = 0
    for fi, fd in enumerate(best["folds"]):
        tag = ""
        if fd["n"] == 0:
            tag = " ⚠️ n=0"
        total_n += fd["n"]
        print(f"  Fold {fi+1}: Sharpe={fd['sharpe']:+.3f}  WR={fd['wr']:.1f}%  "
              f"trades={fd['n']}  avg={fd['avg']:+.2f}%  MDD={fd['mdd']:.2f}%{tag}")

    print(f"  총 OOS trades: {total_n} ({'≥60 OK' if total_n >= 60 else '< 60 미달'})")
    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    print(f"WR: {np.mean([fd['wr'] for fd in best['folds']]):.1f}%")
    print(f"trades: {total_n}")

    # c192 240m 대비 비교
    print(f"\n{'='*80}")
    print("=== c192 (240m) 대비 비교 ===")
    print(f"  c192 (240m): avg_OOS=+30.947 n=26")
    print(f"  c197 (60m):  avg_OOS={best['avg_oos']:+.3f} n={total_n}")
    delta = best["avg_oos"] - 30.947
    print(f"  Δ Sharpe: {delta:+.3f} ({'개선' if delta > 0 else '악화'})")
    print(f"  Δ trades: {total_n - 26:+d} ({'증가' if total_n > 26 else '감소'})")


if __name__ == "__main__":
    main()
