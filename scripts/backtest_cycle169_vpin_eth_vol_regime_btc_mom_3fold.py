"""
vpin_eth 사이클 169 — 변동성 레짐 필터 + BTC 모멘텀 게이트 + 3-fold WF
- 기반: c166 ATR 동적 SL (OOS +3.178 FAIL), c162 고정 SL (OOS +7.011)
- 문제:
  1) c166 Fold 2 (2025-07~2026-04) Sharpe=-3.377, n=17 → 저변동성/약세 구간 진입
  2) ATR 동적 SL/minP가 c162 고정값 대비 개선 없음
  3) 2-fold로는 검증 불충분 (Fold1 OK, Fold2 FAIL → 평균 왜곡)
- 가설:
  1) ATR percentile 기반 변동성 레짐 필터: ATR_pct가 하위 N%일 때 진입 차단
     → 저변동성 구간에서 수익 기회 없이 손실만 발생하는 거래 제거
  2) BTC 모멘텀 게이트 강화: SMA200 위 + BTC N봉 수익률 > 0
     → 단순 SMA 위/아래가 아닌, 방향성 확인으로 횡보 구간 필터
  3) c162 고정 SL/minP 기본값 유지 (ATR 동적화 폐기)
  4) 3-fold WF: 검증 강건성 확보
- 탐색 그리드:
  vol_regime_pctile: [10, 20, 30, 40]  (ATR 하위 N% 차단)
  btc_mom_lookback: [0, 5, 10, 20]     (0=비활성, BTC N봉 수익률>0 요구)
  max_hold: [18, 24, 30]
  base_trail: [0.012, 0.015, 0.018]
  mom_scale: [0.010, 0.015]
  cooldown_bars: [0, 6]
  SL (고정): [0.004, 0.006, 0.008]
  minProfit (고정): [0.012, 0.015, 0.018]
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

# -- 고정값 (c152/c157/c162 검증 완료) --
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

# -- c162 최적 진입 파라미터 (고정) --
VPIN_LOW = 0.3
VPIN_MOM = 0.0007
BTC_SMA_PERIOD = 200

# -- 탐색 그리드 --
MAX_HOLD_LIST = [18, 24, 30]
BASE_TRAIL_LIST = [0.012, 0.015, 0.018]
MOM_SCALE_LIST = [0.010, 0.015]
COOLDOWN_BARS_LIST = [0, 6]
SL_LIST = [0.004, 0.006, 0.008]
MIN_PROFIT_LIST = [0.012, 0.015, 0.018]

# ★ 새 필터 파라미터
VOL_REGIME_PCTILE_LIST = [10, 20, 30, 40]   # ATR_pct 하위 N% 차단
BTC_MOM_LOOKBACK_LIST = [0, 5, 10, 20]       # 0=비활성

ATR_PERIOD = 14  # ATR 계산용 (레짐 필터 전용, exit은 고정)

# -- 3-Fold Walkforward 기간 --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-12-31"), "test": ("2025-01-01", "2025-09-30")},
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


def compute_atr_pct(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int,
) -> np.ndarray:
    """ATR을 가격 대비 비율(%)로 반환."""
    n = len(closes)
    tr = np.full(n, np.nan)
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr
    atr[period] = np.nanmean(tr[1:period + 1])
    k = 2.0 / (period + 1)
    for i in range(period + 1, n):
        if not np.isnan(tr[i]) and not np.isnan(atr[i - 1]):
            atr[i] = tr[i] * k + atr[i - 1] * (1 - k)
    atr_pct = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(atr[i]) and closes[i] > 0:
            atr_pct[i] = atr[i] / closes[i]
    return atr_pct


def compute_atr_percentile_threshold(
    df: pd.DataFrame, atr_period: int, pctile: int,
) -> float:
    """전체 데이터에서 ATR_pct의 하위 N% 임계값 계산."""
    atr_pct = compute_atr_pct(
        df["high"].values, df["low"].values, df["close"].values, atr_period,
    )
    valid = atr_pct[~np.isnan(atr_pct)]
    if len(valid) < 50:
        return 0.0
    return float(np.percentile(valid, pctile))


def align_btc_to_eth(
    df_eth: pd.DataFrame, df_btc: pd.DataFrame, btc_sma_period: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """BTC close, SMA, momentum 배열을 ETH 인덱스에 맞춤."""
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, btc_sma_period)
    btc_close_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_close_aligned = btc_close_s.reindex(df_eth.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_eth.index, method="ffill").values
    return btc_close_aligned, btc_sma_aligned, btc_close.copy()


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    max_hold: int,
    base_trail: float,
    mom_scale: float,
    cooldown_bars: int,
    stop_loss: float,
    min_profit: float,
    vol_regime_threshold: float,
    btc_mom_lookback: int,
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
    atr_pct_arr = compute_atr_pct(h, lo, c, ATR_PERIOD)

    # BTC 모멘텀 계산 (btc_close_aligned 기반)
    btc_mom_arr = np.full(n, np.nan)
    if btc_mom_lookback > 0:
        for i in range(btc_mom_lookback, n):
            prev = btc_close_aligned[i - btc_mom_lookback]
            cur = btc_close_aligned[i]
            if prev > 0 and not np.isnan(prev) and not np.isnan(cur):
                btc_mom_arr[i] = cur / prev - 1

    # 모멘텀 중위값 (정규화 기준)
    valid_mom = mom_arr[~np.isnan(mom_arr)]
    positive_mom = valid_mom[valid_mom > 0]
    mom_median = float(np.median(positive_mom)) if len(positive_mom) > 10 else 0.005

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 ATR_PERIOD + 1, btc_mom_lookback + 1, 50) + 5
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
        atr_pct_val = atr_pct_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)):
            i += 1
            continue

        # -- 진입 조건 (c162 기본) --
        vpin_ok = (
            vpin_val < VPIN_LOW
            and mom_val >= VPIN_MOM
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )
        btc_sma_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )

        # ★ 새 필터 1: BTC 모멘텀 게이트
        btc_mom_ok = True
        if btc_mom_lookback > 0:
            if np.isnan(btc_mom_arr[i]) or btc_mom_arr[i] <= 0:
                btc_mom_ok = False

        # ★ 새 필터 2: 변동성 레짐 필터
        vol_ok = True
        if vol_regime_threshold > 0:
            if np.isnan(atr_pct_val) or atr_pct_val < vol_regime_threshold:
                vol_ok = False

        if vpin_ok and btc_sma_ok and btc_mom_ok and vol_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy

            # 적응형 트레일링: 진입 모멘텀 강도에 비례
            norm_mom = min(mom_val / (mom_median + 1e-9), 2.0)
            adaptive_trail = base_trail + mom_scale * norm_mom

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]
                ret = current_price / buy - 1

                # 고정 스톱로스
                if ret <= -stop_loss:
                    exit_ret = -stop_loss - FEE - slippage
                    i = j
                    break

                # 최고가 갱신
                if current_price > peak_price:
                    peak_price = current_price

                # 적응형 트레일링 스톱 (고정 minProfit)
                peak_ret = peak_price / buy - 1
                if peak_ret >= min_profit:
                    drawdown_from_peak = (peak_price - current_price) / peak_price
                    if drawdown_from_peak >= adaptive_trail:
                        exit_ret = ret - FEE - slippage
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
    print("=== vpin_eth c169 — 변동성 레짐 필터 + BTC 모멘텀 게이트 + 3-fold WF ===")
    print(f"심볼: {SYMBOL}  목표: OOS Sharpe >= 5.0 (all folds)")
    print("가설: ATR 하위 N% 차단 + BTC mom>0 게이트 → Fold 2/3 악조건 필터링")
    print("기준선: c162 OOS +7.011 (2-fold), c166 OOS +3.178 FAIL")
    print("=" * 80)

    # -- 전체 데이터 로드 --
    df_full = load_historical(SYMBOL, "240m", "2021-06-01", "2026-12-31")
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_full.empty or df_btc_full.empty:
        print("데이터 로드 실패.")
        return

    # ATR percentile 임계값 사전 계산 (전체 데이터 기준)
    vol_thresholds: dict[int, float] = {}
    for pctile in VOL_REGIME_PCTILE_LIST:
        vol_thresholds[pctile] = compute_atr_percentile_threshold(
            df_full, ATR_PERIOD, pctile,
        )
        print(f"  ATR percentile {pctile}%: threshold={vol_thresholds[pctile]:.6f}")

    # -- Phase 1: Fold 0 train 그리드 서치 (대표 fold로 필터링) --
    fold0 = WF_FOLDS[0]
    df_train = load_historical(SYMBOL, "240m", fold0["train"][0], fold0["train"][1])
    if df_train.empty:
        print("train 데이터 없음.")
        return
    print(f"\nPhase 1: train 데이터 {len(df_train)}행 "
          f"({fold0['train'][0]} ~ {fold0['train'][1]})")

    btc_c_tr, btc_sma_tr, _ = align_btc_to_eth(df_train, df_btc_full, BTC_SMA_PERIOD)

    combos = list(product(
        MAX_HOLD_LIST, BASE_TRAIL_LIST, MOM_SCALE_LIST,
        COOLDOWN_BARS_LIST, SL_LIST, MIN_PROFIT_LIST,
        VOL_REGIME_PCTILE_LIST, BTC_MOM_LOOKBACK_LIST,
    ))
    print(f"총 조합: {len(combos)}개")

    results: list[dict] = []
    for idx, (mh, bt, ms, cb, sl, mp, vp, bml) in enumerate(combos):
        if idx % 5000 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")
        vt = vol_thresholds[vp]
        r = backtest(df_train, mh, bt, ms, cb, sl, mp, vt, bml,
                     btc_c_tr, btc_sma_tr)
        results.append({
            "max_hold": mh, "base_trail": bt, "mom_scale": ms,
            "cooldown_bars": cb, "stop_loss": sl, "min_profit": mp,
            "vol_pctile": vp, "btc_mom_lb": bml, **r,
        })

    valid = [r for r in results
             if r["trades"] >= 15
             and not np.isnan(r["sharpe"])
             and r["sharpe"] > 0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=15, Sharpe>0): {len(valid)}/{len(results)}")
    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    print(f"\n=== Train Top 15 ===")
    hdr = (f"{'hold':>4} {'bTr':>5} {'mSc':>5} {'cool':>4} "
           f"{'SL':>5} {'minP':>5} {'vPct':>4} {'bMom':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        sh = f"{r['sharpe']:+.3f}"
        print(
            f"{r['max_hold']:>4} "
            f"{r['base_trail']:>5.3f} {r['mom_scale']:>5.3f} "
            f"{r['cooldown_bars']:>4} "
            f"{r['stop_loss']:>5.3f} {r['min_profit']:>5.3f} "
            f"{r['vol_pctile']:>4} {r['btc_mom_lb']:>4} | "
            f"{sh:>7} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    # -- Phase 2: 3-Fold Walk-Forward (Top 30 고유) --
    seen: set[tuple] = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["max_hold"], r["base_trail"], r["mom_scale"],
               r["cooldown_bars"], r["stop_loss"], r["min_profit"],
               r["vol_pctile"], r["btc_mom_lb"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 30:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-Fold Walk-Forward 검증 (Top {len(unique_top)} 고유) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        mh = params["max_hold"]
        bt = params["base_trail"]
        ms = params["mom_scale"]
        cb = params["cooldown_bars"]
        sl = params["stop_loss"]
        mp = params["min_profit"]
        vp = params["vol_pctile"]
        bml = params["btc_mom_lb"]
        vt = vol_thresholds[vp]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []

        for fold_i, fold in enumerate(WF_FOLDS):
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                continue
            btc_c_t, btc_sma_t, _ = align_btc_to_eth(
                df_test, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_test, mh, bt, ms, cb, sl, mp, vt, bml,
                         btc_c_t, btc_sma_t)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            total_oos_n = sum(oos_trades)
            # 각 fold 최소 n>=5 요구
            all_n_ok = all(t >= 5 for t in oos_trades)
            all_pass = all(s >= 3.0 for s in oos_sharpes) and all_n_ok
            status = "PASS" if all_pass else "FAIL"
            print(f"  #{rank}: hold={mh} bTr={bt} mSc={ms} cool={cb} "
                  f"SL={sl} minP={mp} vPct={vp} bMom={bml} | "
                  f"train={params['sharpe']:+.3f} -> avg_OOS={avg_oos:+.3f} "
                  f"min_OOS={min_oos:+.3f} total_n={total_oos_n} {status}")
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

    # -- Phase 3: 통과 결과 분석 --
    passed = [w for w in wf_results if w["all_pass"]]
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                       reverse=True)

    print(f"\n{'=' * 80}")
    print(f"=== WF 통과: {len(passed)}/{len(wf_results)} ===")

    if passed:
        passed_sorted = sorted(passed, key=lambda x: x["avg_oos_sharpe"],
                               reverse=True)
        print("\n  통과 목록 (avg OOS Sharpe 기준):")
        for i, w in enumerate(passed_sorted[:10], 1):
            folds_str = " | ".join(
                f"F{fi + 1}: Sh={sh:+.1f} n={nt}"
                for fi, (sh, nt) in enumerate(
                    zip(w["oos_sharpes"], w["oos_trades"]))
            )
            print(f"  {i}. avg={w['avg_oos_sharpe']:+.3f} "
                  f"hold={w['max_hold']} SL={w['stop_loss']} "
                  f"minP={w['min_profit']} vPct={w['vol_pctile']} "
                  f"bMom={w['btc_mom_lb']} [{folds_str}]")
        best_pool = passed_sorted
    else:
        print("  WF 통과 조합 없음 — 전체 OOS Top 사용")
        best_pool = wf_sorted

    # -- Phase 4: 슬리피지 스트레스 (Top 3) --
    wf_top3 = best_pool[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (Top 3) ===")

    btc_c_f, btc_sma_f, _ = align_btc_to_eth(df_full, df_btc_full, BTC_SMA_PERIOD)
    for rank, params in enumerate(wf_top3, 1):
        mh = params["max_hold"]
        bt = params["base_trail"]
        ms = params["mom_scale"]
        cb = params["cooldown_bars"]
        sl = params["stop_loss"]
        mp = params["min_profit"]
        vt = vol_thresholds[params["vol_pctile"]]
        bml = params["btc_mom_lb"]
        print(f"\n--- #{rank}: hold={mh} bTr={bt} mSc={ms} cool={cb} "
              f"SL={sl} minP={mp} vPct={params['vol_pctile']} bMom={bml} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_full, mh, bt, ms, cb, sl, mp, vt, bml,
                         btc_c_f, btc_sma_f, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # -- 최종 요약 --
    best = best_pool[0]
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"★ OOS 최적: hold={best['max_hold']} "
          f"bTr={best['base_trail']} mSc={best['mom_scale']} "
          f"cool={best['cooldown_bars']} "
          f"SL={best['stop_loss']} minP={best['min_profit']} "
          f"vPct={best['vol_pctile']} bMom={best['btc_mom_lb']}")
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
    all_wrs = [fd["wr"] for fd in best["fold_details"]]
    avg_wr = float(np.mean(all_wrs))

    print(f"\nSharpe: {oos_avg:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
