#!/usr/bin/env python3
"""Auto-tune: run grid search on synthetic/cached data and write optimal params to TOML.

Usage:
    PYTHONPATH=src .venv/bin/python3 scripts/auto_tune.py [days] [output_toml]

Combines strategy param grid search + risk param grid search, then writes
the best parameters to a TOML config file ready for production use.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from crypto_trader.backtest.engine import BacktestEngine  # noqa: E402
from crypto_trader.config import (  # noqa: E402
    BacktestConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
)
from crypto_trader.models import Candle  # noqa: E402
from crypto_trader.risk.manager import RiskManager  # noqa: E402
from scripts.grid_search import (  # noqa: E402
    SYMBOLS,
    _create_strategy_for_grid,
    _setup_kimchi_premium_mock,
    fetch_candles,
    run_grid_for_strategy,
    top_param_sets,
)


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
    best_score: float
    candidate_rank: int
    top_candidates: list[dict[str, object]]
    per_symbol: dict[str, dict[str, float]]


DEFAULT_STRATEGIES = [
    "momentum",
    "momentum_pullback",
    "mean_reversion",
    "composite",
    "kimchi_premium",
    "obi",
    "vpin",
    "volatility_breakout",
]


# Risk parameter grid
RISK_GRID = {
    "stop_loss_pct": [0.02, 0.03, 0.04],
    "take_profit_pct": [0.04, 0.06, 0.08, 0.10],
    "risk_per_trade_pct": [0.005, 0.01, 0.015],
    "trailing_stop_pct": [0.0, 0.02, 0.04],
    "atr_stop_multiplier": [0.0, 2.0, 3.0],
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
    strategy = _create_strategy_for_grid(
        strategy_type,
        strategy_params,
        strategy_config,
        regime_config,
    )
    if strategy_type == "kimchi_premium":
        _setup_kimchi_premium_mock(strategy, candles)

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
    risk_manager = RiskManager(
        risk_config,
        trailing_stop_pct=float(risk_params.get("trailing_stop_pct", 0.0)),
        atr_stop_multiplier=float(risk_params.get("atr_stop_multiplier", 0.0)),
    )
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
        risk_params = dict(zip(risk_param_names, combo, strict=True))
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


def evaluate_strategy_params(
    strategy_type: str,
    strategy_params: dict[str, float | int],
    risk_params: dict[str, float],
    candles_by_symbol: dict[str, list[Candle]],
) -> dict[str, object] | None:
    """Evaluate a strategy/risk parameter set across all provided symbols."""
    totals = {
        "return_pct": 0.0,
        "sharpe": 0.0,
        "mdd_pct": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "trade_count": 0,
    }
    per_symbol: dict[str, dict[str, float]] = {}
    count = 0

    for symbol, candles in candles_by_symbol.items():
        result = _run_single_backtest(strategy_type, strategy_params, risk_params, candles, symbol)
        for key in totals:
            totals[key] += result[key]
        per_symbol[symbol] = result
        count += 1

    if count == 0:
        return None

    return {
        "avg_return_pct": totals["return_pct"] / count,
        "avg_sharpe": totals["sharpe"] / count,
        "avg_mdd_pct": totals["mdd_pct"] / count,
        "avg_win_rate": totals["win_rate"] / count,
        "avg_profit_factor": totals["profit_factor"] / count,
        "total_trades": int(totals["trade_count"]),
        "per_symbol": per_symbol,
    }


def collect_baseline_results(
    strategies: list[str],
    candles_by_symbol: dict[str, list[Candle]],
) -> list[dict[str, object]]:
    """Collect baseline backtest results using default params."""
    baseline_results: list[dict[str, object]] = []
    for strategy_type in strategies:
        for symbol, candles in candles_by_symbol.items():
            baseline = _run_single_backtest(strategy_type, {}, {}, candles, symbol)
            baseline_results.append(
                {
                    "strategy": strategy_type,
                    "symbol": symbol,
                    **baseline,
                }
            )
    return baseline_results


def tune_strategy(
    strategy_type: str,
    candles_by_symbol: dict[str, list[Candle]],
    top_n: int = 3,
    verbose: bool = True,
) -> TuneResult | None:
    """Tune one strategy on a symbol->candles dataset."""
    risk_combo_count = len(list(itertools.product(*RISK_GRID.values())))

    if verbose:
        print(f"\n{'─' * 60}")
        print(f"  Optimizing: {strategy_type}")
        print(f"{'─' * 60}")

    grid_results = run_grid_for_strategy(strategy_type, candles_by_symbol)
    if not grid_results:
        if verbose:
            print(f"  SKIP: no grid results for {strategy_type}")
        return None

    top_candidates = top_param_sets(grid_results, top_n=top_n)
    if not top_candidates:
        if verbose:
            print(f"  SKIP: no candidate summaries for {strategy_type}")
        return None

    candidate_results: list[dict[str, object]] = []
    for idx, candidate in enumerate(top_candidates, start=1):
        if verbose:
            print(f"  Candidate #{idx} params: {candidate.params}")
            print(f"  Optimizing risk params ({risk_combo_count} combos)...")

        best_risk, best_score = optimize_risk_for_strategy(
            strategy_type,
            candidate.params,
            candles_by_symbol,
        )
        evaluation = evaluate_strategy_params(
            strategy_type,
            candidate.params,
            best_risk,
            candles_by_symbol,
        )
        if evaluation is None:
            continue

        candidate_results.append(
            {
                "rank": idx,
                "params": candidate.params,
                "base_score": candidate.score,
                "risk_params": best_risk,
                "optimized_score": best_score,
                **evaluation,
            }
        )

    if not candidate_results:
        return None

    best_candidate = max(
        candidate_results,
        key=lambda item: (
            float(item["optimized_score"]),
            float(item["avg_sharpe"]),
            float(item["avg_return_pct"]),
        ),
    )
    if verbose:
        print(
            f"  Best candidate: #{best_candidate['rank']} "
            f"score={float(best_candidate['optimized_score']):.4f} "
            f"sharpe={float(best_candidate['avg_sharpe']):.2f}"
        )

    return TuneResult(
        strategy=strategy_type,
        params=dict(best_candidate["params"]),
        risk_params=dict(best_candidate["risk_params"]),
        avg_return_pct=float(best_candidate["avg_return_pct"]),
        avg_sharpe=float(best_candidate["avg_sharpe"]),
        avg_mdd_pct=float(best_candidate["avg_mdd_pct"]),
        avg_win_rate=float(best_candidate["avg_win_rate"]),
        avg_profit_factor=float(best_candidate["avg_profit_factor"]),
        total_trades=int(best_candidate["total_trades"]),
        best_score=float(best_candidate["optimized_score"]),
        candidate_rank=int(best_candidate["rank"]),
        top_candidates=candidate_results,
        per_symbol=dict(best_candidate["per_symbol"]),
    )


def write_results_json(
    baseline_results: list[dict[str, object]],
    tune_results: list[TuneResult],
    output_path: str,
    days: int,
) -> None:
    """Write baseline and optimization results as JSON for reporting."""
    payload = {
        "days": days,
        "baseline_results": baseline_results,
        "optimized_results": [asdict(result) for result in tune_results],
    }
    Path(output_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Detailed results written to: {output_path}")


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
        "# Generated from grid search optimization",
        (
            "# Best strategy in evaluated candidate sweep: "
            f"{best_overall.strategy if best_overall else 'none'}"
        ),
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
    rendered_symbols = ", ".join(_toml_literal(symbol) for symbol in symbols)
    lines.append(f"symbols = [{rendered_symbols}]")
    lines.append("")

    # Strategy section from best mean_reversion or momentum params
    lines.append("[strategy]")
    if best_overall:
        for key, value in sorted(_strategy_config_params(best_overall.params).items()):
            lines.append(f"{key} = {_toml_literal(value)}")
    lines.append("")

    # Risk section from best risk params
    lines.append("[risk]")
    if best_overall:
        for key, value in sorted(best_overall.risk_params.items()):
            lines.append(f"{key} = {_toml_literal(value)}")
    lines.append("")

    # Wallet sections carry per-strategy overrides so multi-runtime can run
    # the tuned parameter set for each strategy without losing constructor-only params.
    lines.append("# Optimized wallet allocation")
    wallet_capital = 1_000_000.0
    for result in sorted(results, key=lambda item: (-item.avg_sharpe, item.strategy)):
        lines.append("")
        lines.append(
            f"# {result.strategy}: Sharpe={result.avg_sharpe:.2f} "
            f"Return={result.avg_return_pct:+.2f}% "
            f"MDD={result.avg_mdd_pct:.2f}% "
            f"WR={result.avg_win_rate:.1f}% "
            f"PF={result.avg_profit_factor:.2f} "
            f"Trades={result.total_trades}"
        )
        lines.append("[[wallets]]")
        lines.append(f'name = "{result.strategy}_wallet"')
        lines.append(f'strategy = "{result.strategy}"')
        lines.append(f"initial_capital = {_toml_literal(wallet_capital)}")

        if result.params:
            lines.append("")
            lines.append("[wallets.strategy_overrides]")
            for key, value in sorted(result.params.items()):
                lines.append(f"{key} = {_toml_literal(value)}")

        if result.risk_params:
            lines.append("")
            lines.append("[wallets.risk_overrides]")
            for key, value in sorted(result.risk_params.items()):
                lines.append(f"{key} = {_toml_literal(value)}")
    lines.append("")

    # Per-strategy optimal params as comments for reference
    lines.append("# === Per-Strategy Optimization Results ===")
    for r in sorted(results, key=lambda x: -x.avg_sharpe):
        lines.append(
            f"# {r.strategy}: Sharpe={r.avg_sharpe:.2f} "
            f"Return={r.avg_return_pct:+.2f}% "
            f"MDD={r.avg_mdd_pct:.2f}% "
            f"WR={r.avg_win_rate:.1f}% "
            f"PF={r.avg_profit_factor:.2f} "
            f"Trades={r.total_trades}"
        )
        lines.append(f"#   params: {r.params}")
        lines.append(f"#   risk: {r.risk_params}")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Optimized config written to: {output_path}")


def _strategy_config_params(params: dict[str, float | int]) -> dict[str, float | int]:
    config_fields = set(StrategyConfig.__dataclass_fields__)
    return {key: value for key, value in params.items() if key in config_fields}


def _toml_literal(value: object) -> str:
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run strategy/risk auto-tuning and write optimized config.",
    )
    parser.add_argument("days", nargs="?", type=int, default=30)
    parser.add_argument("output_toml", nargs="?", default="config/optimized.toml")
    parser.add_argument("--json-out", dest="json_out")
    parser.add_argument("--top-n", dest="top_n", type=int, default=3)
    parser.add_argument("--cache-dir", dest="cache_dir")
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=DEFAULT_STRATEGIES,
        help="Strategies to optimize.",
    )
    args = parser.parse_args()

    days = args.days
    output_toml = args.output_toml
    if args.cache_dir:
        os.environ["CT_CANDLE_CACHE_DIR"] = args.cache_dir

    print(f"\n{'=' * 80}")
    print(f"  AUTO-TUNE: Grid Search + Risk Optimization ({days}d)")
    print(f"{'=' * 80}")

    # Fetch data
    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    baseline_results = collect_baseline_results(args.strategies, candles_by_symbol)

    tune_results: list[TuneResult] = []

    for strategy_type in args.strategies:
        result = tune_strategy(strategy_type, candles_by_symbol, top_n=args.top_n, verbose=True)
        if result is not None:
            tune_results.append(result)

    # Summary
    print(f"\n{'=' * 80}")
    print("  AUTO-TUNE RESULTS")
    print(f"{'=' * 80}")
    print(
        f"\n  {'Strategy':<20} {'Sharpe':>8} {'Return%':>9} "
        f"{'MDD%':>7} {'WR%':>7} {'PF':>7} {'Trades':>7}"
    )
    print(f"  {'─' * 66}")
    for r in sorted(tune_results, key=lambda x: -x.avg_sharpe):
        pf = f"{r.avg_profit_factor:.2f}" if r.avg_profit_factor < 1000 else "inf"
        print(
            f"  {r.strategy:<20} {r.avg_sharpe:>7.2f} {r.avg_return_pct:>+8.2f}% "
            f"{r.avg_mdd_pct:>6.2f}% {r.avg_win_rate:>6.1f}% {pf:>7} {r.total_trades:>7}"
        )

    # Write optimized TOML
    write_optimized_toml(tune_results, output_toml)
    if args.json_out:
        write_results_json(baseline_results, tune_results, args.json_out, days)
    print(f"\n{'=' * 80}")
    print(f"  Auto-tune complete. Apply with: --config {output_toml}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
