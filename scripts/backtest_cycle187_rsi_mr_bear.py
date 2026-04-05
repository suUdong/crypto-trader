"""
사이클 187: RSI Mean-Reversion BEAR 전용 전략
- 목적: BTC BEAR 레짐(BTC < SMA200)에서만 작동하는 역추세 전략 확보
  → BULL 전용 VPIN/BB_squeeze와 레짐 보완적 포트폴리오 구성
- 진입: RSI < rsi_entry (과매도) + BTC < SMA(200) (BEAR gate)
- 청산 (우선순위):
  1) RSI > rsi_exit (평균회귀 완료)
  2) Stop loss: entry × (1 - sl_pct)
  3) Max hold: max_hold bars
- 심볼: ETH/BTC (2종)
- 타임프레임: 60m, 240m (dual)
- 그리드: rsi_entry=[20,25,30] × rsi_exit=[40,45,50] × sl_pct=[2,3,5]%
         × max_hold=[12,24,48] = 81조합/TF
- 3-fold WF:
  F1: train=2022-01~2024-05 → OOS=2024-06~2025-03
  F2: train=2022-07~2024-11 → OOS=2024-12~2025-09
  F3: train=2023-01~2025-05 → OOS=2025-06~2026-04
- 🔄다음봉시가진입 | ★슬리피지포함
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOLS = ["KRW-ETH", "KRW-BTC"]
FEE = 0.0005
SLIPPAGE_BASE = 0.0005

BTC_SMA_PERIOD = 200

# Grid
RSI_ENTRY_LIST = [20, 25, 30]
RSI_EXIT_LIST = [40, 45, 50]
SL_PCT_LIST = [0.02, 0.03, 0.05]
MAX_HOLD_LIST = [12, 24, 48]
TIMEFRAMES = ["60m", "240m"]

WF_FOLDS = [
    {"train": ("2022-01-01", "2024-05-31"), "test": ("2024-06-01", "2025-03-31")},
    {"train": ("2022-07-01", "2024-11-30"), "test": ("2024-12-01", "2025-09-30")},
    {"train": ("2023-01-01", "2025-05-31"), "test": ("2025-06-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


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
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate(
        ([0.0], cumsum[:-period]))) / period
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
    slippage: float = 0.0005,
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

        # BEAR gate: BTC < SMA(200)
        if (np.isnan(btc_close_aligned[i]) or np.isnan(btc_sma_aligned[i])
                or btc_close_aligned[i] >= btc_sma_aligned[i]):
            i += 1
            continue

        # RSI oversold entry
        if rsi_val >= rsi_entry:
            i += 1
            continue

        # Enter at next bar open
        buy = o[i + 1] * (1 + FEE + slippage)
        sl_price = buy * (1 - sl_pct)

        exit_ret = None
        for j in range(i + 2, min(i + 1 + max_hold, n)):
            cur_rsi = rsi_arr[j] if j < len(rsi_arr) and not np.isnan(rsi_arr[j]) else 50.0

            # Stop loss first
            if c[j] <= sl_price:
                exit_ret = (sl_price / buy - 1) - FEE - slippage
                i = j
                break

            # RSI exit (mean reversion achieved)
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
                "trades": 0, "max_dd": 0.0, "mcl": 0}

    arr = np.array(returns)
    # Annualize based on timeframe (set externally)
    annual_factor = getattr(backtest, '_annual_factor', np.sqrt(365 * 6))
    sh = float(arr.mean() / (arr.std() + 1e-9) * annual_factor)
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

    # Buy & Hold
    bh_ret = (c[-1] - c[0]) / c[0] if c[0] > 0 else 0.0

    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl, "bh_ret": bh_ret}


def pool_results(results_list: list[dict]) -> dict:
    valid = [r for r in results_list if r["trades"] > 0
             and not np.isnan(r["sharpe"])]
    if not valid:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    return {
        "sharpe": float(np.mean([r["sharpe"] for r in valid])),
        "wr": float(np.mean([r["wr"] for r in valid])),
        "avg_ret": float(np.mean([r["avg_ret"] for r in valid])),
        "trades": sum(r["trades"] for r in valid),
        "max_dd": float(np.mean([r["max_dd"] for r in valid])),
        "mcl": max(r["mcl"] for r in valid),
    }


def main() -> None:
    print("=" * 80)
    print("=== 사이클 187: RSI Mean-Reversion BEAR 전용 전략 ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"BEAR gate: BTC < SMA({BTC_SMA_PERIOD})")
    print(f"진입: RSI < threshold | 청산: RSI > exit 또는 SL 또는 max_hold")
    print(f"타임프레임: {', '.join(TIMEFRAMES)}")
    print("=" * 80)

    # BTC data (use 240m for SMA200 regardless of symbol TF)
    df_btc_240 = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_240.empty:
        print("BTC 데이터 없음")
        return

    combos = list(product(RSI_ENTRY_LIST, RSI_EXIT_LIST, SL_PCT_LIST, MAX_HOLD_LIST))
    print(f"\n그리드: {len(combos)}조합 × {len(SYMBOLS)} 심볼 × {len(TIMEFRAMES)} TF")

    best_overall = None

    for tf in TIMEFRAMES:
        if tf == "60m":
            annual_factor = np.sqrt(365 * 24)
            backtest._annual_factor = annual_factor
        else:
            annual_factor = np.sqrt(365 * 6)
            backtest._annual_factor = annual_factor

        print(f"\n{'=' * 60}")
        print(f"=== 타임프레임: {tf} (annual_factor={annual_factor:.1f}) ===")
        print(f"{'=' * 60}")

        # BTC reference for gate (always 240m for SMA200 stability)
        df_btc_ref = df_btc_240

        # Load symbol data
        sym_data: dict[str, pd.DataFrame] = {}
        for sym in SYMBOLS:
            df = load_historical(sym, tf, "2022-01-01", "2026-04-05")
            if not df.empty and len(df) >= 500:
                sym_data[sym] = df
                print(f"  {sym}: {len(df)}행")
            else:
                print(f"  {sym}: 데이터 부족 ({len(df) if not df.empty else 0}행)")

        if not sym_data:
            print("  유효 심볼 없음, 건너뜀")
            continue

        # Phase 1: Train grid search (Fold 1 train)
        train_start, train_end = WF_FOLDS[0]["train"]
        print(f"\n  Phase 1: train 그리드 서치 ({train_start} ~ {train_end})")

        train_results: list[dict] = []
        for idx, (rsi_e, rsi_x, sl, mh) in enumerate(combos):
            if (idx + 1) % 20 == 0:
                print(f"    진행: {idx + 1}/{len(combos)}")
            sym_res = []
            for sym in sym_data:
                df_tr = sym_data[sym].loc[train_start:train_end]
                if df_tr.empty or len(df_tr) < 200:
                    continue
                btc_c, btc_s = align_btc(df_tr, df_btc_ref, BTC_SMA_PERIOD)
                r = backtest(df_tr, rsi_e, rsi_x, sl, mh, btc_c, btc_s)
                sym_res.append(r)
            pooled = pool_results(sym_res)
            train_results.append({
                "rsi_e": rsi_e, "rsi_x": rsi_x, "sl": sl, "mh": mh,
                **pooled,
            })

        valid = [r for r in train_results if r["trades"] >= 5
                 and not np.isnan(r["sharpe"]) and r["sharpe"] > 0]
        valid.sort(key=lambda x: x["sharpe"], reverse=True)

        if not valid:
            print("  ❌ 유효 train 결과 없음")
            continue

        top5 = valid[:5]
        print(f"\n  --- Train Top 5 ---")
        for rank, r in enumerate(top5, 1):
            print(f"    #{rank}: rsiE={r['rsi_e']} rsiX={r['rsi_x']} sl={r['sl']:.0%} "
                  f"mh={r['mh']} | Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1%} "
                  f"n={r['trades']} MDD={r['max_dd']:.2%}")

        # Phase 2: 3-fold WF on top 5
        print(f"\n  Phase 2: 3-fold Walk-Forward (Top 5)")

        wf_results: list[dict] = []
        for combo_r in top5:
            rsi_e, rsi_x, sl, mh = combo_r["rsi_e"], combo_r["rsi_x"], combo_r["sl"], combo_r["mh"]
            fold_results = []

            for fi, fold in enumerate(WF_FOLDS):
                test_start, test_end = fold["test"]
                sym_fold_res = []
                sym_details = []
                for sym in sym_data:
                    df_test = sym_data[sym].loc[test_start:test_end]
                    if df_test.empty or len(df_test) < 100:
                        continue
                    btc_c, btc_s = align_btc(df_test, df_btc_ref, BTC_SMA_PERIOD)
                    r = backtest(df_test, rsi_e, rsi_x, sl, mh, btc_c, btc_s)
                    sym_fold_res.append(r)
                    sym_details.append((sym, r))

                pooled = pool_results(sym_fold_res)
                fold_results.append(pooled)

                print(f"    rsiE={rsi_e} rsiX={rsi_x} sl={sl:.0%} mh={mh} "
                      f"Fold {fi + 1}: Sharpe={pooled['sharpe']:+.3f} "
                      f"WR={pooled['wr']:.1%} n={pooled['trades']} "
                      f"MDD={pooled['max_dd']:.2%}")
                for sym_name, sr in sym_details:
                    if sr['trades'] > 0:
                        print(f"      {sym_name}: Sharpe={sr['sharpe']:+.3f} "
                              f"WR={sr['wr']:.1%} n={sr['trades']}")

            # Average OOS
            valid_folds = [f for f in fold_results if not np.isnan(f["sharpe"])
                          and f["trades"] > 0]
            if valid_folds:
                avg_sharpe = np.mean([f["sharpe"] for f in valid_folds])
                avg_wr = np.mean([f["wr"] for f in valid_folds])
                total_n = sum(f["trades"] for f in valid_folds)
                avg_mdd = np.mean([f["max_dd"] for f in valid_folds])
                min_sharpe = min(f["sharpe"] for f in valid_folds)

                # PASS criteria: avg > 3 & min > 0 & n >= 30
                passed = avg_sharpe > 3.0 and min_sharpe > 0.0 and total_n >= 30
                status = "PASS" if passed else "FAIL"

                wf_results.append({
                    "rsi_e": rsi_e, "rsi_x": rsi_x, "sl": sl, "mh": mh,
                    "avg_sharpe": float(avg_sharpe), "avg_wr": float(avg_wr),
                    "total_n": total_n, "avg_mdd": float(avg_mdd),
                    "min_sharpe": float(min_sharpe), "status": status,
                    "tf": tf,
                })

                print(f"  → avg OOS: Sharpe={avg_sharpe:+.3f} WR={avg_wr:.1%} "
                      f"n={total_n} MDD={avg_mdd:.2%} min={min_sharpe:+.3f} "
                      f"[{status}]")

        # Best for this TF
        if wf_results:
            wf_results.sort(key=lambda x: x["avg_sharpe"], reverse=True)
            best_tf = wf_results[0]
            print(f"\n  ★ {tf} 최적: rsiE={best_tf['rsi_e']} rsiX={best_tf['rsi_x']} "
                  f"sl={best_tf['sl']:.0%} mh={best_tf['mh']} | "
                  f"avg OOS Sharpe={best_tf['avg_sharpe']:+.3f} [{best_tf['status']}]")

            if best_overall is None or best_tf["avg_sharpe"] > best_overall["avg_sharpe"]:
                best_overall = best_tf

    # Phase 3: Slippage stress on best
    if best_overall and best_overall["status"] == "PASS":
        print(f"\n{'=' * 60}")
        print(f"=== Phase 3: 슬리피지 스트레스 (최적 조합) ===")
        tf = best_overall["tf"]
        if tf == "60m":
            backtest._annual_factor = np.sqrt(365 * 24)
        else:
            backtest._annual_factor = np.sqrt(365 * 6)

        rsi_e = best_overall["rsi_e"]
        rsi_x = best_overall["rsi_x"]
        sl = best_overall["sl"]
        mh = best_overall["mh"]

        print(f"  {tf} rsiE={rsi_e} rsiX={rsi_x} sl={sl:.0%} mh={mh}")
        print(f"  {'slip':>6} | {'Sharpe':>8} | {'WR':>6} | {'n':>4} | {'MDD':>7}")
        print("  " + "-" * 42)

        for slip_val in SLIPPAGE_LEVELS:
            fold_results = []
            for fold in WF_FOLDS:
                test_start, test_end = fold["test"]
                sym_fold_res = []
                for sym_name, df_sym in [(s, load_historical(s, tf, "2022-01-01", "2026-04-05"))
                                         for s in SYMBOLS]:
                    if df_sym.empty:
                        continue
                    df_test = df_sym.loc[test_start:test_end]
                    if df_test.empty or len(df_test) < 100:
                        continue
                    btc_c, btc_s = align_btc(df_test, df_btc_240, BTC_SMA_PERIOD)
                    r = backtest(df_test, rsi_e, rsi_x, sl, mh, btc_c, btc_s,
                                 slippage=slip_val)
                    sym_fold_res.append(r)
                pooled = pool_results(sym_fold_res)
                fold_results.append(pooled)

            valid_folds = [f for f in fold_results if not np.isnan(f["sharpe"])
                          and f["trades"] > 0]
            if valid_folds:
                avg_sh = np.mean([f["sharpe"] for f in valid_folds])
                avg_wr = np.mean([f["wr"] for f in valid_folds])
                total_n = sum(f["trades"] for f in valid_folds)
                avg_mdd = np.mean([f["max_dd"] for f in valid_folds])
                print(f"  {slip_val:.2%} | {avg_sh:+8.3f} | {avg_wr:5.1%} | "
                      f"{total_n:>4} | {avg_mdd:>6.2%}")

    # Final summary
    print(f"\n{'=' * 80}")
    print(f"=== 최종 요약 ===")
    if best_overall:
        print(f"  ★ 전체 최적: {best_overall['tf']} "
              f"rsiE={best_overall['rsi_e']} rsiX={best_overall['rsi_x']} "
              f"sl={best_overall['sl']:.0%} mh={best_overall['mh']}")
        print(f"    avg OOS Sharpe: {best_overall['avg_sharpe']:+.3f} "
              f"[{best_overall['status']}]")
        print(f"    WR: {best_overall['avg_wr']:.1%} | n: {best_overall['total_n']} "
              f"| MDD: {best_overall['avg_mdd']:.2%}")
        print(f"\nSharpe: {best_overall['avg_sharpe']:+.3f}")
        print(f"WR: {best_overall['avg_wr']:.1%}")
        print(f"trades: {best_overall['total_n']}")
    else:
        print("  ❌ 유효한 PASS 전략 없음")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")


if __name__ == "__main__":
    main()
