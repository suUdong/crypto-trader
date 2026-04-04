"""
vpin_eth 사이클 152 — TP=7% daemon 배포 결정
- 배경: cycle 151에서 TP=7.0%/SL=0.8% avg OOS +8.379 (최적)
        daemon 현행 TP=6.0%/SL=0.8% avg OOS +7.625
        TP=7%가 Δ+0.754 우세하나 daemon 반영 전 상세 검증 필요
- 검증:
  1) TP=6% vs 7% 슬리피지 스트레스 (0.05%~0.30%, 6단계)
  2) 연도별 분해 (2022~2026, 각 Sharpe/WR/n/MDD)
  3) MDD/MCL/cumR 직접 비교
  4) TP=6.5%/7.5%도 포함 (경계 분석)
- BVC VPIN 프로덕션 로직, 진입: next_bar open
- 2-fold WF: F1=2024-07~2025-06 / F2=2025-07~2026-04
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
FEE = 0.0005

# daemon 고정 파라미터
VPIN_LOW = 0.35
VPIN_MOM = 0.0005
MAX_HOLD = 18
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8

# 비교 대상
TP_LIST = [0.055, 0.060, 0.065, 0.070, 0.075, 0.080]
SL = 0.008  # daemon 고정

# WF 기간
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020, 0.0025, 0.0030]

YEAR_RANGES = [
    ("2022", "2022-01-01", "2022-12-31"),
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026", "2026-01-01", "2026-04-05"),
]


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


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    tp: float,
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
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE - slippage)
                    i = j
                    break
                if ret <= -SL:
                    returns.append(-SL - FEE - slippage)
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE - slippage)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0, "cum_r": 0.0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    cum_r = float(cum[-1]) if len(cum) > 0 else 0.0
    mcl = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl, "cum_r": cum_r}


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth 사이클 152 — TP=7% daemon 배포 결정 ===")
    print(f"심볼: {SYMBOL}")
    print(f"고정: VPIN_LOW={VPIN_LOW} MOM={VPIN_MOM} HOLD={MAX_HOLD} "
          f"SL={SL*100}% EMA={EMA_PERIOD}")
    print(f"비교: TP = {[f'{t*100:.1f}%' for t in TP_LIST]}")
    print("=" * 80)

    # ── 전체 데이터 로드 ─────────────────────────────────────────────────────
    df_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_full.empty:
        print("데이터 없음.")
        return
    print(f"\n데이터: {len(df_full)}행 ({df_full.index[0]} ~ {df_full.index[-1]})")
    bh_full = buy_and_hold(df_full)
    print(f"ETH Buy-and-Hold: {bh_full * 100:+.1f}%")

    # ── 1. 전체기간 TP 비교 ──────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 1. 전체기간 TP 비교 (SL=0.8%, slippage=0.05%) ===")
    print(f"{'TP':>6} | {'Sharpe':>8} {'WR':>6} {'avg%':>7} {'MDD':>7} "
          f"{'MCL':>4} {'n':>5} {'cumR%':>8}")
    print("-" * 65)
    full_results = {}
    for tp in TP_LIST:
        r = backtest(df_full, tp)
        full_results[tp] = r
        print(f"{tp*100:>5.1f}% | {r['sharpe']:>+8.3f} {r['wr']:>5.1%} "
              f"{r['avg_ret']*100:>+6.2f}% {r['max_dd']*100:>+6.2f}% "
              f"{r['mcl']:>4} {r['trades']:>5} {r['cum_r']*100:>+7.1f}%")

    # ── 2. WF 2-fold 검증 ───────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 2. Walk-Forward 2-fold OOS 비교 ===")
    print(f"{'TP':>6} | {'F1 Sharpe':>10} {'F1 n':>5} | "
          f"{'F2 Sharpe':>10} {'F2 n':>5} | {'avg OOS':>9} {'status':>6}")
    print("-" * 72)

    wf_data = {}
    for tp in TP_LIST:
        fold_sharpes = []
        fold_ns = []
        fold_details = []
        for fold in WF_FOLDS:
            df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            if df_test.empty:
                fold_sharpes.append(0.0)
                fold_ns.append(0)
                fold_details.append({})
                continue
            r = backtest(df_test, tp)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            fold_sharpes.append(sh)
            fold_ns.append(r["trades"])
            fold_details.append(r)

        avg_oos = np.mean(fold_sharpes)
        both_pass = all(s >= 5.0 for s in fold_sharpes)
        status = "✅" if both_pass else "❌"
        wf_data[tp] = {
            "fold_sharpes": fold_sharpes, "fold_ns": fold_ns,
            "avg_oos": avg_oos, "both_pass": both_pass,
            "fold_details": fold_details,
        }
        print(f"{tp*100:>5.1f}% | {fold_sharpes[0]:>+10.3f} {fold_ns[0]:>5} | "
              f"{fold_sharpes[1]:>+10.3f} {fold_ns[1]:>5} | "
              f"{avg_oos:>+9.3f} {status:>6}")

    # ── 3. 슬리피지 스트레스 (TP=6% vs 7% 직접 비교) ──────────────────────
    print(f"\n{'=' * 80}")
    print("=== 3. 슬리피지 스트레스 (전체기간) ===")
    focus_tps = [0.060, 0.065, 0.070, 0.075]
    header = f"{'slip':>6}"
    for tp in focus_tps:
        header += f" | TP={tp*100:.1f}% Sh"
    print(header)
    print("-" * (8 + len(focus_tps) * 16))

    slip_data = {tp: {} for tp in focus_tps}
    for slip in SLIPPAGE_LEVELS:
        line = f"{slip*100:>5.2f}%"
        for tp in focus_tps:
            r = backtest(df_full, tp, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            slip_data[tp][slip] = sh
            line += f" |    {sh:>+8.3f}"
        print(line)

    # Sharpe 5.0 유지 한계 슬리피지
    print("\nSharpe ≥ 5.0 유지 최대 슬리피지:")
    for tp in focus_tps:
        max_slip = 0.0
        for slip in SLIPPAGE_LEVELS:
            if slip_data[tp].get(slip, 0.0) >= 5.0:
                max_slip = slip
        print(f"  TP={tp*100:.1f}%: {max_slip*100:.2f}%"
              f" (Sharpe={slip_data[tp].get(max_slip, 0.0):+.3f})")

    # ── 4. 연도별 분해 (TP=6% vs 7%) ────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 4. 연도별 분해 (TP=6% vs 7%) ===")
    print(f"{'연도':>6} | {'TP=6% Sh':>9} {'WR':>6} {'n':>4} {'MDD':>7} "
          f"| {'TP=7% Sh':>9} {'WR':>6} {'n':>4} {'MDD':>7} | {'Δ Sharpe':>9}")
    print("-" * 90)

    for year_label, y_start, y_end in YEAR_RANGES:
        df_year = load_historical(SYMBOL, "240m", y_start, y_end)
        if df_year.empty or len(df_year) < 50:
            print(f"{year_label:>6} | 데이터 부족")
            continue
        r6 = backtest(df_year, 0.06)
        r7 = backtest(df_year, 0.07)
        sh6 = r6["sharpe"] if not np.isnan(r6["sharpe"]) else 0.0
        sh7 = r7["sharpe"] if not np.isnan(r7["sharpe"]) else 0.0
        delta = sh7 - sh6
        print(f"{year_label:>6} | {sh6:>+9.3f} {r6['wr']:>5.1%} {r6['trades']:>4} "
              f"{r6['max_dd']*100:>+6.2f}% "
              f"| {sh7:>+9.3f} {r7['wr']:>5.1%} {r7['trades']:>4} "
              f"{r7['max_dd']*100:>+6.2f}% "
              f"| {delta:>+9.3f}")

    # ── 5. OOS 연도별 분해 (F1, F2 별도) ─────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 5. OOS 구간별 상세 (TP=6% vs 7%) ===")
    for fold_i, fold in enumerate(WF_FOLDS):
        df_test = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if df_test.empty:
            continue
        r6 = backtest(df_test, 0.06)
        r7 = backtest(df_test, 0.07)
        bh = buy_and_hold(df_test)
        print(f"\nFold {fold_i+1} [{fold['test'][0]}~{fold['test'][1]}]  "
              f"BH={bh*100:+.1f}%")
        for label, r in [("TP=6%", r6), ("TP=7%", r7)]:
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {label}: Sharpe={sh:+.3f} WR={r['wr']:.1%} "
                  f"n={r['trades']} avg={r['avg_ret']*100:+.2f}% "
                  f"MDD={r['max_dd']*100:+.2f}% MCL={r['mcl']} "
                  f"cumR={r['cum_r']*100:+.1f}%")

    # ── 6. 최종 결론 ─────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 6. 최종 결론 ===")

    # TP=6% vs 7% 핵심 지표
    r6_full = full_results[0.06]
    r7_full = full_results[0.07]
    wf6 = wf_data[0.06]
    wf7 = wf_data[0.07]

    print(f"\n{'지표':>20} | {'TP=6% (daemon)':>15} | {'TP=7% (후보)':>15} | {'Δ':>10}")
    print("-" * 70)
    metrics = [
        ("전체 Sharpe", f"{r6_full['sharpe']:+.3f}", f"{r7_full['sharpe']:+.3f}",
         f"{r7_full['sharpe']-r6_full['sharpe']:+.3f}"),
        ("WF avg OOS", f"{wf6['avg_oos']:+.3f}", f"{wf7['avg_oos']:+.3f}",
         f"{wf7['avg_oos']-wf6['avg_oos']:+.3f}"),
        ("WR", f"{r6_full['wr']:.1%}", f"{r7_full['wr']:.1%}", ""),
        ("avg ret", f"{r6_full['avg_ret']*100:+.2f}%",
         f"{r7_full['avg_ret']*100:+.2f}%", ""),
        ("MDD", f"{r6_full['max_dd']*100:+.2f}%",
         f"{r7_full['max_dd']*100:+.2f}%", ""),
        ("MCL", f"{r6_full['mcl']}", f"{r7_full['mcl']}", ""),
        ("trades", f"{r6_full['trades']}", f"{r7_full['trades']}", ""),
        ("cumR", f"{r6_full['cum_r']*100:+.1f}%",
         f"{r7_full['cum_r']*100:+.1f}%", ""),
    ]
    for label, v6, v7, delta in metrics:
        print(f"{label:>20} | {v6:>15} | {v7:>15} | {delta:>10}")

    # 배포 판단
    tp7_pass = wf7["both_pass"]
    tp7_slip_ok = all(slip_data[0.07].get(s, 0) >= 5.0
                      for s in [0.0005, 0.0010, 0.0015])
    tp7_better = wf7["avg_oos"] > wf6["avg_oos"]

    print(f"\n배포 체크리스트:")
    print(f"  [{'✅' if tp7_pass else '❌'}] WF 양 Fold Sharpe ≥ 5.0")
    print(f"  [{'✅' if tp7_slip_ok else '❌'}] 슬리피지 0.15%까지 Sharpe ≥ 5.0")
    print(f"  [{'✅' if tp7_better else '❌'}] avg OOS > daemon (TP=6%)")
    print(f"  [{'✅' if r7_full['trades'] >= 30 else '❌'}] n ≥ 30 "
          f"(OOS: F1={wf7['fold_ns'][0]}, F2={wf7['fold_ns'][1]})")

    all_pass = tp7_pass and tp7_slip_ok and tp7_better and r7_full["trades"] >= 30
    if all_pass:
        print(f"\n★★★ TP=7.0% 배포 승인 ★★★")
        print(f"  daemon.toml 변경: take_profit_pct = 0.06 → 0.07")
        print(f"  기대 개선: avg OOS Sharpe {wf6['avg_oos']:+.3f} → "
              f"{wf7['avg_oos']:+.3f} (Δ={wf7['avg_oos']-wf6['avg_oos']:+.3f})")
    else:
        print(f"\n★ TP=7.0% 배포 보류 — 위 체크리스트 미충족 항목 확인")

    # pipeline output
    best_tp = max(TP_LIST, key=lambda t: wf_data[t]["avg_oos"])
    best_wf = wf_data[best_tp]
    print(f"\nSharpe: {best_wf['avg_oos']:+.3f}")
    avg_wr = np.mean([fd.get("wr", 0) for fd in best_wf["fold_details"] if fd])
    print(f"WR: {avg_wr*100:.1f}%")
    total_n = sum(best_wf["fold_ns"])
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
