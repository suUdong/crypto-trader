#!/usr/bin/env python3
"""Auto-tune: run grid search on synthetic/cached data and write optimal params to TOML.

Usage:
    PYTHONPATH=src .venv/bin/python3 scripts/auto_tune.py [days] [output_toml]

Combines strategy param grid search + risk param grid search, then writes
the best parameters to a TOML config file ready for production use.
"""
from __future__ import annotations

import itertools
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, "src")

from crypto_trader.backtest.engine import BacktestEngine  # noqa: E402
from crypto_trader.config import (  # noqa: E402
    BacktestConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
)
from crypto_trader.models import Candle  # noqa: E402
from crypto_trader.risk.manager import RiskManager  # noqa: E402
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy  # noqa: E402
from crypto_trader.wallet import create_strategy  # noqa: E402


@dataclass
class TuneResult:
    strategy: str
    params: dict[str, float | int]
    risk_params: dict[str, float]
    avg_return_pct: float
    avg_sharpe: float
    avg_mdd_pct: float
    avg_win_rate: float
    avg_profit_factor: float
    total_trades: int


# Risk parameter grid
RISK_GRID = {
    "stop_loss_pct": [0.02, 0.03, 0.04],
    "take_profit_pct": [0.04, 0.06, 0.08, 0.10],
    "risk_per_trade_pct": [0.005, 0.01, 0.015],
}


def _approx_sharpe(equity_curve: list[float]) -> float:
    if len(equity_curve) < 3:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / max(1.0, equity_curve[i - 1])
        for i in range(1, len(equity_curve))
    ]
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = variance**0.5
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * (8760**0.5)


def _run_single_backtest(
    strategy_type: str,
    strategy_params: dict[str, float | int],
    risk_params: dict[str, float],
    candles: list[Candle],
    symbol: str,
) -> dict[str, float]:
    """Run one backtest with given strategy + risk params."""
    config_fields = set(StrategyConfig.__dataclass_fields__)
    config_kwargs = {k: v for k, v in strategy_params.items() if k in config_fields}
    strategy_config = StrategyConfig(**config_kwargs)
    regime_config = RegimeConfig()

    if strategy_type == "volatility_breakout":
        strategy = VolatilityBreakoutStrategy(
            strategy_config,
            k_base=float(strategy_params.get("k_base", 0.5)),
            noise_lookback=int(strategy_params.get("noise_lookback", 20)),
            ma_filter_period=int(strategy_params.get("ma_filter_period", 20)),
        )
    else:
        strategy = create_strategy(strategy_type, strategy_config, regime_config)

    # Ensure take_profit > stop_loss
    sl = risk_params.get("stop_loss_pct", 0.03)
    tp = risk_params.get("take_profit_pct", 0.06)
    if tp <= sl:
        tp = sl + 0.01

    risk_config = RiskConfig(
        risk_per_trade_pct=risk_params.get("risk_per_trade_pct", 0.01),
        stop_loss_pct=sl,
        take_profit_pct=tp,
    )
    risk_manager = RiskManager(risk_config)
    engine = BacktestEngine(
        strategy=strategy,
        risk_manager=risk_manager,
        config=BacktestConfig(initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005),
        symbol=symbol,
    )
    result = engine.run(candles)
    sharpe = _approx_sharpe(result.equity_curve)
    return {
        "return_pct": result.total_return_pct * 100,
        "sharpe": sharpe,
        "mdd_pct": result.max_drawdown * 100,
        "win_rate": result.win_rate * 100,
        "profit_factor": result.profit_factor,
        "trade_count": len(result.trade_log),
    }


def optimize_risk_for_strategy(
    strategy_type: str,
    strategy_params: dict[str, float | int],
    candles_by_symbol: dict[str, list[Candle]],
) -> tuple[dict[str, float], float]:
    """Find best risk params for a given strategy + strategy params combo."""
    risk_param_names = list(RISK_GRID.keys())
    risk_combos = list(itertools.product(*RISK_GRID.values()))

    best_score = float("-inf")
    best_risk: dict[str, float] = {}

    for combo in risk_combos:
        risk_params = dict(zip(risk_param_names, combo))
        # Skip invalid: take_profit must exceed stop_loss
        if risk_params["take_profit_pct"] <= risk_params["stop_loss_pct"]:
            continue

        scores = []
        for symbol, candles in candles_by_symbol.items():
            r = _run_single_backtest(strategy_type, strategy_params, risk_params, candles, symbol)
            score = r["sharpe"] * (1.0 - r["mdd_pct"] / 100.0)
            scores.append(score)

        avg_score = sum(scores) / len(scores) if scores else 0.0
        if avg_score > best_score:
            best_score = avg_score
            best_risk = risk_params

    return best_risk, best_score


def write_optimized_toml(
    results: list[TuneResult],
    output_path: str,
    base_toml: str | None = None,
) -> None:
    """Write optimized parameters to a TOML config file."""
    base: dict = {}
    if base_toml and Path(base_toml).exists():
        base = tomllib.loads(Path(base_toml).read_text(encoding="utf-8"))

    # Write best strategy params as [strategy] section
    # Use the best overall strategy's params (highest avg_sharpe)
    best_overall = max(results, key=lambda r: r.avg_sharpe) if results else None

    lines = [
        "# Auto-tuned configuration",
        f"# Generated from grid search optimization",
        f"# Best strategy: {best_overall.strategy if best_overall else 'none'}",
        f"# Avg Sharpe: {best_overall.avg_sharpe:.2f}" if best_overall else "",
        "",
    ]

    # Trading section (preserve base)
    trading = base.get("trading", {})
    lines.append("[trading]")
    lines.append(f'exchange = "{trading.get("exchange", "upbit")}"')
    lines.append(f'interval = "{trading.get("interval", "minute60")}"')
    lines.append("paper_trading = true")
    symbols = trading.get("symbols", ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"])
    lines.append(f"symbols = {symbols}")
    lines.append("")

    # Strategy section from best mean_reversion or momentum params
    lines.append("[strategy]")
    if best_overall:
        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k, v in sorted(best_overall.params.items()):
            if k in config_fields:
                if isinstance(v, float):
                    lines.append(f"{k} = {v}")
                else:
                    lines.append(f"{k} = {v}")
    lines.append("")

    # Risk section from best risk params
    lines.append("[risk]")
    if best_overall:
        for k, v in sorted(best_overall.risk_params.items()):
            lines.append(f"{k} = {v}")
    lines.append("")

    # Wallets section with all optimized strategies
    lines.append("# Optimized wallet allocation")
    for i, r in enumerate(sorted(results, key=lambda x: -x.avg_sharpe)):
        lines.append(f"")
        lines.append(f"[[wallets]]")
        lines.append(f'name = "{r.strategy}_wallet"')
        lines.append(f'strategy = "{r.strategy}"')
        # Sharpe-proportional capital allocation (minimum 100K)
        lines.append(f"initial_capital = 1_000_000.0")
    lines.append("")

    # Per-strategy optimal params as comments for reference
    lines.append("# === Per-Strategy Optimization Results ===")
    for r in sorted(results, key=lambda x: -x.avg_sharpe):
        lines.append(f"# {r.strategy}: Sharpe={r.avg_sharpe:.2f} Return={r.avg_return_pct:+.2f}% "
                      f"MDD={r.avg_mdd_pct:.2f}% WR={r.avg_win_rate:.1f}% PF={r.avg_profit_factor:.2f} "
                      f"Trades={r.total_trades}")
        lines.append(f"#   params: {r.params}")
        lines.append(f"#   risk: {r.risk_params}")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Optimized config written to: {output_path}")


def main() -> None:
    days = 30
    if len(sys.argv) > 1:
        days = int(sys.argv[1])
    output_toml = "config/optimized.toml"
    if len(sys.argv) > 2:
        output_toml = sys.argv[2]

    print(f"\n{'='*80}")
    print(f"  AUTO-TUNE: Grid Search + Risk Optimization ({days}d)")
    print(f"{'='*80}")

    # Import grid search components
    from scripts.grid_search import (
        STRATEGY_GRIDS,
        SYMBOLS,
        fetch_candles,
        find_best_params,
        run_grid_for_strategy,
    )

    # Fetch data
    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    tune_results: list[TuneResult] = []

    for strategy_type in STRATEGY_GRIDS:
        print(f"\n{'─'*60}")
        print(f"  Optimizing: {strategy_type}")
        print(f"{'─'*60}")

        # Phase 1: Find best strategy params
        grid_results = run_grid_for_strategy(strategy_type, candles_by_symbol)
        if not grid_results:
            print(f"  SKIP: no grid results for {strategy_type}")
            continue

        best_strategy_params = find_best_params(grid_results)
        print(f"  Best strategy params: {best_strategy_params}")

        # Phase 2: Optimize risk params for this strategy
        print(f"  Optimizing risk params ({len(list(itertools.product(*RISK_GRID.values())))} combos)...")
        best_risk, best_score = optimize_risk_for_strategy(
            strategy_type, best_strategy_params, candles_by_symbol,
        )
        print(f"  Best risk params: {best_risk} (score={best_score:.4f})")

        # Phase 3: Collect final results with best params
        totals = {"return_pct": 0.0, "sharpe": 0.0, "mdd_pct": 0.0,
                  "win_rate": 0.0, "profit_factor": 0.0, "trade_count": 0}
        count = 0
        for symbol, candles in candles_by_symbol.items():
            r = _run_single_backtest(strategy_type, best_strategy_params, best_risk, candles, symbol)
            for k in totals:
                totals[k] += r[k]
            count += 1

        if count > 0:
            tune_results.append(TuneResult(
                strategy=strategy_type,
                params=best_strategy_params,
                risk_params=best_risk,
                avg_return_pct=totals["return_pct"] / count,
                avg_sharpe=totals["sharpe"] / count,
                avg_mdd_pct=totals["mdd_pct"] / count,
                avg_win_rate=totals["win_rate"] / count,
                avg_profit_factor=totals["profit_factor"] / count,
                total_trades=int(totals["trade_count"]),
            ))

    # Summary
    print(f"\n{'='*80}")
    print(f"  AUTO-TUNE RESULTS")
    print(f"{'='*80}")
    print(f"\n  {'Strategy':<20} {'Sharpe':>8} {'Return%':>9} {'MDD%':>7} {'WR%':>7} {'PF':>7} {'Trades':>7}")
    print(f"  {'─'*66}")
    for r in sorted(tune_results, key=lambda x: -x.avg_sharpe):
        pf = f"{r.avg_profit_factor:.2f}" if r.avg_profit_factor < 1000 else "inf"
        print(f"  {r.strategy:<20} {r.avg_sharpe:>7.2f} {r.avg_return_pct:>+8.2f}% "
              f"{r.avg_mdd_pct:>6.2f}% {r.avg_win_rate:>6.1f}% {pf:>7} {r.total_trades:>7}")

    # Write optimized TOML
    write_optimized_toml(tune_results, output_toml)
    print(f"\n{'='*80}")
    print(f"  Auto-tune complete. Apply with: --config {output_toml}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
