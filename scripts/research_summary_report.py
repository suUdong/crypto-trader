#!/usr/bin/env python3
"""Generate a concise research summary from baseline, walk-forward, and wallet artifacts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = ROOT / "artifacts" / "backtest-results-90d.json"
DEFAULT_WALK_FORWARD = ROOT / "artifacts" / "walk-forward-90d" / "grid-wf-summary.json"
DEFAULT_PORTFOLIO = ROOT / "artifacts" / "portfolio-optimization.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "backtest-research-report.md"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _aggregate_baseline(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    aggregates: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "return_total": 0.0,
            "pf_total": 0.0,
            "mdd_total": 0.0,
            "trade_total": 0.0,
            "count": 0.0,
        }
    )
    for row in payload.get("results", []):
        if not isinstance(row, dict):
            continue
        strategy = row.get("strategy")
        if not isinstance(strategy, str):
            continue
        item = aggregates[strategy]
        item["return_total"] += float(row.get("return_pct", 0.0))
        item["pf_total"] += float(row.get("profit_factor", 0.0))
        item["mdd_total"] += float(row.get("max_drawdown", 0.0))
        item["trade_total"] += float(row.get("trade_count", 0.0))
        item["count"] += 1.0

    return {
        strategy: {
            "avg_return_pct": values["return_total"] / values["count"],
            "avg_profit_factor": values["pf_total"] / values["count"],
            "avg_mdd_pct": values["mdd_total"] / values["count"],
            "total_trades": values["trade_total"],
        }
        for strategy, values in aggregates.items()
        if values["count"] > 0
    }


def generate_report(
    baseline_path: Path,
    walk_forward_path: Path,
    portfolio_path: Path,
) -> str:
    baseline = _aggregate_baseline(_read_json(baseline_path))
    walk_forward = _read_json(walk_forward_path)
    portfolio = _read_json(portfolio_path) if portfolio_path.exists() else {"weights": []}
    portfolio_weights = {
        row["strategy"]: row
        for row in portfolio.get("weights", [])
        if isinstance(row, dict) and isinstance(row.get("strategy"), str)
    }

    wf_rows = {}
    for row in walk_forward.get("strategies", []):
        if not isinstance(row, dict) or not isinstance(row.get("strategy"), str):
            continue
        best = row.get("best")
        if not isinstance(best, dict):
            continue
        wf_rows[row["strategy"]] = best

    strategies = sorted(set(baseline) | set(wf_rows))
    validated_count = int(walk_forward.get("validated_count", 0))
    best_research = walk_forward.get("best_research_candidate")
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Backtest Research Report",
        "",
        f"- Generated: `{generated_at}`",
        f"- Baseline artifact: `{baseline_path.as_posix()}`",
        f"- Walk-forward artifact: `{walk_forward_path.as_posix()}`",
        f"- Portfolio artifact: `{portfolio_path.as_posix()}`",
        "",
        "## Executive Summary",
        "",
        f"- Strategy universe: `{len(strategies)}`",
        f"- Walk-forward validated strategies: `{validated_count}`",
    ]
    if isinstance(best_research, dict):
        lines.append(
            f"- Best research candidate: `{best_research.get('strategy', 'n/a')}` "
            f"at `{float(best_research.get('best', {}).get('avg_sharpe', 0.0)):.2f}` Sharpe"
        )
    if portfolio_weights:
        top_weight = max(
            portfolio_weights.values(),
            key=lambda row: float(row.get("weight", 0.0)),
        )
        lines.append(
            f"- Largest wallet weight: `{top_weight.get('strategy', 'n/a')}` "
            f"at `{float(top_weight.get('weight', 0.0)):.1%}`"
        )

    lines.extend(
        [
            "",
            "## Comparison Matrix",
            "",
            (
                "| Strategy | Baseline Ret | Baseline PF | WF Sharpe | WF Return | "
                "OOS Win Rate | Validated | Wallet Weight |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
        ]
    )

    def _sort_key(strategy: str) -> tuple[float, float]:
        wf_best = wf_rows.get(strategy, {})
        return (
            float(wf_best.get("avg_sharpe", float("-inf"))),
            float(wf_best.get("avg_return_pct", float("-inf"))),
        )

    for strategy in sorted(strategies, key=_sort_key, reverse=True):
        base = baseline.get(strategy, {})
        wf_best = wf_rows.get(strategy, {})
        portfolio_row = portfolio_weights.get(strategy, {})
        lines.append(
            f"| {strategy} | "
            f"{float(base.get('avg_return_pct', 0.0)):+.2f}% | "
            f"{float(base.get('avg_profit_factor', 0.0)):.2f} | "
            f"{float(wf_best.get('avg_sharpe', 0.0)):.2f} | "
            f"{float(wf_best.get('avg_return_pct', 0.0)):+.2f}% | "
            f"{float(wf_best.get('wf_oos_win_rate', 0.0)) * 100:.1f}% | "
            f"{'YES' if bool(wf_best.get('validated', False)) else 'NO'} | "
            f"{float(portfolio_row.get('weight', 0.0)):.1%} |"
        )

    lines.extend(
        [
            "",
            "## Wallet Recommendation",
            "",
            "| Strategy | Weight | Allocation | WF Sharpe |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in sorted(
        portfolio.get("weights", []),
        key=lambda item: float(item.get("weight", 0.0)) if isinstance(item, dict) else 0.0,
        reverse=True,
    ):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| {row.get('strategy', 'unknown')} | "
            f"{float(row.get('weight', 0.0)):.1%} | "
            f"{float(row.get('allocation_krw', 0.0)):,.0f} KRW | "
            f"{float(row.get('walk_forward_sharpe', 0.0)):.2f} |"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a backtest research summary report.",
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--walk-forward",
        dest="walk_forward",
        type=Path,
        default=DEFAULT_WALK_FORWARD,
    )
    parser.add_argument("--portfolio", type=Path, default=DEFAULT_PORTFOLIO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = generate_report(args.baseline, args.walk_forward, args.portfolio)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
