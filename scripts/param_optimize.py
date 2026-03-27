#!/usr/bin/env python3
"""Focused parameter optimization for ADX, momentum entry, kimchi cooldown, vbreak k_base."""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from scripts.grid_search import (  # noqa: E402
    STRATEGY_GRIDS,
    SYMBOLS,
    _param_key,
    fetch_candles,
    run_grid_for_strategy,
    top_param_sets,
)

# Override grids with finer-grained search ranges for target params

# 1) Momentum: ADX threshold + entry_threshold (fine grid)
STRATEGY_GRIDS["momentum"] = {
    "momentum_lookback": [12, 15],
    "momentum_entry_threshold": [0.001, 0.0015, 0.002, 0.003, 0.005],
    "rsi_period": [14],
    "rsi_overbought": [72.0],
    "max_holding_bars": [48],
    "adx_threshold": [15.0, 18.0, 20.0, 22.0, 25.0, 28.0],
}

# 2) Kimchi premium: cooldown + min_trade_interval + k params
STRATEGY_GRIDS["kimchi_premium"] = {
    "rsi_period": [14],
    "rsi_recovery_ceiling": [50.0],
    "rsi_overbought": [75.0],
    "max_holding_bars": [24],
    "min_trade_interval_bars": [12, 18, 24],
    "min_confidence": [0.3, 0.4, 0.5],
    "cooldown_hours": [4.0, 6.0, 8.0, 12.0, 16.0, 24.0],
}

# 3) Volatility breakout: k_base fine tuning
STRATEGY_GRIDS["volatility_breakout"] = {
    "k_base": [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
    "noise_lookback": [12, 15],
    "ma_filter_period": [8, 10],
    "max_holding_bars": [36],
}


def main() -> None:
    days = 90

    print(f"\n{'=' * 80}")
    print(f"  FOCUSED PARAM OPTIMIZATION - {days}-day data")
    print("  Targets: ADX threshold, momentum entry, kimchi cooldown, vbreak k_base")
    print(f"{'=' * 80}")

    candles_by_symbol = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    for strategy_type in ["momentum", "kimchi_premium", "volatility_breakout"]:
        results = run_grid_for_strategy(strategy_type, candles_by_symbol)
        if not results:
            continue

        top_candidates = top_param_sets(results, top_n=5)
        best = top_candidates[0] if top_candidates else None

        print(f"\n  === {strategy_type.upper()} ===")
        if best:
            print("  Best params:")
            for k, v in sorted(best.params.items()):
                print(f"    {k}: {v}")
            print(
                f"  Score: {best.score:.4f} | Sharpe: {best.avg_sharpe:.2f} | "
                f"Return: {best.avg_return_pct:+.2f}% | MDD: {best.avg_max_drawdown:.2f}% | "
                f"Trades: {best.total_trades}"
            )

        print("\n  Top 5 candidates:")
        for idx, c in enumerate(top_candidates, 1):
            print(
                f"    #{idx} score={c.score:.4f} sharpe={c.avg_sharpe:.2f} "
                f"ret={c.avg_return_pct:+.2f}% mdd={c.avg_max_drawdown:.2f}% "
                f"wr={c.avg_win_rate:.1f}% trades={c.total_trades}"
            )
            print(f"       {c.params}")

        # Per-symbol breakdown for best
        if best:
            best_key = _param_key(best.params)
            print("\n  Per-symbol (best params):")
            print(
                f"  {'Symbol':<12} {'Return%':>9} {'WR%':>6} {'PF':>7} "
                f"{'MDD%':>7} {'Sharpe':>8} {'Trades':>7}"
            )
            print(f"  {'-' * 60}")
            for r in results:
                if _param_key(r.params) == best_key:
                    pf = f"{r.profit_factor:.2f}" if r.profit_factor < 1000 else "inf"
                    print(
                        f"  {r.symbol:<12} {r.return_pct:>+8.2f}% {r.win_rate:>5.1f}% "
                        f"{pf:>7} {r.max_drawdown:>6.2f}% "
                        f"{r.sharpe_approx:>7.2f} {r.trade_count:>7}"
                    )

    print(f"\n{'=' * 80}")
    print("  Optimization complete.")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
