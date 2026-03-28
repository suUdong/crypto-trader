#!/usr/bin/env python3
"""Run a 90-day sweep for momentum, mean reversion, and breakout strategies."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
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
from scripts.grid_search import SYMBOLS, fetch_candles  # noqa: E402

TARGET_STRATEGIES = [
    "momentum",
    "mean_reversion",
    "volatility_breakout",
]

DISPLAY_NAMES = {
    "momentum": "momentum",
    "mean_reversion": "mean_reversion",
    "volatility_breakout": "breakout (volatility_breakout)",
}


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


def _display_name(strategy: str) -> str:
    return DISPLAY_NAMES.get(strategy, strategy)


def render_report(
    *,
    days: int,
    json_path: str,
    toml_path: str,
    tune_results: list[TuneResult],
    baseline_results: list[dict[str, object]],
) -> str:
    baseline = _baseline_by_strategy(baseline_results)
    ranked = sorted(
        tune_results,
        key=lambda item: (-item.avg_sharpe, item.avg_mdd_pct, item.strategy),
    )
    report_date = datetime.now(UTC).date().isoformat()
    leader = ranked[0] if ranked else None

    lines = [
        "# 3-Month Strategy Backtest Sweep",
        "",
        f"Date: {report_date}",
        "",
        "## Scope",
        "",
        f"- Window: latest `{days}` days of hourly Upbit candles",
        f"- Symbols: `{', '.join(SYMBOLS)}`",
        "- Strategies: `momentum`, `mean_reversion`, `breakout (volatility_breakout)`",
        "- Outputs: baseline metrics, optimized metrics, best parameter combinations, report",
        "",
        "## Ranking Summary",
        "",
        (
            "| Rank | Strategy | Baseline Sharpe | Optimized Sharpe | "
            "Optimized Win Rate | Optimized MDD | Optimized Return | Trades |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for rank, result in enumerate(ranked, start=1):
        base = baseline.get(result.strategy, {})
        lines.append(
            "| "
            f"{rank} | "
            f"{_display_name(result.strategy)} | "
            f"{float(base.get('avg_sharpe', 0.0)):.2f} | "
            f"{result.avg_sharpe:.2f} | "
            f"{result.avg_win_rate:.1f}% | "
            f"{result.avg_mdd_pct:.2f}% | "
            f"{result.avg_return_pct:+.2f}% | "
            f"{result.total_trades} |"
        )

    lines.extend(
        [
            "",
            "## Per-Strategy Details",
            "",
        ]
    )

    for result in ranked:
        base = baseline.get(result.strategy, {})
        lines.extend(
            [
                f"### `{_display_name(result.strategy)}`",
                "",
                f"- Baseline avg win rate: `{float(base.get('avg_win_rate', 0.0)):.1f}%`",
                f"- Baseline avg Sharpe: `{float(base.get('avg_sharpe', 0.0)):.2f}`",
                f"- Baseline avg MDD: `{float(base.get('avg_mdd_pct', 0.0)):.2f}%`",
                f"- Optimized avg win rate: `{result.avg_win_rate:.1f}%`",
                f"- Optimized avg Sharpe: `{result.avg_sharpe:.2f}`",
                f"- Optimized avg MDD: `{result.avg_mdd_pct:.2f}%`",
                f"- Optimized avg return: `{result.avg_return_pct:+.2f}%`",
                f"- Optimized avg profit factor: `{result.avg_profit_factor:.2f}`",
                f"- Total trades: `{result.total_trades}`",
                f"- Selected candidate rank: `#{result.candidate_rank}`",
                f"- Best score: `{result.best_score:.4f}`",
                f"- Best strategy params: `{result.params}`",
                f"- Best risk params: `{result.risk_params}`",
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

    lines.extend(
        [
            "## Verdict",
            "",
            (
                f"- Best risk-adjusted strategy in this 3-month pass: "
                f"`{_display_name(leader.strategy)}` "
                f"(Sharpe `{leader.avg_sharpe:.2f}`, win rate `{leader.avg_win_rate:.1f}%`, "
                f"MDD `{leader.avg_mdd_pct:.2f}%`)."
                if leader is not None
                else "- No optimized result was produced."
            ),
            "- Ranking is sorted by optimized Sharpe, then lower MDD, then strategy name.",
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
        description="Run a 90-day sweep for momentum, mean_reversion, and volatility_breakout.",
    )
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--cache-dir")
    parser.add_argument("--output-dir", default="backtest_results")
    parser.add_argument("--json-name", default="strategy-sweep-90d.json")
    parser.add_argument("--toml-name", default="strategy-sweep-90d.toml")
    parser.add_argument("--report-name", default="strategy-sweep-90d-report.md")
    args = parser.parse_args()

    if args.cache_dir:
        os.environ["CT_CANDLE_CACHE_DIR"] = args.cache_dir

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / args.json_name
    toml_path = output_dir / args.toml_name
    report_path = output_dir / args.report_name

    candles_by_symbol = {}
    for symbol in SYMBOLS:
        print(f"Fetching {symbol} ({args.days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, args.days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    if not candles_by_symbol:
        raise RuntimeError("No symbols had enough candle history for the requested sweep.")

    baseline_results = collect_baseline_results(TARGET_STRATEGIES, candles_by_symbol)
    tune_results: list[TuneResult] = []
    for strategy in TARGET_STRATEGIES:
        result = tune_strategy(strategy, candles_by_symbol, top_n=args.top_n, verbose=True)
        if result is not None:
            tune_results.append(result)

    completed = {result.strategy for result in tune_results}
    missing = [strategy for strategy in TARGET_STRATEGIES if strategy not in completed]
    if missing:
        raise RuntimeError(f"Optimization did not produce results for: {', '.join(missing)}")

    write_optimized_toml(tune_results, str(toml_path))
    write_results_json(baseline_results, tune_results, str(json_path), args.days)
    report_path.write_text(
        render_report(
            days=args.days,
            json_path=str(json_path),
            toml_path=str(toml_path),
            tune_results=tune_results,
            baseline_results=baseline_results,
        ),
        encoding="utf-8",
    )
    print(f"  Report written to: {report_path}")


if __name__ == "__main__":
    main()
