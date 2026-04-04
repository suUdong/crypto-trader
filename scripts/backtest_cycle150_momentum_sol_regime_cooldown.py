"""
momentum_sol ADX-tight + BTC 레짐 필터 + 연속손실 쿨다운 — 사이클 150
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: 사이클 147 결과에서 ADX-tight (adx=25) 가 OOS Sharpe +8.879 로 최강.
      그러나 연속손실=6 (SAFE_MAX=3 초과), MDD=-15.25%.
      2022/2026 약세장 구간이 성과를 끌어내림.

목적:
  1) BTC SMA 레짐 필터: BTC close > SMA(N) 일 때만 진입 → 약세장 필터링
  2) 연속손실 쿨다운: K회 연속 손실 후 C캔들 동안 진입 금지
  3) 두 조건 결합 시 MDD/연속손실 개선 + Sharpe 유지 여부 검증
  4) Walkforward OOS로 과적합 체크

그리드:
  BTC SMA: [50, 100, 150, 200]
  쿨다운 트리거: [2, 3]
  쿨다운 기간: [6, 12, 24]
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

# ADX-tight base params from cycle 147
LOOKBACK = 20
ADX_THRESH = 25.0
VOL_MULT = 1.5
TP = 0.08
SL = 0.03
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
ENTRY_THRESHOLD = 0.005
MAX_HOLD = 48

# Grid
BTC_SMA_PERIODS = [50, 100, 150, 200]
COOLDOWN_TRIGGERS = [2, 3]   # 연속 손실 N회 후 쿨다운
COOLDOWN_BARS = [6, 12, 24]  # 쿨다운 캔들 수

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


# ── 백테스트 (레짐 필터 + 쿨다운) ────────────────────────────────────────────

def backtest(
    df_sol: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    cooldown_trigger: int,
    cooldown_bars: int,
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
    adx_arr = adx_indicator(h, lo, c, 14)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = LOOKBACK + RSI_PERIOD + 28
    consec_loss = 0
    cooldown_until = 0  # bar index until which we skip entries

    i = warmup
    while i < n - 1:
        # Cooldown check
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

        # SOL entry signal (ADX-tight base)
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > ADX_THRESH
            and vol_ok[i]
        )
        if entry_ok:
            buy = o[i + 1] * (1 + FEE)  # next bar open (규칙 준수)
            ret = None
            exit_bar = i + 1
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                r = c[j] / buy - 1
                if r >= TP:
                    ret = TP - FEE
                    exit_bar = j
                    break
                if r <= -SL:
                    ret = -SL - FEE
                    exit_bar = j
                    break
            if ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                ret = c[hold_end] / buy - 1 - FEE
                exit_bar = hold_end

            returns.append(ret)

            # Update consecutive loss tracker
            if ret < 0:
                consec_loss += 1
                if consec_loss >= cooldown_trigger:
                    cooldown_until = exit_bar + cooldown_bars
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
    df_sol: pd.DataFrame, df_btc: pd.DataFrame, sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Align BTC close and SMA to SOL index via forward-fill."""
    btc_close = df_btc["close"].reindex(df_sol.index, method="ffill").values
    btc_sma = compute_sma(df_btc["close"].values, sma_period)
    btc_sma_series = pd.Series(btc_sma, index=df_btc.index)
    btc_sma_aligned = btc_sma_series.reindex(df_sol.index, method="ffill").values
    return btc_close, btc_sma_aligned


def main() -> None:
    print("=" * 72)
    print("momentum_sol ADX-tight + BTC 레짐 + 쿨다운 (사이클 150)")
    print("=" * 72)
    print(f"심볼: {SYMBOL}  베이스: ADX-tight (adx=25, lb=20, tp=8%, sl=3%)")
    print(f"BTC SMA 기간: {BTC_SMA_PERIODS}")
    print(f"쿨다운 트리거: {COOLDOWN_TRIGGERS}  쿨다운 캔들: {COOLDOWN_BARS}\n")

    df_sol = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC, "240m", "2022-01-01", "2026-12-31")
    if df_sol.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"SOL 데이터: {len(df_sol)}행  BTC 데이터: {len(df_btc)}행\n")

    # ── Phase 1: Baseline (필터 없음) ─────────────────────────────────────────
    print("=== Phase 1: Baseline (ADX-tight, 필터 없음) ===")
    btc_c_dummy = np.full(len(df_sol), 1e9)  # always above SMA
    btc_sma_dummy = np.full(len(df_sol), 0.0)
    base = backtest(df_sol, btc_c_dummy, btc_sma_dummy, 999, 0)
    print(f"  Sharpe: {base['sharpe']:+.3f}  WR: {base['wr']:.1%}  "
          f"avg: {base['avg_ret'] * 100:+.2f}%  MDD: {base['max_dd'] * 100:+.2f}%  "
          f"consec_loss: {base['max_consec_loss']}  trades: {base['trades']}\n")

    # ── Phase 2: 그리드 탐색 ─────────────────────────────────────────────────
    print("=== Phase 2: BTC 레짐 + 쿨다운 그리드 ===")
    print(f"{'sma':>5} {'trig':>5} {'cool':>5} {'Sharpe':>8} {'WR':>6} "
          f"{'avg%':>7} {'MDD%':>8} {'cLoss':>6} {'trades':>7}")
    print("-" * 68)

    results = []
    for sma_p in BTC_SMA_PERIODS:
        btc_c, btc_sma = align_btc_to_sol(df_sol, df_btc, sma_p)
        for trig in COOLDOWN_TRIGGERS:
            for cool in COOLDOWN_BARS:
                r = backtest(df_sol, btc_c, btc_sma, trig, cool)
                results.append((sma_p, trig, cool, r))
                sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "    nan"
                print(
                    f"{sma_p:>5} {trig:>5} {cool:>5} {sh:>8} "
                    f"{r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
                    f"{r['max_dd'] * 100:>+7.2f}% "
                    f"{r['max_consec_loss']:>6} {r['trades']:>7}"
                )

    # ── Phase 3: Top-5 by Sharpe ─────────────────────────────────────────────
    valid = [(s, t, c, r) for s, t, c, r in results if not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x[3]["sharpe"], reverse=True)
    top5 = valid[:5]

    print(f"\n=== Phase 3: Top-5 조합 ===")
    for rank, (sma_p, trig, cool, r) in enumerate(top5, 1):
        safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
        safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
        print(
            f"  #{rank} SMA={sma_p} trig={trig} cool={cool}  "
            f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
            f"consec={r['max_consec_loss']}{safe_cl}  trades={r['trades']}"
        )

    # ── Phase 4: Top-1 연도별 분해 ───────────────────────────────────────────
    if top5:
        best_sma, best_trig, best_cool, best_r = top5[0]
        print(f"\n=== Phase 4: Top-1 연도별 성과 분해 ===")
        print(f"  파라미터: SMA={best_sma} trig={best_trig} cool={best_cool}")
        for year in range(2022, 2027):
            df_sol_yr = load_historical(SYMBOL, "240m", f"{year}-01-01", f"{year}-12-31")
            df_btc_yr = load_historical(BTC, "240m", f"{year}-01-01", f"{year}-12-31")
            if df_sol_yr.empty or df_btc_yr.empty or len(df_sol_yr) < 100:
                print(f"  {year}: 데이터 부족")
                continue
            btc_c, btc_sma = align_btc_to_sol(df_sol_yr, df_btc_yr, best_sma)
            r = backtest(df_sol_yr, btc_c, btc_sma, best_trig, best_cool)
            sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
            print(
                f"  {year}: Sharpe={sh}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd'] * 100:+.2f}%  "
                f"consec={r['max_consec_loss']}  trades={r['trades']}"
            )

    # ── Phase 5: Walkforward OOS 검증 (Top-3) ────────────────────────────────
    print(f"\n=== Phase 5: Walkforward OOS 검증 (Top-3) ===")
    for rank, (sma_p, trig, cool, _) in enumerate(top5[:3], 1):
        label = f"SMA{sma_p}_t{trig}_c{cool}"
        oos_sharpes = []
        for fi, fold in enumerate(WF_FOLDS):
            df_sol_t = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_t = load_historical(BTC, "240m", fold["test"][0], fold["test"][1])
            if df_sol_t.empty or df_btc_t.empty:
                continue
            btc_c, btc_sma = align_btc_to_sol(df_sol_t, df_btc_t, sma_p)
            r = backtest(df_sol_t, btc_c, btc_sma, trig, cool)
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

    # ── Phase 6: 안전성 요약 ─────────────────────────────────────────────────
    if top5:
        _, _, _, best_r = top5[0]
        print(f"\n=== 안전성 요약 (Top-1) ===")
        print(f"  연속손실 ≤ 3: "
              f"{'✅ PASS' if best_r['max_consec_loss'] <= 3 else '❌ FAIL'} "
              f"(실제: {best_r['max_consec_loss']})")
        print(f"  MDD < 15%: "
              f"{'✅ PASS' if abs(best_r['max_dd']) < 0.15 else '⚠️ 주의'} "
              f"(실제: {best_r['max_dd'] * 100:+.2f}%)")

    # ── 최종 결과 ────────────────────────────────────────────────────────────
    if top5:
        _, _, _, best_r = top5[0]
        print(f"\nSharpe: {best_r['sharpe']:+.3f}")
        print(f"WR: {best_r['wr'] * 100:.1f}%")
        print(f"trades: {best_r['trades']}")


if __name__ == "__main__":
    main()
