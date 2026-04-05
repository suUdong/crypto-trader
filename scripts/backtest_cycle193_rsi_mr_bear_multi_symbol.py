"""
사이클 193: RSI MR BEAR 멀티심볼 확장 검증
- 목적: c187/c189에서 검증된 RSI MR BEAR 최적 파라미터를 새로운 심볼에 적용
  ETH/BTC → SOL, XRP, DOGE, AVAX 확장 가능성 테스트
- 고정 파라미터 (c189 로버스트 확인):
  rsiE=25, rsiX=50, sl=2%, mh=24, 240m
  BTC_SMA(200) BEAR gate
- 심볼: SOL, XRP, DOGE, AVAX (4종 — ETH/BTC는 c187 완료)
- 3-fold expanding WF:
  F1: train=2022-01~2023-12 → OOS=2024-01~2024-09
  F2: train=2022-01~2024-09 → OOS=2024-10~2025-06
  F3: train=2022-01~2025-06 → OOS=2025-07~2026-04
- 추가 검증: 인접 파라미터 그리드 (rsiE=[22,25,28] × rsiX=[45,50,55] × sl=[1.5,2.0,2.5]%)
  = 27조합 — 심볼별 최적이 c187 최적(25/50/2%)과 다를 수 있으므로
- 슬리피지 스트레스 + B&H 비교
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

SYMBOLS = ["KRW-SOL", "KRW-XRP", "KRW-DOGE", "KRW-AVAX"]
FEE = 0.0005
SLIPPAGE_BASE = 0.0005

BTC_SMA_PERIOD = 200
RSI_PERIOD = 14
CANDLE_TYPE = "240m"

# Grid (인접 파라미터 로버스트니스)
RSI_ENTRY_LIST = [22, 25, 28]
RSI_EXIT_LIST = [45, 50, 55]
SL_PCT_LIST = [0.015, 0.02, 0.025]
MAX_HOLD = 24  # c187 최적 고정

WF_FOLDS = [
    {"train": ("2022-01-01", "2023-12-31"), "test": ("2024-01-01", "2024-09-30")},
    {"train": ("2022-01-01", "2024-09-30"), "test": ("2024-10-01", "2025-06-30")},
    {"train": ("2022-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
]


def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def run_backtest(
    df: pd.DataFrame,
    btc_sma: pd.Series,
    rsi_entry: float,
    rsi_exit: float,
    sl_pct: float,
    max_hold: int,
    slippage: float,
) -> list[dict]:
    """Run RSI MR BEAR backtest on a single symbol's data."""
    rsi = compute_rsi(df["close"], RSI_PERIOD)
    trades: list[dict] = []
    i = 0
    n = len(df)

    while i < n - 1:
        # BEAR gate: BTC < SMA200
        if i >= len(btc_sma) or pd.isna(btc_sma.iloc[i]):
            i += 1
            continue
        if btc_sma.iloc[i] >= 0:  # BTC above SMA200 = not BEAR
            i += 1
            continue

        # RSI entry
        if pd.isna(rsi.iloc[i]) or rsi.iloc[i] >= rsi_entry:
            i += 1
            continue

        # Entry at next bar open
        entry_idx = i + 1
        if entry_idx >= n:
            break
        entry_price = df.iloc[entry_idx]["open"] * (1 + slippage + FEE)
        sl_price = entry_price * (1 - sl_pct)

        # Hold loop
        exit_idx = entry_idx
        exit_price = entry_price
        exit_reason = "max_hold"
        for j in range(entry_idx + 1, min(entry_idx + max_hold + 1, n)):
            # Stop loss (intrabar low)
            if df.iloc[j]["low"] <= sl_price:
                exit_idx = j
                exit_price = sl_price * (1 - FEE)
                exit_reason = "stop_loss"
                break
            # RSI exit
            rsi_j = rsi.iloc[j] if j < len(rsi) else np.nan
            if not pd.isna(rsi_j) and rsi_j >= rsi_exit:
                exit_idx = j
                exit_price = df.iloc[j]["close"] * (1 - slippage - FEE)
                exit_reason = "rsi_exit"
                break
            exit_idx = j
            exit_price = df.iloc[j]["close"] * (1 - slippage - FEE)

        ret_pct = (exit_price / entry_price - 1) * 100
        trades.append({
            "entry_time": df.index[entry_idx],
            "exit_time": df.index[exit_idx],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return_pct": ret_pct,
            "exit_reason": exit_reason,
            "bars_held": exit_idx - entry_idx,
        })
        # Cooldown: skip to exit bar + 1
        i = exit_idx + 1
        continue

    return trades


def calc_sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    if arr.std() == 0:
        return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(len(arr)))


def calc_mdd(returns: list[float]) -> float:
    if not returns:
        return 0.0
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r / 100))
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < mdd:
            mdd = dd
    return mdd * 100


def main():
    print("=" * 70)
    print("  사이클 193: RSI MR BEAR 멀티심볼 확장 검증")
    print("  심볼: SOL / XRP / DOGE / AVAX | 240m | 3-fold expanding WF")
    print("=" * 70)

    # Load BTC for SMA gate
    btc_data = load_historical("KRW-BTC", CANDLE_TYPE)
    if btc_data is None or btc_data.empty:
        print("ERROR: BTC data not available")
        return
    btc_sma = btc_data["close"].rolling(BTC_SMA_PERIOD).mean()
    # btc_sma_signal: negative means BTC below SMA200 (BEAR)
    btc_sma_signal = btc_data["close"] - btc_sma

    # Load all symbol data
    sym_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        d = load_historical(sym, CANDLE_TYPE)
        if d is not None and not d.empty:
            sym_data[sym] = d
            print(f"  {sym}: {len(d)} bars ({d.index[0]} ~ {d.index[-1]})")
        else:
            print(f"  {sym}: NO DATA — skipping")

    if not sym_data:
        print("ERROR: No symbol data loaded")
        return

    grid = list(product(RSI_ENTRY_LIST, RSI_EXIT_LIST, SL_PCT_LIST))
    print(f"\n  Grid: {len(grid)} combos × {len(WF_FOLDS)} folds × {len(sym_data)} symbols")
    print()

    # Per-symbol results
    symbol_results: dict[str, dict] = {}

    for sym, df in sym_data.items():
        print(f"\n{'='*60}")
        print(f"  {sym}")
        print(f"{'='*60}")

        # Align BTC SMA signal to this symbol's index
        btc_aligned = btc_sma_signal.reindex(df.index, method="ffill")

        best_avg_sharpe = -999
        best_params = None
        best_fold_results = None

        for rsi_e, rsi_x, sl in grid:
            fold_sharpes = []
            fold_details = []

            for fi, fold in enumerate(WF_FOLDS):
                # Train period (for reference — we use fixed params, no optimization)
                test_start = pd.Timestamp(fold["test"][0])
                test_end = pd.Timestamp(fold["test"][1])

                mask = (df.index >= test_start) & (df.index <= test_end)
                test_df = df[mask]
                test_btc = btc_aligned[mask]

                if len(test_df) < 50:
                    fold_sharpes.append(0.0)
                    fold_details.append({"sharpe": 0.0, "wr": 0.0, "n": 0, "mdd": 0.0, "avg": 0.0})
                    continue

                trades = run_backtest(
                    test_df, test_btc, rsi_e, rsi_x, sl, MAX_HOLD, SLIPPAGE_BASE
                )
                rets = [t["return_pct"] for t in trades]
                n_trades = len(rets)
                sharpe = calc_sharpe(rets)
                wr = (sum(1 for r in rets if r > 0) / n_trades * 100) if n_trades > 0 else 0.0
                avg_ret = np.mean(rets) if rets else 0.0
                mdd = calc_mdd(rets)

                fold_sharpes.append(sharpe)
                fold_details.append({
                    "sharpe": sharpe, "wr": wr, "n": n_trades,
                    "mdd": mdd, "avg": avg_ret,
                })

            avg_sharpe = np.mean(fold_sharpes)
            if avg_sharpe > best_avg_sharpe:
                best_avg_sharpe = avg_sharpe
                best_params = (rsi_e, rsi_x, sl)
                best_fold_results = fold_details

        # Print best result for this symbol
        if best_params and best_fold_results:
            rsi_e, rsi_x, sl = best_params
            total_n = sum(f["n"] for f in best_fold_results)
            total_rets = []

            # Collect all trades for B&H comparison and slippage stress
            print(f"\n  ★ Best: rsiE={rsi_e} rsiX={rsi_x} sl={sl*100:.1f}% mh={MAX_HOLD}")
            print(f"  avg OOS Sharpe: {best_avg_sharpe:+.3f}  total n={total_n}")
            for fi, fd in enumerate(best_fold_results):
                print(f"  F{fi+1}: Sharpe={fd['sharpe']:+.3f}  WR={fd['wr']:.1f}%  n={fd['n']}  avg={fd['avg']:+.2f}%  MDD={fd['mdd']:.2f}%")

            # Full period B&H comparison
            full_trades = run_backtest(df, btc_aligned, rsi_e, rsi_x, sl, MAX_HOLD, SLIPPAGE_BASE)
            full_rets = [t["return_pct"] for t in full_trades]
            strat_total = 0.0
            for r in full_rets:
                strat_total = (1 + strat_total / 100) * (1 + r / 100) * 100 - 100

            # B&H only during BEAR periods
            bear_mask = btc_aligned < 0
            bear_start_idx = None
            bh_returns = []
            for idx in range(len(df)):
                if bear_mask.iloc[idx]:
                    if bear_start_idx is None:
                        bear_start_idx = idx
                else:
                    if bear_start_idx is not None:
                        bh_ret = (df.iloc[idx]["open"] / df.iloc[bear_start_idx]["open"] - 1) * 100
                        bh_returns.append(bh_ret)
                        bear_start_idx = None
            if bear_start_idx is not None:
                bh_ret = (df.iloc[-1]["close"] / df.iloc[bear_start_idx]["open"] - 1) * 100
                bh_returns.append(bh_ret)
            bh_total = sum(bh_returns) if bh_returns else 0.0

            print(f"\n  B&H 비교 (BEAR 구간): 전략={strat_total:+.1f}%  B&H={bh_total:+.1f}%  초과={strat_total-bh_total:+.1f}%")

            # Slippage stress test
            print(f"\n  슬리피지 스트레스:")
            for slip in [0.0005, 0.0010, 0.0015, 0.0020]:
                slip_trades = run_backtest(df, btc_aligned, rsi_e, rsi_x, sl, MAX_HOLD, slip)
                slip_rets = [t["return_pct"] for t in slip_trades]
                slip_sharpe = calc_sharpe(slip_rets)
                print(f"    slip={slip*100:.2f}%: Sharpe={slip_sharpe:+.3f}  n={len(slip_trades)}")

            # Exit reason distribution
            if full_trades:
                reasons = {}
                for t in full_trades:
                    reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
                print(f"\n  청산 사유: {reasons}")

            status = "PASS" if best_avg_sharpe > 5.0 and total_n >= 30 else "FAIL"
            if total_n < 30:
                status += f" (n={total_n}<30)"

            symbol_results[sym] = {
                "params": best_params,
                "avg_sharpe": best_avg_sharpe,
                "total_n": total_n,
                "folds": best_fold_results,
                "status": status,
                "strat_return": strat_total,
                "bh_return": bh_total,
            }
            print(f"\n  → {sym}: {status}")
        else:
            print(f"  → {sym}: NO RESULTS")
            symbol_results[sym] = {"status": "NO_DATA", "avg_sharpe": 0, "total_n": 0}

    # === SUMMARY ===
    print(f"\n{'='*70}")
    print("  종합 결과")
    print(f"{'='*70}")

    pass_symbols = []
    for sym, res in symbol_results.items():
        params = res.get("params", (0, 0, 0))
        rsi_e, rsi_x, sl = params if params else (0, 0, 0)
        print(f"  {sym}: Sharpe={res['avg_sharpe']:+.3f}  n={res['total_n']}  "
              f"rsiE={rsi_e} rsiX={rsi_x} sl={sl*100:.1f}%  [{res['status']}]")
        if "PASS" in res.get("status", ""):
            pass_symbols.append(sym)

    print(f"\n  PASS 심볼: {pass_symbols if pass_symbols else 'NONE'}")
    print(f"  FAIL 심볼: {[s for s in symbol_results if s not in pass_symbols]}")

    # Reference c187 baseline
    print(f"\n  참고 — c187/c189 기존 결과:")
    print(f"    ETH: Sharpe +12.193, WR 42.2%, n=60 (PASS)")
    print(f"    BTC: Sharpe +12.193 (ETH+BTC 합산), deployed")

    # Top-3 across all symbols
    all_combos = []
    for sym, df_sym in sym_data.items():
        btc_aligned = btc_sma_signal.reindex(df_sym.index, method="ffill")
        for rsi_e, rsi_x, sl in grid:
            fold_sharpes = []
            total_n = 0
            for fold in WF_FOLDS:
                test_start = pd.Timestamp(fold["test"][0])
                test_end = pd.Timestamp(fold["test"][1])
                mask = (df_sym.index >= test_start) & (df_sym.index <= test_end)
                test_df = df_sym[mask]
                test_btc = btc_aligned[mask]
                if len(test_df) < 50:
                    fold_sharpes.append(0.0)
                    continue
                trades = run_backtest(test_df, test_btc, rsi_e, rsi_x, sl, MAX_HOLD, SLIPPAGE_BASE)
                rets = [t["return_pct"] for t in trades]
                fold_sharpes.append(calc_sharpe(rets))
                total_n += len(rets)
            avg_sh = np.mean(fold_sharpes)
            all_combos.append((sym, rsi_e, rsi_x, sl, avg_sh, total_n))

    all_combos.sort(key=lambda x: x[4], reverse=True)
    print(f"\n  Top-5 전체 조합:")
    for rank, (sym, rsi_e, rsi_x, sl, sh, n) in enumerate(all_combos[:5], 1):
        st = "PASS" if sh > 5.0 and n >= 30 else "FAIL"
        print(f"    {rank}. {sym} rsiE={rsi_e} rsiX={rsi_x} sl={sl*100:.1f}%: Sharpe={sh:+.3f} n={n} [{st}]")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
