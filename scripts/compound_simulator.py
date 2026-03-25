#!/usr/bin/env python3
"""Simulate compound returns over time using observed strategy performance."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, "src")


@dataclass
class Scenario:
    name: str
    daily_return_pct: float


@dataclass
class SimulationResult:
    scenario: str
    days: int
    starting_capital: float
    final_equity: float
    total_return_pct: float
    equity_curve: list[float]


def simulate_compound(
    starting_capital: float,
    daily_return_pct: float,
    days: int,
) -> SimulationResult:
    """Simulate daily compounding at a fixed return rate."""
    equity = starting_capital
    curve = [equity]
    daily_factor = 1.0 + daily_return_pct / 100.0

    for _ in range(days):
        equity *= daily_factor
        curve.append(equity)

    total_return = (equity / starting_capital - 1.0) * 100.0
    return SimulationResult(
        scenario="",
        days=days,
        starting_capital=starting_capital,
        final_equity=equity,
        total_return_pct=total_return,
        equity_curve=curve,
    )


def generate_report(
    starting_capital: float,
    observed_48h_return_pct: float,
    output_path: str | None = None,
) -> str:
    """Generate compound simulation report with multiple scenarios."""
    # Convert 48h return to daily
    observed_daily = observed_48h_return_pct / 2.0

    scenarios = [
        Scenario("Conservative (50% of observed)", observed_daily * 0.5),
        Scenario("Base (observed rate)", observed_daily),
        Scenario("Optimistic (150% of observed)", observed_daily * 1.5),
        Scenario("Drawdown (-50% of observed)", -observed_daily * 0.5),
    ]

    periods = [30, 90, 180, 365]

    lines = [
        "# Compound Return Simulation Report",
        "",
        f"**Starting Capital**: {starting_capital:,.0f} KRW",
        f"**Observed 48h Return**: {observed_48h_return_pct:+.3f}%",
        f"**Implied Daily Return**: {observed_daily:+.4f}%",
        "",
        "---",
        "",
        "## Projected Equity by Scenario",
        "",
    ]

    header = f"| {'Scenario':<35} | {'Daily%':>8} |"
    for d in periods:
        header += f" {d}d Equity |"
        header += f" {d}d Return |"
    lines.append(header)

    sep = f"|{'-'*37}|{'-'*10}|"
    for _ in periods:
        sep += f"{'-'*12}|{'-'*12}|"
    lines.append(sep)

    for scenario in scenarios:
        row = f"| {scenario.name:<35} | {scenario.daily_return_pct:>+7.4f}% |"
        for d in periods:
            result = simulate_compound(starting_capital, scenario.daily_return_pct, d)
            row += f" {result.final_equity:>10,.0f} |"
            row += f" {result.total_return_pct:>+9.2f}% |"
        lines.append(row)

    lines.extend([
        "",
        "---",
        "",
        "## Key Milestones (Base Scenario)",
        "",
    ])

    base_daily = observed_daily
    if base_daily > 0:
        # Days to double
        import math
        days_to_2x = math.log(2) / math.log(1 + base_daily / 100.0)
        days_to_3x = math.log(3) / math.log(1 + base_daily / 100.0)
        days_to_10x = math.log(10) / math.log(1 + base_daily / 100.0)

        lines.extend([
            f"- **2x Capital**: ~{days_to_2x:.0f} days ({days_to_2x/30:.1f} months)",
            f"- **3x Capital**: ~{days_to_3x:.0f} days ({days_to_3x/30:.1f} months)",
            f"- **10x Capital**: ~{days_to_10x:.0f} days ({days_to_10x/30:.1f} months)",
        ])
    else:
        lines.append("- Base scenario return is not positive; milestones not applicable.")

    lines.extend([
        "",
        "---",
        "",
        "## Portfolio Scaling Projections (Base Scenario)",
        "",
        "| Starting Capital | 30d | 90d | 365d |",
        "|-----------------|-----|-----|------|",
    ])

    for cap in [1_000_000, 5_000_000, 10_000_000, 50_000_000, 100_000_000]:
        r30 = simulate_compound(cap, base_daily, 30)
        r90 = simulate_compound(cap, base_daily, 90)
        r365 = simulate_compound(cap, base_daily, 365)
        lines.append(
            f"| {cap:>15,.0f} KRW | {r30.final_equity:>12,.0f} | "
            f"{r90.final_equity:>12,.0f} | {r365.final_equity:>12,.0f} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Caveats",
        "",
        "- Returns are NOT guaranteed to compound at observed rates",
        "- Slippage, fees, and market impact increase with capital",
        "- Drawdown periods can significantly reduce compound growth",
        "- Past performance does not predict future results",
        "- This simulation assumes daily rebalancing at a fixed return rate",
        "",
        "*Report generated from 48h paper trading observations. No real capital at risk.*",
    ])

    report = "\n".join(lines)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"Report saved to {output_path}")

    return report


def main() -> None:
    starting_capital = 6_000_000.0  # 6M KRW (6 wallets x 1M)
    observed_48h_return = 0.332  # From 48h report

    if len(sys.argv) > 1:
        observed_48h_return = float(sys.argv[1])
    if len(sys.argv) > 2:
        starting_capital = float(sys.argv[2])

    report = generate_report(
        starting_capital=starting_capital,
        observed_48h_return_pct=observed_48h_return,
        output_path="artifacts/compound-simulation.md",
    )
    print(report)


if __name__ == "__main__":
    main()
