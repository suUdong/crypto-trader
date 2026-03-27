"""Generate an offline strategy comparison report from research artifacts."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StrategyComparisonRow:
    strategy: str
    baseline_return_pct: float
    baseline_mdd_pct: float
    baseline_profit_factor: float
    baseline_trades: int
    tuned_return_pct: float
    tuned_sharpe: float
    tuned_mdd_pct: float
    tuned_profit_factor: float
    tuned_trades: int
    return_lift_pct: float
    walk_forward_return_pct: float
    walk_forward_sharpe: float
    walk_forward_profit_factor: float
    walk_forward_trades: int
    walk_forward_oos_win_rate: float
    walk_forward_efficiency: float
    validated: bool


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def _aggregate_baseline(results: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    aggregates: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "return_total": 0.0,
            "mdd_total": 0.0,
            "profit_factor_total": 0.0,
            "trade_total": 0,
            "count": 0,
        }
    )
    for result in results:
        strategy = str(result["strategy"])
        aggregate = aggregates[strategy]
        aggregate["return_total"] = float(aggregate["return_total"]) + float(result["return_pct"])
        aggregate["mdd_total"] = float(aggregate["mdd_total"]) + float(result["max_drawdown"])
        aggregate["profit_factor_total"] = float(aggregate["profit_factor_total"]) + float(
            result["profit_factor"]
        )
        aggregate["trade_total"] = int(aggregate["trade_total"]) + int(result["trade_count"])
        aggregate["count"] = int(aggregate["count"]) + 1

    summary: dict[str, dict[str, float | int]] = {}
    for strategy, aggregate in aggregates.items():
        count = int(aggregate["count"])
        if count == 0:
            continue
        summary[strategy] = {
            "avg_return_pct": float(aggregate["return_total"]) / count,
            "avg_mdd_pct": float(aggregate["mdd_total"]) / count,
            "avg_profit_factor": float(aggregate["profit_factor_total"]) / count,
            "total_trades": int(aggregate["trade_total"]),
        }
    return summary


def _format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _format_float(value: float) -> str:
    if value == float("inf"):
        return "inf"
    return f"{value:.2f}"


def _build_rows(
    baseline: dict[str, Any],
    tuned: dict[str, Any],
    walk_forward: dict[str, Any],
) -> list[StrategyComparisonRow]:
    baseline_by_strategy = _aggregate_baseline(list(baseline["results"]))
    tuned_by_strategy = {
        str(result["strategy"]): result for result in list(tuned["optimized_results"])
    }
    walk_forward_by_strategy = {
        str(result["strategy"]): result for result in list(walk_forward["strategies"])
    }

    strategies = sorted(
        set(baseline_by_strategy) & set(tuned_by_strategy) & set(walk_forward_by_strategy)
    )

    rows: list[StrategyComparisonRow] = []
    for strategy in strategies:
        baseline_row = baseline_by_strategy[strategy]
        tuned_row = tuned_by_strategy[strategy]
        walk_forward_row = walk_forward_by_strategy[strategy]["best"]

        baseline_return = float(baseline_row["avg_return_pct"])
        tuned_return = float(tuned_row["avg_return_pct"])
        rows.append(
            StrategyComparisonRow(
                strategy=strategy,
                baseline_return_pct=baseline_return,
                baseline_mdd_pct=float(baseline_row["avg_mdd_pct"]),
                baseline_profit_factor=float(baseline_row["avg_profit_factor"]),
                baseline_trades=int(baseline_row["total_trades"]),
                tuned_return_pct=tuned_return,
                tuned_sharpe=float(tuned_row["avg_sharpe"]),
                tuned_mdd_pct=float(tuned_row["avg_mdd_pct"]),
                tuned_profit_factor=float(tuned_row["avg_profit_factor"]),
                tuned_trades=int(tuned_row["total_trades"]),
                return_lift_pct=tuned_return - baseline_return,
                walk_forward_return_pct=float(walk_forward_row["avg_return_pct"]),
                walk_forward_sharpe=float(walk_forward_row["avg_sharpe"]),
                walk_forward_profit_factor=float(walk_forward_row["avg_profit_factor"]),
                walk_forward_trades=int(walk_forward_row["total_trades"]),
                walk_forward_oos_win_rate=float(walk_forward_row["wf_oos_win_rate"]),
                walk_forward_efficiency=float(walk_forward_row["wf_avg_efficiency_ratio"]),
                validated=bool(walk_forward_row["validated"]),
            )
        )
    return rows


def _verdict(row: StrategyComparisonRow) -> str:
    if row.validated:
        return "Validated"
    if row.walk_forward_return_pct > 0 and row.walk_forward_sharpe > 0:
        return "OOS positive, gate fail"
    if row.tuned_return_pct > 0:
        return "Tuned positive only"
    return "Negative edge"


def _research_tier(row: StrategyComparisonRow) -> str:
    if row.validated:
        return "deployable"
    if row.walk_forward_return_pct > 0 and row.walk_forward_sharpe > 0:
        return "research hold"
    if row.tuned_return_pct > 0:
        return "watchlist"
    return "drop"


def _live_snapshot_note(
    live_checkpoint_path: Path | None,
    strategy_universe: set[str],
) -> list[str]:
    if live_checkpoint_path is None or not live_checkpoint_path.exists():
        return []

    checkpoint = _read_json(live_checkpoint_path)
    wallet_states = checkpoint.get("wallet_states", {})
    if not isinstance(wallet_states, dict):
        return []

    live_strategies = {
        str(wallet["strategy_type"])
        for wallet in wallet_states.values()
        if isinstance(wallet, dict) and "strategy_type" in wallet
    }
    if live_strategies == strategy_universe:
        return []

    missing = sorted(strategy_universe - live_strategies)
    extra = sorted(live_strategies - strategy_universe)
    lines = [
        "## Live Snapshot Scope Note",
        "",
        "The current `runtime-checkpoint.json` was excluded from the ranking table.",
        "",
        f"- Offline research universe: `{', '.join(sorted(strategy_universe))}`",
        f"- Live snapshot universe: `{', '.join(sorted(live_strategies))}`",
    ]
    if missing:
        lines.append(f"- Missing from live snapshot: `{', '.join(missing)}`")
    if extra:
        lines.append(f"- Extra live-only strategies: `{', '.join(extra)}`")
    lines.append(
        "- Reason: the live wallet mix is not the same 7-strategy matrix, "
        "so including it would distort cross-strategy comparison."
    )
    return lines


def _portfolio_note(portfolio_path: Path | None) -> list[str]:
    if portfolio_path is None or not portfolio_path.exists():
        return []

    portfolio = _read_json(portfolio_path)
    weights = portfolio.get("weights", [])
    if not isinstance(weights, list) or not weights:
        return []

    lines = [
        "## Recommended Wallet Mix",
        "",
        (
            f"- Weighting basis: `{portfolio.get('score_basis', 'unknown')}` "
            f"across `{len(weights)}` strategies"
        ),
        (
            f"- Total capital: `{float(portfolio.get('total_capital_krw', 0.0)):,.0f} KRW`"
        ),
        "",
        "| Strategy | Weight | Allocation | WF Sharpe | WF Return |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in weights:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| {row.get('strategy', 'unknown')} | "
            f"{float(row.get('weight', 0.0)):.1%} | "
            f"{float(row.get('allocation_krw', 0.0)):,.0f} KRW | "
            f"{float(row.get('walk_forward_sharpe', 0.0)):.2f} | "
            f"{float(row.get('walk_forward_return_pct', 0.0)):+.2f}% |"
        )
    return lines


def generate_offline_strategy_report(
    baseline_path: Path,
    tuned_path: Path,
    walk_forward_path: Path,
    live_checkpoint_path: Path | None = None,
    portfolio_path: Path | None = None,
) -> str:
    baseline = _read_json(baseline_path)
    tuned = _read_json(tuned_path)
    walk_forward = _read_json(walk_forward_path)
    rows = _build_rows(baseline, tuned, walk_forward)
    if not rows:
        raise ValueError(
            "No overlapping strategies found across baseline, tuned, and walk-forward."
        )

    baseline_leader = max(
        rows,
        key=lambda row: (row.baseline_return_pct, row.baseline_profit_factor),
    )
    tuned_sharpe_leader = max(rows, key=lambda row: (row.tuned_sharpe, row.tuned_return_pct))
    tuned_return_leader = max(rows, key=lambda row: (row.tuned_return_pct, row.tuned_sharpe))
    walk_forward_leader = max(
        rows,
        key=lambda row: (
            row.walk_forward_sharpe,
            row.walk_forward_return_pct,
            row.walk_forward_trades,
        ),
    )
    largest_lift = max(rows, key=lambda row: row.return_lift_pct)
    validated_count = sum(1 for row in rows if row.validated)
    positive_oos = [row.strategy for row in rows if row.walk_forward_return_pct > 0]
    tuned_only_positive = [
        row.strategy
        for row in rows
        if row.tuned_return_pct > 0 and row.walk_forward_return_pct <= 0
    ]
    weakest_strategies = [
        row.strategy
        for row in sorted(rows, key=lambda item: item.walk_forward_sharpe)[:3]
        if row.strategy != walk_forward_leader.strategy
    ]
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    baseline_days = int(baseline.get("days", 0))
    walk_forward_days = int(walk_forward.get("dataset_days", 0))

    lines = [
        "# Strategy Performance Comparison Report",
        "",
        f"**Generated**: {timestamp}",
        (
            f"**Scope**: 7-strategy offline comparison across `{baseline_days}`-day baseline, "
            f"tuned in-sample search, and `{walk_forward_days}`-day walk-forward validation"
        ),
        (
            "**Authoritative sources**: "
            f"`{baseline_path.as_posix()}`, "
            f"`{tuned_path.as_posix()}`, "
            f"`{walk_forward_path.as_posix()}`"
        ),
        "",
        "## Executive Summary",
        "",
        (
            f"- Baseline leader: `{baseline_leader.strategy}` at "
            f"`{_format_pct(baseline_leader.baseline_return_pct)}` average return "
            f"with `{baseline_leader.baseline_profit_factor:.2f}` PF."
        ),
        (
            f"- Best in-sample Sharpe after tuning: `{tuned_sharpe_leader.strategy}` "
            f"at `{tuned_sharpe_leader.tuned_sharpe:.2f}`."
        ),
        (
            f"- Best in-sample return after tuning: `{tuned_return_leader.strategy}` "
            f"at `{_format_pct(tuned_return_leader.tuned_return_pct)}`."
        ),
        (
            f"- Largest tuning lift: `{largest_lift.strategy}` improved average return by "
            f"`{_format_pct(largest_lift.return_lift_pct)}` versus the untuned baseline."
        ),
        (
            f"- Best out-of-sample research candidate: `{walk_forward_leader.strategy}` "
            f"with `{_format_pct(walk_forward_leader.walk_forward_return_pct)}` return and "
            f"`{walk_forward_leader.walk_forward_sharpe:.2f}` Sharpe."
        ),
        (
            f"- Positive out-of-sample return appeared in `{len(positive_oos)}` strategies: "
            f"`{', '.join(sorted(positive_oos))}`."
        ),
        (
            f"- Validation result: `{validated_count} / {len(rows)}` strategies passed. "
            "Promotion remains `NO`."
        ),
        "",
        "## Comparison Matrix",
        "",
        (
            "| Strategy | Baseline Ret | Baseline PF | Tuned Ret | Tuned Sharpe | "
            "Lift | OOS Ret | OOS Sharpe | OOS Win Rate | Verdict |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for row in sorted(
        rows,
        key=lambda item: (item.walk_forward_sharpe, item.tuned_return_pct),
        reverse=True,
    ):
        lines.append(
            f"| {row.strategy} | {_format_pct(row.baseline_return_pct)} | "
            f"{_format_float(row.baseline_profit_factor)} | "
            f"{_format_pct(row.tuned_return_pct)} | {row.tuned_sharpe:.2f} | "
            f"{_format_pct(row.return_lift_pct)} | "
            f"{_format_pct(row.walk_forward_return_pct)} | {row.walk_forward_sharpe:.2f} | "
            f"{row.walk_forward_oos_win_rate * 100:.1f}% | {_verdict(row)} |"
        )

    lines.extend(
        [
            "",
            "## Stability And Risk",
            "",
            "| Strategy | Baseline MDD | Tuned MDD | OOS PF | OOS Trades | Efficiency | Tier |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in sorted(
        rows,
        key=lambda item: (item.walk_forward_profit_factor, item.walk_forward_trades),
        reverse=True,
    ):
        lines.append(
            f"| {row.strategy} | {row.baseline_mdd_pct:.2f}% | {row.tuned_mdd_pct:.2f}% | "
            f"{_format_float(row.walk_forward_profit_factor)} | {row.walk_forward_trades} | "
            f"{row.walk_forward_efficiency:.2f} | {_research_tier(row)} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                f"1. `{walk_forward_leader.strategy}` is the current best research candidate. "
                f"It finished top out of sample at "
                f"`{_format_pct(walk_forward_leader.walk_forward_return_pct)}` with "
                f"`{walk_forward_leader.walk_forward_sharpe:.2f}` Sharpe, but still did not "
                "clear the promotion gate."
            ),
            (
                f"2. `{tuned_return_leader.strategy}` produced the biggest in-sample upside "
                f"(`{_format_pct(tuned_return_leader.tuned_return_pct)}`), but it failed "
                "to convert that edge into a validated deployment candidate."
            ),
            (
                f"3. `{largest_lift.strategy}` showed the biggest tuning lift "
                f"(`{_format_pct(largest_lift.return_lift_pct)}`), which is useful for research, "
                "but lift alone was not enough to prove robustness."
            ),
            (
                f"4. Strategies that only looked good in sample remain a watchlist, not a "
                f"deployment queue: `{', '.join(sorted(tuned_only_positive)) or 'none'}`."
            ),
            (
                f"5. The weakest validation cohort was `{', '.join(weakest_strategies) or 'n/a'}`. "
                "No strategy cleared the promotion gate, so `config/optimized.toml` should "
                "remain a paper/research artifact rather than a validated deployment config."
            ),
        ]
    )

    live_note = _live_snapshot_note(live_checkpoint_path, {row.strategy for row in rows})
    if live_note:
        lines.extend(["", *live_note])
    portfolio_note = _portfolio_note(portfolio_path)
    if portfolio_note:
        lines.extend(["", *portfolio_note])
    lines.append("")
    return "\n".join(lines)


def save_offline_strategy_report(report: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
