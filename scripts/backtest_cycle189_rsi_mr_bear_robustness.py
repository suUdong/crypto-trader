"""
사이클 189: RSI MR BEAR 인접 파라미터 로버스트니스 검증
- 목적: c187 최적(rsiE=25, rsiX=50, sl=2%, mh=24) 인접 파라미터 Sharpe 편차 < 30% 확인
- 그리드: rsiE=[22,24,25,26,28] × rsiX=[45,48,50,52,55] × sl=[1.5,2.0,2.5]% × mh=[18,24,30]
         = 5×5×3×3 = 225조합
- 심볼: ETH/BTC (2종), 240m
- 3-fold WF (c187과 동일):
  F1: train=2022-01~2024-05 → OOS=2024-06~2025-03
  F2: train=2022-07~2024-11 → OOS=2024-12~2025-09
  F3: train=2023-01~2025-05 → OOS=2025-06~2026-04
- 로버스트니스 기준: PASS 비율(Sharpe>3 & n≥30) + 인접 Sharpe 편차
- 🔄다음봉시가진입 | ★슬리피지포함
- B&H 비교 포함
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOLS = ["KRW-ETH", "KRW-BTC"]
FEE = 0.0005
SLIPPAGE = 0.0005
BTC_SMA_PERIOD = 200
TF = "240m"
ANNUAL_FACTOR = np.sqrt(365 * 6)

# Fine grid around optimal rsiE=25, rsiX=50, sl=2%, mh=24
RSI_ENTRY_LIST = [22, 24, 25, 26, 28]
RSI_EXIT_LIST = [45, 48, 50, 52, 55]
SL_PCT_LIST = [0.015, 0.020, 0.025]
MAX_HOLD_LIST = [18, 24, 30]

WF_FOLDS = [
    {"train": ("2022-01-01", "2024-05-31"), "test": ("2024-06-01", "2025-03-31")},
    {"train": ("2022-07-01", "2024-11-30"), "test": ("2024-12-01", "2025-09-30")},
    {"train": ("2023-01-01", "2025-05-31"), "test": ("2025-06-01", "2026-04-05")},
]

OPTIMAL = {"rsi_e": 25, "rsi_x": 50, "sl": 0.02, "mh": 24}


def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    rsi_arr = np.full(n, np.nan)
    if n < period + 1:
        return rsi_arr
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    if avg_loss == 0:
        rsi_arr[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_arr[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_arr[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_arr[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return rsi_arr


def sma_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    cumsum = np.cumsum(series)
    result[period - 1:] = (
        cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))
    ) / period
    return result


def align_btc(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame, sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, sma_period)
    btc_c_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    return (
        btc_c_s.reindex(df_sym.index, method="ffill").values,
        btc_sma_s.reindex(df_sym.index, method="ffill").values,
    )


def backtest(
    df: pd.DataFrame,
    rsi_entry: float,
    rsi_exit: float,
    sl_pct: float,
    max_hold: int,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    slippage: float = SLIPPAGE,
) -> dict:
    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)
    n = len(c)
    rsi_arr = compute_rsi(c, 14)
    returns: list[float] = []
    warmup = max(BTC_SMA_PERIOD, 20) + 5
    i = warmup

    while i < n - 1:
        rsi_val = rsi_arr[i]
        if np.isnan(rsi_val):
            i += 1
            continue
        if (np.isnan(btc_close_aligned[i]) or np.isnan(btc_sma_aligned[i])
                or btc_close_aligned[i] >= btc_sma_aligned[i]):
            i += 1
            continue
        if rsi_val >= rsi_entry:
            i += 1
            continue

        buy = o[i + 1] * (1 + FEE + slippage)
        sl_price = buy * (1 - sl_pct)
        exit_ret = None

        for j in range(i + 2, min(i + 1 + max_hold, n)):
            if c[j] <= sl_price:
                exit_ret = (sl_price / buy - 1) - FEE - slippage
                i = j
                break
            cur_rsi = rsi_arr[j] if j < len(rsi_arr) and not np.isnan(rsi_arr[j]) else 50.0
            if cur_rsi > rsi_exit:
                exit_ret = (c[j] / buy - 1) - FEE - slippage
                i = j
                break

        if exit_ret is None:
            hold_end = min(i + max_hold, n - 1)
            exit_ret = (c[hold_end] / buy - 1) - FEE - slippage
            i = hold_end

        returns.append(exit_ret)
        i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0}

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * ANNUAL_FACTOR)
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0

    bh_ret = (c[-1] - c[0]) / c[0] if c[0] > 0 else 0.0
    strat_ret = float(arr.sum())

    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd,
            "bh_ret": bh_ret, "strat_ret": strat_ret}


def pool_results(results_list: list[dict]) -> dict:
    valid = [r for r in results_list if r["trades"] > 0
             and not np.isnan(r["sharpe"])]
    if not valid:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "bh_ret": 0.0, "strat_ret": 0.0}
    return {
        "sharpe": float(np.mean([r["sharpe"] for r in valid])),
        "wr": float(np.mean([r["wr"] for r in valid])),
        "avg_ret": float(np.mean([r["avg_ret"] for r in valid])),
        "trades": sum(r["trades"] for r in valid),
        "max_dd": float(np.mean([r["max_dd"] for r in valid])),
        "bh_ret": float(np.mean([r["bh_ret"] for r in valid])),
        "strat_ret": float(np.sum([r["strat_ret"] for r in valid])),
    }


def main() -> None:
    print("=" * 80)
    print("=== 사이클 189: RSI MR BEAR 인접 파라미터 로버스트니스 검증 ===")
    print(f"최적 기준: rsiE={OPTIMAL['rsi_e']} rsiX={OPTIMAL['rsi_x']} "
          f"sl={OPTIMAL['sl']:.1%} mh={OPTIMAL['mh']}")
    print(f"그리드: rsiE={RSI_ENTRY_LIST} × rsiX={RSI_EXIT_LIST} "
          f"× sl={SL_PCT_LIST} × mh={MAX_HOLD_LIST}")
    print("=" * 80)

    df_btc_240 = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_240.empty:
        print("BTC 데이터 없음")
        return

    sym_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = load_historical(sym, TF, "2022-01-01", "2026-04-05")
        if not df.empty and len(df) >= 500:
            sym_data[sym] = df
            print(f"  {sym}: {len(df)}행")

    combos = list(product(RSI_ENTRY_LIST, RSI_EXIT_LIST, SL_PCT_LIST, MAX_HOLD_LIST))
    print(f"\n총 조합: {len(combos)}")

    # Run 3-fold WF for all combos
    all_results: list[dict] = []
    for idx, (rsi_e, rsi_x, sl, mh) in enumerate(combos):
        if (idx + 1) % 50 == 0:
            print(f"  진행: {idx + 1}/{len(combos)}")

        fold_sharpes = []
        fold_pooled = []
        for fold in WF_FOLDS:
            test_start, test_end = fold["test"]
            sym_fold_res = []
            for sym in sym_data:
                df_test = sym_data[sym].loc[test_start:test_end]
                if df_test.empty or len(df_test) < 100:
                    continue
                btc_c, btc_s = align_btc(df_test, df_btc_240, BTC_SMA_PERIOD)
                r = backtest(df_test, rsi_e, rsi_x, sl, mh, btc_c, btc_s)
                sym_fold_res.append(r)
            pooled = pool_results(sym_fold_res)
            fold_pooled.append(pooled)
            if not np.isnan(pooled["sharpe"]):
                fold_sharpes.append(pooled["sharpe"])

        if len(fold_sharpes) == 3:
            avg_sh = float(np.mean(fold_sharpes))
            min_sh = float(np.min(fold_sharpes))
            total_n = sum(p["trades"] for p in fold_pooled)
            avg_wr = float(np.mean([p["wr"] for p in fold_pooled]))
            avg_mdd = float(np.mean([p["max_dd"] for p in fold_pooled]))
            avg_bh = float(np.mean([p["bh_ret"] for p in fold_pooled]))
            total_strat = float(np.sum([p["strat_ret"] for p in fold_pooled]))

            passed = avg_sh > 3.0 and min_sh > 0.0 and total_n >= 30
            all_results.append({
                "rsi_e": rsi_e, "rsi_x": rsi_x, "sl": sl, "mh": mh,
                "avg_sharpe": avg_sh, "min_sharpe": min_sh,
                "total_n": total_n, "avg_wr": avg_wr, "avg_mdd": avg_mdd,
                "avg_bh_ret": avg_bh, "total_strat_ret": total_strat,
                "passed": passed,
                "fold_sharpes": fold_sharpes,
            })

    print(f"\n유효 결과: {len(all_results)}개")

    # Robustness analysis
    passed = [r for r in all_results if r["passed"]]
    total = len(all_results)
    pass_count = len(passed)
    pass_pct = pass_count / total * 100 if total > 0 else 0

    print(f"\n{'=' * 60}")
    print(f"=== 로버스트니스 분석 ===")
    print(f"총 조합: {total} | PASS(Sharpe>3 & n≥30): {pass_count} ({pass_pct:.1f}%)")

    # Find optimal in results
    opt_result = None
    for r in all_results:
        if (r["rsi_e"] == OPTIMAL["rsi_e"] and r["rsi_x"] == OPTIMAL["rsi_x"]
                and r["sl"] == OPTIMAL["sl"] and r["mh"] == OPTIMAL["mh"]):
            opt_result = r
            break

    if opt_result:
        opt_sharpe = opt_result["avg_sharpe"]
        print(f"\n기준점 (최적): Sharpe={opt_sharpe:+.3f}")

        # Adjacent parameter deviation
        adjacent = [r for r in all_results if r["passed"]
                    and abs(r["rsi_e"] - OPTIMAL["rsi_e"]) <= 2
                    and abs(r["rsi_x"] - OPTIMAL["rsi_x"]) <= 5
                    and abs(r["sl"] - OPTIMAL["sl"]) <= 0.005
                    and abs(r["mh"] - OPTIMAL["mh"]) <= 6]

        if adjacent:
            adj_sharpes = [r["avg_sharpe"] for r in adjacent]
            adj_mean = np.mean(adj_sharpes)
            adj_std = np.std(adj_sharpes)
            deviation = adj_std / adj_mean * 100 if adj_mean > 0 else float("inf")
            min_adj = min(adj_sharpes)
            max_adj = max(adj_sharpes)

            print(f"\n인접 파라미터 (±2/±5/±0.5%/±6봉):")
            print(f"  조합 수: {len(adjacent)}")
            print(f"  Sharpe 범위: [{min_adj:+.3f}, {max_adj:+.3f}]")
            print(f"  Sharpe 평균: {adj_mean:+.3f} ± {adj_std:.3f}")
            print(f"  편차(CV): {deviation:.1f}%")
            print(f"  편차 < 30%: {'✅ ROBUST' if deviation < 30 else '❌ NOT ROBUST'}")
    else:
        print("  ⚠️ 최적 조합 결과 없음")

    # Top 10
    all_results.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n{'=' * 60}")
    print(f"=== Top 10 WF 결과 ===")
    print(f"{'rsiE':>4} {'rsiX':>4} {'sl':>5} {'mh':>3} | "
          f"{'avgSh':>7} {'minSh':>7} {'WR':>6} {'n':>4} {'MDD':>7} | "
          f"{'B&H':>7} {'Strat':>7} | {'status':>6}")
    print("-" * 85)
    for r in all_results[:10]:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{r['rsi_e']:>4} {r['rsi_x']:>4} {r['sl']:>5.1%} {r['mh']:>3} | "
              f"{r['avg_sharpe']:>+7.3f} {r['min_sharpe']:>+7.3f} "
              f"{r['avg_wr']:>5.1%} {r['total_n']:>4} {r['avg_mdd']:>6.2%} | "
              f"{r['avg_bh_ret']:>6.2%} {r['total_strat_ret']:>6.2%} | "
              f"{status:>6}")

    # B&H comparison for optimal
    if opt_result:
        print(f"\n{'=' * 60}")
        print(f"=== Buy & Hold 비교 (최적 조합) ===")
        print(f"  전략 총 수익: {opt_result['total_strat_ret']:+.2%}")
        print(f"  B&H 평균 수익: {opt_result['avg_bh_ret']:+.2%}")
        excess = opt_result["total_strat_ret"] - opt_result["avg_bh_ret"]
        print(f"  초과수익(전략-B&H): {excess:+.2%}")
        if opt_result["avg_bh_ret"] != 0:
            ratio = opt_result["total_strat_ret"] / opt_result["avg_bh_ret"]
            print(f"  배율: {ratio:.2f}x")

    # Sharpe > 5 count (daemon deployment threshold)
    sharpe5 = [r for r in all_results if r["avg_sharpe"] > 5.0 and r["total_n"] >= 30]
    print(f"\n{'=' * 60}")
    print(f"=== Daemon 배포 자격 (Sharpe>5 & n≥30) ===")
    print(f"  자격 조합: {len(sharpe5)}/{total} ({len(sharpe5)/total*100:.1f}%)")

    # Summary
    print(f"\n{'=' * 80}")
    print(f"=== 최종 요약 ===")
    print(f"  총 {total}조합 중 {pass_count}개 PASS ({pass_pct:.1f}%)")
    print(f"  Sharpe>5 자격: {len(sharpe5)}개 ({len(sharpe5)/total*100:.1f}%)")
    if opt_result:
        print(f"  최적 Sharpe: {opt_result['avg_sharpe']:+.3f}")
        print(f"  B&H 대비 초과수익: {opt_result['total_strat_ret'] - opt_result['avg_bh_ret']:+.2%}")

    # Machine-readable summary
    print(f"\nSharpe: {all_results[0]['avg_sharpe']:+.3f}" if all_results else "\nSharpe: nan")
    print(f"WR: {all_results[0]['avg_wr']:.1%}" if all_results else "WR: 0.0%")
    print(f"trades: {all_results[0]['total_n']}" if all_results else "trades: 0")
    print(f"ROBUST: {pass_pct:.1f}%")
    print(f"PASS_COUNT: {pass_count}/{total}")


if __name__ == "__main__":
    main()
