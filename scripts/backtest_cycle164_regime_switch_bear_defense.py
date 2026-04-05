"""
사이클 164: BEAR/횡보장 방어 — BTC Regime-Switch 전략
평가자 최우선 블로커: 현 6전략 모두 하락장 무력화, BEAR 방어 전략 부재

전략 개요:
  - BTC가 SMA(daily) 아래로 하락 시 → 알트 매도 (현금 대기)
  - BTC가 SMA(daily) 위로 복귀 시 → 알트 재매수
  - 포트폴리오 레짐 오버레이 (개별 트레이드 시그널 아닌 자산 배분 전환)

그리드:
  - SMA period: [100, 150, 200]
  - Confirmation bars (연속 N일 확인 후 전환): [0, 1, 3, 5]
  - 대상 심볼: ETH, SOL, XRP, AVAX, 4종 basket
  - 슬리피지+수수료: 0.20% round-trip (전환 시마다)

WF 3-fold:
  - F1: train 2022-01~2023-12, OOS 2024-01-01~2024-12-31
  - F2: train 2022-01~2024-12, OOS 2025-01-01~2025-12-31
  - F3: train 2022-01~2025-12, OOS 2026-01-01~2026-04-05

비교 기준: 단순 보유(buy-and-hold) 대비 MDD 개선, Sharpe 개선
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical

# ── Config ──────────────────────────────────────────────
BTC = "KRW-BTC"
ALTS = ["KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-AVAX"]
START = "2022-01-01"
END = "2026-04-05"

# Grid parameters
SMA_PERIODS = [100, 150, 200]
CONFIRM_BARS = [0, 1, 3, 5]

# Costs per switch (buy or sell)
SWITCH_COST = 0.002  # 0.20% round-trip (slippage + fee)

# Walk-forward folds
FOLDS = [
    {"name": "F1", "train": ("2022-01-01", "2023-12-31"), "oos": ("2024-01-01", "2024-12-31")},
    {"name": "F2", "train": ("2022-01-01", "2024-12-31"), "oos": ("2025-01-01", "2025-12-31")},
    {"name": "F3", "train": ("2022-01-01", "2025-12-31"), "oos": ("2026-01-01", "2026-04-05")},
]

# Pass criteria
MIN_SWITCHES = 4       # 최소 전환 횟수 (OOS에서)
SHARPE_IMPROVEMENT = 0  # BH 대비 Sharpe 개선 > 0


def load_data():
    """Load BTC daily + alt daily data."""
    btc_day = load_historical(BTC, "day", START, END)
    alt_data = {}
    for sym in ALTS:
        try:
            df = load_historical(sym, "day", START, END)
            if len(df) > 100:
                alt_data[sym] = df
        except Exception as e:
            print(f"  [skip] {sym}: {e}")
    return btc_day, alt_data


def compute_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def regime_signal(btc_close: pd.Series, sma_period: int, confirm: int) -> pd.Series:
    """
    Returns daily regime series: True = BULL (hold alts), False = BEAR (cash).
    Uses confirmation: regime changes only after `confirm` consecutive bars.
    """
    sma = compute_sma(btc_close, sma_period)
    raw_bull = btc_close > sma  # True when above SMA

    if confirm == 0:
        return raw_bull

    # Apply confirmation filter
    regime = pd.Series(np.nan, index=btc_close.index, dtype=float)
    current_regime = None
    counter = 0

    for i, (idx, is_bull) in enumerate(raw_bull.items()):
        if pd.isna(is_bull):
            regime.iloc[i] = np.nan
            continue

        target = bool(is_bull)
        if current_regime is None:
            current_regime = target
            counter = 0
            regime.iloc[i] = float(current_regime)
            continue

        if target != current_regime:
            counter += 1
            if counter >= confirm:
                current_regime = target
                counter = 0
        else:
            counter = 0

        regime.iloc[i] = float(current_regime)

    return regime.astype(bool)


def backtest_regime_switch(
    alt_close: pd.Series,
    regime: pd.Series,
    start_date: str,
    end_date: str,
    switch_cost: float = SWITCH_COST,
):
    """
    Backtest regime-switch overlay on a single alt.

    When regime=True (BULL): hold alt
    When regime=False (BEAR): hold cash (0% return)

    Entry: next day's open after signal (simulated as next close for daily)
    """
    mask = (alt_close.index >= pd.Timestamp(start_date)) & \
           (alt_close.index <= pd.Timestamp(end_date))
    alt_period = alt_close[mask]
    regime_period = regime.reindex(alt_period.index).ffill()

    if len(alt_period) < 10:
        return None

    # Daily returns of alt
    alt_returns = alt_period.pct_change()

    # Regime-switch equity curve
    # Signal is lagged by 1 day (next-bar entry rule)
    position = regime_period.shift(1).fillna(False)  # 1-day lag

    # Count switches
    switches = (position != position.shift(1)).sum()

    # Strategy returns: alt return when in position, 0 when in cash
    # Apply switch cost on each transition
    transition = position != position.shift(1)
    strategy_returns = alt_returns.copy()
    strategy_returns[~position] = 0.0
    strategy_returns[transition] = strategy_returns[transition] - switch_cost

    # Equity curves
    equity_strategy = (1 + strategy_returns).cumprod()
    equity_bh = (1 + alt_returns).cumprod()

    # Metrics
    total_days = len(alt_period)
    days_in_market = position.sum()
    pct_in_market = days_in_market / total_days * 100 if total_days > 0 else 0

    # Sharpe (annualized, daily)
    sr_mean = strategy_returns.mean()
    sr_std = strategy_returns.std()
    sharpe_strategy = (sr_mean / sr_std * np.sqrt(365)) if sr_std > 0 else 0.0

    bh_mean = alt_returns.mean()
    bh_std = alt_returns.std()
    sharpe_bh = (bh_mean / bh_std * np.sqrt(365)) if bh_std > 0 else 0.0

    # MDD
    def max_drawdown(equity):
        peak = equity.expanding().max()
        dd = (equity - peak) / peak
        return dd.min()

    mdd_strategy = max_drawdown(equity_strategy)
    mdd_bh = max_drawdown(equity_bh)

    # Total return
    ret_strategy = equity_strategy.iloc[-1] / equity_strategy.iloc[0] - 1 if len(equity_strategy) > 0 else 0
    ret_bh = equity_bh.iloc[-1] / equity_bh.iloc[0] - 1 if len(equity_bh) > 0 else 0

    return {
        "total_return": ret_strategy,
        "bh_return": ret_bh,
        "sharpe": sharpe_strategy,
        "sharpe_bh": sharpe_bh,
        "mdd": mdd_strategy,
        "mdd_bh": mdd_bh,
        "switches": int(switches),
        "days_in_market_pct": pct_in_market,
        "total_days": total_days,
    }


def run_grid_search(btc_close, alt_close, start_date, end_date):
    """Run grid search on training period, return best params."""
    best_sharpe = -999
    best_params = None
    results = []

    for sma_p, conf in product(SMA_PERIODS, CONFIRM_BARS):
        regime = regime_signal(btc_close, sma_p, conf)
        res = backtest_regime_switch(alt_close, regime, start_date, end_date)
        if res is None:
            continue

        # Optimization target: Sharpe improvement over BH
        sharpe_diff = res["sharpe"] - res["sharpe_bh"]
        results.append({
            "sma": sma_p, "confirm": conf,
            "sharpe": res["sharpe"], "sharpe_bh": res["sharpe_bh"],
            "sharpe_diff": sharpe_diff,
            "mdd": res["mdd"], "mdd_bh": res["mdd_bh"],
            "mdd_improvement": res["mdd"] - res["mdd_bh"],  # less negative = better
            "return": res["total_return"], "bh_return": res["bh_return"],
            "switches": res["switches"],
            "in_market_pct": res["days_in_market_pct"],
        })

        # Rank by composite: Sharpe improvement + MDD improvement (normalized)
        composite = sharpe_diff + (res["mdd"] - res["mdd_bh"]) * 10  # MDD improvement weighted
        if composite > best_sharpe:
            best_sharpe = composite
            best_params = (sma_p, conf)

    return best_params, results


def main():
    t0 = time.time()
    print("=" * 80)
    print("=== Cycle 164: BEAR Regime-Switch Strategy ===")
    print("=== BTC SMA regime overlay — alt hold/cash switching ===")
    print("=" * 80)

    print("\n[1] Loading data...")
    btc_day, alt_data = load_data()
    btc_close = btc_day["close"]
    print(f"  BTC daily: {len(btc_day)} bars ({btc_day.index[0]} ~ {btc_day.index[-1]})")
    for sym, df in alt_data.items():
        print(f"  {sym}: {len(df)} bars")

    # ── Phase 1: Full-period analysis (all params, all alts) ──
    print("\n" + "=" * 80)
    print("[2] Full-period grid analysis (2022-01-01 ~ 2026-04-05)")
    print("=" * 80)

    for sym in alt_data:
        print(f"\n--- {sym} ---")
        print(f"  {'SMA':>5} {'Conf':>5} | {'Sharpe':>8} {'BH_Sh':>8} {'Δ':>8} | "
              f"{'MDD':>8} {'BH_MDD':>8} {'ΔMDD':>8} | {'Ret%':>8} {'BH%':>8} | {'Sw':>4} {'InMkt%':>7}")

        for sma_p, conf in product(SMA_PERIODS, CONFIRM_BARS):
            regime = regime_signal(btc_close, sma_p, conf)
            res = backtest_regime_switch(alt_data[sym]["close"], regime, START, END)
            if res is None:
                continue
            print(f"  {sma_p:>5} {conf:>5} | "
                  f"{res['sharpe']:>+8.3f} {res['sharpe_bh']:>+8.3f} {res['sharpe'] - res['sharpe_bh']:>+8.3f} | "
                  f"{res['mdd']*100:>+8.2f}% {res['mdd_bh']*100:>+8.2f}% {(res['mdd'] - res['mdd_bh'])*100:>+8.2f}% | "
                  f"{res['total_return']*100:>+8.2f}% {res['bh_return']*100:>+8.2f}% | "
                  f"{res['switches']:>4} {res['days_in_market_pct']:>6.1f}%")

    # ── Phase 2: 3-fold Walk-Forward ──
    print("\n" + "=" * 80)
    print("[3] 3-Fold Walk-Forward Validation")
    print("=" * 80)

    wf_results = {}
    for sym in alt_data:
        alt_close = alt_data[sym]["close"]
        print(f"\n{'='*60}")
        print(f"=== {sym} ===")
        print(f"{'='*60}")

        fold_results = []
        all_pass = True

        for fold in FOLDS:
            fname = fold["name"]
            train_start, train_end = fold["train"]
            oos_start, oos_end = fold["oos"]

            # Train: find best params
            best_params, train_results = run_grid_search(
                btc_close, alt_close, train_start, train_end
            )

            if best_params is None:
                print(f"  {fname}: No valid params in training")
                all_pass = False
                fold_results.append(None)
                continue

            sma_p, conf = best_params
            print(f"\n  {fname} Train best: SMA={sma_p} Confirm={conf}")

            # Show top-3 training results
            train_results.sort(key=lambda x: x["sharpe_diff"], reverse=True)
            for i, tr in enumerate(train_results[:3]):
                print(f"    T#{i+1}: SMA={tr['sma']} C={tr['confirm']} "
                      f"Sharpe={tr['sharpe']:+.3f} BH={tr['sharpe_bh']:+.3f} "
                      f"Δ={tr['sharpe_diff']:+.3f} MDD={tr['mdd']*100:+.1f}%")

            # OOS: apply best params
            regime = regime_signal(btc_close, sma_p, conf)
            oos_res = backtest_regime_switch(alt_close, regime, oos_start, oos_end)

            if oos_res is None:
                print(f"  {fname} OOS: No data")
                all_pass = False
                fold_results.append(None)
                continue

            sharpe_diff = oos_res["sharpe"] - oos_res["sharpe_bh"]
            mdd_diff = (oos_res["mdd"] - oos_res["mdd_bh"]) * 100

            # Pass criteria: Sharpe improvement OR significant MDD improvement
            fold_pass = (sharpe_diff > SHARPE_IMPROVEMENT) or (mdd_diff > 10)  # 10pp MDD improvement
            status = "PASS" if fold_pass else "FAIL"
            if not fold_pass:
                all_pass = False

            print(f"  {fname} OOS ({oos_start}~{oos_end}): [{status}]")
            print(f"    Strategy: Sharpe={oos_res['sharpe']:+.3f} MDD={oos_res['mdd']*100:+.2f}% Ret={oos_res['total_return']*100:+.2f}%")
            print(f"    BuyHold:  Sharpe={oos_res['sharpe_bh']:+.3f} MDD={oos_res['mdd_bh']*100:+.2f}% Ret={oos_res['bh_return']*100:+.2f}%")
            print(f"    Δ Sharpe={sharpe_diff:+.3f} Δ MDD={mdd_diff:+.2f}pp Switches={oos_res['switches']} InMarket={oos_res['days_in_market_pct']:.1f}%")

            fold_results.append({
                "fold": fname,
                "params": {"sma": sma_p, "confirm": conf},
                "oos": oos_res,
                "sharpe_diff": sharpe_diff,
                "mdd_diff_pp": mdd_diff,
                "pass": fold_pass,
            })

        wf_results[sym] = {"folds": fold_results, "all_pass": all_pass}

    # ── Phase 3: Basket (equal-weight 4 alts) ──
    print("\n" + "=" * 80)
    print("[4] Equal-Weight Basket (4 alts)")
    print("=" * 80)

    # Create equal-weight basket returns
    all_alt_returns = {}
    common_idx = None
    for sym in alt_data:
        r = alt_data[sym]["close"].pct_change()
        all_alt_returns[sym] = r
        if common_idx is None:
            common_idx = r.index
        else:
            common_idx = common_idx.intersection(r.index)

    basket_returns = pd.DataFrame({s: all_alt_returns[s] for s in alt_data}).reindex(common_idx).mean(axis=1)
    basket_close = (1 + basket_returns).cumprod()

    print("\n--- Equal-weight basket ---")
    for fold in FOLDS:
        fname = fold["name"]
        train_start, train_end = fold["train"]
        oos_start, oos_end = fold["oos"]

        # Train on basket
        best_params_basket = None
        best_composite = -999

        for sma_p, conf in product(SMA_PERIODS, CONFIRM_BARS):
            regime = regime_signal(btc_close, sma_p, conf)
            res = backtest_regime_switch(basket_close, regime, train_start, train_end)
            if res is None:
                continue
            sharpe_diff = res["sharpe"] - res["sharpe_bh"]
            mdd_imp = (res["mdd"] - res["mdd_bh"]) * 10
            composite = sharpe_diff + mdd_imp
            if composite > best_composite:
                best_composite = composite
                best_params_basket = (sma_p, conf)

        if best_params_basket is None:
            print(f"  {fname}: No valid params")
            continue

        sma_p, conf = best_params_basket
        regime = regime_signal(btc_close, sma_p, conf)
        oos_res = backtest_regime_switch(basket_close, regime, oos_start, oos_end)
        if oos_res is None:
            print(f"  {fname}: No OOS data")
            continue

        sharpe_diff = oos_res["sharpe"] - oos_res["sharpe_bh"]
        mdd_diff = (oos_res["mdd"] - oos_res["mdd_bh"]) * 100

        print(f"\n  {fname} (SMA={sma_p} C={conf}):")
        print(f"    Strategy: Sharpe={oos_res['sharpe']:+.3f} MDD={oos_res['mdd']*100:+.2f}% Ret={oos_res['total_return']*100:+.2f}%")
        print(f"    BuyHold:  Sharpe={oos_res['sharpe_bh']:+.3f} MDD={oos_res['mdd_bh']*100:+.2f}% Ret={oos_res['bh_return']*100:+.2f}%")
        print(f"    Δ Sharpe={sharpe_diff:+.3f} Δ MDD={mdd_diff:+.2f}pp Switches={oos_res['switches']} InMarket={oos_res['days_in_market_pct']:.1f}%")

    # ── Phase 4: BEAR-period specific analysis ──
    print("\n" + "=" * 80)
    print("[5] BEAR Period Zoom-in")
    print("=" * 80)

    bear_periods = [
        ("2022 BEAR", "2022-01-01", "2022-12-31"),
        ("2025-Q4 BEAR", "2025-07-01", "2025-12-31"),
    ]

    for period_name, bp_start, bp_end in bear_periods:
        print(f"\n--- {period_name} ({bp_start} ~ {bp_end}) ---")
        for sym in alt_data:
            for sma_p in SMA_PERIODS:
                for conf in [0, 3]:  # Just key configs
                    regime = regime_signal(btc_close, sma_p, conf)
                    res = backtest_regime_switch(alt_data[sym]["close"], regime, bp_start, bp_end)
                    if res is None:
                        continue
                    avoided_loss = res["total_return"] - res["bh_return"]
                    print(f"  {sym:12s} SMA={sma_p} C={conf}: "
                          f"Strat={res['total_return']*100:+7.2f}% BH={res['bh_return']*100:+7.2f}% "
                          f"Avoided={avoided_loss*100:+7.2f}% MDD={res['mdd']*100:+7.2f}% vs {res['mdd_bh']*100:+7.2f}%")

    # ── Summary ──
    print("\n" + "=" * 80)
    print("[6] FINAL SUMMARY")
    print("=" * 80)

    any_pass = False
    for sym, wr in wf_results.items():
        status = "✅ ALL PASS" if wr["all_pass"] else "❌ FAIL"
        if wr["all_pass"]:
            any_pass = True
        print(f"\n  {sym}: {status}")
        for fr in wr["folds"]:
            if fr is None:
                print("    (no data)")
                continue
            p = fr["params"]
            o = fr["oos"]
            print(f"    {fr['fold']}: SMA={p['sma']} C={p['confirm']} "
                  f"Sharpe={o['sharpe']:+.3f}(BH:{o['sharpe_bh']:+.3f}) "
                  f"MDD={o['mdd']*100:+.1f}%(BH:{o['mdd_bh']*100:+.1f}%) "
                  f"Ret={o['total_return']*100:+.1f}%(BH:{o['bh_return']*100:+.1f}%) "
                  f"[{'PASS' if fr['pass'] else 'FAIL'}]")

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")
    print(f"  Conclusion: {'DEPLOYABLE' if any_pass else 'NOT DEPLOYABLE'}")


if __name__ == "__main__":
    main()
