#!/usr/bin/env python3
"""Focused 30-day optimization for momentum and mean_reversion."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from scripts.auto_tune import (  # noqa: E402
    TuneResult,
    collect_baseline_results,
    tune_strategy,
    write_optimized_toml,
    write_results_json,
)
from scripts.grid_search import STRATEGY_GRIDS, SYMBOLS, fetch_candles  # noqa: E402

FOCUSED_STRATEGIES = ["momentum", "mean_reversion"]

FOCUSED_GRIDS: dict[str, dict[str, list[float | int]]] = {
    "momentum": {
        "momentum_lookback": [10, 12, 15],
        "momentum_entry_threshold": [0.001, 0.002, 0.003, 0.005],
        "rsi_period": [14],
        "rsi_recovery_ceiling": [60.0, 70.0],
        "rsi_overbought": [70.0, 75.0],
        "max_holding_bars": [24, 36, 48],
        "adx_threshold": [15.0, 20.0, 25.0],
        "volume_filter_mult": [0.0, 0.8],
    },
    "mean_reversion": {
        "bollinger_window": [12, 16],
        "bollinger_stddev": [1.2, 1.4, 1.6],
        "rsi_period": [6, 8, 10],
        "rsi_oversold_floor": [15.0, 20.0],
        "rsi_recovery_ceiling": [24.0, 30.0, 36.0],
        "noise_lookback": [10],
        "adx_threshold": [24.0, 28.0],
        "max_holding_bars": [8, 12, 18],
        "volume_filter_mult": [0.0, 0.8],
    },
}


def install_focused_grids() -> dict[str, dict[str, list[float | int]]]:
    original = {
        strategy: copy.deepcopy(STRATEGY_GRIDS.get(strategy, {}))
        for strategy in FOCUSED_STRATEGIES
    }
    for strategy, grid in FOCUSED_GRIDS.items():
        STRATEGY_GRIDS[strategy] = copy.deepcopy(grid)
    return original


def restore_grids(original: dict[str, dict[str, list[float | int]]]) -> None:
    for strategy, grid in original.items():
        STRATEGY_GRIDS[strategy] = copy.deepcopy(grid)


def _baseline_by_strategy(
    baseline_results: list[dict[str, object]],
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, dict[str, float | int]] = {}
    counts: dict[str, int] = {}
    for row in baseline_results:
        strategy = str(row["strategy"])
        bucket = grouped.setdefault(
            strategy,
            {
                "avg_return_pct": 0.0,
                "avg_sharpe": 0.0,
                "avg_mdd_pct": 0.0,
                "avg_win_rate": 0.0,
                "avg_profit_factor": 0.0,
                "total_trades": 0,
            },
        )
        bucket["avg_return_pct"] += float(row["return_pct"])
        bucket["avg_sharpe"] += float(row["sharpe"])
        bucket["avg_mdd_pct"] += float(row["mdd_pct"])
        bucket["avg_win_rate"] += float(row["win_rate"])
        bucket["avg_profit_factor"] += float(row["profit_factor"])
        bucket["total_trades"] += int(row["trade_count"])
        counts[strategy] = counts.get(strategy, 0) + 1

    for strategy, bucket in grouped.items():
        count = max(1, counts[strategy])
        for key in (
            "avg_return_pct",
            "avg_sharpe",
            "avg_mdd_pct",
            "avg_win_rate",
            "avg_profit_factor",
        ):
            bucket[key] = float(bucket[key]) / count
    return grouped


def render_report(
    *,
    days: int,
    json_path: str,
    toml_path: str,
    tune_results: list[TuneResult],
    baseline_results: list[dict[str, object]],
) -> str:
    baseline = _baseline_by_strategy(baseline_results)
    lines = [
        "# 30-Day Momentum and Mean Reversion Optimization",
        "",
        "Date: 2026-03-28",
        "",
        "## Scope",
        "",
        f"- Window: latest `{days}` days of hourly Upbit candles",
        f"- Symbols: `{', '.join(SYMBOLS)}`",
        "- Strategies: `momentum`, `mean_reversion`",
        "- Search method: focused grid search + risk sweep via existing offline backtest pipeline",
        (
            "- Notes: this pass optimizes base strategy parameters only; "
            "weekend-specific mean-reversion overlays remain a separate research lane"
        ),
        "",
        "## Search Surfaces",
        "",
        f"- `momentum`: `{json.dumps(FOCUSED_GRIDS['momentum'], ensure_ascii=False)}`",
        f"- `mean_reversion`: `{json.dumps(FOCUSED_GRIDS['mean_reversion'], ensure_ascii=False)}`",
        "",
        "## Results",
        "",
    ]

    for result in sorted(tune_results, key=lambda item: (-item.avg_sharpe, item.strategy)):
        base = baseline.get(result.strategy, {})
        lines.extend(
            [
                f"### `{result.strategy}`",
                "",
                f"- Baseline avg return: `{float(base.get('avg_return_pct', 0.0)):+.2f}%`",
                f"- Baseline avg Sharpe: `{float(base.get('avg_sharpe', 0.0)):.2f}`",
                f"- Optimized avg return: `{result.avg_return_pct:+.2f}%`",
                f"- Optimized avg Sharpe: `{result.avg_sharpe:.2f}`",
                f"- Optimized avg max drawdown: `{result.avg_mdd_pct:.2f}%`",
                f"- Optimized avg win rate: `{result.avg_win_rate:.1f}%`",
                f"- Optimized avg profit factor: `{result.avg_profit_factor:.2f}`",
                f"- Total trades: `{result.total_trades}`",
                f"- Selected candidate rank: `#{result.candidate_rank}`",
                f"- Best score: `{result.best_score:.4f}`",
                (
                    "- Strategy params: "
                    f"`{json.dumps(result.params, ensure_ascii=False, sort_keys=True)}`"
                ),
                (
                    "- Risk params: "
                    f"`{json.dumps(result.risk_params, ensure_ascii=False, sort_keys=True)}`"
                ),
                "",
                "| Symbol | Return | Sharpe | MDD | Win Rate | PF | Trades |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for symbol in SYMBOLS:
            metrics = result.per_symbol.get(symbol, {})
            lines.append(
                "| "
                f"{symbol} | "
                f"{float(metrics.get('return_pct', 0.0)):+.2f}% | "
                f"{float(metrics.get('sharpe', 0.0)):.2f} | "
                f"{float(metrics.get('mdd_pct', 0.0)):.2f}% | "
                f"{float(metrics.get('win_rate', 0.0)):.1f}% | "
                f"{float(metrics.get('profit_factor', 0.0)):.2f} | "
                f"{int(metrics.get('trade_count', 0))} |"
            )
        lines.append("")

    leader = max(tune_results, key=lambda item: item.avg_sharpe) if tune_results else None
    lines.extend(
        [
            "## Verdict",
            "",
            (
                f"- Best risk-adjusted candidate in this 30-day pass: `{leader.strategy}` "
                f"(Sharpe `{leader.avg_sharpe:.2f}`, return `{leader.avg_return_pct:+.2f}%`)."
                if leader is not None
                else "- No optimized result was produced."
            ),
            "- Treat this as a research artifact, not an automatic live deployment decision.",
            "",
            "## Artifacts",
            "",
            f"- JSON: `{json_path}`",
            f"- TOML: `{toml_path}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optimize recent 30-day momentum and mean_reversion settings.",
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--top-n", type=int, default=4)
    parser.add_argument("--cache-dir")
    parser.add_argument(
        "--json-out",
        default="artifacts/momentum-mean-reversion-30d-optimization-2026-03-28.json",
    )
    parser.add_argument(
        "--toml-out",
        default="artifacts/momentum-mean-reversion-30d-optimized-2026-03-28.toml",
    )
    parser.add_argument(
        "--doc-out",
        default="docs/momentum-mean-reversion-optimization-20260328.md",
    )
    args = parser.parse_args()

    if args.cache_dir:
        os.environ["CT_CANDLE_CACHE_DIR"] = args.cache_dir

    original = install_focused_grids()
    try:
        candles_by_symbol = {}
        for symbol in SYMBOLS:
            print(f"Fetching {symbol} ({args.days}d)...", end=" ", flush=True)
            candles = fetch_candles(symbol, args.days)
            print(f"{len(candles)} candles")
            if len(candles) >= 50:
                candles_by_symbol[symbol] = candles

        baseline_results = collect_baseline_results(FOCUSED_STRATEGIES, candles_by_symbol)
        tune_results: list[TuneResult] = []
        for strategy in FOCUSED_STRATEGIES:
            result = tune_strategy(
                strategy,
                candles_by_symbol,
                top_n=args.top_n,
                verbose=True,
            )
            if result is not None:
                tune_results.append(result)

        if not tune_results:
            raise RuntimeError("No optimization results were produced.")

        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.toml_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.doc_out).parent.mkdir(parents=True, exist_ok=True)

        write_optimized_toml(tune_results, args.toml_out)
        write_results_json(baseline_results, tune_results, args.json_out, args.days)
        Path(args.doc_out).write_text(
            render_report(
                days=args.days,
                json_path=args.json_out,
                toml_path=args.toml_out,
                tune_results=tune_results,
                baseline_results=baseline_results,
            ),
            encoding="utf-8",
        )
        print(f"  Report written to: {args.doc_out}")
    finally:
        restore_grids(original)


if __name__ == "__main__":
    main()
