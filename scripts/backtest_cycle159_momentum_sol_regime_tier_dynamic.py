"""
momentum_sol ATR 레짐 티어별 동적 TP/SL + ADX 그래디언트 — 사이클 159
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: 사이클 156 최적 lb=180 pct=70 TrA=2.0 TrS=1.0
      Sharpe +15.631, WR 66.7%, MDD -14.49%, consec=3 ✅
      WF OOS avg +14.805 (TrA=1.5 → +17.142)

가설:
  1) ATR 레짐 티어별 동적 TP/SL — 이진 필터 대신 3-tier 접근:
     - low_vol (ATR pct ≤ T1): TP/SL 축소 → 빈번한 소익절
     - mid_vol (T1 < ATR pct ≤ T2): 기본 TP/SL (현 최적)
     - high_vol (ATR pct > T2): 진입 차단 (기존 필터)
  2) ADX 그래디언트: ADX가 직전 N봉 대비 상승 중일 때만 진입
     → 약화 추세 진입 차단, 더 높은 승률 기대
  3) 두 개선을 결합하여 MDD 추가 감소 + Sharpe 개선 목표

그리드:
  - tier1_pct: [40, 50, 60] — low/mid 경계
  - tier2_pct: [70] (확정, 사이클 156 최적)
  - low_vol_tp_mult: [3.0, 3.5] — low-vol 구간 TP 축소 (기본 4.0)
  - low_vol_sl_mult: [1.5, 2.0] — low-vol 구간 SL 축소 (기본 2.0)
  - adx_grad_bars: [3, 6, 0(비활성)] — ADX 상승 확인 봉수
  - trailing: [(1.5, 1.0), (2.0, 1.0)]
  = 3×2×2×3×2 = 72 조합
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

# Base params (cycle 150/153/156 확정)
LOOKBACK = 20
ADX_THRESH = 25.0
VOL_MULT = 1.5
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
ENTRY_THRESHOLD = 0.005
MAX_HOLD = 48
BTC_SMA = 200
COOLDOWN_TRIGGER = 3
COOLDOWN_BARS = 24
ATR_PERIOD = 20
ATR_VOL_LOOKBACK = 180  # 사이클 156 확정

# Fixed from cycle 156
BASE_SL_ATR = 2.0
BASE_TP_ATR = 4.0

# Tier boundary grid
TIER1_PCTS = [40, 50, 60]       # low/mid 경계
TIER2_PCT = 70                   # mid/high 경계 (확정)

# Low-vol regime TP/SL scaling
LOW_VOL_TP_MULTS = [3.0, 3.5]   # low-vol에서 TP 축소
LOW_VOL_SL_MULTS = [1.5, 2.0]   # low-vol에서 SL 축소

# ADX gradient bars (0 = disabled)
ADX_GRAD_BARS_LIST = [0, 3, 6]

# Trailing combos
TRAILING_COMBOS = [
    (1.5, 1.0),
    (2.0, 1.0),
]

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


def compute_atr_percentile(
    atr_arr: np.ndarray, lookback: int,
) -> np.ndarray:
    n = len(atr_arr)
    pctile = np.full(n, np.nan)
    for i in range(lookback, n):
        window = atr_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        rank = np.sum(valid <= atr_arr[i])
        pctile[i] = rank / len(valid) * 100.0
    return pctile


# ── 백테스트 (3-tier 동적 TP/SL + ADX 그래디언트) ────────────────────────────

def backtest(
    df_sol: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    atr_arr: np.ndarray,
    atr_pctile: np.ndarray,
    adx_arr_ind: np.ndarray,
    *,
    tier1_pct: float,
    tier2_pct: float,
    low_tp_mult: float,
    low_sl_mult: float,
    adx_grad_bars: int,
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
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = max(LOOKBACK + RSI_PERIOD + 28, BTC_SMA + 10)
    consec_loss = 0
    cooldown_until = 0
    vol_filtered = 0
    adx_grad_filtered = 0
    tier_counts = {"low": 0, "mid": 0, "blocked": 0}

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

        if np.isnan(atr_arr[i]) or atr_arr[i] <= 0:
            i += 1
            continue

        # ★ 3-tier ATR regime classification
        cur_pctile = atr_pctile[i] if not np.isnan(atr_pctile[i]) else 50.0
        if cur_pctile > tier2_pct:
            # high-vol: block entry
            vol_filtered += 1
            tier_counts["blocked"] += 1
            i += 1
            continue

        # ★ ADX gradient filter — ADX rising over last N bars
        if adx_grad_bars > 0:
            ref_idx = i - adx_grad_bars
            if (
                ref_idx >= 0
                and not np.isnan(adx_arr_ind[i])
                and not np.isnan(adx_arr_ind[ref_idx])
                and adx_arr_ind[i] <= adx_arr_ind[ref_idx]
            ):
                adx_grad_filtered += 1
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

            # ★ Dynamic TP/SL by tier
            if cur_pctile <= tier1_pct:
                # low-vol tier: tighter targets
                sl_mult = low_sl_mult
                tp_mult = low_tp_mult
                tier_counts["low"] += 1
            else:
                # mid-vol tier: base targets
                sl_mult = BASE_SL_ATR
                tp_mult = BASE_TP_ATR
                tier_counts["mid"] += 1

            sl_pct = (entry_atr * sl_mult) / buy
            tp_pct = (entry_atr * tp_mult) / buy
            trail_activate_pct = (entry_atr * trail_activate_mult) / buy
            trail_sl_dist = (entry_atr * trail_sl_mult) / buy

            sl_pct = min(max(sl_pct, 0.01), 0.10)
            tp_pct = min(max(tp_pct, 0.02), 0.20)

            ret = None
            exit_bar = i + 1
            trailing_active = False
            highest_ret = 0.0

            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                r = c[j] / buy - 1

                if r > highest_ret:
                    highest_ret = r

                if trailing_active:
                    trail_stop = highest_ret - trail_sl_dist
                    if r <= trail_stop:
                        ret = r - FEE
                        exit_bar = j
                        break

                if not trailing_active and r >= trail_activate_pct:
                    trailing_active = True

                if r >= tp_pct:
                    ret = tp_pct - FEE
                    exit_bar = j
                    break

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
            "vol_filtered": vol_filtered, "adx_grad_filtered": adx_grad_filtered,
            "tier_counts": tier_counts,
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
        "vol_filtered": vol_filtered, "adx_grad_filtered": adx_grad_filtered,
        "tier_counts": tier_counts,
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
    print("=" * 80)
    print("momentum_sol ATR 레짐 티어별 동적 TP/SL + ADX 그래디언트 (사이클 159)")
    print("=" * 80)
    print(f"심볼: {SYMBOL}  레짐: BTC SMA{BTC_SMA}  쿨다운: trig={COOLDOWN_TRIGGER}")
    print(f"ATR 기간: {ATR_PERIOD}  Base SL={BASE_SL_ATR:.1f}x  Base TP={BASE_TP_ATR:.1f}x")
    print(f"ATR pctile lookback: {ATR_VOL_LOOKBACK}  Tier2(block): {TIER2_PCT}")
    print(f"Tier1 grid: {TIER1_PCTS}  Low TP: {LOW_VOL_TP_MULTS}  Low SL: {LOW_VOL_SL_MULTS}")
    print(f"ADX grad bars: {ADX_GRAD_BARS_LIST}  Trailing: {TRAILING_COMBOS}\n")

    df_sol = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC, "240m", "2022-01-01", "2026-12-31")
    if df_sol.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"SOL 데이터: {len(df_sol)}행  BTC 데이터: {len(df_btc)}행\n")

    btc_c, btc_sma = align_btc_to_sol(df_sol, df_btc)
    atr_arr = compute_atr(
        df_sol["high"].values, df_sol["low"].values,
        df_sol["close"].values, ATR_PERIOD,
    )
    atr_pctile = compute_atr_percentile(atr_arr, ATR_VOL_LOOKBACK)
    adx_arr = adx_indicator(
        df_sol["high"].values, df_sol["low"].values, df_sol["close"].values, 14,
    )

    # ── Phase 1: Baseline (사이클 156 최적 — 이진 필터) ──────────────────────
    print("=== Phase 1: Baseline (사이클 156 이진 필터, tier 없음) ===")
    for tr_a, tr_s in TRAILING_COMBOS:
        r = backtest(
            df_sol, btc_c, btc_sma, atr_arr, atr_pctile, adx_arr,
            tier1_pct=0.0, tier2_pct=TIER2_PCT,
            low_tp_mult=BASE_TP_ATR, low_sl_mult=BASE_SL_ATR,
            adx_grad_bars=0,
            trail_activate_mult=tr_a, trail_sl_mult=tr_s,
        )
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"  TrA={tr_a:.1f} TrS={tr_s:.1f}: Sharpe={sh}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%  consec={r['max_consec_loss']}  "
            f"trades={r['trades']}"
        )
    print()

    # ── Phase 2: 전체 그리드 탐색 ────────────────────────────────────────────
    print("=== Phase 2: 3-tier 동적 TP/SL + ADX 그래디언트 그리드 ===")
    print(f"{'t1':>4} {'lTP':>5} {'lSL':>5} {'adxG':>5} {'TrA':>5} {'TrS':>5} "
          f"{'Sharpe':>8} {'WR':>6} {'MDD%':>8} {'cL':>4} {'trd':>5} "
          f"{'filt':>5} {'adxF':>5} {'low':>4} {'mid':>4}")
    print("-" * 100)

    results = []
    for t1 in TIER1_PCTS:
        for ltp in LOW_VOL_TP_MULTS:
            for lsl in LOW_VOL_SL_MULTS:
                for adx_gb in ADX_GRAD_BARS_LIST:
                    for tr_a, tr_s in TRAILING_COMBOS:
                        r = backtest(
                            df_sol, btc_c, btc_sma, atr_arr, atr_pctile, adx_arr,
                            tier1_pct=t1, tier2_pct=TIER2_PCT,
                            low_tp_mult=ltp, low_sl_mult=lsl,
                            adx_grad_bars=adx_gb,
                            trail_activate_mult=tr_a, trail_sl_mult=tr_s,
                        )
                        results.append((t1, ltp, lsl, adx_gb, tr_a, tr_s, r))
                        sh = (f"{r['sharpe']:+.3f}"
                              if not np.isnan(r["sharpe"]) else "    nan")
                        tc = r["tier_counts"]
                        print(
                            f"{t1:>4} {ltp:>5.1f} {lsl:>5.1f} {adx_gb:>5} "
                            f"{tr_a:>5.1f} {tr_s:>5.1f} {sh:>8} "
                            f"{r['wr']:>5.1%} {r['max_dd'] * 100:>+7.2f}% "
                            f"{r['max_consec_loss']:>4} {r['trades']:>5} "
                            f"{r['vol_filtered']:>5} {r['adx_grad_filtered']:>5} "
                            f"{tc['low']:>4} {tc['mid']:>4}"
                        )

    # ── Phase 3: Top-10 by Sharpe ────────────────────────────────────────────
    valid = [x for x in results if not np.isnan(x[6]["sharpe"]) and x[6]["trades"] >= 10]
    valid.sort(key=lambda x: x[6]["sharpe"], reverse=True)
    top10 = valid[:10]

    print(f"\n=== Phase 3: Top-10 조합 ===")
    for rank, (t1, ltp, lsl, adx_gb, tr_a, tr_s, r) in enumerate(top10, 1):
        safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
        safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
        print(
            f"  #{rank:>2} t1={t1} lTP={ltp:.1f} lSL={lsl:.1f} adxG={adx_gb} "
            f"TrA={tr_a:.1f} TrS={tr_s:.1f}  "
            f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
            f"consec={r['max_consec_loss']}{safe_cl}  "
            f"trades={r['trades']}"
        )

    # ── Phase 3b: 안전 조합 ──────────────────────────────────────────────────
    safe_combos = [
        x for x in valid
        if abs(x[6]["max_dd"]) < 0.15 and x[6]["max_consec_loss"] <= 3
    ]
    safe_combos.sort(key=lambda x: x[6]["sharpe"], reverse=True)
    print(f"\n=== Phase 3b: 안전 조합 (MDD<15% AND consec≤3) — {len(safe_combos)}개 ===")
    for rank, (t1, ltp, lsl, adx_gb, tr_a, tr_s, r) in enumerate(safe_combos[:5], 1):
        print(
            f"  #{rank} t1={t1} lTP={ltp:.1f} lSL={lsl:.1f} adxG={adx_gb} "
            f"TrA={tr_a:.1f} TrS={tr_s:.1f}  "
            f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%  "
            f"consec={r['max_consec_loss']}  trades={r['trades']}"
        )

    # ── Phase 4: 연도별 성과 분해 ────────────────────────────────────────────
    analysis_target = safe_combos[0] if safe_combos else (top10[0] if top10 else None)
    if analysis_target:
        t1, ltp, lsl, adx_gb, tr_a, tr_s, _ = analysis_target
        print(f"\n=== Phase 4: 연도별 성과 분해 ===")
        print(f"  파라미터: t1={t1} lTP={ltp:.1f} lSL={lsl:.1f} adxG={adx_gb} "
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
                df_sol_yr["close"].values, ATR_PERIOD,
            )
            pctile_yr = compute_atr_percentile(atr_yr, ATR_VOL_LOOKBACK)
            adx_yr = adx_indicator(
                df_sol_yr["high"].values, df_sol_yr["low"].values,
                df_sol_yr["close"].values, 14,
            )
            r = backtest(
                df_sol_yr, btc_c_yr, btc_sma_yr, atr_yr, pctile_yr, adx_yr,
                tier1_pct=t1, tier2_pct=TIER2_PCT,
                low_tp_mult=ltp, low_sl_mult=lsl,
                adx_grad_bars=adx_gb,
                trail_activate_mult=tr_a, trail_sl_mult=tr_s,
            )
            sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
            print(
                f"  {year}: Sharpe={sh}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd'] * 100:+.2f}%  "
                f"consec={r['max_consec_loss']}  trades={r['trades']}  "
                f"filt={r['vol_filtered']}  adxF={r['adx_grad_filtered']}"
            )

    # ── Phase 5: Walkforward OOS 검증 ────────────────────────────────────────
    wf_targets = safe_combos[:3] if safe_combos else top10[:3]
    print(f"\n=== Phase 5: Walkforward OOS 검증 (Top-3) ===")
    best_oos = None
    best_oos_sharpe = -999.0
    for rank, (t1, ltp, lsl, adx_gb, tr_a, tr_s, _) in enumerate(wf_targets, 1):
        label = f"t1_{t1}_ltp{ltp}_lsl{lsl}_adx{adx_gb}_ta{tr_a}_ts{tr_s}"
        oos_sharpes = []
        for fi, fold in enumerate(WF_FOLDS):
            df_sol_t = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_t = load_historical(BTC, "240m", fold["test"][0], fold["test"][1])
            if df_sol_t.empty or df_btc_t.empty:
                continue
            btc_c_t, btc_sma_t = align_btc_to_sol(df_sol_t, df_btc_t)
            atr_t = compute_atr(
                df_sol_t["high"].values, df_sol_t["low"].values,
                df_sol_t["close"].values, ATR_PERIOD,
            )
            pctile_t = compute_atr_percentile(atr_t, ATR_VOL_LOOKBACK)
            adx_t = adx_indicator(
                df_sol_t["high"].values, df_sol_t["low"].values,
                df_sol_t["close"].values, 14,
            )
            r = backtest(
                df_sol_t, btc_c_t, btc_sma_t, atr_t, pctile_t, adx_t,
                tier1_pct=t1, tier2_pct=TIER2_PCT,
                low_tp_mult=ltp, low_sl_mult=lsl,
                adx_grad_bars=adx_gb,
                trail_activate_mult=tr_a, trail_sl_mult=tr_s,
            )
            sh_val = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh_val)
            safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
            safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
            print(
                f"  {label} Fold {fi+1}: Sharpe={sh_val:+.3f}  "
                f"WR={r['wr']:.1%}  MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
                f"consec={r['max_consec_loss']}{safe_cl}  trades={r['trades']}"
            )
        if oos_sharpes:
            avg = np.mean(oos_sharpes)
            print(f"  → {label} 평균 OOS Sharpe: {avg:+.3f}")
            if avg > best_oos_sharpe:
                best_oos_sharpe = avg
                best_oos = (t1, ltp, lsl, adx_gb, tr_a, tr_s)

    # ── Phase 6: 안전성 요약 ─────────────────────────────────────────────────
    final = analysis_target
    if final:
        _, _, _, _, _, _, best_r = final
        print(f"\n=== 안전성 요약 ===")
        print(f"  연속손실 ≤ 3: "
              f"{'✅ PASS' if best_r['max_consec_loss'] <= 3 else '❌ FAIL'} "
              f"(실제: {best_r['max_consec_loss']})")
        print(f"  MDD < 15%: "
              f"{'✅ PASS' if abs(best_r['max_dd']) < 0.15 else '⚠️ 주의'} "
              f"(실제: {best_r['max_dd'] * 100:+.2f}%)")

    # ── 최종 결과 ────────────────────────────────────────────────────────────
    if final:
        _, _, _, _, _, _, best_r = final
        print(f"\nSharpe: {best_r['sharpe']:+.3f}")
        print(f"WR: {best_r['wr'] * 100:.1f}%")
        print(f"trades: {best_r['trades']}")


if __name__ == "__main__":
    main()
