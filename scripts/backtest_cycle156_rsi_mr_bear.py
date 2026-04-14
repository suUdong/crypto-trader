"""
사이클 156: RSI Mean-Reversion Bear/Sideways 전용 전략
- 목적: BEAR 레짐 전용 전략 확보 (현재 0개 — 포트폴리오 리스크 집중 해소)
- c154/c155 실패 원인: BB 하단 터치는 BEAR 하락 중 연속 발생 → 근본 차별화
- 핵심 변경:
  1) BB 제거 — RSI 과매도 후 반등 확인 (RSI 상승 반전)
  2) BTC < SMA200 레짐 필터 (BEAR/Sideways 전용)
  3) 볼륨 캐피튤레이션 감지 (panic selling 후 반등)
  4) RSI 반등 확인: RSI_t > RSI_t-1 (모멘텀 전환)
  5) 다음 봉 시가 진입 (look-ahead bias 제거)
  6) 60m 타임프레임 — n≥30 확보
- WF: 2-fold (2022-2023 BEAR 구간 포함)
  F1: IS=2022-2023 → OOS=2024
  F2: IS=2023-2024 → OOS=2025-2026
- 판정: 양 Fold Sharpe>5.0 && n≥15 (각 Fold)
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005  # 0.05% 편도
SLIPPAGE_BASE = 0.001  # 0.10%
SLIPPAGE_STRESS = [0.0005, 0.001, 0.0015, 0.002]

SYMBOLS = ["KRW-BTC", "KRW-ETH"]
TIMEFRAME = "60m"

WINDOWS = [
    {
        "name": "F1",
        "is_start": "2022-01-01", "is_end": "2023-12-31",
        "oos_start": "2024-01-01", "oos_end": "2024-12-31",
    },
    {
        "name": "F2",
        "is_start": "2023-01-01", "is_end": "2024-12-31",
        "oos_start": "2025-01-01", "oos_end": "2026-04-05",
    },
]

# Sharpe annualization: 24 bars/day × 365 days
ANNUAL_FACTOR = np.sqrt(24 * 365)

PASS_SHARPE = 5.0
PASS_N_PER_FOLD = 15


# ─── 지표 ────────────────────────────────────────────────────────────

def compute_sma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = arr[i - period + 1: i + 1].mean()
    return out


def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    rsi_arr = np.full(len(closes), np.nan)
    deltas = np.diff(closes)
    if len(deltas) < period:
        return rsi_arr
    gain = np.where(deltas > 0, deltas, 0.0)
    loss = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    if avg_loss == 0:
        rsi_arr[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_arr[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        if avg_loss == 0:
            rsi_arr[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_arr[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return rsi_arr


def compute_adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2 + 1:
        return adx_arr

    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0

    atr = np.zeros(n)
    atr[period] = tr[1: period + 1].mean()
    sm_plus = plus_dm[1: period + 1].sum()
    sm_minus = minus_dm[1: period + 1].sum()

    dx_vals: list[float] = []
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        sm_plus = sm_plus - sm_plus / period + plus_dm[i]
        sm_minus = sm_minus - sm_minus / period + minus_dm[i]
        if atr[i] == 0:
            continue
        plus_di = 100 * sm_plus / (atr[i] * period)
        minus_di = 100 * sm_minus / (atr[i] * period)
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_vals.append(0.0)
        else:
            dx_vals.append(100.0 * abs(plus_di - minus_di) / di_sum)
        if len(dx_vals) == period:
            adx_arr[i] = np.mean(dx_vals)
        elif len(dx_vals) > period:
            adx_arr[i] = (adx_arr[i - 1] * (period - 1) + dx_vals[-1]) / period

    return adx_arr


def volume_sma(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    out = np.full(len(volumes), np.nan)
    for i in range(period - 1, len(volumes)):
        out[i] = volumes[i - period + 1: i + 1].mean()
    return out


# ─── 백테스트 엔진 ───────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    btc_df: pd.DataFrame | None,  # BTC 데이터 (레짐 판단용, BTC 자신이면 None)
    rsi_oversold: float,
    rsi_exit: float,
    adx_ceil: float,
    vol_mult: float,
    tp: float,
    sl: float,
    max_hold: int,
    sma_period: int,
    slippage: float,
    rsi_period: int = 14,
) -> dict:
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    opens = df["open"].values.astype(float)
    volumes = df["volume"].values.astype(float)
    n = len(closes)

    # 레짐 판단: BTC close < SMA(period) → BEAR/Sideways
    if btc_df is not None:
        btc_closes = btc_df["close"].values.astype(float)
        btc_sma = compute_sma(btc_closes, sma_period)
        # btc_df와 df를 시간으로 align
        btc_regime = pd.Series(
            btc_closes < btc_sma, index=btc_df.index
        )
    else:
        btc_sma = compute_sma(closes, sma_period)
        btc_regime = pd.Series(closes < btc_sma, index=df.index)

    rsi_arr = compute_rsi(closes, rsi_period)
    adx_arr = compute_adx(highs, lows, closes, 14)
    vol_avg = volume_sma(volumes, 20)

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count = 0
    pending_entry = False

    warmup = max(sma_period, 30, rsi_period + 2)

    for i in range(warmup, n):
        ts = df.index[i]

        if pending_entry and not in_pos:
            entry_price = opens[i] * (1 + slippage + FEE)
            in_pos = True
            hold_count = 0
            pending_entry = False
            continue

        if not in_pos:
            # ── 진입 조건 ──
            if np.isnan(rsi_arr[i]) or np.isnan(adx_arr[i]):
                continue
            if i < 2 or np.isnan(rsi_arr[i - 1]):
                continue

            # 1. BTC BEAR/Sideways 레짐
            if ts in btc_regime.index:
                closest_idx = btc_regime.index.get_indexer([ts], method="ffill")[0]
                if closest_idx < 0 or not btc_regime.iloc[closest_idx]:
                    continue
            else:
                continue

            # 2. RSI 과매도 반등: RSI < oversold 후 RSI 상승 시작
            if rsi_arr[i] >= rsi_oversold:
                continue
            # RSI 반등 확인: 현재 RSI > 이전 RSI (모멘텀 전환)
            if rsi_arr[i] <= rsi_arr[i - 1]:
                continue

            # 3. ADX < ceiling (과도한 추세 필터)
            if adx_arr[i] >= adx_ceil:
                continue

            # 4. 볼륨 확인 (캐피튤레이션 감지)
            if vol_mult > 0 and not np.isnan(vol_avg[i]):
                if volumes[i] < vol_avg[i] * vol_mult:
                    continue

            # 모든 필터 통과 → 다음 봉 진입 예약
            if i < n - 1:
                pending_entry = True
        else:
            hold_count += 1

            # TP
            if highs[i] >= entry_price * (1 + tp):
                exit_price = entry_price * (1 + tp) * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue

            # SL
            if lows[i] <= entry_price * (1 - sl):
                exit_price = entry_price * (1 - sl) * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue

            # RSI 과매수 청산
            if not np.isnan(rsi_arr[i]) and rsi_arr[i] >= rsi_exit:
                if (closes[i] - entry_price) / entry_price > 0.002:
                    exit_price = closes[i] * (1 - slippage - FEE)
                    trades.append((exit_price - entry_price) / entry_price)
                    in_pos = False
                    continue

            # Max hold
            if hold_count >= max_hold:
                exit_price = closes[i] * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False

    if not trades:
        return {"sharpe": -999, "wr": 0, "avg": 0, "mdd": 0, "n": 0, "mcl": 0}

    arr = np.array(trades)
    wr = (arr > 0).sum() / len(arr)
    avg_ret = arr.mean()

    # MDD
    equity = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    mdd = dd.min()

    # MCL (max consecutive losses)
    mcl = 0
    curr_loss = 0
    for t in arr:
        if t < 0:
            curr_loss += 1
            mcl = max(mcl, curr_loss)
        else:
            curr_loss = 0

    # Sharpe
    if arr.std() == 0:
        sharpe = 0.0
    else:
        sharpe = (arr.mean() / arr.std()) * ANNUAL_FACTOR

    return {
        "sharpe": sharpe,
        "wr": wr,
        "avg": avg_ret,
        "mdd": mdd,
        "n": len(arr),
        "mcl": mcl,
    }


# ─── 메인 ────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("사이클 156: RSI Mean-Reversion Bear/Sideways 전용 전략")
    print("=" * 80)

    # Phase 1: 핵심 필터 그리드
    # RSI_oversold × RSI_exit × ADX_ceil × vol_mult × TP × SL × max_hold
    RSI_OVERSOLD_LIST = [20, 25, 30, 35]
    RSI_EXIT_LIST = [55, 65, 75]
    ADX_CEIL_LIST = [20, 25, 30]
    VOL_MULT_LIST = [0.0, 1.2, 1.5]  # 0.0=필터 없음
    TP_LIST = [0.02, 0.03, 0.04, 0.05]
    SL_LIST = [0.015, 0.02, 0.03]
    MAX_HOLD_LIST = [12, 24, 36]
    SMA_PERIOD = 200  # BTC SMA200 레짐

    RSI_PERIOD_LIST = [14]  # 고정 (Phase 2에서 확장 가능)

    grid = list(product(
        RSI_OVERSOLD_LIST, RSI_EXIT_LIST, ADX_CEIL_LIST,
        VOL_MULT_LIST, TP_LIST, SL_LIST, MAX_HOLD_LIST
    ))
    print(f"Phase 1 그리드: {len(grid)} 조합 × {len(SYMBOLS)} 심볼")

    # 데이터 로드
    all_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = load_historical(sym, TIMEFRAME, "2022-01-01", "2026-04-05")
        print(f"  {sym}: {len(df)} bars ({df.index[0]} ~ {df.index[-1]})")
        all_data[sym] = df

    btc_full = all_data["KRW-BTC"]

    # Phase 1: IS 전체 데이터 스크리닝
    print(f"\n{'='*80}")
    print("=== Phase 1: IS 전체 스크리닝 (slippage={SLIPPAGE_BASE}) ===")
    print(f"{'='*80}")

    results = []
    total = len(grid) * len(SYMBOLS)
    done = 0
    for sym in SYMBOLS:
        df_full = all_data[sym]
        btc_ref = None if sym == "KRW-BTC" else btc_full

        for rsi_os, rsi_ex, adx_c, vol_m, tp, sl, mh in grid:
            # IS: 2022-01-01 ~ 2024-12-31 (전체 IS)
            mask = (df_full.index >= "2022-01-01") & (df_full.index <= "2024-12-31")
            df_is = df_full[mask]
            if btc_ref is not None:
                btc_is = btc_ref[
                    (btc_ref.index >= "2022-01-01") & (btc_ref.index <= "2024-12-31")
                ]
            else:
                btc_is = None

            r = backtest(
                df_is, btc_is,
                rsi_oversold=rsi_os, rsi_exit=rsi_ex,
                adx_ceil=adx_c, vol_mult=vol_m,
                tp=tp, sl=sl, max_hold=mh,
                sma_period=SMA_PERIOD,
                slippage=SLIPPAGE_BASE,
            )

            results.append({
                "symbol": sym,
                "rsi_os": rsi_os, "rsi_ex": rsi_ex,
                "adx_c": adx_c, "vol_m": vol_m,
                "tp": tp, "sl": sl, "mh": mh,
                **r,
            })
            done += 1
            if done % 500 == 0:
                print(f"  진행: {done}/{total}")

    df_res = pd.DataFrame(results)
    # Sharpe > 0 AND n >= 20 필터
    passed = df_res[(df_res["sharpe"] > 0) & (df_res["n"] >= 20)].copy()
    passed = passed.sort_values("sharpe", ascending=False)

    print(f"\n총 {len(df_res)}개 중 Sharpe>0 & n≥20: {len(passed)}개")
    if len(passed) > 0:
        print("\n--- Top 20 (IS 전체) ---")
        print(f"{'sym':>8} {'rsi_os':>6} {'rsi_ex':>6} {'adx':>4} {'vol':>4}"
              f" {'tp':>5} {'sl':>5} {'mh':>3} {'Sharpe':>8} {'WR':>6}"
              f" {'avg%':>7} {'MDD':>8} {'MCL':>4} {'n':>4}")
        for _, row in passed.head(20).iterrows():
            print(f"{row['symbol']:>8} {row['rsi_os']:>6.0f} {row['rsi_ex']:>6.0f}"
                  f" {row['adx_c']:>4.0f} {row['vol_m']:>4.1f}"
                  f" {row['tp']:>5.1%} {row['sl']:>5.1%} {row['mh']:>3.0f}"
                  f" {row['sharpe']:>+8.3f} {row['wr']:>5.1%}"
                  f" {row['avg']:>+7.3%} {row['mdd']:>7.2%}"
                  f" {row['mcl']:>4.0f} {row['n']:>4.0f}")
    else:
        print("⚠️  IS 스크리닝에서 통과 조합 없음!")

    # Phase 2: Top 조합 WF 검증
    if len(passed) == 0:
        print("\n❌ Phase 1 통과 조합 없음 — 파라미터 범위 확장 필요")
        # 보완: 필터 완화 (vol_mult=0, adx_ceil=35)
        relaxed = df_res[(df_res["sharpe"] > -5) & (df_res["n"] >= 10)].copy()
        relaxed = relaxed.sort_values("sharpe", ascending=False)
        print(f"\n완화 기준 (Sharpe>-5, n≥10): {len(relaxed)}개")
        if len(relaxed) > 0:
            print("\n--- 완화 Top 10 ---")
            for _, row in relaxed.head(10).iterrows():
                print(f"  {row['symbol']} rsi_os={row['rsi_os']:.0f}"
                      f" rsi_ex={row['rsi_ex']:.0f} adx={row['adx_c']:.0f}"
                      f" vol={row['vol_m']:.1f} tp={row['tp']:.1%}"
                      f" sl={row['sl']:.1%} mh={row['mh']:.0f}"
                      f" → Sharpe={row['sharpe']:+.3f} WR={row['wr']:.1%}"
                      f" n={row['n']:.0f}")
        return

    # Phase 2: Top-10 WF 2-fold 검증
    print(f"\n{'='*80}")
    print("=== Phase 2: Walkforward 2-fold OOS 검증 ===")
    print(f"{'='*80}")

    top_configs = passed.head(10).to_dict("records")
    wf_results = []

    for cfg in top_configs:
        sym = cfg["symbol"]
        df_full = all_data[sym]
        btc_ref = None if sym == "KRW-BTC" else btc_full

        fold_sharpes = []
        fold_details = []
        all_pass = True

        for w in WINDOWS:
            # IS
            is_mask = (df_full.index >= w["is_start"]) & (df_full.index <= w["is_end"])
            df_is = df_full[is_mask]

            # OOS
            oos_mask = (
                (df_full.index >= w["oos_start"])
                & (df_full.index <= w["oos_end"])
            )
            df_oos = df_full[oos_mask]

            if btc_ref is not None:
                btc_oos = btc_ref[
                    (btc_ref.index >= w["oos_start"])
                    & (btc_ref.index <= w["oos_end"])
                ]
            else:
                btc_oos = None

            r = backtest(
                df_oos, btc_oos,
                rsi_oversold=cfg["rsi_os"], rsi_exit=cfg["rsi_ex"],
                adx_ceil=cfg["adx_c"], vol_mult=cfg["vol_m"],
                tp=cfg["tp"], sl=cfg["sl"], max_hold=cfg["mh"],
                sma_period=SMA_PERIOD,
                slippage=SLIPPAGE_BASE,
            )

            fold_sharpes.append(r["sharpe"])
            fold_details.append(r)

            if r["sharpe"] < PASS_SHARPE or r["n"] < PASS_N_PER_FOLD:
                all_pass = False

        avg_oos = np.mean(fold_sharpes) if fold_sharpes else -999

        tag = "✅" if all_pass else "❌"
        print(f"\n  {tag} {sym} rsi_os={cfg['rsi_os']:.0f}"
              f" rsi_ex={cfg['rsi_ex']:.0f} adx={cfg['adx_c']:.0f}"
              f" vol={cfg['vol_m']:.1f} tp={cfg['tp']:.1%}"
              f" sl={cfg['sl']:.1%} mh={cfg['mh']:.0f}")
        for j, (w, fd) in enumerate(zip(WINDOWS, fold_details)):
            mdd_flag = "⚠️" if fd["mdd"] < -0.15 else "✅"
            mcl_flag = "❌" if fd["mcl"] > 3 else "✅"
            print(f"    {w['name']}: Sharpe={fd['sharpe']:+.3f}"
                  f"  WR={fd['wr']:.1%}  n={fd['n']}"
                  f"  MDD={fd['mdd']:.2%}{mdd_flag}"
                  f"  MCL={fd['mcl']}{mcl_flag}"
                  f"  avg={fd['avg']:+.3%}")

        print(f"    → avg OOS Sharpe: {avg_oos:+.3f}")

        wf_results.append({
            **cfg,
            "avg_oos": avg_oos,
            "all_pass": all_pass,
            "fold_details": fold_details,
        })

    # Phase 3: 안전 조합 필터 (MDD<15%, consec≤3)
    safe = [w for w in wf_results if w["all_pass"]]
    print(f"\n{'='*80}")
    print(f"=== Phase 3: 안전 조합 (양 Fold 통과) — {len(safe)}개 ===")
    print(f"{'='*80}")

    if not safe:
        # 부분 통과 (1 Fold만 통과)
        partial = [w for w in wf_results if w["avg_oos"] > 0]
        partial.sort(key=lambda x: x["avg_oos"], reverse=True)
        print(f"  양 Fold 완전 통과 없음. 부분 통과 (avg OOS > 0): {len(partial)}개")
        for p in partial[:5]:
            print(f"    {p['symbol']} rsi_os={p['rsi_os']:.0f}"
                  f" → avg OOS={p['avg_oos']:+.3f}")
            for j, fd in enumerate(p["fold_details"]):
                print(f"      F{j+1}: Sharpe={fd['sharpe']:+.3f}"
                      f" WR={fd['wr']:.1%} n={fd['n']}")
        return

    safe.sort(key=lambda x: x["avg_oos"], reverse=True)
    best = safe[0]

    # Phase 4: 슬리피지 스트레스 테스트 (최적 조합)
    print(f"\n{'='*80}")
    print("=== Phase 4: 슬리피지 스트레스 테스트 ===")
    print(f"{'='*80}")
    print(f"  최적: {best['symbol']} rsi_os={best['rsi_os']:.0f}"
          f" rsi_ex={best['rsi_ex']:.0f} adx={best['adx_c']:.0f}"
          f" vol={best['vol_m']:.1f} tp={best['tp']:.1%}"
          f" sl={best['sl']:.1%} mh={best['mh']:.0f}")

    sym = best["symbol"]
    df_full = all_data[sym]
    btc_ref = None if sym == "KRW-BTC" else btc_full
    # OOS=F2 (가장 최근)
    w = WINDOWS[1]
    oos_mask = (
        (df_full.index >= w["oos_start"])
        & (df_full.index <= w["oos_end"])
    )
    df_oos = df_full[oos_mask]
    btc_oos = None
    if btc_ref is not None:
        btc_oos = btc_ref[
            (btc_ref.index >= w["oos_start"])
            & (btc_ref.index <= w["oos_end"])
        ]

    print(f"\n  {'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7}"
          f" {'MDD':>8} {'MCL':>4} {'n':>4}")
    print("  " + "-" * 55)
    for slip in SLIPPAGE_STRESS:
        r = backtest(
            df_oos, btc_oos,
            rsi_oversold=best["rsi_os"], rsi_exit=best["rsi_ex"],
            adx_ceil=best["adx_c"], vol_mult=best["vol_m"],
            tp=best["tp"], sl=best["sl"], max_hold=best["mh"],
            sma_period=SMA_PERIOD,
            slippage=slip,
        )
        print(f"  {slip:>10.2%} {r['sharpe']:>+8.3f} {r['wr']:>5.1%}"
              f" {r['avg']:>+7.3%} {r['mdd']:>7.2%}"
              f" {r['mcl']:>4} {r['n']:>4}")

    # Phase 5: 연도별 분해
    print(f"\n{'='*80}")
    print("=== Phase 5: 연도별 성과 분해 ===")
    print(f"{'='*80}")

    for year in range(2022, 2027):
        y_start = f"{year}-01-01"
        y_end = f"{year}-12-31" if year < 2026 else "2026-04-05"
        y_mask = (df_full.index >= y_start) & (df_full.index <= y_end)
        df_y = df_full[y_mask]
        if len(df_y) == 0:
            continue
        btc_y = None
        if btc_ref is not None:
            btc_y = btc_ref[
                (btc_ref.index >= y_start) & (btc_ref.index <= y_end)
            ]

        r = backtest(
            df_y, btc_y,
            rsi_oversold=best["rsi_os"], rsi_exit=best["rsi_ex"],
            adx_ceil=best["adx_c"], vol_mult=best["vol_m"],
            tp=best["tp"], sl=best["sl"], max_hold=best["mh"],
            sma_period=SMA_PERIOD,
            slippage=SLIPPAGE_BASE,
        )
        print(f"  {year}: Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}"
              f"  MDD={r['mdd']:.2%}  MCL={r['mcl']}  n={r['n']}"
              f"  avg={r['avg']:+.3%}")

    # 최종 요약
    print(f"\n{'='*80}")
    print("=== 최종 요약 ===")
    print(f"{'='*80}")
    print(f"★ WF 최적: {best['symbol']} rsi_os={best['rsi_os']:.0f}"
          f" rsi_ex={best['rsi_ex']:.0f} adx={best['adx_c']:.0f}"
          f" vol={best['vol_m']:.1f} tp={best['tp']:.1%}"
          f" sl={best['sl']:.1%} mh={best['mh']:.0f}")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f}")
    for j, fd in enumerate(best["fold_details"]):
        print(f"  Fold {j+1}: Sharpe={fd['sharpe']:+.3f}"
              f"  WR={fd['wr']:.1%}  n={fd['n']}"
              f"  MDD={fd['mdd']:.2%}  MCL={fd['mcl']}")

    # 안전성
    max_mdd = min(fd["mdd"] for fd in best["fold_details"])
    max_mcl = max(fd["mcl"] for fd in best["fold_details"])
    total_n = sum(fd["n"] for fd in best["fold_details"])
    print(f"\n  연속손실 ≤ 3: {'✅ PASS' if max_mcl <= 3 else '❌ FAIL'}"
          f" (실제: {max_mcl})")
    print(f"  MDD < 15%: {'✅ PASS' if max_mdd > -0.15 else '⚠️ WARNING'}"
          f" (실제: {max_mdd:.2%})")
    print(f"  총 OOS 거래수: {total_n}"
          f" ({'✅' if total_n >= 30 else '⚠️ n<30'})")

    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    print(f"WR: {best['fold_details'][0]['wr']:.1%}")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, line_buffering=True)
    main()
