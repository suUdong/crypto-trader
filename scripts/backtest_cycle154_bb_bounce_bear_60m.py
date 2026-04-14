"""
사이클 154-B: BB bounce Bear/Sideways — 60m(1H) 타임프레임
- Phase 1 (240m) 실패: n=7~9 → 4H에서 BB bounce 이벤트 구조적 부족
- 60m → 4배 데이터, BB touch 빈도 증가
- 볼륨 필터 제거 (Phase 1에서 이미 충분한 필터 확인)
- ADX ceiling 확장: {15,20,25,30}
- TP/SL 축소 (1H 기준 적절한 레벨)
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
SLIPPAGE_BASE = 0.001
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
    for i in range(period - 1, n):
        w = closes[i - period + 1 : i + 1]
        m = w.mean()
        s = w.std(ddof=1)
        mid[i] = m
        upper[i] = m + n_std * s
        lower[i] = m - n_std * s
    return upper, mid, lower


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


def compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14):
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
        dx_vals.append(100.0 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0)
        if len(dx_vals) == period:
            adx_arr[i] = np.mean(dx_vals)
        elif len(dx_vals) > period:
            adx_arr[i] = (adx_arr[i - 1] * (period - 1) + dx_vals[-1]) / period
    return adx_arr


# ─── 백테스트 ────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    bb_period: int, bb_std: float,
    adx_ceil: float,
    rsi_floor: float, rsi_ceil: float,
    tp: float, sl: float,
    max_hold: int,
    bb_exit_mid: bool,
    slippage: float,
    cooldown: int = 0,
) -> dict:
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    opens = df["open"].values.astype(float)
    n = len(closes)

    _, bb_mid, bb_lower = bollinger_bands(closes, bb_period, bb_std)
    rsi_arr = compute_rsi(closes, 14)
    adx_arr = compute_adx(highs, lows, closes, 14)

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count = 0
    pending_entry = False
    last_exit_bar = -100

    warmup = max(bb_period, 30)

    for i in range(warmup, n):
        if pending_entry and not in_pos:
            entry_price = opens[i] * (1 + slippage + FEE)
            in_pos = True
            hold_count = 0
            pending_entry = False
            continue

        if not in_pos:
            if np.isnan(bb_lower[i]) or np.isnan(rsi_arr[i]) or np.isnan(adx_arr[i]):
                continue
            # 쿨다운
            if i - last_exit_bar < cooldown:
                continue
            # BB 하단 터치/이탈
            if closes[i] > bb_lower[i]:
                continue
            # ADX < ceiling
            if adx_arr[i] >= adx_ceil:
                continue
            # RSI 범위
            if not (rsi_floor <= rsi_arr[i] <= rsi_ceil):
                continue
            # 다음 봉 진입 예약
            if i < n - 1:
                pending_entry = True
        else:
            hold_count += 1
            current_bb_mid = bb_mid[i] if not np.isnan(bb_mid[i]) else entry_price * 1.02

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
            if bb_exit_mid and closes[i] >= current_bb_mid and (
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

    return {
        "sharpe": float(sharpe), "wr": wr, "avg": avg_r,
        "n": len(trades), "mdd": mdd,
        "cum_ret": float(equity[-1] - 1), "bh_ret": float(bh_ret),
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
    print("사이클 154-B: BB bounce Bear/Sideways — 60m(1H) 타임프레임")
    print("  4H→1H 전환: 4배 데이터, BB touch 빈도 증가")
    print("  볼륨 필터 제거, ADX 범위 확장")
    print("=" * 80)

    # ── 그리드 정의 ──
    ADX_CEIL   = [15, 20, 25, 30]
    RSI_FLOOR  = [20, 25, 30]
    RSI_CEIL   = [40, 45, 50]
    TP         = [0.015, 0.02, 0.025, 0.03]
    SL         = [0.008, 0.01, 0.015]
    MAX_HOLD   = [12, 24]   # 1H bars
    BB_EXIT    = [True, False]

    # BB 고정: period=20, std=2.0
    FIXED = {"bb_period": 20, "bb_std": 2.0}

    grid = list(product(ADX_CEIL, RSI_FLOOR, RSI_CEIL, TP, SL, MAX_HOLD, BB_EXIT))
    total = len(grid)
    print(f"  그리드: {total} 조합 per symbol")

    all_results: list[dict] = []

    for symbol in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"  {symbol}")
        print(f"{'='*60}")

        passed_count = 0
        for idx, (adx_c, rsi_f, rsi_c, tp, sl, hold, exit_mid) in enumerate(grid):
            params = {
                **FIXED,
                "adx_ceil": adx_c,
                "rsi_floor": rsi_f, "rsi_ceil": rsi_c,
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
            all_results.append(row)

            if passed:
                passed_count += 1
                print(f"  ✅ ADX<{adx_c} RSI[{rsi_f},{rsi_c}] TP={tp} SL={sl}"
                      f" hold={hold} mid={exit_mid}"
                      f" → avg={avg_s:+.3f} n={total_n}")

            if (idx + 1) % 200 == 0:
                print(f"  ... {idx+1}/{total} ({passed_count} passed)")

        print(f"  {symbol} 완료: {passed_count} passed / {total}")

    # ── 결과 저장 ──
    df_results = pd.DataFrame(all_results)
    csv_path = Path(__file__).parent / "cycle154_bb_bounce_60m_results.csv"
    df_results.to_csv(csv_path, index=False)
    print(f"\n결과 저장: {csv_path}")

    passed_df = df_results[df_results["passed"] == True]  # noqa: E712
    print(f"\n{'='*80}")
    print(f"총 통과: {len(passed_df)} / {len(df_results)}")
    print(f"{'='*80}")

    if len(passed_df) == 0:
        print("\n❌ 60m에서도 통과 조합 0개")
        # 가장 나은 n≥15 결과
        adequate_n = df_results[df_results["total_n"] >= 30]
        if len(adequate_n) > 0:
            best_idx = adequate_n["avg_oos"].idxmax()
            best = adequate_n.loc[best_idx]
            print(f"\n  n≥30 중 최선: {best['symbol']} ADX<{best['adx_ceil']}"
                  f" RSI[{best['rsi_floor']},{best['rsi_ceil']}]"
                  f" TP={best['tp']} SL={best['sl']}"
                  f" hold={best['max_hold']} mid={best['bb_exit_mid']}")
            print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} n={best['total_n']}")
            for w in ["F1", "F2"]:
                s = best.get(f"{w}_sharpe", float("nan"))
                n = best.get(f"{w}_n", 0)
                wr = best.get(f"{w}_wr", float("nan"))
                print(f"    {w}: Sharpe={s:+.3f} WR={wr:.1%} n={n}")
        else:
            print("  n≥30 조합 없음 — BB bounce 전략 엣지 부재 확정")

        # 전체 최선 결과 (n 무관)
        if len(df_results) > 0:
            best_any = df_results.loc[df_results["avg_oos"].idxmax()]
            print(f"\n  전체 최선: {best_any['symbol']} ADX<{best_any['adx_ceil']}"
                  f" RSI[{best_any['rsi_floor']},{best_any['rsi_ceil']}]"
                  f" TP={best_any['tp']} SL={best_any['sl']}"
                  f" → avg Sharpe={best_any['avg_oos']:+.3f} n={best_any['total_n']}")
        return

    # ── Top 5 + 후속 분석 ──
    top5 = passed_df.nlargest(5, "avg_oos")
    print("\n--- Top 5 by avg OOS Sharpe ---")
    for _, row in top5.iterrows():
        print(f"\n  {row['symbol']} ADX<{row['adx_ceil']}"
              f" RSI[{row['rsi_floor']},{row['rsi_ceil']}]"
              f" TP={row['tp']} SL={row['sl']}"
              f" hold={row['max_hold']} mid={row['bb_exit_mid']}")
        print(f"    avg OOS: {row['avg_oos']:+.3f} n={row['total_n']}")
        for w in ["F1", "F2"]:
            s = row.get(f"{w}_sharpe", float("nan"))
            n_w = row.get(f"{w}_n", 0)
            wr = row.get(f"{w}_wr", float("nan"))
            mdd = row.get(f"{w}_mdd", float("nan"))
            avg_r = row.get(f"{w}_avg", float("nan"))
            print(f"    {w}: Sharpe={s:+.3f} WR={wr:.1%} n={n_w}"
                  f" avg={avg_r:+.2%} MDD={mdd:.2%}")

    # ── 챔피언 슬리피지 + 연도별 ──
    champ = top5.iloc[0]
    champ_sym = str(champ["symbol"])
    champ_params = {
        "bb_period": int(champ["bb_period"]), "bb_std": float(champ["bb_std"]),
        "adx_ceil": float(champ["adx_ceil"]),
        "rsi_floor": float(champ["rsi_floor"]), "rsi_ceil": float(champ["rsi_ceil"]),
        "tp": float(champ["tp"]), "sl": float(champ["sl"]),
        "max_hold": int(champ["max_hold"]),
        "bb_exit_mid": bool(champ["bb_exit_mid"]),
    }

    print(f"\n{'='*60}")
    print(f"챔피언 슬리피지 스트레스: {champ_sym}")
    print(f"{'='*60}")
    print(f"  {'slip':>6}  {'Sharpe':>8}  {'WR':>6}  {'avg%':>8}  {'MDD':>8}  {'n':>5}")
    print(f"  {'-'*50}")
    for slip in SLIPPAGE_STRESS:
        full = full_period_backtest(champ_params, champ_sym, slip)
        s = full.get("sharpe", float("nan"))
        wr = full.get("wr", float("nan"))
        avg_r = full.get("avg", float("nan"))
        mdd = full.get("mdd", float("nan"))
        n = full.get("n", 0)
        print(f"  {slip:.2%}  {s:+8.3f}  {wr:5.1%}  {avg_r:+7.2%}  {mdd:7.2%}  {n:5}")

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
        n = yr_res.get("n", 0)
        wr = yr_res.get("wr", float("nan"))
        avg_r = yr_res.get("avg", float("nan"))
        cum = yr_res.get("cum_ret", float("nan"))
        bh = yr_res.get("bh_ret", float("nan"))
        print(f"  {yr_name}: Sharpe={s:+.3f} WR={wr:.1%} n={n}"
              f" avg={avg_r:+.2%} cumR={cum:+.1%} BH={bh:+.1%}")

    full_base = full_period_backtest(champ_params, champ_sym, SLIPPAGE_BASE)
    print(f"\n전체기간 (2022-2026): Sharpe={full_base['sharpe']:+.3f}"
          f" WR={full_base['wr']:.1%} n={full_base['n']}"
          f" cumR={full_base.get('cum_ret',0):+.1%}"
          f" BH={full_base.get('bh_ret',0):+.1%}")

    print("\n" + "=" * 80)
    print("사이클 154-B 완료")
    print("=" * 80)


if __name__ == "__main__":
    main()
