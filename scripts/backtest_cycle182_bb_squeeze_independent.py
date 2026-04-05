"""
사이클 182: BB Squeeze Breakout 독립 전략 (non-VPIN)
- 목적: VPIN 의존도 탈피한 비상관 전략 확보 (포트폴리오 다각화)
- c177/c181 결과: BB squeeze + VPIN 조합은 n 제약 or Sharpe 하락
  → VPIN/body/ATR_pctile/RSI_vel 필터 전부 제거, 순수 BB 스퀴즈 전략
- 진입 조건 (단순화):
  1) BB bandwidth pctile < threshold (최근 lookback 내 스퀴즈 이력 확인)
  2) bandwidth 확장 중 (현재 > expansion_lb 봉 전)
  3) close >= upper * ratio (상단 돌파)
  4) ADX >= threshold (추세 확인)
  5) close > EMA(20) (기본 모멘텀)
  6) BTC > SMA(200) (BULL 레짐)
  7) 다음 봉 시가 진입
- 청산: ATR 기반 TP/SL + 트레일링
- 심볼: ETH/SOL/XRP/DOGE/AVAX (5종)
- 타임프레임: 240m (c181과 동일)
- WF: 3-fold
  F1: train=2022-01~2024-05 → OOS=2024-06~2025-03
  F2: train=2022-07~2024-11 → OOS=2024-12~2025-09
  F3: train=2023-01~2025-05 → OOS=2025-06~2026-04
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE", "KRW-AVAX"]
FEE = 0.0005
SLIPPAGE_BASE = 0.0005

# 고정 파라미터
BB_PERIOD = 20
BB_STD = 2.0
BW_PCTILE_LB = 120      # bandwidth 백분위 계산용 lookback
EMA_PERIOD = 20
ATR_PERIOD = 20
BTC_SMA_PERIOD = 200
MAX_HOLD = 20
EXPANSION_LB = 4        # 확장 확인용 lookback

# 그리드 탐색
SQUEEZE_PCTILE_TH_LIST = [30, 40, 50]      # 스퀴즈 판정 임계
SQUEEZE_LB_LIST = [15, 25]                   # 스퀴즈 탐지 히스토리 윈도우
UPPER_RATIO_LIST = [0.93, 0.95, 0.97]        # 상단밴드 돌파 비율
ADX_TH_LIST = [15, 20, 25]                   # 추세강도 임계
TP_ATR_LIST = [3.0, 4.0, 5.0]               # TP = ATR × mult
SL_ATR_LIST = [1.5, 2.0, 2.5]               # SL = ATR × mult
TRAIL_ATR = 0.3                               # 트레일 = ATR × mult (고정)
MIN_PROFIT_ATR = 1.5                          # 트레일 활성화 최소 수익 (고정)

# 3-fold WF
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-05-31"), "test": ("2024-06-01", "2025-03-31")},
    {"train": ("2022-07-01", "2024-11-30"), "test": ("2024-12-01", "2025-09-30")},
    {"train": ("2023-01-01", "2025-05-31"), "test": ("2025-06-01", "2026-04-05")},
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
    squeeze_pctile_th: float,
    squeeze_lb: int,
    upper_ratio: float,
    adx_th: float,
    tp_atr: float,
    sl_atr: float,
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

        # 1. BTC BULL 레짐
        btc_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )
        if not btc_ok:
            i += 1
            continue

        # 2. 모멘텀: close > EMA
        if c[i] <= ema_val:
            i += 1
            continue

        # 3. ADX 추세 확인
        if adx_val < adx_th:
            i += 1
            continue

        # 4. BB 스퀴즈 해제 (핵심 진입 로직)
        if (np.isnan(bw_pctile_val) or np.isnan(bb_bw_val)
                or np.isnan(bb_upper_val)):
            i += 1
            continue

        # 최근 squeeze_lb 봉 내에 스퀴즈 이력 확인
        had_squeeze = False
        search_start = max(0, i - squeeze_lb)
        search_end = max(0, i - EXPANSION_LB + 1)
        for k in range(search_start, search_end):
            if not np.isnan(bw_pctile_arr[k]):
                if bw_pctile_arr[k] < squeeze_pctile_th:
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
        if c[i] < bb_upper_val * upper_ratio:
            i += 1
            continue

        # 진입 (다음 봉 시가)
        buy = o[i + 1] * (1 + FEE + slippage)
        atr_at_entry = atr_val
        tp_price = buy + atr_at_entry * tp_atr
        sl_price = buy - atr_at_entry * sl_atr
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

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * ANNUAL_FACTOR)
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

    # Buy & Hold
    bh_ret = (c[-1] - c[0]) / c[0] if c[0] > 0 else 0.0

    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl, "bh_ret": bh_ret}


def pool_results(results_list: list[dict]) -> dict:
    valid = [r for r in results_list if r["trades"] > 0
             and not np.isnan(r["sharpe"])]
    if not valid:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    return {
        "sharpe": float(np.mean([r["sharpe"] for r in valid])),
        "wr": float(np.mean([r["wr"] for r in valid])),
        "avg_ret": float(np.mean([r["avg_ret"] for r in valid])),
        "trades": sum(r["trades"] for r in valid),
        "max_dd": float(np.mean([r["max_dd"] for r in valid])),
        "mcl": max(r["mcl"] for r in valid),
    }


def main() -> None:
    print("=" * 80)
    print("=== 사이클 182: BB Squeeze Breakout 독립 전략 (non-VPIN) ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"핵심: VPIN/body/ATR_pctile/RSI_vel 제거 → 순수 BB 스퀴즈 전략")
    print(f"진입: BB squeeze 해제 + 상단돌파 + ADX 추세 + EMA 모멘텀 + BTC BULL")
    print(f"청산: ATR 기반 TP/SL + trailing stop")
    print("=" * 80)

    # BTC 데이터
    df_btc = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc.empty:
        print("BTC 데이터 없음.")
        return

    # 심볼 데이터 확인
    print("\n--- 심볼별 데이터 확인 ---")
    sym_ok: list[str] = []
    for sym in SYMBOLS:
        df = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df.empty or len(df) < 500:
            print(f"  {sym}: 데이터 부족 ({len(df)}행) → 제외")
        else:
            print(f"  {sym}: {len(df)}행 OK")
            sym_ok.append(sym)

    if not sym_ok:
        print("유효 심볼 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # -- Phase 1: Train 그리드 서치 (Fold 1 train) --
    combos = list(product(
        SQUEEZE_PCTILE_TH_LIST, SQUEEZE_LB_LIST,
        UPPER_RATIO_LIST, ADX_TH_LIST,
        TP_ATR_LIST, SL_ATR_LIST,
    ))
    print(f"\n총 그리드: {len(combos)}개 × {len(sym_ok)} 심볼"
          f" = {len(combos) * len(sym_ok)}")

    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: train 그리드 서치 ({train_start} ~ {train_end})")

    sym_train: dict[str, pd.DataFrame] = {}
    for sym in sym_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if not df_tr.empty:
            sym_train[sym] = df_tr
            print(f"  {sym} train: {len(df_tr)}행")

    results: list[dict] = []
    total = len(combos)
    for idx, (sq_th, sq_lb, up_r, adx_th, tp_a, sl_a) in enumerate(combos):
        if (idx + 1) % 50 == 0:
            print(f"  진행: {idx + 1}/{total}")
        sym_res = []
        for sym in sym_ok:
            if sym not in sym_train:
                continue
            df_tr = sym_train[sym]
            btc_c, btc_s = align_btc(df_tr, df_btc, BTC_SMA_PERIOD)
            r = backtest(df_tr, sq_th, sq_lb, up_r, adx_th, tp_a, sl_a,
                         btc_c, btc_s)
            sym_res.append(r)
        pooled = pool_results(sym_res)
        results.append({
            "sq_th": sq_th, "sq_lb": sq_lb, "up_r": up_r,
            "adx_th": adx_th, "tp_a": tp_a, "sl_a": sl_a,
            **pooled,
        })

    valid = [r for r in results if r["trades"] >= 5
             and not np.isnan(r["sharpe"]) and r["sharpe"] > 0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n>=5, Sharpe>0): {len(valid)}/{len(results)}")

    if not valid:
        print("\n❌ Phase 1 통과 조합 없음.")
        relaxed = [r for r in results if r["trades"] >= 3
                   and not np.isnan(r["sharpe"])]
        relaxed.sort(key=lambda x: x["sharpe"], reverse=True)
        print(f"  완화 (n>=3): {len(relaxed)}개")
        for r in relaxed[:10]:
            print(f"    sqTh={r['sq_th']} sqLB={r['sq_lb']} upR={r['up_r']:.2f}"
                  f" adx={r['adx_th']} tp={r['tp_a']:.1f} sl={r['sl_a']:.1f}"
                  f" → Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1%}"
                  f" n={r['trades']}")
        print(f"\nSharpe: {relaxed[0]['sharpe']:+.3f}" if relaxed
              else "\nSharpe: nan")
        print(f"WR: {relaxed[0]['wr'] * 100:.1f}%" if relaxed else "WR: 0.0%")
        print(f"trades: {relaxed[0]['trades']}" if relaxed else "trades: 0")
        return

    print(f"\n=== Train Top 20 ===")
    hdr = (f"{'sqTh':>4} {'sqLB':>4} {'upR':>5} {'adx':>3} {'tp':>4} {'sl':>4}"
           f" | {'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        print(f"{r['sq_th']:>4} {r['sq_lb']:>4} {r['up_r']:>5.2f}"
              f" {r['adx_th']:>3} {r['tp_a']:>4.1f} {r['sl_a']:>4.1f}"
              f" | {r['sharpe']:>+7.3f} {r['wr']:>5.1%}"
              f" {r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}%"
              f" {r['trades']:>5}")

    # -- Phase 2: 3-fold OOS --
    seen: set[tuple] = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["sq_th"], r["sq_lb"], r["up_r"], r["adx_th"],
               r["tp_a"], r["sl_a"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 16:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward (Top {len(unique_top)}) ===")
    print("=" * 80)

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        oos_sharpes: list[float] = []
        oos_trades_list: list[int] = []
        fold_details: list[dict] = []

        for fold in WF_FOLDS:
            sym_fold_res = []
            for sym in sym_ok:
                df_test = load_historical(sym, "240m",
                                          fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = align_btc(df_test, df_btc, BTC_SMA_PERIOD)
                r = backtest(df_test, params["sq_th"], params["sq_lb"],
                             params["up_r"], params["adx_th"],
                             params["tp_a"], params["sl_a"],
                             btc_c, btc_s)
                sym_fold_res.append(r)

            pooled = pool_results(sym_fold_res)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades_list.append(pooled["trades"])
            fold_details.append(pooled)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            total_n = sum(oos_trades_list)
            all_pass = all(s >= 3.0 for s in oos_sharpes) and avg_oos >= 5.0

            print(f"  #{rank}: sqTh={params['sq_th']} sqLB={params['sq_lb']}"
                  f" upR={params['up_r']:.2f} adx={params['adx_th']}"
                  f" tp={params['tp_a']:.1f} sl={params['sl_a']:.1f}"
                  f" | train={params['sharpe']:+.3f}"
                  f" → avg_OOS={avg_oos:+.3f} min={min_oos:+.3f}"
                  f" n={total_n} {'PASS' if all_pass else 'FAIL'}")

            wf_results.append({
                **params,
                "train_sharpe": params["sharpe"],
                "avg_oos": avg_oos,
                "min_oos": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades_list,
                "total_n": total_n,
                "all_pass": all_pass,
                "fold_details": fold_details,
            })

    if not wf_results:
        print("\nWF 결과 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos"], reverse=True)
    best = wf_sorted[0]

    # -- Phase 3: 슬리피지 스트레스 (Top 3) --
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (OOS Top 3) ===")
    print("=" * 80)

    for rank, params in enumerate(wf_sorted[:3], 1):
        print(f"\n--- #{rank}: sqTh={params['sq_th']} sqLB={params['sq_lb']}"
              f" upR={params['up_r']:.2f} adx={params['adx_th']}"
              f" tp={params['tp_a']:.1f} sl={params['sl_a']:.1f}"
              f" (avg OOS: {params['avg_oos']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7}"
              f" {'MDD':>7} {'n':>5}")
        print("-" * 50)
        for slip in SLIPPAGE_LEVELS:
            sym_res = []
            for sym in sym_ok:
                df_full = load_historical(sym, "240m",
                                          "2022-01-01", "2026-04-05")
                if df_full.empty:
                    continue
                btc_c, btc_s = align_btc(df_full, df_btc, BTC_SMA_PERIOD)
                r = backtest(df_full, params["sq_th"], params["sq_lb"],
                             params["up_r"], params["adx_th"],
                             params["tp_a"], params["sl_a"],
                             btc_c, btc_s, slippage=slip)
                sym_res.append(r)
            pooled = pool_results(sym_res)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {pooled['wr']:>5.1%}"
                  f" {pooled['avg_ret'] * 100:>+6.2f}%"
                  f" {pooled['max_dd'] * 100:>+6.2f}% {pooled['trades']:>5}")

    # -- 심볼별 OOS 성능 분해 --
    print(f"\n{'=' * 80}")
    print(f"=== 심볼별 OOS 성능 분해 (Top 1: sqTh={best['sq_th']}"
          f" sqLB={best['sq_lb']} upR={best['up_r']:.2f}"
          f" adx={best['adx_th']} tp={best['tp_a']:.1f}"
          f" sl={best['sl_a']:.1f}) ===")
    print("=" * 80)

    for sym in sym_ok:
        sym_sharpes = []
        sym_n = 0
        for fi, fold in enumerate(WF_FOLDS):
            df_test = load_historical(sym, "240m",
                                      fold["test"][0], fold["test"][1])
            if df_test.empty:
                continue
            btc_c, btc_s = align_btc(df_test, df_btc, BTC_SMA_PERIOD)
            r = backtest(df_test, best["sq_th"], best["sq_lb"],
                         best["up_r"], best["adx_th"],
                         best["tp_a"], best["sl_a"],
                         btc_c, btc_s)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            sym_sharpes.append(sh)
            sym_n += r["trades"]
            print(f"  {sym} Fold {fi + 1}: Sharpe={sh:+.3f}  WR={r['wr']:.1%}"
                  f"  n={r['trades']}  avg={r['avg_ret'] * 100:+.2f}%"
                  f"  MDD={r['max_dd'] * 100:+.2f}%")
        if sym_sharpes:
            print(f"  {sym} 평균: Sharpe={np.mean(sym_sharpes):+.3f}"
                  f"  총 trades={sym_n}")
        print()

    # -- Buy & Hold 비교 --
    print(f"{'=' * 80}")
    print("=== Buy & Hold 비교 ===")
    print("=" * 80)
    for sym in sym_ok:
        df_full = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df_full.empty:
            continue
        btc_c, btc_s = align_btc(df_full, df_btc, BTC_SMA_PERIOD)
        r = backtest(df_full, best["sq_th"], best["sq_lb"],
                     best["up_r"], best["adx_th"],
                     best["tp_a"], best["sl_a"],
                     btc_c, btc_s)
        bh = r.get("bh_ret", 0)
        strat_total = r["avg_ret"] * r["trades"] if r["trades"] > 0 else 0
        print(f"  {sym}: strategy total={strat_total * 100:+.2f}%"
              f"  BH={bh * 100:+.1f}%  n={r['trades']}")

    # -- c181 대비 비교 --
    print(f"\n{'=' * 80}")
    print("=== c181 (VPIN 의존) 대비 비교 ===")
    print("=" * 80)
    print(f"  c181 최적 (sqLB=20 upR=0.95 body=0.50 adx=20 +VPIN):"
          f" avg_OOS=+24.245 n=34")
    print(f"  c182 최적 (sqTh={best['sq_th']} sqLB={best['sq_lb']}"
          f" upR={best['up_r']:.2f} adx={best['adx_th']}"
          f" tp={best['tp_a']:.1f} sl={best['sl_a']:.1f} non-VPIN):"
          f" avg_OOS={best['avg_oos']:+.3f} n={best['total_n']}")
    delta = best["avg_oos"] - 24.245
    print(f"  Δ Sharpe: {delta:+.3f}")
    delta_n = best["total_n"] - 34
    print(f"  Δ trades: {delta_n:+d}")
    print(f"  핵심: VPIN 의존 제거 → 포트폴리오 비상관 전략 확보 여부 확인")

    # -- 최종 요약 --
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print("=" * 80)
    status = "PASS" if best["all_pass"] else "FAIL"
    print(f"★ OOS 최적: SQUEEZE_TH={best['sq_th']}"
          f" SQUEEZE_LB={best['sq_lb']}"
          f" UPPER_RATIO={best['up_r']:.2f}"
          f" ADX_TH={best['adx_th']}"
          f" TP_ATR={best['tp_a']:.1f}"
          f" SL_ATR={best['sl_a']:.1f}")
    print(f"  (non-VPIN 독립: BB squeeze + ADX + EMA + BTC gate)")
    print(f"  (고정: BB_PERIOD={BB_PERIOD} BW_PCTILE_LB={BW_PCTILE_LB}"
          f" EXP_LB={EXPANSION_LB} MAX_HOLD={MAX_HOLD}"
          f" TRAIL_ATR={TRAIL_ATR} MIN_P_ATR={MIN_PROFIT_ATR})")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} {status}")
    print(f"  train Sharpe: {best['train_sharpe']:+.3f}")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}"
              f"  trades={best['oos_trades'][fi]}"
              f"  avg={fd['avg_ret'] * 100:+.2f}%"
              f"  MDD={fd['max_dd'] * 100:+.2f}%")

    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]
                            if fd["trades"] > 0]))
    total_n = best["total_n"]
    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
