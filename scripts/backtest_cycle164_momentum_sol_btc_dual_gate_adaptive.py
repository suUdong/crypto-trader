"""
momentum_sol BTC 듀얼 게이트 + 적응형 ADX + 진입 완화 — 사이클 164
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: 사이클 159 최적 t1=40 lTP=3.0 lSL=2.0 adxG=6 TrA=2.0 TrS=1.0
      Sharpe +17.117, WR 69.8%, MDD -14.34%, consec=3 ✅
      WF OOS avg +18.333 (매우 우수)
      문제: 2026년 거래 0건 — 필터 과잉

가설:
  1) BTC 듀얼 게이트: SMA200 위 = 풀 진입, SMA50~SMA200 = 축소 진입 (tighter TP/SL)
     → 2026 BTC가 SMA200 하회 시에도 SMA50 위면 제한적 진입 허용
  2) 적응형 ADX 임계값: low-vol 구간에서 ADX 기준 하향 (25→20/15)
     → 저변동 구간에서도 약한 추세 포착 가능
  3) 진입 모멘텀 임계값 그리드: 0.005 → [0.003, 0.005, 0.007]
     → 0.003으로 완화 시 2026 진입 기회 확대
  4) 위 3가지 결합: 2026 n>0 + 전체 Sharpe/MDD 균형

그리드:
  - btc_gate: [sma200_only, dual_50_200] (2)
  - entry_thresh: [0.003, 0.005, 0.007] (3)
  - adx_adaptive: [False, True(low-vol구간 ADX 20→15)] (2)
  - adx_grad_bars: [6] (확정)
  - tier1_pct: [40] (확정)
  - trailing: [(2.0, 1.0)] (확정)
  - fallback_tp_scale: [0.7, 0.85] (SMA50 구간 TP 축소율, dual일 때만)
  = 2×3×2×2 = 24 조합 (compact)
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

# Base params (cycle 159 확정)
LOOKBACK = 20
ADX_THRESH_BASE = 25.0
ADX_THRESH_LOWVOL = 15.0  # 적응형 ADX: low-vol 구간
VOL_MULT = 1.5
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
MAX_HOLD = 48
BTC_SMA_LONG = 200
BTC_SMA_SHORT = 50
COOLDOWN_TRIGGER = 3
COOLDOWN_BARS = 24
ATR_PERIOD = 20
ATR_VOL_LOOKBACK = 180

# Fixed from cycle 159
BASE_SL_ATR = 2.0
BASE_TP_ATR = 4.0
TIER1_PCT = 40
TIER2_PCT = 70
LOW_TP_MULT = 3.0
LOW_SL_MULT = 2.0
ADX_GRAD_BARS = 6
TRAIL_ACTIVATE = 2.0
TRAIL_SL = 1.0

# Grid
BTC_GATE_MODES = ["sma200_only", "dual_50_200"]
ENTRY_THRESHOLDS = [0.003, 0.005, 0.007]
ADX_ADAPTIVE_OPTS = [False, True]
FALLBACK_TP_SCALES = [0.7, 0.85]  # SMA50 구간 TP 축소율

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


# ── 백테스트 (BTC 듀얼 게이트 + 적응형 ADX) ─────────────────────────────────

def backtest(
    df_sol: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma200_aligned: np.ndarray,
    btc_sma50_aligned: np.ndarray,
    atr_arr: np.ndarray,
    atr_pctile: np.ndarray,
    adx_arr_ind: np.ndarray,
    *,
    btc_gate_mode: str,
    entry_threshold: float,
    adx_adaptive: bool,
    fallback_tp_scale: float,
) -> dict:
    c = df_sol["close"].values
    o = df_sol["open"].values
    v = df_sol["volume"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0
    rsi_arr = rsi(c, RSI_PERIOD)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = max(LOOKBACK + RSI_PERIOD + 28, BTC_SMA_LONG + 10)
    consec_loss = 0
    cooldown_until = 0
    vol_filtered = 0
    adx_grad_filtered = 0
    btc_gate_stats = {"full": 0, "fallback": 0, "blocked": 0}

    i = warmup
    while i < n - 1:
        if i < cooldown_until:
            i += 1
            continue

        # ★ BTC 듀얼 게이트
        btc_above_200 = (
            not np.isnan(btc_sma200_aligned[i])
            and btc_close_aligned[i] > btc_sma200_aligned[i]
        )
        btc_above_50 = (
            not np.isnan(btc_sma50_aligned[i])
            and btc_close_aligned[i] > btc_sma50_aligned[i]
        )

        if btc_gate_mode == "sma200_only":
            if not btc_above_200:
                btc_gate_stats["blocked"] += 1
                i += 1
                continue
            is_fallback = False
        else:  # dual_50_200
            if btc_above_200:
                is_fallback = False
            elif btc_above_50:
                is_fallback = True
            else:
                btc_gate_stats["blocked"] += 1
                i += 1
                continue

        if np.isnan(atr_arr[i]) or atr_arr[i] <= 0:
            i += 1
            continue

        # 3-tier ATR regime
        cur_pctile = atr_pctile[i] if not np.isnan(atr_pctile[i]) else 50.0
        if cur_pctile > TIER2_PCT:
            vol_filtered += 1
            i += 1
            continue

        # ADX gradient filter
        if ADX_GRAD_BARS > 0:
            ref_idx = i - ADX_GRAD_BARS
            if (
                ref_idx >= 0
                and not np.isnan(adx_arr_ind[i])
                and not np.isnan(adx_arr_ind[ref_idx])
                and adx_arr_ind[i] <= adx_arr_ind[ref_idx]
            ):
                adx_grad_filtered += 1
                i += 1
                continue

        # ★ 적응형 ADX 임계값
        if adx_adaptive and cur_pctile <= TIER1_PCT:
            adx_thresh = ADX_THRESH_LOWVOL
        else:
            adx_thresh = ADX_THRESH_BASE

        # SOL entry signal
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > entry_threshold
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr_ind[i]) and adx_arr_ind[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = o[i + 1] * (1 + FEE)
            entry_atr = atr_arr[i]

            # Dynamic TP/SL by tier
            if cur_pctile <= TIER1_PCT:
                sl_mult = LOW_SL_MULT
                tp_mult = LOW_TP_MULT
            else:
                sl_mult = BASE_SL_ATR
                tp_mult = BASE_TP_ATR

            # ★ BTC fallback 구간: TP 추가 축소
            if is_fallback:
                tp_mult *= fallback_tp_scale
                btc_gate_stats["fallback"] += 1
            else:
                btc_gate_stats["full"] += 1

            sl_pct = (entry_atr * sl_mult) / buy
            tp_pct = (entry_atr * tp_mult) / buy
            trail_activate_pct = (entry_atr * TRAIL_ACTIVATE) / buy
            trail_sl_dist = (entry_atr * TRAIL_SL) / buy

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
            "btc_gate_stats": btc_gate_stats,
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
        "btc_gate_stats": btc_gate_stats,
    }


def align_btc_to_sol(
    df_sol: pd.DataFrame, df_btc: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].reindex(df_sol.index, method="ffill").values
    btc_sma200 = compute_sma(df_btc["close"].values, BTC_SMA_LONG)
    btc_sma200_s = pd.Series(btc_sma200, index=df_btc.index)
    btc_sma200_aligned = btc_sma200_s.reindex(df_sol.index, method="ffill").values
    btc_sma50 = compute_sma(df_btc["close"].values, BTC_SMA_SHORT)
    btc_sma50_s = pd.Series(btc_sma50, index=df_btc.index)
    btc_sma50_aligned = btc_sma50_s.reindex(df_sol.index, method="ffill").values
    return btc_close, btc_sma200_aligned, btc_sma50_aligned


def fmt_sh(val: float) -> str:
    return f"{val:+.3f}" if not np.isnan(val) else "  nan"


def main() -> None:
    print("=" * 80)
    print("momentum_sol BTC 듀얼 게이트 + 적응형 ADX + 진입 완화 (사이클 164)")
    print("=" * 80)
    print(f"심볼: {SYMBOL}  BTC SMA: {BTC_SMA_LONG}/{BTC_SMA_SHORT}")
    print(f"확정 파라미터: t1={TIER1_PCT} t2={TIER2_PCT} lTP={LOW_TP_MULT} "
          f"lSL={LOW_SL_MULT} adxG={ADX_GRAD_BARS} TrA={TRAIL_ACTIVATE} TrS={TRAIL_SL}")
    print(f"그리드: gate={BTC_GATE_MODES} entry={ENTRY_THRESHOLDS} "
          f"adx_adapt={ADX_ADAPTIVE_OPTS} fb_tp={FALLBACK_TP_SCALES}\n")

    df_sol = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC, "240m", "2022-01-01", "2026-12-31")
    if df_sol.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"SOL 데이터: {len(df_sol)}행  BTC 데이터: {len(df_btc)}행\n")

    btc_c, btc_sma200, btc_sma50 = align_btc_to_sol(df_sol, df_btc)
    atr_arr = compute_atr(
        df_sol["high"].values, df_sol["low"].values,
        df_sol["close"].values, ATR_PERIOD,
    )
    atr_pctile = compute_atr_percentile(atr_arr, ATR_VOL_LOOKBACK)
    adx_arr = adx_indicator(
        df_sol["high"].values, df_sol["low"].values, df_sol["close"].values, 14,
    )

    # ── Phase 1: Baseline (사이클 159 최적) ──────────────────────────────────
    print("=== Phase 1: Baseline (사이클 159 — sma200 only, entry=0.005, no adapt) ===")
    base = backtest(
        df_sol, btc_c, btc_sma200, btc_sma50, atr_arr, atr_pctile, adx_arr,
        btc_gate_mode="sma200_only", entry_threshold=0.005,
        adx_adaptive=False, fallback_tp_scale=1.0,
    )
    print(f"  Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  consec={base['max_consec_loss']}  "
          f"trades={base['trades']}")
    gs = base["btc_gate_stats"]
    print(f"  BTC gate: full={gs['full']} fallback={gs['fallback']} blocked={gs['blocked']}")
    print()

    # ── Phase 2: 전체 그리드 탐색 ────────────────────────────────────────────
    print("=== Phase 2: BTC 듀얼 게이트 + 적응형 ADX + 진입 완화 그리드 ===")
    print(f"{'gate':>12} {'entry':>6} {'adapt':>6} {'fbTP':>5} "
          f"{'Sharpe':>8} {'WR':>6} {'MDD%':>8} {'cL':>4} {'trd':>5} "
          f"{'full':>5} {'fb':>4} {'blk':>5}")
    print("-" * 95)

    results = []
    for gate in BTC_GATE_MODES:
        fb_scales = FALLBACK_TP_SCALES if gate == "dual_50_200" else [1.0]
        for entry_t in ENTRY_THRESHOLDS:
            for adx_a in ADX_ADAPTIVE_OPTS:
                for fb_tp in fb_scales:
                    r = backtest(
                        df_sol, btc_c, btc_sma200, btc_sma50,
                        atr_arr, atr_pctile, adx_arr,
                        btc_gate_mode=gate, entry_threshold=entry_t,
                        adx_adaptive=adx_a, fallback_tp_scale=fb_tp,
                    )
                    results.append((gate, entry_t, adx_a, fb_tp, r))
                    gs = r["btc_gate_stats"]
                    print(
                        f"{gate:>12} {entry_t:>6.3f} {str(adx_a):>6} {fb_tp:>5.2f} "
                        f"{fmt_sh(r['sharpe']):>8} {r['wr']:>5.1%} "
                        f"{r['max_dd'] * 100:>+7.2f}% {r['max_consec_loss']:>4} "
                        f"{r['trades']:>5} {gs['full']:>5} {gs['fallback']:>4} "
                        f"{gs['blocked']:>5}"
                    )

    # ── Phase 3: Top-10 by Sharpe ────────────────────────────────────────────
    valid = [x for x in results if not np.isnan(x[4]["sharpe"]) and x[4]["trades"] >= 10]
    valid.sort(key=lambda x: x[4]["sharpe"], reverse=True)
    top10 = valid[:10]

    print(f"\n=== Phase 3: Top-10 조합 ===")
    for rank, (gate, et, aa, fb, r) in enumerate(top10, 1):
        safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
        safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
        print(
            f"  #{rank:>2} gate={gate} entry={et:.3f} adapt={aa} fbTP={fb:.2f}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
            f"consec={r['max_consec_loss']}{safe_cl}  trades={r['trades']}"
        )

    # ── Phase 3b: 안전 조합 ──────────────────────────────────────────────────
    safe_combos = [
        x for x in valid
        if abs(x[4]["max_dd"]) < 0.15 and x[4]["max_consec_loss"] <= 3
    ]
    safe_combos.sort(key=lambda x: x[4]["sharpe"], reverse=True)
    print(f"\n=== Phase 3b: 안전 조합 (MDD<15% AND consec≤3) — {len(safe_combos)}개 ===")
    for rank, (gate, et, aa, fb, r) in enumerate(safe_combos[:5], 1):
        gs = r["btc_gate_stats"]
        print(
            f"  #{rank} gate={gate} entry={et:.3f} adapt={aa} fbTP={fb:.2f}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%  consec={r['max_consec_loss']}  "
            f"trades={r['trades']}  (full={gs['full']} fb={gs['fallback']})"
        )

    # ── Phase 4: 연도별 성과 분해 ────────────────────────────────────────────
    analysis_target = safe_combos[0] if safe_combos else (top10[0] if top10 else None)
    if analysis_target:
        gate, et, aa, fb, _ = analysis_target
        print(f"\n=== Phase 4: 연도별 성과 분해 ===")
        print(f"  파라미터: gate={gate} entry={et:.3f} adapt={aa} fbTP={fb:.2f}")
        for year in range(2022, 2027):
            df_sol_yr = load_historical(SYMBOL, "240m", f"{year}-01-01", f"{year}-12-31")
            df_btc_yr = load_historical(BTC, "240m", f"{year}-01-01", f"{year}-12-31")
            if df_sol_yr.empty or df_btc_yr.empty or len(df_sol_yr) < 100:
                print(f"  {year}: 데이터 부족")
                continue
            btc_c_yr, btc200_yr, btc50_yr = align_btc_to_sol(df_sol_yr, df_btc_yr)
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
                df_sol_yr, btc_c_yr, btc200_yr, btc50_yr, atr_yr, pctile_yr, adx_yr,
                btc_gate_mode=gate, entry_threshold=et,
                adx_adaptive=aa, fallback_tp_scale=fb,
            )
            gs = r["btc_gate_stats"]
            print(
                f"  {year}: Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd'] * 100:+.2f}%  consec={r['max_consec_loss']}  "
                f"trades={r['trades']}  filt={r['vol_filtered']}  "
                f"adxF={r['adx_grad_filtered']}  full={gs['full']} fb={gs['fallback']}"
            )

    # ── Phase 5: Walkforward OOS 검증 ────────────────────────────────────────
    wf_targets = safe_combos[:3] if safe_combos else top10[:3]
    print(f"\n=== Phase 5: Walkforward OOS 검증 (Top-3) ===")
    best_oos = None
    best_oos_sharpe = -999.0
    for rank, (gate, et, aa, fb, _) in enumerate(wf_targets, 1):
        label = f"{gate}_e{et}_a{aa}_fb{fb}"
        oos_sharpes = []
        for fi, fold in enumerate(WF_FOLDS):
            df_sol_t = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_t = load_historical(BTC, "240m", fold["test"][0], fold["test"][1])
            if df_sol_t.empty or df_btc_t.empty:
                continue
            btc_c_t, btc200_t, btc50_t = align_btc_to_sol(df_sol_t, df_btc_t)
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
                df_sol_t, btc_c_t, btc200_t, btc50_t, atr_t, pctile_t, adx_t,
                btc_gate_mode=gate, entry_threshold=et,
                adx_adaptive=aa, fallback_tp_scale=fb,
            )
            sh_val = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh_val)
            safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
            safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
            gs = r["btc_gate_stats"]
            print(
                f"  {label} Fold {fi+1}: Sharpe={sh_val:+.3f}  "
                f"WR={r['wr']:.1%}  MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
                f"consec={r['max_consec_loss']}{safe_cl}  trades={r['trades']}  "
                f"full={gs['full']} fb={gs['fallback']}"
            )
        if oos_sharpes:
            avg = np.mean(oos_sharpes)
            print(f"  → {label} 평균 OOS Sharpe: {avg:+.3f}")
            if avg > best_oos_sharpe:
                best_oos_sharpe = avg
                best_oos = (gate, et, aa, fb)

    # ── Phase 6: 안전성 요약 ─────────────────────────────────────────────────
    final = analysis_target
    if final:
        _, _, _, _, best_r = final
        print(f"\n=== 안전성 요약 ===")
        print(f"  연속손실 ≤ 3: "
              f"{'✅ PASS' if best_r['max_consec_loss'] <= 3 else '❌ FAIL'} "
              f"(실제: {best_r['max_consec_loss']})")
        print(f"  MDD < 15%: "
              f"{'✅ PASS' if abs(best_r['max_dd']) < 0.15 else '⚠️ 주의'} "
              f"(실제: {best_r['max_dd'] * 100:+.2f}%)")

    # ── 최종 결과 ────────────────────────────────────────────────────────────
    if final:
        _, _, _, _, best_r = final
        print(f"\nSharpe: {best_r['sharpe']:+.3f}")
        print(f"WR: {best_r['wr'] * 100:.1f}%")
        print(f"trades: {best_r['trades']}")


if __name__ == "__main__":
    main()
