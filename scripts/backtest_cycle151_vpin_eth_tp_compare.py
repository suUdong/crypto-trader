"""
vpin_eth 사이클 151 — TP=6% vs TP=4.5% 직접 WF 비교 (평가자 블로커 #1 해소)
- 배경: daemon TP=6%/SL=0.8%, 평가자 보고 최적이 TP=4.5%/SL=0.8%
- 목적: 동일 조건(daemon 파라미터) 하에서 TP 변경만으로 성능 차이 직접 확인
- c148 BVC VPIN 로직 유지, 진입: next_bar open
- TP fine-grid: {3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0}% × SL {0.6, 0.8, 1.0}%
- 2-fold WF + 슬리피지 스트레스 + BH 비교
- 연도별 분해 포함
"""
from __future__ import annotations

import math
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
FEE = 0.0005

# ── daemon 고정 파라미터 (변경하지 않음) ──────────────────────────────────────
VPIN_LOW = 0.35
VPIN_MOM = 0.0005
MAX_HOLD = 18
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8

# ── TP/SL fine-grid (이것만 탐색) ────────────────────────────────────────────
TP_LIST = [0.035, 0.040, 0.045, 0.050, 0.055, 0.060, 0.065, 0.070]
SL_LIST = [0.006, 0.008, 0.010]

# ── Walkforward 기간 ─────────────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def ema_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def rsi_calc(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def compute_vpin_bvc(
    closes: np.ndarray, opens: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray, bucket_count: int = 24,
) -> np.ndarray:
    """Production-matching VPIN: BVC + normal CDF + volume weighting."""
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(bucket_count, n):
        total_vol = 0.0
        abs_imbalance = 0.0
        for j in range(i - bucket_count, i):
            price_range = highs[j] - lows[j]
            if price_range <= 0:
                buy_frac = 0.5
            else:
                z = (closes[j] - opens[j]) / price_range
                buy_frac = _normal_cdf(z)
            bv = volumes[j] * buy_frac
            sv = volumes[j] * (1.0 - buy_frac)
            abs_imbalance += abs(bv - sv)
            total_vol += volumes[j]
        if total_vol > 0:
            result[i] = abs_imbalance / total_vol
        else:
            result[i] = 0.5
    return result


def compute_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


# ── 백테스트 (고정 TP/SL) ────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    tp: float,
    sl: float,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK) + 5
    i = warmup

    while i < n - 1:
        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)):
            i += 1
            continue

        entry_ok = (
            vpin_val < VPIN_LOW
            and mom_val >= VPIN_MOM
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )

        if entry_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            exit_ret = None

            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1

                if ret >= tp:
                    exit_ret = tp - FEE - slippage
                    i = j
                    break

                if ret <= -sl:
                    exit_ret = -sl - FEE - slippage
                    i = j
                    break

            if exit_ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
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
    cum_ret = float(np.prod(1 + arr) - 1)
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl,
            "cum_ret": cum_ret}


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def backtest_yearly(
    df: pd.DataFrame, tp: float, sl: float, slippage: float = 0.0005,
) -> dict[int, dict]:
    """연도별 분해."""
    df = df.copy()
    if "timestamp" in df.columns:
        df["year"] = pd.to_datetime(df["timestamp"]).dt.year
    else:
        df["year"] = df.index.year
    results = {}
    for year, group in df.groupby("year"):
        if len(group) < 30:
            continue
        r = backtest(group.reset_index(drop=True), tp, sl, slippage)
        results[int(year)] = r
    return results


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth 사이클 151 — TP=6% vs TP=4.5% 직접 WF 비교 ===")
    print(f"심볼: {SYMBOL}  목표: 평가자 블로커 #1 해소")
    print(f"daemon 현행: TP=6% SL=0.8%  |  비교 대상: TP=4.5% SL=0.8%")
    print(f"고정: vpin_low={VPIN_LOW} vpin_mom={VPIN_MOM} hold={MAX_HOLD}")
    print("=" * 80)

    # ── Phase 1: 전체 기간 TP fine-grid ──────────────────────────────────────
    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_full.empty:
        print("데이터 로드 실패.")
        return
    print(f"\n전체 데이터: {len(df_full)}행")
    bh_full = buy_and_hold(df_full)
    print(f"Buy-and-Hold (전체): {bh_full * 100:+.1f}%")

    grid_size = len(TP_LIST) * len(SL_LIST)
    print(f"\n--- 전체 기간 TP/SL 그리드 ({len(TP_LIST)}x{len(SL_LIST)}="
          f"{grid_size}조합) ---")
    hdr = (f"{'TP%':>5} {'SL%':>5} | {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
           f"{'MDD':>7} {'MCL':>4} {'n':>5} {'cumR%':>8}")
    print(hdr)
    print("-" * len(hdr))

    all_results: list[dict] = []
    for tp, sl in product(TP_LIST, SL_LIST):
        r = backtest(df_full, tp, sl)
        all_results.append({"tp": tp, "sl": sl, **r})
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(
            f"{tp * 100:>4.1f}% {sl * 100:>4.1f}% | "
            f"{sh:>8} {r['wr']:>5.1%} {r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5} "
            f"{r.get('cum_ret', 0) * 100:>+7.1f}%"
        )

    # ── 핵심 비교: daemon(TP=6%/SL=0.8%) vs 후보(TP=4.5%/SL=0.8%) ──────────
    print(f"\n{'=' * 80}")
    print("=== 핵심 비교: daemon(TP=6%/SL=0.8%) vs 후보(TP=4.5%/SL=0.8%) ===")
    daemon_r = backtest(df_full, 0.06, 0.008)
    cand_r = backtest(df_full, 0.045, 0.008)
    print(f"  daemon TP=6%:   Sharpe={daemon_r['sharpe']:+.3f}  "
          f"WR={daemon_r['wr']:.1%}  n={daemon_r['trades']}  "
          f"avg={daemon_r['avg_ret'] * 100:+.2f}%  "
          f"MDD={daemon_r['max_dd'] * 100:+.2f}%  MCL={daemon_r['mcl']}  "
          f"cumR={daemon_r.get('cum_ret', 0) * 100:+.1f}%")
    print(f"  후보   TP=4.5%: Sharpe={cand_r['sharpe']:+.3f}  "
          f"WR={cand_r['wr']:.1%}  n={cand_r['trades']}  "
          f"avg={cand_r['avg_ret'] * 100:+.2f}%  "
          f"MDD={cand_r['max_dd'] * 100:+.2f}%  MCL={cand_r['mcl']}  "
          f"cumR={cand_r.get('cum_ret', 0) * 100:+.1f}%")
    delta_sh = cand_r["sharpe"] - daemon_r["sharpe"]
    print(f"  Δ Sharpe: {delta_sh:+.3f}")

    # ── Phase 2: OOS Walk-Forward 검증 ────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== OOS Walk-Forward 검증 (전체 TP/SL 그리드, 2-fold) ===")

    wf_results: list[dict] = []
    for tp, sl in product(TP_LIST, SL_LIST):
        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold in WF_FOLDS:
            df_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1],
            )
            if df_test.empty:
                continue
            r = backtest(df_test, tp, sl)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            all_pass = all(s >= 5.0 for s in oos_sharpes)
            print(f"  TP={tp * 100:.1f}% SL={sl * 100:.1f}% | "
                  f"F1={oos_sharpes[0]:+.3f}(n={oos_trades[0]}) "
                  f"F2={oos_sharpes[1]:+.3f}(n={oos_trades[1]}) "
                  f"avg={avg_oos:+.3f} {'✅' if all_pass else '❌'}")
            wf_results.append({
                "tp": tp, "sl": sl,
                "avg_oos": avg_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "all_pass": all_pass,
                "fold_details": fold_details,
            })

    # ── daemon vs 후보 OOS 상세 ────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== daemon(TP=6%) vs 후보(TP=4.5%) OOS 상세 ===")
    for item in wf_results:
        if (item["tp"] == 0.06 and item["sl"] == 0.008) or \
           (item["tp"] == 0.045 and item["sl"] == 0.008):
            label = "daemon" if item["tp"] == 0.06 else "후보  "
            print(f"\n  [{label}] TP={item['tp'] * 100:.1f}% "
                  f"SL={item['sl'] * 100:.1f}%")
            for fi, fd in enumerate(item["fold_details"]):
                print(f"    Fold {fi + 1}: Sharpe="
                      f"{item['oos_sharpes'][fi]:+.3f}  "
                      f"WR={fd['wr']:.1%}  n={item['oos_trades'][fi]}  "
                      f"avg={fd['avg_ret'] * 100:+.2f}%  "
                      f"MDD={fd['max_dd'] * 100:+.2f}%  MCL={fd['mcl']}")
            print(f"    avg OOS: {item['avg_oos']:+.3f}")

    # ── Phase 3: 슬리피지 스트레스 (daemon vs 후보) ───────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (daemon vs 후보) ===")
    for label, tp, sl in [("daemon TP=6%", 0.06, 0.008),
                           ("후보 TP=4.5%", 0.045, 0.008)]:
        print(f"\n--- {label} SL={sl * 100:.1f}% ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_full, tp, sl, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── Phase 4: 연도별 분해 ──────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 연도별 분해 (daemon vs 후보) ===")
    for label, tp, sl in [("daemon TP=6%", 0.06, 0.008),
                           ("후보 TP=4.5%", 0.045, 0.008)]:
        print(f"\n--- {label} ---")
        yearly = backtest_yearly(df_full, tp, sl)
        print(f"  {'연도':>4} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        for year in sorted(yearly.keys()):
            r = yearly[year]
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {year:>4} {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── WF Top 5 + BH 비교 ───────────────────────────────────────────────────
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos"], reverse=True)
    print(f"\n{'=' * 80}")
    print("=== WF OOS Top 5 (avg Sharpe 기준) ===")
    for rank, item in enumerate(wf_sorted[:5], 1):
        tp_pct = item["tp"] * 100
        sl_pct = item["sl"] * 100
        full_r = backtest(df_full, item["tp"], item["sl"])
        print(f"  #{rank}: TP={tp_pct:.1f}% SL={sl_pct:.1f}% | "
              f"avg OOS={item['avg_oos']:+.3f} "
              f"F1={item['oos_sharpes'][0]:+.3f}(n={item['oos_trades'][0]}) "
              f"F2={item['oos_sharpes'][1]:+.3f}(n={item['oos_trades'][1]}) "
              f"| full: Sh={full_r['sharpe']:+.3f} WR={full_r['wr']:.1%} "
              f"cumR={full_r.get('cum_ret', 0) * 100:+.1f}% "
              f"vs BH={bh_full * 100:+.1f}% "
              f"{'✅' if item['all_pass'] else '❌'}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best = wf_sorted[0]
    best_full = backtest(df_full, best["tp"], best["sl"])
    print(f"★ OOS 최적: TP={best['tp'] * 100:.1f}% SL={best['sl'] * 100:.1f}%")
    oos_avg = best["avg_oos"]
    status = "✅ ≥5.0" if oos_avg >= 5.0 else "❌ <5.0"
    print(f"  avg OOS Sharpe: {oos_avg:+.3f} {status}")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={best['oos_trades'][fi]}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    total_trades = sum(best["oos_trades"])
    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))
    print(f"  전체 cumR: {best_full.get('cum_ret', 0) * 100:+.1f}% "
          f"vs BH {bh_full * 100:+.1f}%")

    # daemon vs 후보 결론
    daemon_wf = next((w for w in wf_results
                      if w["tp"] == 0.06 and w["sl"] == 0.008), None)
    cand_wf = next((w for w in wf_results
                    if w["tp"] == 0.045 and w["sl"] == 0.008), None)
    if daemon_wf and cand_wf:
        print(f"\n  daemon(TP=6%) avg OOS: {daemon_wf['avg_oos']:+.3f}")
        print(f"  후보(TP=4.5%) avg OOS: {cand_wf['avg_oos']:+.3f}")
        delta = cand_wf["avg_oos"] - daemon_wf["avg_oos"]
        if delta > 1.0:
            print(f"  → TP=4.5%가 유의미한 개선 (Δ={delta:+.3f}) "
                  "— daemon 업데이트 권장")
        elif delta > 0:
            print(f"  → TP=4.5%가 소폭 우세 (Δ={delta:+.3f}) "
                  "— 현행 유지 또는 전환 검토")
        else:
            print(f"  → TP=6%가 우세 (Δ={delta:+.3f}) — 현행 daemon 유지")

    # pipeline output
    print(f"\nSharpe: {oos_avg:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
