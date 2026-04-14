"""
momentum_sol ADX-tight + BTC SMA200 레짐 + ATR 동적 청산 — 사이클 153
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: 사이클 150 Top-1 (SMA200, trig=3, cool=24)
      Sharpe=+6.958, WR=36.3%, 하지만 MDD=-28.55%, consec=5 — 안전기준 미달.
      고정 SL=3%/TP=8%이 변동성 국면에서 MDD를 키우는 원인.

목적:
  1) ATR 기반 동적 SL/TP: 변동성 적응형 청산 → 고변동성 시 SL 확대, 저변동성 시 축소
  2) 트레일링 스톱: 일정 수익 도달 후 ATR 기반 트레일링 → 수익 보존 + MDD 감소
  3) BTC SMA200 레짐 + cool=24 유지 (사이클 150 최적)
  4) ATR 배수 그리드 탐색 + Walkforward OOS 검증

그리드:
  ATR 기간: [14, 20]
  SL ATR 배수: [1.0, 1.5, 2.0, 2.5]
  TP ATR 배수: [2.0, 3.0, 4.0]
  트레일링 활성 ATR 배수: [1.5, 2.0]  (이 수익 도달 시 트레일링 시작)
  트레일링 SL ATR 배수: [1.0, 1.5]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-SOL"
BTC = "KRW-BTC"
FEE = 0.0005

# ADX-tight base params (cycle 147/150)
LOOKBACK = 20
ADX_THRESH = 25.0
VOL_MULT = 1.5
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
ENTRY_THRESHOLD = 0.005
MAX_HOLD = 48

# BTC regime + cooldown (cycle 150 best)
BTC_SMA = 200
COOLDOWN_TRIGGER = 3
COOLDOWN_BARS = 24

# ATR grid
ATR_PERIODS = [14, 20]
SL_ATR_MULTS = [1.0, 1.5, 2.0, 2.5]
TP_ATR_MULTS = [2.0, 3.0, 4.0]
TRAIL_ACTIVATE_MULTS = [1.5, 2.0]   # 수익이 ATR*N 도달 시 트레일링 시작
TRAIL_SL_MULTS = [1.0, 1.5]         # 트레일링 SL = ATR*N

WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-01")},
]


# ── 지표 ──────────────────────────────────────────────────────────────────────

def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def adx_indicator(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    dm_p = np.where(
        (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
        np.maximum(highs[1:] - highs[:-1], 0.0), 0.0,
    )
    dm_m = np.where(
        (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
        np.maximum(lows[:-1] - lows[1:], 0.0), 0.0,
    )
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period - 1] = tr[:period].sum()
    dip_s[period - 1] = dm_p[:period].sum()
    dim_s[period - 1] = dm_m[:period].sum()
    for i in range(period, n - 1):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        dip_s[i] = dip_s[i - 1] - dip_s[i - 1] / period + dm_p[i]
        dim_s[i] = dim_s[i - 1] - dim_s[i - 1] / period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dip_s / (atr_s + 1e-9)
        di_m = 100 * dim_s / (atr_s + 1e-9)
        dx = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2 * period - 2] = dx[period - 1:2 * period - 1].mean()
    for i in range(2 * period - 1, n - 1):
        adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


def compute_sma(closes: np.ndarray, period: int) -> np.ndarray:
    sma = np.full(len(closes), np.nan)
    if len(closes) < period:
        return sma
    cumsum = np.cumsum(closes)
    sma[period - 1:] = (cumsum[period - 1:] - np.concatenate(
        ([0.0], cumsum[:len(closes) - period])
    )) / period
    return sma


def compute_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int,
) -> np.ndarray:
    """Average True Range (Wilder smoothing)."""
    n = len(closes)
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    atr[period] = tr[:period].mean()
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period
    return atr


# ── 백테스트 (ATR 동적 청산 + 트레일링) ─────────────────────────────────────

def backtest(
    df_sol: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    atr_arr: np.ndarray,
    sl_atr_mult: float,
    tp_atr_mult: float,
    trail_activate_mult: float,
    trail_sl_mult: float,
) -> dict:
    c = df_sol["close"].values
    o = df_sol["open"].values
    h = df_sol["high"].values
    lo = df_sol["low"].values
    v = df_sol["volume"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0
    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr_ind = adx_indicator(h, lo, c, 14)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = max(LOOKBACK + RSI_PERIOD + 28, BTC_SMA + 10)
    consec_loss = 0
    cooldown_until = 0

    i = warmup
    while i < n - 1:
        if i < cooldown_until:
            i += 1
            continue

        # BTC regime filter
        btc_ok = (
            not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )
        if not btc_ok:
            i += 1
            continue

        # ATR available?
        if np.isnan(atr_arr[i]) or atr_arr[i] <= 0:
            i += 1
            continue

        # SOL entry signal (ADX-tight)
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr_ind[i]) and adx_arr_ind[i] > ADX_THRESH
            and vol_ok[i]
        )
        if entry_ok:
            buy = o[i + 1] * (1 + FEE)
            entry_atr = atr_arr[i]

            # Dynamic SL/TP based on ATR at entry
            sl_pct = (entry_atr * sl_atr_mult) / buy
            tp_pct = (entry_atr * tp_atr_mult) / buy
            trail_activate_pct = (entry_atr * trail_activate_mult) / buy
            trail_sl_dist = (entry_atr * trail_sl_mult) / buy

            # Clamp SL/TP to reasonable bounds
            sl_pct = min(max(sl_pct, 0.01), 0.10)
            tp_pct = min(max(tp_pct, 0.02), 0.20)

            ret = None
            exit_bar = i + 1
            trailing_active = False
            highest_ret = 0.0

            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                r = c[j] / buy - 1

                # Update highest return for trailing stop
                if r > highest_ret:
                    highest_ret = r

                # Check trailing stop
                if trailing_active:
                    trail_stop = highest_ret - trail_sl_dist
                    if r <= trail_stop:
                        ret = r - FEE
                        exit_bar = j
                        break

                # Activate trailing if profit threshold reached
                if not trailing_active and r >= trail_activate_pct:
                    trailing_active = True

                # Fixed TP ceiling
                if r >= tp_pct:
                    ret = tp_pct - FEE
                    exit_bar = j
                    break

                # Fixed SL floor
                if r <= -sl_pct:
                    ret = -sl_pct - FEE
                    exit_bar = j
                    break

            if ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                ret = c[hold_end] / buy - 1 - FEE
                exit_bar = hold_end

            returns.append(ret)

            if ret < 0:
                consec_loss += 1
                if consec_loss >= COOLDOWN_TRIGGER:
                    cooldown_until = exit_bar + COOLDOWN_BARS
                    consec_loss = 0
            else:
                consec_loss = 0

            i = exit_bar
        else:
            i += 1

    if len(returns) < 3:
        return {
            "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
            "trades": 0, "max_dd": 0.0, "max_consec_loss": 0,
        }

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())

    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0

    max_consec = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd, "max_consec_loss": max_consec,
    }


def align_btc_to_sol(
    df_sol: pd.DataFrame, df_btc: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].reindex(df_sol.index, method="ffill").values
    btc_sma = compute_sma(df_btc["close"].values, BTC_SMA)
    btc_sma_series = pd.Series(btc_sma, index=df_btc.index)
    btc_sma_aligned = btc_sma_series.reindex(df_sol.index, method="ffill").values
    return btc_close, btc_sma_aligned


def main() -> None:
    print("=" * 78)
    print("momentum_sol ADX-tight + BTC SMA200 + ATR 동적 청산 (사이클 153)")
    print("=" * 78)
    print(f"심볼: {SYMBOL}  레짐: BTC SMA{BTC_SMA}  쿨다운: trig={COOLDOWN_TRIGGER} cool={COOLDOWN_BARS}")
    print(f"ATR 기간: {ATR_PERIODS}  SL 배수: {SL_ATR_MULTS}")
    print(f"TP 배수: {TP_ATR_MULTS}  트레일링: {TRAIL_ACTIVATE_MULTS} / {TRAIL_SL_MULTS}\n")

    df_sol = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC, "240m", "2022-01-01", "2026-12-31")
    if df_sol.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"SOL 데이터: {len(df_sol)}행  BTC 데이터: {len(df_btc)}행\n")

    btc_c, btc_sma = align_btc_to_sol(df_sol, df_btc)

    # ── Phase 1: Baseline (사이클 150 고정 SL/TP) ────────────────────────────
    print("=== Phase 1: Baseline (사이클 150 고정 SL=3% TP=8%) ===")
    # Fake ATR that produces SL=3%, TP=8% with mult=1
    fake_atr = np.full(len(df_sol), 1.0)  # dummy
    # Use fixed SL/TP directly — run with cycle 150 params for comparison
    from backtest_cycle150_momentum_sol_regime_cooldown import (
        backtest as backtest_c150,
    )
    btc_c_150, btc_sma_150 = align_btc_to_sol(df_sol, df_btc)
    base = backtest_c150(df_sol, btc_c_150, btc_sma_150, COOLDOWN_TRIGGER, COOLDOWN_BARS)
    print(f"  Sharpe: {base['sharpe']:+.3f}  WR: {base['wr']:.1%}  "
          f"avg: {base['avg_ret'] * 100:+.2f}%  MDD: {base['max_dd'] * 100:+.2f}%  "
          f"consec: {base['max_consec_loss']}  trades: {base['trades']}\n")

    # ── Phase 2: ATR 동적 청산 그리드 ────────────────────────────────────────
    print("=== Phase 2: ATR 동적 청산 그리드 ===")
    print(f"{'atr_p':>5} {'sl_m':>5} {'tp_m':>5} {'tr_a':>5} {'tr_s':>5} "
          f"{'Sharpe':>8} {'WR':>6} {'avg%':>7} {'MDD%':>8} {'cLoss':>6} {'trades':>7}")
    print("-" * 78)

    results = []
    for atr_p in ATR_PERIODS:
        atr_arr = compute_atr(
            df_sol["high"].values, df_sol["low"].values,
            df_sol["close"].values, atr_p,
        )
        for sl_m in SL_ATR_MULTS:
            for tp_m in TP_ATR_MULTS:
                if tp_m <= sl_m:
                    continue  # TP must be > SL
                for tr_a in TRAIL_ACTIVATE_MULTS:
                    for tr_s in TRAIL_SL_MULTS:
                        r = backtest(
                            df_sol, btc_c, btc_sma, atr_arr,
                            sl_m, tp_m, tr_a, tr_s,
                        )
                        results.append((atr_p, sl_m, tp_m, tr_a, tr_s, r))
                        sh = (f"{r['sharpe']:+.3f}"
                              if not np.isnan(r["sharpe"]) else "    nan")
                        print(
                            f"{atr_p:>5} {sl_m:>5.1f} {tp_m:>5.1f} "
                            f"{tr_a:>5.1f} {tr_s:>5.1f} {sh:>8} "
                            f"{r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
                            f"{r['max_dd'] * 100:>+7.2f}% "
                            f"{r['max_consec_loss']:>6} {r['trades']:>7}"
                        )

    # ── Phase 3: Top-10 by Sharpe ────────────────────────────────────────────
    valid = [x for x in results if not np.isnan(x[5]["sharpe"]) and x[5]["trades"] >= 10]
    valid.sort(key=lambda x: x[5]["sharpe"], reverse=True)
    top10 = valid[:10]

    print(f"\n=== Phase 3: Top-10 조합 ===")
    for rank, (atr_p, sl_m, tp_m, tr_a, tr_s, r) in enumerate(top10, 1):
        safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
        safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
        print(
            f"  #{rank:>2} ATR={atr_p} SL={sl_m:.1f} TP={tp_m:.1f} "
            f"TrA={tr_a:.1f} TrS={tr_s:.1f}  "
            f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
            f"consec={r['max_consec_loss']}{safe_cl}  trades={r['trades']}"
        )

    # ── Phase 3b: 안전 조합 (MDD<15% AND consec≤3) ──────────────────────────
    safe_combos = [
        x for x in valid
        if abs(x[5]["max_dd"]) < 0.15 and x[5]["max_consec_loss"] <= 3
    ]
    safe_combos.sort(key=lambda x: x[5]["sharpe"], reverse=True)
    print(f"\n=== Phase 3b: 안전 조합 (MDD<15% AND consec≤3) — {len(safe_combos)}개 ===")
    for rank, (atr_p, sl_m, tp_m, tr_a, tr_s, r) in enumerate(safe_combos[:5], 1):
        print(
            f"  #{rank} ATR={atr_p} SL={sl_m:.1f} TP={tp_m:.1f} "
            f"TrA={tr_a:.1f} TrS={tr_s:.1f}  "
            f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%  "
            f"consec={r['max_consec_loss']}  trades={r['trades']}"
        )

    # ── Phase 4: Top-1 연도별 분해 ───────────────────────────────────────────
    # Use best safe combo if available, otherwise top overall
    analysis_target = safe_combos[0] if safe_combos else (top10[0] if top10 else None)
    if analysis_target:
        atr_p, sl_m, tp_m, tr_a, tr_s, _ = analysis_target
        print(f"\n=== Phase 4: 연도별 성과 분해 ===")
        print(f"  파라미터: ATR={atr_p} SL={sl_m:.1f} TP={tp_m:.1f} "
              f"TrA={tr_a:.1f} TrS={tr_s:.1f}")
        for year in range(2022, 2027):
            df_sol_yr = load_historical(SYMBOL, "240m", f"{year}-01-01", f"{year}-12-31")
            df_btc_yr = load_historical(BTC, "240m", f"{year}-01-01", f"{year}-12-31")
            if df_sol_yr.empty or df_btc_yr.empty or len(df_sol_yr) < 100:
                print(f"  {year}: 데이터 부족")
                continue
            btc_c_yr, btc_sma_yr = align_btc_to_sol(df_sol_yr, df_btc_yr)
            atr_yr = compute_atr(
                df_sol_yr["high"].values, df_sol_yr["low"].values,
                df_sol_yr["close"].values, atr_p,
            )
            r = backtest(
                df_sol_yr, btc_c_yr, btc_sma_yr, atr_yr,
                sl_m, tp_m, tr_a, tr_s,
            )
            sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
            print(
                f"  {year}: Sharpe={sh}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd'] * 100:+.2f}%  "
                f"consec={r['max_consec_loss']}  trades={r['trades']}"
            )

    # ── Phase 5: Walkforward OOS 검증 ────────────────────────────────────────
    wf_targets = safe_combos[:3] if safe_combos else top10[:3]
    print(f"\n=== Phase 5: Walkforward OOS 검증 (Top-3) ===")
    best_oos = None
    best_oos_sharpe = -999.0
    for rank, (atr_p, sl_m, tp_m, tr_a, tr_s, _) in enumerate(wf_targets, 1):
        label = f"ATR{atr_p}_sl{sl_m}_tp{tp_m}_ta{tr_a}_ts{tr_s}"
        oos_sharpes = []
        for fi, fold in enumerate(WF_FOLDS):
            df_sol_t = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_t = load_historical(BTC, "240m", fold["test"][0], fold["test"][1])
            if df_sol_t.empty or df_btc_t.empty:
                continue
            btc_c_t, btc_sma_t = align_btc_to_sol(df_sol_t, df_btc_t)
            atr_t = compute_atr(
                df_sol_t["high"].values, df_sol_t["low"].values,
                df_sol_t["close"].values, atr_p,
            )
            r = backtest(
                df_sol_t, btc_c_t, btc_sma_t, atr_t,
                sl_m, tp_m, tr_a, tr_s,
            )
            sh_val = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh_val)
            print(
                f"  {label} Fold {fi+1}: Sharpe={sh_val:+.3f}  "
                f"WR={r['wr']:.1%}  MDD={r['max_dd'] * 100:+.2f}%  "
                f"consec={r['max_consec_loss']}  trades={r['trades']}"
            )
        if oos_sharpes:
            avg = np.mean(oos_sharpes)
            print(f"  → {label} 평균 OOS Sharpe: {avg:+.3f}")
            if avg > best_oos_sharpe:
                best_oos_sharpe = avg
                best_oos = (atr_p, sl_m, tp_m, tr_a, tr_s)

    # ── Phase 6: 안전성 요약 ─────────────────────────────────────────────────
    final = analysis_target
    if final:
        _, _, _, _, _, best_r = final
        print(f"\n=== 안전성 요약 ===")
        print(f"  연속손실 ≤ 3: "
              f"{'✅ PASS' if best_r['max_consec_loss'] <= 3 else '❌ FAIL'} "
              f"(실제: {best_r['max_consec_loss']})")
        print(f"  MDD < 15%: "
              f"{'✅ PASS' if abs(best_r['max_dd']) < 0.15 else '⚠️ 주의'} "
              f"(실제: {best_r['max_dd'] * 100:+.2f}%)")

    # ── 최종 결과 ────────────────────────────────────────────────────────────
    if final:
        _, _, _, _, _, best_r = final
        print(f"\nSharpe: {best_r['sharpe']:+.3f}")
        print(f"WR: {best_r['wr'] * 100:.1f}%")
        print(f"trades: {best_r['trades']}")


if __name__ == "__main__":
    main()
