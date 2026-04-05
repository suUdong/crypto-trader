"""
사이클 215: BB Squeeze 개별 심볼 3-fold WF 스크리닝
- 목적: c182 검증 파라미터로 개별 심볼 성능 분해 → daemon 배포 적격 심볼 식별
- 배경: c182는 5심볼 pooled Sharpe +12.291. SOL/DOGE는 daemon 배포됐으나
  개별 WF 미검증(평가자 블로커). XRP/LINK/AVAX 추가 스크리닝(평가자 [explore]).
- 파라미터: c182 최적 고정 (그리드 탐색 없음, 순수 검증)
  sqPth=40, sqLB=15, upR=0.97, adxTh=25, tpATR=5.0, slATR=2.0
- 심볼: SOL, DOGE, XRP, LINK, AVAX (ETH는 c185에서 검증 완료)
- WF: 3-fold (c182 대비 1개월 시프트, OOS 중복 최소화)
  F1: train=2022-02~2024-06 → OOS=2024-07~2025-04
  F2: train=2022-09~2025-01 → OOS=2025-02~2025-10
  F3: train=2023-03~2025-07 → OOS=2025-08~2026-04
- 기준: 개별 Sharpe > 5.0 AND 총 n ≥ 10 → daemon 적격
- 슬리피지: 0.0005 (기본) + 스트레스 0.0010~0.0020
- 🔄다음봉시가진입 | ★슬리피지포함
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SCREEN_SYMBOLS = ["KRW-SOL", "KRW-DOGE", "KRW-XRP", "KRW-LINK", "KRW-AVAX"]
FEE = 0.0005
SLIPPAGE_BASE = 0.0005

# c182 검증 완료 고정 파라미터
BB_PERIOD = 20
BB_STD = 2.0
BW_PCTILE_LB = 120
EMA_PERIOD = 20
ATR_PERIOD = 20
BTC_SMA_PERIOD = 200
MAX_HOLD = 20
EXPANSION_LB = 4
TRAIL_ATR = 0.3
MIN_PROFIT_ATR = 1.5

# c182 최적 파라미터 (고정)
SQUEEZE_PCTILE_TH = 40.0
SQUEEZE_LB = 15
UPPER_RATIO = 0.97
ADX_TH = 25.0
TP_ATR = 5.0
SL_ATR = 2.0

# 3-fold WF (c182 대비 1개월 시프트)
WF_FOLDS = [
    {"train": ("2022-02-01", "2024-06-30"), "test": ("2024-07-01", "2025-04-30")},
    {"train": ("2022-09-01", "2025-01-31"), "test": ("2025-02-01", "2025-10-31")},
    {"train": ("2023-03-01", "2025-07-31"), "test": ("2025-08-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]
ANNUAL_FACTOR = np.sqrt(365 * 6)  # 240m = 6 bars/day


# -- 지표 --

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


def compute_bb(
    closes: np.ndarray, period: int = 20, num_std: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(closes)
    middle = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    bw = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        middle[i] = m
        upper[i] = m + num_std * s
        lower[i] = m - num_std * s
        if m > 0:
            bw[i] = (upper[i] - lower[i]) / m * 100.0
        else:
            bw[i] = 0.0
    return middle, upper, lower, bw


def compute_bw_percentile(bw_arr: np.ndarray, lookback: int = 120) -> np.ndarray:
    n = len(bw_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = bw_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        current = bw_arr[i]
        if np.isnan(current):
            continue
        result[i] = float(np.sum(valid < current)) / len(valid) * 100.0
    return result


def compute_adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
) -> np.ndarray:
    n = len(closes)
    adx = np.full(n, np.nan)
    if n < period * 2 + 1:
        return adx
    tr = np.full(n, 0.0)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    plus_dm = np.full(n, 0.0)
    minus_dm = np.full(n, 0.0)
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
    atr_s = np.full(n, np.nan)
    plus_dm_s = np.full(n, np.nan)
    minus_dm_s = np.full(n, np.nan)
    atr_s[period] = np.sum(tr[1:period + 1])
    plus_dm_s[period] = np.sum(plus_dm[1:period + 1])
    minus_dm_s[period] = np.sum(minus_dm[1:period + 1])
    for i in range(period + 1, n):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        plus_dm_s[i] = plus_dm_s[i - 1] - plus_dm_s[i - 1] / period + plus_dm[i]
        minus_dm_s[i] = minus_dm_s[i - 1] - minus_dm_s[i - 1] / period + minus_dm[i]
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if np.isnan(atr_s[i]) or atr_s[i] <= 0:
            continue
        plus_di = 100.0 * plus_dm_s[i] / atr_s[i]
        minus_di = 100.0 * minus_dm_s[i] / atr_s[i]
        di_sum = plus_di + minus_di
        if di_sum > 0:
            dx[i] = 100.0 * abs(plus_di - minus_di) / di_sum
    start_idx = period * 2
    if start_idx >= n:
        return adx
    dx_window = []
    for i in range(period, start_idx + 1):
        if not np.isnan(dx[i]):
            dx_window.append(dx[i])
    if len(dx_window) < period:
        return adx
    adx[start_idx] = np.mean(dx_window[-period:])
    for i in range(start_idx + 1, n):
        if np.isnan(dx[i]) or np.isnan(adx[i - 1]):
            adx[i] = adx[i - 1] if not np.isnan(adx[i - 1]) else np.nan
            continue
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def align_btc(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame, sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, sma_period)
    btc_c_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    return (
        btc_c_s.reindex(df_sym.index, method="ffill").values,
        btc_sma_s.reindex(df_sym.index, method="ffill").values,
    )


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    lo = df["low"].values.astype(float)
    n = len(c)

    ema_arr = ema_calc(c, EMA_PERIOD)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    adx_arr = compute_adx(h, lo, c, 14)
    _mid, bb_upper, _lower, bb_bw = compute_bb(c, BB_PERIOD, BB_STD)
    bw_pctile_arr = compute_bw_percentile(bb_bw, BW_PCTILE_LB)

    returns: list[float] = []
    warmup = max(BW_PCTILE_LB, BTC_SMA_PERIOD, ATR_PERIOD, 30) + 5

    i = warmup
    while i < n - 1:
        ema_val = ema_arr[i]
        atr_val = atr_arr[i]
        adx_val = adx_arr[i]
        bw_pctile_val = bw_pctile_arr[i]
        bb_upper_val = bb_upper[i]
        bb_bw_val = bb_bw[i]

        if (np.isnan(ema_val) or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(adx_val)):
            i += 1
            continue

        # BTC BULL 레짐
        btc_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )
        if not btc_ok:
            i += 1
            continue

        # 모멘텀: close > EMA
        if c[i] <= ema_val:
            i += 1
            continue

        # ADX 추세 확인
        if adx_val < ADX_TH:
            i += 1
            continue

        # BB 스퀴즈 해제
        if (np.isnan(bw_pctile_val) or np.isnan(bb_bw_val)
                or np.isnan(bb_upper_val)):
            i += 1
            continue

        # 최근 SQUEEZE_LB 봉 내에 스퀴즈 이력 확인
        had_squeeze = False
        search_start = max(0, i - SQUEEZE_LB)
        search_end = max(0, i - EXPANSION_LB + 1)
        for k in range(search_start, search_end):
            if not np.isnan(bw_pctile_arr[k]):
                if bw_pctile_arr[k] < SQUEEZE_PCTILE_TH:
                    had_squeeze = True
                    break
        if not had_squeeze:
            i += 1
            continue

        # bandwidth 확장 중
        expanding = False
        if i - EXPANSION_LB >= 0:
            prev_bw = bb_bw[i - EXPANSION_LB]
            if not np.isnan(prev_bw) and prev_bw > 0:
                expanding = bb_bw_val > prev_bw
        if not expanding:
            i += 1
            continue

        # 상단밴드 돌파
        if c[i] < bb_upper_val * UPPER_RATIO:
            i += 1
            continue

        # 진입 (다음 봉 시가)
        buy = o[i + 1] * (1 + FEE + slippage)
        atr_at_entry = atr_val
        tp_price = buy + atr_at_entry * TP_ATR
        sl_price = buy - atr_at_entry * SL_ATR
        trail_dist = atr_at_entry * TRAIL_ATR
        min_profit_dist = atr_at_entry * MIN_PROFIT_ATR
        peak_price = buy

        exit_ret = None
        for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
            cur_price = c[j]

            if cur_price >= tp_price:
                exit_ret = (tp_price / buy - 1) - FEE - slippage
                i = j
                break

            if cur_price <= sl_price:
                exit_ret = (sl_price / buy - 1) - FEE - slippage
                i = j
                break

            if cur_price > peak_price:
                peak_price = cur_price

            unrealized = peak_price - buy
            if unrealized >= min_profit_dist:
                if peak_price - cur_price >= trail_dist:
                    exit_ret = (cur_price / buy - 1) - FEE - slippage
                    i = j
                    break

        if exit_ret is None:
            hold_end = min(i + MAX_HOLD, n - 1)
            exit_ret = c[hold_end] / buy - 1 - FEE - slippage
            i = hold_end

        returns.append(exit_ret)
        i += 1

    if len(returns) < 1:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0}

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * ANNUAL_FACTOR)
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0

    # Buy & Hold
    df_c = df["close"].values
    bh_ret = (df_c[-1] - df_c[0]) / df_c[0] if df_c[0] > 0 else 0.0

    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "bh_ret": bh_ret}


def main() -> None:
    print("=" * 80)
    print("=== 사이클 215: BB Squeeze 개별 심볼 3-fold WF 스크리닝 ===")
    print(f"심볼: {', '.join(SCREEN_SYMBOLS)}")
    print(f"고정 파라미터 (c182 최적): sqPth={SQUEEZE_PCTILE_TH} sqLB={SQUEEZE_LB}"
          f" upR={UPPER_RATIO} adxTh={ADX_TH} tpATR={TP_ATR} slATR={SL_ATR}")
    print(f"기준: 개별 avg OOS Sharpe > 5.0 AND 총 n ≥ 10 → daemon 적격")
    print("=" * 80)

    # BTC 데이터
    df_btc = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc.empty:
        print("BTC 데이터 없음.")
        return

    # 심볼 데이터 확인
    print("\n--- 심볼별 데이터 확인 ---")
    sym_data: dict[str, pd.DataFrame] = {}
    for sym in SCREEN_SYMBOLS:
        df = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df.empty or len(df) < 500:
            print(f"  {sym}: 데이터 부족 ({len(df)}행) → 제외")
        else:
            print(f"  {sym}: {len(df)}행 OK")
            sym_data[sym] = df

    if not sym_data:
        print("유효 심볼 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # -- 심볼별 3-fold WF --
    all_results: dict[str, list[dict]] = {}

    for sym, df_full in sym_data.items():
        print(f"\n{'=' * 60}")
        print(f"=== {sym} 개별 WF 검증 ===")
        fold_results = []

        for fi, fold in enumerate(WF_FOLDS):
            # Train (검증 전용이므로 train은 참고용)
            tr_start, tr_end = fold["train"]
            te_start, te_end = fold["test"]

            df_train = df_full.loc[tr_start:tr_end]
            df_test = df_full.loc[te_start:te_end]

            if len(df_test) < 50:
                print(f"  Fold {fi+1} OOS 데이터 부족 ({len(df_test)}행)")
                fold_results.append(
                    {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                     "trades": 0, "max_dd": 0.0})
                continue

            # BTC 정렬
            btc_c, btc_sma = align_btc(df_test, df_btc, BTC_SMA_PERIOD)

            # OOS 백테스트
            res = backtest(df_test, btc_c, btc_sma, SLIPPAGE_BASE)
            fold_results.append(res)

            print(f"  Fold {fi+1} OOS ({te_start}~{te_end}): "
                  f"Sharpe={res['sharpe']:+.3f}  WR={res['wr']:.1%}  "
                  f"n={res['trades']}  avg={res['avg_ret']:+.2%}  "
                  f"MDD={res['max_dd']:+.4f}")

        all_results[sym] = fold_results

        # 심볼 요약
        valid = [r for r in fold_results
                 if r["trades"] > 0 and not np.isnan(r["sharpe"])]
        if valid:
            avg_sharpe = np.mean([r["sharpe"] for r in valid])
            total_n = sum(r["trades"] for r in valid)
            avg_wr = np.mean([r["wr"] for r in valid])
            status = "✅ PASS" if avg_sharpe > 5.0 and total_n >= 10 else "❌ FAIL"
            print(f"  → {sym} 요약: avg Sharpe={avg_sharpe:+.3f}  "
                  f"총n={total_n}  avgWR={avg_wr:.1%}  {status}")
        else:
            print(f"  → {sym} 요약: 유효 Fold 없음 ❌ FAIL")

    # -- 슬리피지 스트레스 (PASS 심볼만) --
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (PASS 심볼) ===")

    pass_symbols = []
    for sym, folds in all_results.items():
        valid = [r for r in folds
                 if r["trades"] > 0 and not np.isnan(r["sharpe"])]
        if valid:
            avg_sh = np.mean([r["sharpe"] for r in valid])
            total_n = sum(r["trades"] for r in valid)
            if avg_sh > 5.0 and total_n >= 10:
                pass_symbols.append(sym)

    if not pass_symbols:
        print("  PASS 심볼 없음 — 스트레스 테스트 불필요")
    else:
        for sym in pass_symbols:
            print(f"\n  {sym}:")
            df_full = sym_data[sym]
            for slip in SLIPPAGE_LEVELS:
                fold_sharpes = []
                fold_n = 0
                for fi, fold in enumerate(WF_FOLDS):
                    te_start, te_end = fold["test"]
                    df_test = df_full.loc[te_start:te_end]
                    if len(df_test) < 50:
                        continue
                    btc_c, btc_sma = align_btc(df_test, df_btc, BTC_SMA_PERIOD)
                    res = backtest(df_test, btc_c, btc_sma, slip)
                    if res["trades"] > 0 and not np.isnan(res["sharpe"]):
                        fold_sharpes.append(res["sharpe"])
                        fold_n += res["trades"]
                if fold_sharpes:
                    avg_sh = np.mean(fold_sharpes)
                    print(f"    slip={slip:.4f}: avgSharpe={avg_sh:+.3f}  n={fold_n}")
                else:
                    print(f"    slip={slip:.4f}: 유효 결과 없음")

    # -- Buy & Hold 대비 --
    print(f"\n{'=' * 80}")
    print("=== Buy & Hold 대비 수익률 (전체 OOS 구간) ===")
    for sym, folds in all_results.items():
        valid = [r for r in folds
                 if r["trades"] > 0 and not np.isnan(r["sharpe"])]
        if valid:
            avg_strat = np.mean([r["avg_ret"] for r in valid])
            # B&H는 마지막 fold에서 추정
            bh = folds[-1].get("bh_ret", 0.0) if folds else 0.0
            excess = avg_strat * sum(r["trades"] for r in valid) - bh
            print(f"  {sym}: 전략 avgRet={avg_strat:+.2%}/거래  "
                  f"B&H(F3)={bh:+.2%}  ")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    total_sharpe_sum = 0.0
    total_sharpe_cnt = 0
    total_trades = 0
    total_wr_sum = 0.0
    total_wr_cnt = 0

    for sym, folds in all_results.items():
        valid = [r for r in folds
                 if r["trades"] > 0 and not np.isnan(r["sharpe"])]
        if valid:
            avg_sh = np.mean([r["sharpe"] for r in valid])
            total_n = sum(r["trades"] for r in valid)
            avg_wr = np.mean([r["wr"] for r in valid])
            status = "✅ PASS" if avg_sh > 5.0 and total_n >= 10 else "❌ FAIL"
            print(f"  {sym}: avg OOS Sharpe={avg_sh:+.3f}  n={total_n}  "
                  f"WR={avg_wr:.1%}  {status}")
            total_sharpe_sum += avg_sh
            total_sharpe_cnt += 1
            total_trades += total_n
            total_wr_sum += avg_wr
            total_wr_cnt += 1
        else:
            print(f"  {sym}: 유효 데이터 없음 ❌ FAIL")

    if total_sharpe_cnt > 0:
        overall_sharpe = total_sharpe_sum / total_sharpe_cnt
        overall_wr = total_wr_sum / total_wr_cnt
    else:
        overall_sharpe = float("nan")
        overall_wr = 0.0

    print(f"\n  daemon 적격: {', '.join(pass_symbols) if pass_symbols else '없음'}")
    print(f"  (c182 고정: sqPth={SQUEEZE_PCTILE_TH} sqLB={SQUEEZE_LB}"
          f" upR={UPPER_RATIO} adxTh={ADX_TH})")
    print(f"  (TP/SL: tpATR={TP_ATR} slATR={SL_ATR}"
          f" trail={TRAIL_ATR} minP={MIN_PROFIT_ATR})")
    print(f"  (BB: bbP={BB_PERIOD} bbS={BB_STD} bwLB={BW_PCTILE_LB}"
          f" expLB={EXPANSION_LB})")
    print(f"  avg OOS Sharpe: {overall_sharpe:+.3f}"
          f" {'PASS' if overall_sharpe > 5.0 else 'FAIL'}")

    print(f"\nSharpe: {overall_sharpe:+.3f}")
    print(f"WR: {overall_wr:.1%}")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
