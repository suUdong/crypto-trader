#!/usr/bin/env python3
"""Sharpe-weighted wallet optimization from offline research artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TUNED = ROOT / "artifacts" / "backtest-grid-90d" / "combined.json"
DEFAULT_WALK_FORWARD = ROOT / "artifacts" / "walk-forward-90d" / "grid-wf-summary.json"
DEFAULT_OUTPUT_MD = ROOT / "artifacts" / "portfolio-optimization.md"
DEFAULT_OUTPUT_JSON = ROOT / "artifacts" / "portfolio-optimization.json"
DEFAULT_OUTPUT_TOML = ROOT / "artifacts" / "portfolio-weights.toml"


@dataclass(frozen=True)
class PortfolioAllocation:
    strategy: str
    tuned_sharpe: float
    tuned_return_pct: float
    walk_forward_sharpe: float
    walk_forward_return_pct: float
    walk_forward_profit_factor: float
    validated: bool
    score: float
    score_basis: str
    weight: float
    allocation_krw: float


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _normalize_tuned_results(payload: dict[str, Any]) -> dict[str, dict[str, float | bool]]:
    optimized_results = payload.get("optimized_results", [])
    if not isinstance(optimized_results, list):
        raise ValueError("optimized_results must be a list")
    normalized: dict[str, dict[str, float | bool]] = {}
    for row in optimized_results:
        if not isinstance(row, dict):
            continue
        strategy = row.get("strategy")
        if not isinstance(strategy, str):
            continue
        normalized[strategy] = {
            "tuned_sharpe": float(row.get("avg_sharpe", 0.0)),
            "tuned_return_pct": float(row.get("avg_return_pct", 0.0)),
        }
    return normalized


def _normalize_walk_forward_results(
    payload: dict[str, Any],
) -> dict[str, dict[str, float | bool]]:
    strategies = payload.get("strategies", [])
    normalized: dict[str, dict[str, float | bool]] = {}

    if isinstance(strategies, list):
        for row in strategies:
            if not isinstance(row, dict):
                continue
            strategy = row.get("strategy")
            best = row.get("best")
            if not isinstance(strategy, str) or not isinstance(best, dict):
                continue
            normalized[strategy] = {
                "walk_forward_sharpe": float(best.get("avg_sharpe", 0.0)),
                "walk_forward_return_pct": float(best.get("avg_return_pct", 0.0)),
                "walk_forward_profit_factor": float(best.get("avg_profit_factor", 0.0)),
                "validated": bool(best.get("validated", False)),
            }
        return normalized

    if isinstance(strategies, dict):
        for strategy, row in strategies.items():
            if not isinstance(strategy, str) or not isinstance(row, dict):
                continue
            aggregate = row.get("aggregate", {})
            if not isinstance(aggregate, dict):
                continue
            normalized[strategy] = {
                "walk_forward_sharpe": float(aggregate.get("avg_test_sharpe", 0.0)),
                "walk_forward_return_pct": float(aggregate.get("avg_test_return_pct", 0.0)),
                "walk_forward_profit_factor": float(aggregate.get("avg_test_profit_factor", 0.0)),
                "validated": False,
            }
        return normalized

    raise ValueError("Unsupported walk-forward strategies payload")


def build_portfolio_allocations(
    tuned_payload: dict[str, Any],
    walk_forward_payload: dict[str, Any],
    capital_per_strategy: float,
) -> tuple[list[PortfolioAllocation], str, float]:
    tuned = _normalize_tuned_results(tuned_payload)
    walk_forward = _normalize_walk_forward_results(walk_forward_payload)
    strategy_names = sorted(set(tuned) & set(walk_forward))
    if not strategy_names:
        raise ValueError("No overlapping strategies found across tuned and walk-forward inputs.")

    base_rows: list[dict[str, float | bool | str]] = []
    for strategy in strategy_names:
        tuned_row = tuned[strategy]
        walk_forward_row = walk_forward[strategy]
        base_rows.append(
            {
                "strategy": strategy,
                "tuned_sharpe": float(tuned_row["tuned_sharpe"]),
                "tuned_return_pct": float(tuned_row["tuned_return_pct"]),
                "walk_forward_sharpe": float(walk_forward_row["walk_forward_sharpe"]),
                "walk_forward_return_pct": float(walk_forward_row["walk_forward_return_pct"]),
                "walk_forward_profit_factor": float(walk_forward_row["walk_forward_profit_factor"]),
                "validated": bool(walk_forward_row["validated"]),
            }
        )

    score_basis = "walk_forward_sharpe"
    scores = [max(0.0, float(row["walk_forward_sharpe"])) for row in base_rows]
    score_total = sum(scores)
    if score_total == 0.0:
        score_basis = "tuned_sharpe_fallback"
        scores = [max(0.0, float(row["tuned_sharpe"])) for row in base_rows]
        score_total = sum(scores)

    if score_total == 0.0:
        score_basis = "equal_weight_fallback"
        scores = [1.0 for _ in base_rows]
        score_total = float(len(base_rows))

    total_capital = capital_per_strategy * len(base_rows)
    allocations = [
        PortfolioAllocation(
            strategy=str(row["strategy"]),
            tuned_sharpe=float(row["tuned_sharpe"]),
            tuned_return_pct=float(row["tuned_return_pct"]),
            walk_forward_sharpe=float(row["walk_forward_sharpe"]),
            walk_forward_return_pct=float(row["walk_forward_return_pct"]),
            walk_forward_profit_factor=float(row["walk_forward_profit_factor"]),
            validated=bool(row["validated"]),
            score=score,
            score_basis=score_basis,
            weight=score / score_total,
            allocation_krw=total_capital * (score / score_total),
        )
        for row, score in zip(base_rows, scores, strict=True)
    ]
    allocations.sort(key=lambda row: (row.weight, row.walk_forward_sharpe), reverse=True)
    return allocations, score_basis, total_capital


def write_portfolio_json(
    output_path: Path,
    allocations: list[PortfolioAllocation],
    score_basis: str,
    total_capital: float,
    tuned_path: Path,
    walk_forward_path: Path,
) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "score_basis": score_basis,
        "total_capital_krw": total_capital,
        "input_paths": {
            "tuned": tuned_path.as_posix(),
            "walk_forward": walk_forward_path.as_posix(),
        },
        "weights": [asdict(allocation) for allocation in allocations],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_portfolio_markdown(
    output_path: Path,
    allocations: list[PortfolioAllocation],
    score_basis: str,
    total_capital: float,
) -> None:
    lines = [
        "# Portfolio Optimization Report",
        "",
        f"- Generated: `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}`",
        f"- Total capital: `{total_capital:,.0f} KRW`",
        f"- Weighting basis: `{score_basis}`",
        "",
        "| Strategy | Weight | Allocation | WF Sharpe | WF Return | Tuned Sharpe | Validated |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for allocation in allocations:
        lines.append(
            f"| {allocation.strategy} | {allocation.weight:.1%} | "
            f"{allocation.allocation_krw:,.0f} KRW | "
            f"{allocation.walk_forward_sharpe:.2f} | "
            f"{allocation.walk_forward_return_pct:+.2f}% | "
            f"{allocation.tuned_sharpe:.2f} | "
            f"{'YES' if allocation.validated else 'NO'} |"
        )
    lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_wallet_toml(output_path: Path, allocations: list[PortfolioAllocation]) -> None:
    lines = [
        "# Sharpe-weighted research wallet mix",
        f"# Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    for allocation in allocations:
        lines.extend(
            [
                "[[wallets]]",
                f'name = "{allocation.strategy}_research_wallet"',
                f'strategy = "{allocation.strategy}"',
                f"initial_capital = {allocation.allocation_krw:.0f}",
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a Sharpe-weighted wallet mix from research artifacts.",
    )
    parser.add_argument("days", nargs="?", type=int, default=90)
    parser.add_argument("--tuned", type=Path, default=DEFAULT_TUNED)
    parser.add_argument(
        "--walk-forward",
        dest="walk_forward",
        type=Path,
        default=DEFAULT_WALK_FORWARD,
    )
    parser.add_argument("--capital-per-strategy", type=float, default=1_000_000.0)
    parser.add_argument("--output-md", dest="output_md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--output-json", dest="output_json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-toml", dest="output_toml", type=Path, default=DEFAULT_OUTPUT_TOML)
    args = parser.parse_args()

    allocations, score_basis, total_capital = build_portfolio_allocations(
        tuned_payload=_read_json(args.tuned),
        walk_forward_payload=_read_json(args.walk_forward),
        capital_per_strategy=args.capital_per_strategy,
    )
    write_portfolio_json(
        args.output_json,
        allocations,
        score_basis,
        total_capital,
        args.tuned,
        args.walk_forward,
    )
    write_portfolio_markdown(args.output_md, allocations, score_basis, total_capital)
    write_wallet_toml(args.output_toml, allocations)

    print(f"\n{'=' * 80}")
    print(f"  PORTFOLIO OPTIMIZER - {args.days}-day artifact analysis")
    print(f"{'=' * 80}")
    print(f"  Weighting basis: {score_basis}")
    print(f"  Total capital: {total_capital:,.0f} KRW")
    for allocation in allocations:
        print(
            f"  {allocation.strategy:<20} {allocation.weight:>6.1%}  "
            f"({allocation.allocation_krw:>12,.0f} KRW)"
        )
    print(f"\n  JSON report saved to {args.output_json}")
    print(f"  Markdown report saved to {args.output_md}")
    print(f"  Wallet TOML saved to {args.output_toml}")


if __name__ == "__main__":
    main()
