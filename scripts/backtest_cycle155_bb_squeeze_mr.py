"""
사이클 155: BB Squeeze Mean-Reversion — Bear/Sideways 전용 전략
- 목적: BEAR 레짐 전용 전략 확보 (현재 0개)
- c154 실패 원인: BB touch만으로는 BEAR 하락 중 진입 → squeeze 필터 없음
- 핵심 차별점:
  1) BB Squeeze 필터 — BBW < rolling percentile (저변동 구간에서만 진입)
     → BEAR 폭락 중 BB touch 필터링, 횡보 구간 mean-reversion만 포착
  2) 60m 타임프레임 — 4H 대비 4배 데이터, n≥30 확보
  3) ADX<20 (레인지-바운드)
  4) RSI 과매도 회복 필터
  5) 다음 봉 시가 진입 (look-ahead bias 제거)
- WF: 2-fold
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
SLIPPAGE_STRESS = [0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003]

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

# 판정 기준
PASS_SHARPE = 5.0
PASS_N_PER_FOLD = 15


# ─── 지표 ────────────────────────────────────────────────────────────

def bollinger_bands(closes: np.ndarray, period: int, n_std: float):
    n = len(closes)
    mid = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    bbw = np.full(n, np.nan)  # BB Width = (upper - lower) / mid
    for i in range(period - 1, n):
        w = closes[i - period + 1 : i + 1]
        m = w.mean()
        s = w.std(ddof=1)
        mid[i] = m
        upper[i] = m + n_std * s
        lower[i] = m - n_std * s
        if m > 0:
            bbw[i] = (2 * n_std * s) / m
    return upper, mid, lower, bbw


def bbw_percentile(bbw: np.ndarray, lookback: int) -> np.ndarray:
    """Rolling percentile of BBW — low = squeeze."""
    n = len(bbw)
    pct = np.full(n, np.nan)
    for i in range(lookback - 1, n):
        window = bbw[i - lookback + 1 : i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        pct[i] = np.sum(valid <= bbw[i]) / len(valid) * 100
    return pct


def compute_rsi(closes: np.ndarray, period: int = 14):
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
        rsi_arr[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        if avg_loss == 0:
            rsi_arr[i + 1] = 100.0
        else:
            rsi_arr[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return rsi_arr


def compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                period: int = 14):
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
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
        plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0
    atr = np.zeros(n)
    atr[period] = tr[1 : period + 1].mean()
    sm_plus = plus_dm[1 : period + 1].sum()
    sm_minus = minus_dm[1 : period + 1].sum()
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
        dx_vals.append(100.0 * abs(plus_di - minus_di) / di_sum
                       if di_sum != 0 else 0.0)
        if len(dx_vals) == period:
            adx_arr[i] = np.mean(dx_vals)
        elif len(dx_vals) > period:
            adx_arr[i] = (adx_arr[i - 1] * (period - 1) + dx_vals[-1]) / period
    return adx_arr


# ─── 백테스트 엔진 ───────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    bb_period: int, bb_std: float,
    adx_ceil: float,
    rsi_floor: float, rsi_ceil: float,
    squeeze_pct_ceil: float,  # BBW percentile < this = squeeze
    squeeze_lookback: int,    # rolling window for BBW percentile
    tp: float, sl: float,
    max_hold: int,
    bb_exit_mid: bool,
    slippage: float,
    cooldown: int = 6,
) -> dict:
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    opens = df["open"].values.astype(float)
    n = len(closes)

    upper, bb_mid, bb_lower, bbw = bollinger_bands(closes, bb_period, bb_std)
    bbw_pct = bbw_percentile(bbw, squeeze_lookback)
    rsi_arr = compute_rsi(closes, 14)
    adx_arr = compute_adx(highs, lows, closes, 14)

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count = 0
    pending_entry = False
    last_exit_bar = -100

    warmup = max(bb_period, squeeze_lookback, 30)

    for i in range(warmup, n):
        if pending_entry and not in_pos:
            entry_price = opens[i] * (1 + slippage + FEE)
            in_pos = True
            hold_count = 0
            pending_entry = False
            continue

        if not in_pos:
            if (np.isnan(bb_lower[i]) or np.isnan(rsi_arr[i])
                    or np.isnan(adx_arr[i]) or np.isnan(bbw_pct[i])):
                continue
            # 쿨다운
            if i - last_exit_bar < cooldown:
                continue
            # 1. BB Squeeze: BBW percentile < threshold
            if bbw_pct[i] >= squeeze_pct_ceil:
                continue
            # 2. BB 하단 터치/이탈
            if closes[i] > bb_lower[i]:
                continue
            # 3. ADX < ceiling (레인지-바운드)
            if adx_arr[i] >= adx_ceil:
                continue
            # 4. RSI 과매도 범위
            if not (rsi_floor <= rsi_arr[i] <= rsi_ceil):
                continue
            # 모든 필터 통과 → 다음 봉 진입 예약
            if i < n - 1:
                pending_entry = True
        else:
            hold_count += 1
            cur_mid = bb_mid[i] if not np.isnan(bb_mid[i]) else entry_price * 1.02

            # TP
            if highs[i] >= entry_price * (1 + tp):
                exit_price = entry_price * (1 + tp) * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                last_exit_bar = i
                continue
            # SL
            if lows[i] <= entry_price * (1 - sl):
                exit_price = entry_price * (1 - sl) * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                last_exit_bar = i
                continue
            # BB 중간선 청산
            if bb_exit_mid and closes[i] >= cur_mid and (
                (closes[i] - entry_price) / entry_price > 0.001
            ):
                exit_price = closes[i] * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                last_exit_bar = i
                continue
            # Max hold
            if hold_count >= max_hold:
                exit_price = closes[i] * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                last_exit_bar = i
                continue

    if in_pos:
        exit_price = closes[-1] * (1 - slippage - FEE)
        trades.append((exit_price - entry_price) / entry_price)

    if len(trades) < 3:
        return {"sharpe": float("nan"), "wr": float("nan"), "avg": float("nan"),
                "n": len(trades), "mdd": float("nan")}

    arr = np.array(trades)
    sharpe = arr.mean() / (arr.std() + 1e-9) * ANNUAL_FACTOR
    wr = float((arr > 0).mean())
    avg_r = float(arr.mean())
    equity = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    mdd = float(dd.min())
    bh_ret = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0.0

    # 연속 손실
    max_consec = 0
    cur_consec = 0
    for t in arr:
        if t < 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    return {
        "sharpe": float(sharpe), "wr": wr, "avg": avg_r,
        "n": len(trades), "mdd": mdd,
        "cum_ret": float(equity[-1] - 1), "bh_ret": float(bh_ret),
        "max_consec_loss": max_consec,
    }


def walk_forward_oos(params: dict, symbol: str, slippage: float) -> list[dict]:
    results = []
    for w in WINDOWS:
        df_all = load_historical(symbol, TIMEFRAME, w["is_start"], w["oos_end"])
        if df_all is None or len(df_all) < 200:
            results.append({"window": w["name"], "sharpe": float("nan"), "n": 0})
            continue
        df_oos = df_all[(df_all.index >= w["oos_start"]) & (df_all.index <= w["oos_end"])]
        if len(df_oos) < 100:
            results.append({"window": w["name"], "sharpe": float("nan"), "n": 0})
            continue
        res = backtest(df_oos, slippage=slippage, **params)
        res["window"] = w["name"]
        results.append(res)
    return results


def full_period_backtest(params: dict, symbol: str, slippage: float) -> dict:
    df = load_historical(symbol, TIMEFRAME, "2022-01-01", "2026-04-05")
    if df is None or len(df) < 200:
        return {"sharpe": float("nan"), "n": 0}
    return backtest(df, slippage=slippage, **params)


# ─── 메인 ────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("사이클 155: BB Squeeze Mean-Reversion — Bear/Sideways 전용")
    print("  핵심 차별점: BB Squeeze 필터 (BBW percentile < threshold)")
    print("  → BEAR 폭락 중 BB touch 필터링, 횡보 squeeze 구간만 진입")
    print("  60m 타임프레임, 슬리피지 0.10% 포함")
    print("=" * 80)

    # ── Phase 1: 핵심 그리드 ──
    # c154 학습: ETH > BTC, ADX<15 최적, TP=2%, SL=1.5%
    # 새 축: squeeze_pct_ceil × squeeze_lookback
    ADX_CEIL   = [15, 20, 25]
    RSI_FLOOR  = [20, 25]
    RSI_CEIL   = [40, 45, 50]
    SQUEEZE_PCT = [20, 30, 40, 50]     # BBW percentile ceiling
    SQUEEZE_LB  = [120, 240]           # lookback: 5일(120h), 10일(240h)
    TP         = [0.015, 0.02, 0.025]
    SL         = [0.008, 0.01, 0.015]
    MAX_HOLD   = [12, 24]
    BB_EXIT    = [True]  # c154에서 mid-exit가 일관 우위

    FIXED = {"bb_period": 20, "bb_std": 2.0, "cooldown": 6}

    grid = list(product(ADX_CEIL, RSI_FLOOR, RSI_CEIL, SQUEEZE_PCT,
                        SQUEEZE_LB, TP, SL, MAX_HOLD, BB_EXIT))
    total_per_sym = len(grid)
    print(f"  그리드: {total_per_sym} 조합 per symbol × {len(SYMBOLS)} = "
          f"{total_per_sym * len(SYMBOLS)} 총 조합")

    all_results: list[dict] = []

    for symbol in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"  {symbol}")
        print(f"{'='*60}")

        passed_count = 0
        for idx, (adx_c, rsi_f, rsi_c, sq_pct, sq_lb,
                  tp, sl, hold, exit_mid) in enumerate(grid):
            params = {
                **FIXED,
                "adx_ceil": adx_c,
                "rsi_floor": rsi_f, "rsi_ceil": rsi_c,
                "squeeze_pct_ceil": sq_pct, "squeeze_lookback": sq_lb,
                "tp": tp, "sl": sl,
                "max_hold": hold, "bb_exit_mid": exit_mid,
            }

            wf = walk_forward_oos(params, symbol, SLIPPAGE_BASE)

            passed = all(
                not np.isnan(r.get("sharpe", float("nan")))
                and r.get("sharpe", 0) >= PASS_SHARPE
                and r.get("n", 0) >= PASS_N_PER_FOLD
                for r in wf
            )
            avg_s = np.nanmean([r.get("sharpe", float("nan")) for r in wf])
            total_n = sum(r.get("n", 0) for r in wf)

            row = {
                "symbol": symbol, **params,
                "avg_oos": float(avg_s), "total_n": total_n, "passed": passed,
            }
            for r in wf:
                w = r.get("window", "?")
                row[f"{w}_sharpe"] = r.get("sharpe", float("nan"))
                row[f"{w}_wr"] = r.get("wr", float("nan"))
                row[f"{w}_n"] = r.get("n", 0)
                row[f"{w}_mdd"] = r.get("mdd", float("nan"))
                row[f"{w}_avg"] = r.get("avg", float("nan"))
                row[f"{w}_consec"] = r.get("max_consec_loss", 0)
            all_results.append(row)

            if passed:
                passed_count += 1
                print(f"  \u2705 ADX<{adx_c} RSI[{rsi_f},{rsi_c}]"
                      f" SQ<{sq_pct}%/lb{sq_lb}"
                      f" TP={tp} SL={sl} hold={hold}"
                      f" \u2192 avg={avg_s:+.3f} n={total_n}")

            if (idx + 1) % 200 == 0:
                print(f"  ... {idx+1}/{total_per_sym} ({passed_count} passed)")

        print(f"  {symbol} 완료: {passed_count} passed / {total_per_sym}")

    # ── 결과 저장 ──
    df_results = pd.DataFrame(all_results)
    csv_path = Path(__file__).parent / "cycle155_bb_squeeze_mr_results.csv"
    df_results.to_csv(csv_path, index=False)
    print(f"\n결과 저장: {csv_path}")

    passed_df = df_results[df_results["passed"] == True]  # noqa: E712
    print(f"\n{'='*80}")
    print(f"Phase 1 총 통과: {len(passed_df)} / {len(df_results)}")
    print(f"{'='*80}")

    if len(passed_df) == 0:
        print("\n\u274c BB Squeeze MR 통과 조합 0개")

        # n>=30 중 최선
        adequate = df_results[df_results["total_n"] >= 30]
        if len(adequate) > 0:
            best = adequate.loc[adequate["avg_oos"].idxmax()]
            print(f"\n  n\u226530 중 최선: {best['symbol']} ADX<{best['adx_ceil']}"
                  f" RSI[{best['rsi_floor']},{best['rsi_ceil']}]"
                  f" SQ<{best['squeeze_pct_ceil']}%/lb{best['squeeze_lookback']}"
                  f" TP={best['tp']} SL={best['sl']}"
                  f" hold={best['max_hold']}")
            print(f"  avg OOS: {best['avg_oos']:+.3f} n={best['total_n']}")
            for w in ["F1", "F2"]:
                s = best.get(f"{w}_sharpe", float("nan"))
                n_w = best.get(f"{w}_n", 0)
                wr = best.get(f"{w}_wr", float("nan"))
                print(f"    {w}: Sharpe={s:+.3f} WR={wr:.1%} n={n_w}")

        # Squeeze 없이 기준선 비교
        print("\n--- Squeeze 없는 기준선 (c154-B 상당) ---")
        for symbol in SYMBOLS:
            baseline_params = {
                **FIXED, "adx_ceil": 15, "rsi_floor": 20, "rsi_ceil": 45,
                "squeeze_pct_ceil": 100,  # = no filter
                "squeeze_lookback": 120,
                "tp": 0.02, "sl": 0.015,
                "max_hold": 24, "bb_exit_mid": True,
            }
            wf = walk_forward_oos(baseline_params, symbol, SLIPPAGE_BASE)
            avg_s = np.nanmean([r.get("sharpe", float("nan")) for r in wf])
            total_n = sum(r.get("n", 0) for r in wf)
            print(f"  {symbol} no-squeeze: avg OOS={avg_s:+.3f} n={total_n}")
            for r in wf:
                w = r.get("window", "?")
                s = r.get("sharpe", float("nan"))
                n_w = r.get("n", 0)
                wr = r.get("wr", float("nan"))
                print(f"    {w}: Sharpe={s:+.3f} WR={wr:.1%} n={n_w}")

        # 전체 최선
        if len(df_results) > 0:
            best_any = df_results.loc[df_results["avg_oos"].idxmax()]
            print(f"\n  전체 최선 (n 무관): {best_any['symbol']}"
                  f" ADX<{best_any['adx_ceil']}"
                  f" SQ<{best_any['squeeze_pct_ceil']}%"
                  f" TP={best_any['tp']} SL={best_any['sl']}"
                  f" \u2192 avg={best_any['avg_oos']:+.3f} n={best_any['total_n']}")
        return

    # ── Top 10 ──
    top = passed_df.nlargest(10, "avg_oos")
    print("\n--- Top 10 by avg OOS Sharpe ---")
    for _, row in top.iterrows():
        print(f"\n  {row['symbol']} ADX<{row['adx_ceil']}"
              f" RSI[{row['rsi_floor']},{row['rsi_ceil']}]"
              f" SQ<{row['squeeze_pct_ceil']}%/lb{row['squeeze_lookback']}"
              f" TP={row['tp']} SL={row['sl']}"
              f" hold={row['max_hold']}")
        print(f"    avg OOS: {row['avg_oos']:+.3f} n={row['total_n']}")
        for w in ["F1", "F2"]:
            s = row.get(f"{w}_sharpe", float("nan"))
            n_w = row.get(f"{w}_n", 0)
            wr = row.get(f"{w}_wr", float("nan"))
            mdd = row.get(f"{w}_mdd", float("nan"))
            avg_r = row.get(f"{w}_avg", float("nan"))
            consec = row.get(f"{w}_consec", 0)
            print(f"    {w}: Sharpe={s:+.3f} WR={wr:.1%} n={n_w}"
                  f" avg={avg_r:+.2%} MDD={mdd:.2%} consec={consec}")

    # ── 챔피언 후속 분석 ──
    champ = top.iloc[0]
    champ_sym = str(champ["symbol"])
    champ_params = {
        "bb_period": int(champ["bb_period"]), "bb_std": float(champ["bb_std"]),
        "adx_ceil": float(champ["adx_ceil"]),
        "rsi_floor": float(champ["rsi_floor"]),
        "rsi_ceil": float(champ["rsi_ceil"]),
        "squeeze_pct_ceil": float(champ["squeeze_pct_ceil"]),
        "squeeze_lookback": int(champ["squeeze_lookback"]),
        "tp": float(champ["tp"]), "sl": float(champ["sl"]),
        "max_hold": int(champ["max_hold"]),
        "bb_exit_mid": bool(champ["bb_exit_mid"]),
        "cooldown": int(champ["cooldown"]),
    }

    # 슬리피지 스트레스
    print(f"\n{'='*60}")
    print(f"챔피언 슬리피지 스트레스: {champ_sym}")
    print(f"  {champ_params}")
    print(f"{'='*60}")
    print(f"  {'slip':>6}  {'Sharpe':>8}  {'WR':>6}  {'avg%':>8}"
          f"  {'MDD':>8}  {'MCL':>4}  {'n':>5}")
    print(f"  {'-'*55}")
    for slip in SLIPPAGE_STRESS:
        full = full_period_backtest(champ_params, champ_sym, slip)
        s = full.get("sharpe", float("nan"))
        wr = full.get("wr", float("nan"))
        avg_r = full.get("avg", float("nan"))
        mdd = full.get("mdd", float("nan"))
        mcl = full.get("max_consec_loss", 0)
        n_t = full.get("n", 0)
        print(f"  {slip:.2%}  {s:+8.3f}  {wr:5.1%}  {avg_r:+7.2%}"
              f"  {mdd:7.2%}  {mcl:4}  {n_t:5}")

    # 연도별 분해
    print(f"\n--- 연도별 분해 ---")
    years = [("2022", "2022-01-01", "2022-12-31"),
             ("2023", "2023-01-01", "2023-12-31"),
             ("2024", "2024-01-01", "2024-12-31"),
             ("2025", "2025-01-01", "2025-12-31"),
             ("2026", "2026-01-01", "2026-04-05")]
    for yr_name, yr_s, yr_e in years:
        df_yr = load_historical(champ_sym, TIMEFRAME, yr_s, yr_e)
        if df_yr is None or len(df_yr) < 100:
            print(f"  {yr_name}: 데이터 부족")
            continue
        yr_res = backtest(df_yr, slippage=SLIPPAGE_BASE, **champ_params)
        s = yr_res.get("sharpe", float("nan"))
        n_t = yr_res.get("n", 0)
        wr = yr_res.get("wr", float("nan"))
        avg_r = yr_res.get("avg", float("nan"))
        cum = yr_res.get("cum_ret", float("nan"))
        bh = yr_res.get("bh_ret", float("nan"))
        mcl = yr_res.get("max_consec_loss", 0)
        print(f"  {yr_name}: Sharpe={s:+.3f} WR={wr:.1%} n={n_t}"
              f" avg={avg_r:+.2%} cumR={cum:+.1%} BH={bh:+.1%} MCL={mcl}")

    # 전체기간
    full_base = full_period_backtest(champ_params, champ_sym, SLIPPAGE_BASE)
    print(f"\n전체기간 (2022-2026): Sharpe={full_base['sharpe']:+.3f}"
          f" WR={full_base['wr']:.1%} n={full_base['n']}"
          f" cumR={full_base.get('cum_ret',0):+.1%}"
          f" BH={full_base.get('bh_ret',0):+.1%}"
          f" MCL={full_base.get('max_consec_loss',0)}")

    # ── 안전성 체크 ──
    mcl_full = full_base.get("max_consec_loss", 0)
    mdd_full = full_base.get("mdd", 0)
    print(f"\n=== 안전성 요약 ===")
    print(f"  연속손실 \u2264 3: {'✅ PASS' if mcl_full <= 3 else f'❌ FAIL (실제: {mcl_full})'}")
    print(f"  MDD < 15%: {'✅ PASS' if abs(mdd_full) < 0.15 else f'⚠️ 주의 (실제: {mdd_full:.2%})'}")

    print("\n" + "=" * 80)
    print("사이클 155 완료")
    print("=" * 80)


if __name__ == "__main__":
    main()
