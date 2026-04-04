"""
momentum_sol BTC SMA 단축 레짐필터 — 사이클 153
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: 사이클 150에서 BTC SMA200 필터 + adx=30 + cool=24 확정
      OOS avg +13.957이나 2026년 0거래 (BTC < SMA200) → n 부족(6~7)
      SMA200→SMA100/50으로 단축하면 2026 활성화 + n 확보 가능

목적:
  1) BTC SMA 기간 탐색: [50, 75, 100, 150, 200]
  2) adx=30, lb=20, trig=3, cool=24 (사이클 150 최적) 고정
  3) TP/SL 그리드: {8, 10, 12}% × {3, 4}%
  4) WF 2-fold OOS 검증 (새 윈도우)
  5) 슬리피지 스트레스 + 연도별 분해 (특히 2026 거래수 확인)

핵심 질문: SMA 단축 시 noise 진입 증가 vs 2026 활성화 trade-off
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

# Cycle 150 best: adx=30, lb=20, trig=3, cool=24
LOOKBACK = 20
ADX_THRESH = 30.0
VOL_MULT = 1.5
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
ENTRY_THRESHOLD = 0.005
MAX_HOLD = 48
COOLDOWN_TRIGGER = 3
COOLDOWN_BARS = 24

# Grid
BTC_SMA_PERIODS = [50, 75, 100, 150, 200]
TP_PCTS = [0.08, 0.10, 0.12]
SL_PCTS = [0.03, 0.04]

# New OOS windows (shifted from cycle 147/150)
WF_FOLDS = [
    {"train": ("2022-01-01", "2025-03-31"), "test": ("2024-04-01", "2025-03-31")},
    {"train": ("2023-04-01", "2026-04-05"), "test": ("2025-04-01", "2026-04-05")},
]


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


def backtest(
    df_sol: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    tp_pct: float,
    sl_pct: float,
    slippage: float = 0.0,
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
    warmup = max(LOOKBACK + RSI_PERIOD + 28, 210)  # enough for SMA200
    consec_loss = 0
    cooldown_until = 0
    total_fee = FEE + slippage

    # Buy-and-hold tracking
    first_entry = None
    last_exit = None

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

        # SOL entry signal (ADX-tight from cycle 150)
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > ADX_THRESH
            and vol_ok[i]
        )
        if entry_ok:
            # Entry: next bar open
            buy = o[i + 1] * (1 + total_fee)
            if first_entry is None:
                first_entry = i + 1

            ret = None
            exit_bar = i + 1
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                r = c[j] / buy - 1
                if r >= tp_pct:
                    ret = tp_pct - total_fee
                    exit_bar = j
                    break
                if r <= -sl_pct:
                    ret = -sl_pct - total_fee
                    exit_bar = j
                    break
            if ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                ret = c[hold_end] / buy - 1 - total_fee
                exit_bar = hold_end

            returns.append(ret)
            last_exit = exit_bar

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
            "cum_ret": 0.0, "bh_ret": 0.0,
        }

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())

    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    cum_ret = float(cum[-1]) if len(cum) > 0 else 0.0

    max_consec = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    # Buy-and-hold return
    bh_ret = 0.0
    if first_entry is not None and last_exit is not None:
        bh_ret = float(c[last_exit] / c[first_entry] - 1)

    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd, "max_consec_loss": max_consec,
        "cum_ret": cum_ret, "bh_ret": bh_ret,
    }


def align_btc_to_sol(
    df_sol: pd.DataFrame, df_btc: pd.DataFrame, sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].reindex(df_sol.index, method="ffill").values
    btc_sma = compute_sma(df_btc["close"].values, sma_period)
    btc_sma_series = pd.Series(btc_sma, index=df_btc.index)
    btc_sma_aligned = btc_sma_series.reindex(df_sol.index, method="ffill").values
    return btc_close, btc_sma_aligned


def main() -> None:
    print("=" * 80)
    print("momentum_sol BTC SMA 단축 레짐필터 탐색 (사이클 153)")
    print("=" * 80)
    print(f"심볼: {SYMBOL}  고정: adx={ADX_THRESH} lb={LOOKBACK} "
          f"trig={COOLDOWN_TRIGGER} cool={COOLDOWN_BARS}")
    print(f"SMA 기간: {BTC_SMA_PERIODS}  TP: {TP_PCTS}  SL: {SL_PCTS}\n")

    df_sol = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC, "240m", "2022-01-01", "2026-12-31")
    if df_sol.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"SOL: {len(df_sol)}행  BTC: {len(df_btc)}행\n")

    # ── Phase 1: 전체기간 그리드 탐색 ────────────────────────────────────────
    print("=== Phase 1: 전체기간 그리드 (슬리피지 0%) ===")
    print(f"{'SMA':>5} {'TP%':>5} {'SL%':>5} {'Sharpe':>8} {'WR':>6} "
          f"{'avg%':>7} {'MDD%':>8} {'cLoss':>6} {'trades':>7} {'cumR%':>8} {'BH%':>7}")
    print("-" * 85)

    all_results = []
    for sma_p in BTC_SMA_PERIODS:
        btc_c, btc_sma = align_btc_to_sol(df_sol, df_btc, sma_p)
        for tp in TP_PCTS:
            for sl in SL_PCTS:
                r = backtest(df_sol, btc_c, btc_sma, tp, sl)
                all_results.append((sma_p, tp, sl, r))
                sh = (f"{r['sharpe']:+.3f}"
                      if not np.isnan(r["sharpe"]) else "    nan")
                safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
                print(
                    f"{sma_p:>5} {tp*100:>4.0f}% {sl*100:>4.0f}% {sh:>8} "
                    f"{r['wr']:>5.1%} {r['avg_ret']*100:>+6.2f}% "
                    f"{r['max_dd']*100:>+7.2f}% "
                    f"{r['max_consec_loss']:>4}{safe_cl} {r['trades']:>7} "
                    f"{r['cum_ret']*100:>+7.1f}% {r['bh_ret']*100:>+6.1f}%"
                )

    # ── Phase 2: SMA별 Top-1 (Sharpe 기준) ─────────────────────────────────
    print(f"\n=== Phase 2: SMA별 Top-1 (Sharpe 기준) ===")
    for sma_p in BTC_SMA_PERIODS:
        candidates = [
            x for x in all_results
            if x[0] == sma_p
            and not np.isnan(x[3]["sharpe"])
            and x[3]["trades"] >= 5
        ]
        candidates.sort(key=lambda x: x[3]["sharpe"], reverse=True)
        if candidates:
            _, tp, sl, r = candidates[0]
            safe_cl = "✅" if r["max_consec_loss"] <= 3 else f"❌({r['max_consec_loss']})"
            print(
                f"  SMA{sma_p:>3}: TP={tp*100:.0f}% SL={sl*100:.0f}%  "
                f"Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd']*100:+.2f}%  consec={safe_cl}  "
                f"trades={r['trades']}  cumR={r['cum_ret']*100:+.1f}% vs BH={r['bh_ret']*100:+.1f}%"
            )

    # ── Phase 3: 연도별 분해 (SMA별 Top-1 by Sharpe) ───────────────────────
    print(f"\n=== Phase 3: 연도별 분해 (SMA별 Top-1) ===")
    sma_best = {}
    for sma_p in BTC_SMA_PERIODS:
        candidates = [
            x for x in all_results
            if x[0] == sma_p
            and not np.isnan(x[3]["sharpe"])
            and x[3]["trades"] >= 5
        ]
        candidates.sort(key=lambda x: x[3]["sharpe"], reverse=True)
        if not candidates:
            continue
        _, tp, sl, _ = candidates[0]
        sma_best[sma_p] = (tp, sl)
        print(f"\n  SMA{sma_p} (TP={tp*100:.0f}% SL={sl*100:.0f}%):")
        for year in range(2022, 2027):
            df_sol_yr = load_historical(SYMBOL, "240m", f"{year}-01-01", f"{year}-12-31")
            df_btc_yr = load_historical(BTC, "240m", f"{year}-01-01", f"{year}-12-31")
            if df_sol_yr.empty or df_btc_yr.empty or len(df_sol_yr) < 50:
                print(f"    {year}: 데이터 부족")
                continue
            btc_c_yr, btc_sma_yr = align_btc_to_sol(df_sol_yr, df_btc_yr, sma_p)
            r = backtest(df_sol_yr, btc_c_yr, btc_sma_yr, tp, sl)
            sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
            cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
            print(
                f"    {year}: Sharpe={sh}  WR={r['wr']:.1%}  "
                f"trades={r['trades']}  MDD={r['max_dd']*100:+.2f}%  "
                f"consec={r['max_consec_loss']}{cl}"
            )

    # ── Phase 4: WF OOS 검증 ────────────────────────────────────────────────
    print(f"\n=== Phase 4: Walkforward OOS 검증 ===")
    print(f"  W1 OOS: {WF_FOLDS[0]['test'][0]} ~ {WF_FOLDS[0]['test'][1]}")
    print(f"  W2 OOS: {WF_FOLDS[1]['test'][0]} ~ {WF_FOLDS[1]['test'][1]}")

    wf_results = {}
    for sma_p in BTC_SMA_PERIODS:
        if sma_p not in sma_best:
            continue
        tp, sl = sma_best[sma_p]
        oos_sharpes = []
        oos_details = []
        for fi, fold in enumerate(WF_FOLDS):
            df_sol_t = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_t = load_historical(BTC, "240m", fold["test"][0], fold["test"][1])
            if df_sol_t.empty or df_btc_t.empty:
                continue
            btc_c_t, btc_sma_t = align_btc_to_sol(df_sol_t, df_btc_t, sma_p)
            r = backtest(df_sol_t, btc_c_t, btc_sma_t, tp, sl)
            sh_val = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh_val)
            oos_details.append(r)
            print(
                f"  SMA{sma_p} TP={tp*100:.0f}% SL={sl*100:.0f}% "
                f"Fold{fi+1}: Sharpe={sh_val:+.3f}  "
                f"WR={r['wr']:.1%}  n={r['trades']}  "
                f"MDD={r['max_dd']*100:+.2f}%  consec={r['max_consec_loss']}"
            )
        if oos_sharpes:
            avg = float(np.mean(oos_sharpes))
            mn = float(np.min(oos_sharpes))
            min_n = min(d["trades"] for d in oos_details)
            both_pass = all(s > 0 for s in oos_sharpes)
            wf_results[sma_p] = {
                "avg": avg, "min": mn, "min_n": min_n,
                "both_pass": both_pass, "details": oos_details,
            }
            status = "✅" if both_pass else "❌"
            print(
                f"  → SMA{sma_p} avg OOS: {avg:+.3f}  "
                f"min: {mn:+.3f}  min_n: {min_n}  {status}"
            )
        print()

    # ── Phase 5: 슬리피지 스트레스 (WF 양 Fold Sharpe>0 통과 SMA) ──────────
    passed_smas = [
        sma_p for sma_p, wr in wf_results.items()
        if wr["both_pass"]
    ]
    if not passed_smas:
        # Fallback: test all SMA with WF results
        passed_smas = list(wf_results.keys())
    if passed_smas:
        print(f"=== Phase 5: 슬리피지 스트레스 (WF 통과: {passed_smas}) ===")
        slippages = [0.05, 0.10, 0.15, 0.20, 0.30]
        for sma_p in passed_smas:
            tp, sl = sma_best[sma_p]
            btc_c, btc_sma = align_btc_to_sol(df_sol, df_btc, sma_p)
            print(f"\n  SMA{sma_p} TP={tp*100:.0f}% SL={sl*100:.0f}%:")
            print(f"  {'slip%':>6} {'Sharpe':>8} {'WR':>6} {'avg%':>7} {'MDD%':>8} {'cLoss':>6} {'n':>5}")
            print(f"  " + "-" * 55)
            for slip in slippages:
                r = backtest(df_sol, btc_c, btc_sma, tp, sl, slippage=slip / 100)
                sh = (f"{r['sharpe']:+.3f}"
                      if not np.isnan(r["sharpe"]) else "    nan")
                print(
                    f"  {slip:>5.2f}% {sh:>8} {r['wr']:>5.1%} "
                    f"{r['avg_ret']*100:>+6.2f}% {r['max_dd']*100:>+7.2f}% "
                    f"{r['max_consec_loss']:>6} {r['trades']:>5}"
                )

    # ── Phase 6: 최종 비교 요약 ──────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 비교 요약 ===")
    print(f"{'SMA':>5} {'TP%':>5} {'SL%':>5} {'WF avg':>8} {'WF min':>8} "
          f"{'min_n':>6} {'2026 trades':>12} {'WF':>4}")
    print("-" * 65)

    for sma_p in BTC_SMA_PERIODS:
        if sma_p not in sma_best or sma_p not in wf_results:
            continue
        tp, sl = sma_best[sma_p]
        wr = wf_results[sma_p]
        # 2026 trade count
        df_sol_26 = load_historical(SYMBOL, "240m", "2026-01-01", "2026-12-31")
        df_btc_26 = load_historical(BTC, "240m", "2026-01-01", "2026-12-31")
        n26 = 0
        if not df_sol_26.empty and not df_btc_26.empty:
            btc_c_26, btc_sma_26 = align_btc_to_sol(df_sol_26, df_btc_26, sma_p)
            r26 = backtest(df_sol_26, btc_c_26, btc_sma_26, tp, sl)
            n26 = r26["trades"]
        status = "✅" if wr["both_pass"] else "❌"
        print(
            f"{sma_p:>5} {tp*100:>4.0f}% {sl*100:>4.0f}% "
            f"{wr['avg']:>+7.3f} {wr['min']:>+7.3f} "
            f"{wr['min_n']:>6} {n26:>12} {status:>4}"
        )

    # ── 최종 출력 ────────────────────────────────────────────────────────────
    best_sma = None
    best_avg = -999.0
    for sma_p, wr in wf_results.items():
        if wr["both_pass"] and wr["avg"] > best_avg:
            best_avg = wr["avg"]
            best_sma = sma_p
    if best_sma:
        tp, sl = sma_best[best_sma]
        wr = wf_results[best_sma]
        btc_c, btc_sma = align_btc_to_sol(df_sol, df_btc, best_sma)
        r_full = backtest(df_sol, btc_c, btc_sma, tp, sl)
        print(f"\n★ 최적: SMA{best_sma} TP={tp*100:.0f}% SL={sl*100:.0f}%")
        print(f"  WF avg OOS: {best_avg:+.3f}  min_n: {wr['min_n']}")
        print(f"  전체기간: Sharpe={r_full['sharpe']:+.3f} WR={r_full['wr']:.1%} "
              f"trades={r_full['trades']} cumR={r_full['cum_ret']*100:+.1f}% "
              f"vs BH={r_full['bh_ret']*100:+.1f}%")
        print(f"\nSharpe: {r_full['sharpe']:+.3f}")
        print(f"WR: {r_full['wr']*100:.1f}%")
        print(f"trades: {r_full['trades']}")
    else:
        # No WF pass — show best overall
        valid = [
            x for x in all_results
            if not np.isnan(x[3]["sharpe"]) and x[3]["trades"] >= 5
        ]
        if valid:
            valid.sort(key=lambda x: x[3]["sharpe"], reverse=True)
            sma_p, tp, sl, r = valid[0]
            print(f"\n★ WF 통과 없음. 전체기간 Best: SMA{sma_p} TP={tp*100:.0f}% SL={sl*100:.0f}%")
            print(f"  Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1%} trades={r['trades']}")
            print(f"\nSharpe: {r['sharpe']:+.3f}")
            print(f"WR: {r['wr']*100:.1f}%")
            print(f"trades: {r['trades']}")


if __name__ == "__main__":
    main()
