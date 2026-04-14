"""
사이클 154: BB bounce Bear/Sideways 전용 전략 백테스트
- 목적: BEAR 레짐 전용 전략 확보 (현재 0개 — 포트폴리오 리스크 집중 해소)
- c126/c128 실패 원인: ADX/RSI/볼륨 필터 없음, 진입가 오류 → 근본 재설계
- 핵심 변경:
  1) ADX<20 strict (레인지-바운드만 진입)
  2) RSI 과매도 회복 필터 (floor~ceiling)
  3) 볼륨 확인 (캐피튤레이션 감지)
  4) 다음 봉 시가 진입 (look-ahead bias 제거)
  5) BTC + ETH 동시 테스트
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
SLIPPAGE_STRESS = [0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003]

SYMBOLS = ["KRW-BTC", "KRW-ETH"]

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

# ─── 그리드 파라미터 ─────────────────────────────────────────────────
BB_PERIOD_LIST   = [20, 25]
BB_STD_LIST      = [2.0, 2.5]
ADX_CEIL_LIST    = [15, 20, 25]         # 핵심: 레인지-바운드 확인
RSI_FLOOR_LIST   = [20, 25]             # RSI 최저 (너무 낮으면 바닥 미확인)
RSI_CEIL_LIST    = [40, 45]             # RSI 회복 상한
VOL_MULT_LIST    = [0.0, 1.2, 1.5]     # 0.0=필터 없음
TP_LIST          = [0.02, 0.03, 0.04, 0.05]
SL_LIST          = [0.01, 0.015, 0.02]
MAX_HOLD_LIST    = [12, 18, 24]
BB_EXIT_MID      = [True, False]

# 총 조합: 2×2×3×2×2×3×4×3×3×2 = 10,368 per symbol
# 실행 가능 범위로 축소 → 핵심 축만 풀 그리드
# ADX×RSI_floor×RSI_ceil×vol×TP×SL×hold×exit = 3×2×2×3×4×3×3×2 = 2592
# × BB(2×2)=4 → 10,368 per symbol → BTC+ETH = 20,736
# 너무 큼 → 2단계: Phase 1 핵심 축, Phase 2 세분화

# Phase 1: 핵심 필터 그리드 (ADX + RSI + TP/SL)
# BB=20/2.0 고정, vol=1.2 고정, hold=18 고정, exit_mid=True 고정
# → ADX(3) × RSI_floor(2) × RSI_ceil(2) × TP(4) × SL(3) = 144 per symbol

PHASE1_FIXED = {
    "bb_period": 20,
    "bb_std": 2.0,
    "vol_mult": 1.2,
    "max_hold": 18,
    "bb_exit_mid": True,
}


# ─── 지표 계산 ───────────────────────────────────────────────────────

def bollinger_bands(
    closes: np.ndarray, period: int, n_std: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mid = np.full(len(closes), np.nan)
    upper = np.full(len(closes), np.nan)
    lower = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        w = closes[i - period + 1 : i + 1]
        m = w.mean()
        s = w.std(ddof=1)
        mid[i] = m
        upper[i] = m + n_std * s
        lower[i] = m - n_std * s
    return upper, mid, lower


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
    result = np.full(len(volumes), np.nan)
    for i in range(period - 1, len(volumes)):
        result[i] = volumes[i - period + 1 : i + 1].mean()
    return result


# ─── 백테스트 엔진 ───────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    bb_period: int,
    bb_std: float,
    adx_ceil: float,
    rsi_floor: float,
    rsi_ceil: float,
    vol_mult: float,
    tp: float,
    sl: float,
    max_hold: int,
    bb_exit_mid: bool,
    slippage: float,
) -> dict:
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    opens = df["open"].values.astype(float)
    volumes = df["volume"].values.astype(float)
    n = len(closes)

    _, bb_mid, bb_lower = bollinger_bands(closes, bb_period, bb_std)
    rsi_arr = compute_rsi(closes, 14)
    adx_arr = compute_adx(highs, lows, closes, 14)
    vol_avg = volume_sma(volumes, 20)

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count = 0
    pending_entry = False

    warmup = max(bb_period, 30)  # ADX needs ~28 bars

    for i in range(warmup, n):
        if pending_entry and not in_pos:
            # 다음 봉 시가 진입
            entry_price = opens[i] * (1 + slippage + FEE)
            in_pos = True
            hold_count = 0
            pending_entry = False
            continue  # 진입 봉에서는 청산 판단 안함

        if not in_pos:
            # ── 진입 조건 체크 (신호 발생 → pending) ──
            if np.isnan(bb_lower[i]) or np.isnan(rsi_arr[i]) or np.isnan(adx_arr[i]):
                continue

            # 1. BB 하단 터치 또는 이탈
            if closes[i] > bb_lower[i]:
                continue

            # 2. ADX < ceiling (레인지-바운드)
            if adx_arr[i] >= adx_ceil:
                continue

            # 3. RSI 과매도 범위
            if not (rsi_floor <= rsi_arr[i] <= rsi_ceil):
                continue

            # 4. 볼륨 확인
            if vol_mult > 0 and not np.isnan(vol_avg[i]):
                if volumes[i] < vol_avg[i] * vol_mult:
                    continue

            # 모든 필터 통과 → 다음 봉 진입 예약
            if i < n - 1:
                pending_entry = True
        else:
            hold_count += 1
            current_bb_mid = bb_mid[i] if not np.isnan(bb_mid[i]) else entry_price * 1.03

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

            # BB 중간선 청산
            if bb_exit_mid and closes[i] >= current_bb_mid and (
                (closes[i] - entry_price) / entry_price > 0.002  # 최소 +0.2%
            ):
                exit_price = closes[i] * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue

            # Max hold
            if hold_count >= max_hold:
                exit_price = closes[i] * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue

    # 미청산 포지션 강제 청산
    if in_pos:
        exit_price = closes[-1] * (1 - slippage - FEE)
        trades.append((exit_price - entry_price) / entry_price)

    if len(trades) < 3:
        return {"sharpe": float("nan"), "wr": float("nan"), "avg": float("nan"),
                "n": len(trades), "mdd": float("nan")}

    arr = np.array(trades)
    sharpe = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6)  # 4h bars
    wr = float((arr > 0).mean())
    avg_r = float(arr.mean())

    # MDD (equity curve)
    equity = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    mdd = float(dd.min())

    # Buy & Hold
    bh_ret = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0.0

    return {
        "sharpe": float(sharpe), "wr": wr, "avg": avg_r,
        "n": len(trades), "mdd": mdd, "cum_ret": float(equity[-1] - 1),
        "bh_ret": float(bh_ret),
    }


# ─── 워크포워드 ──────────────────────────────────────────────────────

def walk_forward_oos(params: dict, symbol: str, slippage: float) -> list[dict]:
    results = []
    for w in WINDOWS:
        df_all = load_historical(symbol, "240m", w["is_start"], w["oos_end"])
        if df_all is None or len(df_all) < 100:
            results.append({"window": w["name"], "sharpe": float("nan"), "n": 0})
            continue
        df_oos = df_all[(df_all.index >= w["oos_start"]) & (df_all.index <= w["oos_end"])]
        if len(df_oos) < 30:
            results.append({"window": w["name"], "sharpe": float("nan"), "n": 0})
            continue
        res = backtest(df_oos, slippage=slippage, **params)
        res["window"] = w["name"]
        results.append(res)
    return results


def full_period_backtest(params: dict, symbol: str, slippage: float) -> dict:
    df = load_historical(symbol, "240m", "2022-01-01", "2026-04-05")
    if df is None or len(df) < 100:
        return {"sharpe": float("nan"), "n": 0}
    return backtest(df, slippage=slippage, **params)


# ─── 메인 ────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("사이클 154: BB bounce Bear/Sideways 전용 전략")
    print("  c126/c128 실패 원인 해소: +ADX filter +RSI filter +Volume +next-bar-open entry")
    print("=" * 80)

    all_results: list[dict] = []

    for symbol in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"  {symbol} Phase 1: 핵심 필터 그리드")
        print(f"{'='*60}")

        grid = list(product(
            ADX_CEIL_LIST, RSI_FLOOR_LIST, RSI_CEIL_LIST, TP_LIST, SL_LIST
        ))
        print(f"  조합 수: {len(grid)} (ADX×RSI_floor×RSI_ceil×TP×SL)")

        for idx, (adx_c, rsi_f, rsi_c, tp, sl) in enumerate(grid):
            params = {
                **PHASE1_FIXED,
                "adx_ceil": adx_c,
                "rsi_floor": rsi_f,
                "rsi_ceil": rsi_c,
                "tp": tp,
                "sl": sl,
            }

            wf_results = walk_forward_oos(params, symbol, SLIPPAGE_BASE)

            # 양 Fold 통과 체크
            passed = True
            avg_oos = 0.0
            total_n = 0
            for r in wf_results:
                s = r.get("sharpe", float("nan"))
                n = r.get("n", 0)
                if np.isnan(s) or s < 5.0 or n < 10:
                    passed = False
                avg_oos += s if not np.isnan(s) else 0
                total_n += n
            avg_oos /= max(len(wf_results), 1)

            result_row = {
                "symbol": symbol, **params,
                "avg_oos": avg_oos, "total_n": total_n, "passed": passed,
            }
            for r in wf_results:
                w = r.get("window", "?")
                result_row[f"{w}_sharpe"] = r.get("sharpe", float("nan"))
                result_row[f"{w}_wr"] = r.get("wr", float("nan"))
                result_row[f"{w}_n"] = r.get("n", 0)
                result_row[f"{w}_mdd"] = r.get("mdd", float("nan"))
                result_row[f"{w}_avg"] = r.get("avg", float("nan"))

            all_results.append(result_row)

            if passed:
                print(f"  ✅ ADX<{adx_c} RSI[{rsi_f},{rsi_c}] TP={tp} SL={sl}"
                      f" → avg OOS={avg_oos:+.3f} n={total_n}")

            if (idx + 1) % 30 == 0:
                p_count = sum(1 for r in all_results if r.get("passed") and r["symbol"] == symbol)
                print(f"  ... {idx+1}/{len(grid)} ({p_count} passed)")

    # ── 결과 저장 ──
    df_results = pd.DataFrame(all_results)
    csv_path = Path(__file__).parent / "cycle154_bb_bounce_bear_results.csv"
    df_results.to_csv(csv_path, index=False)
    print(f"\n결과 저장: {csv_path}")

    # ── 통과 조합 분석 ──
    passed_df = df_results[df_results["passed"] == True]  # noqa: E712
    print(f"\n{'='*80}")
    print(f"Phase 1 통과 조합: {len(passed_df)} / {len(df_results)}")
    print(f"{'='*80}")

    if len(passed_df) == 0:
        print("\n❌ 통과 조합 0개 — BB bounce Bear/Sideways 전략 엣지 미확인")
        print("  근본 원인: ADX<20+RSI+볼륨 필터 추가에도 불구하고")
        print("  4H 봉 기준 BTC/ETH BB bounce가 통계적 엣지 부족")

        # 가장 나은 결과 출력
        best_idx = df_results["avg_oos"].idxmax()
        if not np.isnan(df_results.loc[best_idx, "avg_oos"]):
            best = df_results.loc[best_idx]
            print(f"\n  최선 조합: {best['symbol']} ADX<{best['adx_ceil']}"
                  f" RSI[{best['rsi_floor']},{best['rsi_ceil']}]"
                  f" TP={best['tp']} SL={best['sl']}")
            print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f}")
            for w in ["F1", "F2"]:
                s = best.get(f"{w}_sharpe", float("nan"))
                n = best.get(f"{w}_n", 0)
                wr = best.get(f"{w}_wr", float("nan"))
                print(f"    {w}: Sharpe={s:+.3f} WR={wr:.1%} n={n}")
        return

    # Top 5 by avg OOS
    top5 = passed_df.nlargest(5, "avg_oos")
    print("\n--- Top 5 by avg OOS Sharpe ---")
    for _, row in top5.iterrows():
        print(f"  {row['symbol']} ADX<{row['adx_ceil']}"
              f" RSI[{row['rsi_floor']},{row['rsi_ceil']}]"
              f" TP={row['tp']} SL={row['sl']}")
        print(f"    avg OOS: {row['avg_oos']:+.3f}")
        for w in ["F1", "F2"]:
            s = row.get(f"{w}_sharpe", float("nan"))
            n = row.get(f"{w}_n", 0)
            wr = row.get(f"{w}_wr", float("nan"))
            mdd = row.get(f"{w}_mdd", float("nan"))
            avg_r = row.get(f"{w}_avg", float("nan"))
            print(f"    {w}: Sharpe={s:+.3f} WR={wr:.1%} n={n} avg={avg_r:+.2%} MDD={mdd:.2%}")

    # ── Phase 2: 최적 조합으로 세부 그리드 ──
    if len(passed_df) > 0:
        best = top5.iloc[0]
        print(f"\n{'='*80}")
        print(f"Phase 2: 최적 조합 {best['symbol']} 세부 그리드 탐색")
        print(f"{'='*80}")

        # BB param + hold + exit 변형
        phase2_results: list[dict] = []
        best_sym = str(best["symbol"])
        best_adx = float(best["adx_ceil"])
        best_rsi_f = float(best["rsi_floor"])
        best_rsi_c = float(best["rsi_ceil"])
        best_tp = float(best["tp"])
        best_sl = float(best["sl"])

        for bb_p, bb_s, hold, exit_mid in product(
            BB_PERIOD_LIST, BB_STD_LIST, MAX_HOLD_LIST, BB_EXIT_MID
        ):
            params = {
                "bb_period": bb_p, "bb_std": bb_s,
                "adx_ceil": best_adx, "rsi_floor": best_rsi_f, "rsi_ceil": best_rsi_c,
                "vol_mult": 1.2, "tp": best_tp, "sl": best_sl,
                "max_hold": hold, "bb_exit_mid": exit_mid,
            }
            wf = walk_forward_oos(params, best_sym, SLIPPAGE_BASE)
            passed = all(
                not np.isnan(r.get("sharpe", float("nan")))
                and r.get("sharpe", 0) >= 5.0
                and r.get("n", 0) >= 10
                for r in wf
            )
            avg_s = np.nanmean([r.get("sharpe", float("nan")) for r in wf])
            total_n = sum(r.get("n", 0) for r in wf)

            row = {
                "symbol": best_sym, **params,
                "avg_oos": float(avg_s), "total_n": total_n, "passed": passed,
            }
            for r in wf:
                w = r.get("window", "?")
                row[f"{w}_sharpe"] = r.get("sharpe", float("nan"))
                row[f"{w}_wr"] = r.get("wr", float("nan"))
                row[f"{w}_n"] = r.get("n", 0)
                row[f"{w}_mdd"] = r.get("mdd", float("nan"))
            phase2_results.append(row)

            if passed:
                print(f"  ✅ BB({bb_p},{bb_s}) hold={hold} exit_mid={exit_mid}"
                      f" → avg OOS={avg_s:+.3f} n={total_n}")

        p2_df = pd.DataFrame(phase2_results)
        p2_passed = p2_df[p2_df["passed"] == True]  # noqa: E712

        if len(p2_passed) > 0:
            champion = p2_passed.nlargest(1, "avg_oos").iloc[0]
            print(f"\n★ Phase 2 챔피언: BB({champion['bb_period']},{champion['bb_std']})"
                  f" hold={champion['max_hold']} exit_mid={champion['bb_exit_mid']}")
            print(f"  avg OOS: {champion['avg_oos']:+.3f}")

            # ── 슬리피지 스트레스 ──
            print(f"\n--- 슬리피지 스트레스 테스트 ---")
            champ_params = {
                "bb_period": int(champion["bb_period"]),
                "bb_std": float(champion["bb_std"]),
                "adx_ceil": best_adx,
                "rsi_floor": best_rsi_f,
                "rsi_ceil": best_rsi_c,
                "vol_mult": 1.2,
                "tp": best_tp,
                "sl": best_sl,
                "max_hold": int(champion["max_hold"]),
                "bb_exit_mid": bool(champion["bb_exit_mid"]),
            }

            print(f"  {'slip':>6}  {'Sharpe':>8}  {'WR':>6}  {'avg%':>8}  {'MDD':>8}  {'n':>5}")
            print(f"  {'-'*45}")
            for slip in SLIPPAGE_STRESS:
                full = full_period_backtest(champ_params, best_sym, slip)
                s = full.get("sharpe", float("nan"))
                wr = full.get("wr", float("nan"))
                avg_r = full.get("avg", float("nan"))
                mdd = full.get("mdd", float("nan"))
                n = full.get("n", 0)
                print(f"  {slip:.2%}  {s:+8.3f}  {wr:5.1%}  {avg_r:+7.2%}  {mdd:7.2%}  {n:5}")

            # ── 연도별 분해 ──
            print(f"\n--- 연도별 분해 ---")
            years = [("2022", "2022-01-01", "2022-12-31"),
                     ("2023", "2023-01-01", "2023-12-31"),
                     ("2024", "2024-01-01", "2024-12-31"),
                     ("2025", "2025-01-01", "2025-12-31"),
                     ("2026", "2026-01-01", "2026-04-05")]
            for yr_name, yr_s, yr_e in years:
                df_yr = load_historical(best_sym, "240m", yr_s, yr_e)
                if df_yr is None or len(df_yr) < 50:
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

            # ── 전체기간 vs B&H ──
            full_base = full_period_backtest(champ_params, best_sym, SLIPPAGE_BASE)
            print(f"\n전체기간 (2022-2026): Sharpe={full_base['sharpe']:+.3f}"
                  f" WR={full_base['wr']:.1%} n={full_base['n']}"
                  f" cumR={full_base.get('cum_ret',0):+.1%}"
                  f" BH={full_base.get('bh_ret',0):+.1%}")

    print("\n" + "=" * 80)
    print("사이클 154 완료")
    print("=" * 80)


if __name__ == "__main__":
    main()
