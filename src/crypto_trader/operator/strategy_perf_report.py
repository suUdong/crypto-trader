"""Strategy performance analysis report generator from backtest results."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.models import BacktestResult


@dataclass(slots=True)
class StrategyMetrics:
    strategy: str
    return_pct: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown_pct: float
    profit_factor: float
    win_rate: float
    trade_count: int
    avg_trade_pnl: float
    regime_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    risk_adjusted_score: float = 0.0


def _compute_risk_adjusted_score(
    sharpe: float,
    sortino: float,
    profit_factor: float,
    win_rate: float,
) -> float:
    """Compute composite risk-adjusted score.

    score = 0.4*sharpe + 0.3*sortino_norm + 0.2*pf_norm + 0.1*wr_adj
    where:
        sortino_norm = min(sortino / 3, 1.0)
        pf_norm      = min(profit_factor / 3, 1.0)
        wr_adj       = win_rate - 0.5  (centered around 50%)
    """
    sortino_norm = min(sortino / 3.0, 1.0)
    pf_norm = min(profit_factor / 3.0, 1.0)
    wr_adj = win_rate - 0.5
    return 0.4 * sharpe + 0.3 * sortino_norm + 0.2 * pf_norm + 0.1 * wr_adj


def _metrics_from_result(strategy: str, result: BacktestResult) -> StrategyMetrics:
    trade_count = len(result.trade_log)
    avg_trade_pnl = (
        sum(t.pnl for t in result.trade_log) / trade_count if trade_count > 0 else 0.0
    )
    # max_drawdown is stored as a fraction (0-1); convert to percentage
    max_drawdown_pct = result.max_drawdown * 100.0

    # Build regime breakdown from BacktestResult.regime_breakdown if present.
    # The stored dict is regime -> {win_rate, avg_pnl, trade_count} already if populated
    # by the backtester; fall back to empty dict when absent.
    regime_breakdown: dict[str, dict[str, float]] = {}
    if result.regime_breakdown:
        for regime, stats in result.regime_breakdown.items():
            regime_breakdown[regime] = {k: float(v) for k, v in stats.items()}

    score = _compute_risk_adjusted_score(
        sharpe=result.sharpe_ratio,
        sortino=result.sortino_ratio,
        profit_factor=result.profit_factor,
        win_rate=result.win_rate,
    )

    return StrategyMetrics(
        strategy=strategy,
        return_pct=result.total_return_pct,
        sharpe=result.sharpe_ratio,
        sortino=result.sortino_ratio,
        calmar=result.calmar_ratio,
        max_drawdown_pct=max_drawdown_pct,
        profit_factor=result.profit_factor,
        win_rate=result.win_rate,
        trade_count=trade_count,
        avg_trade_pnl=avg_trade_pnl,
        regime_breakdown=regime_breakdown,
        risk_adjusted_score=score,
    )


def _fmt_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _fmt_f(value: float, decimals: int = 2) -> str:
    if value == float("inf"):
        return "inf"
    return f"{value:.{decimals}f}"


class StrategyPerformanceAnalyzer:
    """Analyse backtest results and generate structured performance reports."""

    def generate_from_backtest_results(
        self,
        results: list[tuple[str, BacktestResult]],
    ) -> list[StrategyMetrics]:
        """Convert (strategy_name, BacktestResult) tuples into sorted StrategyMetrics.

        Returns the list sorted by risk_adjusted_score descending.
        """
        metrics = [_metrics_from_result(name, result) for name, result in results]
        metrics.sort(key=lambda m: m.risk_adjusted_score, reverse=True)
        return metrics

    def to_markdown(self, metrics: list[StrategyMetrics]) -> str:
        """Generate a full markdown performance report from StrategyMetrics."""
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        lines: list[str] = [
            "# Strategy Performance Analysis Report",
            "",
            f"**Generated**: {timestamp}",
            f"**Strategies analysed**: {len(metrics)}",
            "",
        ]

        # --- Summary table ---
        lines.extend(
            [
                "## Summary",
                "",
                (
                    "| Strategy | Return% | Sharpe | Sortino | Calmar | MDD% | "
                    "PF | Win Rate | Trades | Score |"
                ),
                (
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
                ),
            ]
        )
        for m in metrics:
            lines.append(
                f"| {m.strategy} "
                f"| {_fmt_pct(m.return_pct)} "
                f"| {_fmt_f(m.sharpe)} "
                f"| {_fmt_f(m.sortino)} "
                f"| {_fmt_f(m.calmar)} "
                f"| {_fmt_f(m.max_drawdown_pct)} "
                f"| {_fmt_f(m.profit_factor)} "
                f"| {m.win_rate:.1%} "
                f"| {m.trade_count} "
                f"| {_fmt_f(m.risk_adjusted_score, 4)} |"
            )

        # --- Rankings ---
        lines.extend(["", "## Rankings", ""])
        for rank, m in enumerate(metrics, start=1):
            lines.append(
                f"{rank}. **{m.strategy}** — score `{_fmt_f(m.risk_adjusted_score, 4)}`, "
                f"return `{_fmt_pct(m.return_pct)}`, "
                f"Sharpe `{_fmt_f(m.sharpe)}`, "
                f"win rate `{m.win_rate:.1%}`, "
                f"trades `{m.trade_count}`"
            )

        # --- Regime breakdown ---
        regime_lines: list[str] = []
        for m in metrics:
            if not m.regime_breakdown:
                continue
            if not regime_lines:
                regime_lines.extend(["", "## Regime Breakdown", ""])
            regime_lines.extend([f"### {m.strategy}", ""])
            regime_lines.extend(
                [
                    "| Regime | Win Rate | Avg PnL | Trades |",
                    "| --- | ---: | ---: | ---: |",
                ]
            )
            for regime, stats in sorted(m.regime_breakdown.items()):
                wr = stats.get("win_rate", 0.0)
                avg_pnl = stats.get("avg_pnl", 0.0)
                tc = stats.get("trade_count", 0.0)
                regime_lines.append(
                    f"| {regime} | {wr:.1%} | {_fmt_f(avg_pnl)} | {tc:.0f} |"
                )
            regime_lines.append("")
        lines.extend(regime_lines)

        # --- Allocation recommendations ---
        lines.extend(["", "## Allocation Recommendations", ""])
        if not metrics:
            lines.append("No strategies to rank.")
        else:
            top = [m for m in metrics if m.risk_adjusted_score > 0.0]
            neutral = [m for m in metrics if m.risk_adjusted_score == 0.0]
            underperform = [m for m in metrics if m.risk_adjusted_score < 0.0]

            if top:
                names = ", ".join(f"`{m.strategy}`" for m in top)
                lines.append(f"**Allocate / maintain**: {names}")
            if neutral:
                names = ", ".join(f"`{m.strategy}`" for m in neutral)
                lines.append(f"**Monitor (neutral score)**: {names}")
            if underperform:
                names = ", ".join(f"`{m.strategy}`" for m in underperform)
                lines.append(f"**Review / reduce**: {names}")

            best = metrics[0]
            lines.extend(
                [
                    "",
                    (
                        f"Top-ranked strategy **{best.strategy}** "
                        f"(score `{_fmt_f(best.risk_adjusted_score, 4)}`) should receive "
                        "highest capital weight. "
                        f"Risk-adjusted score threshold for deployment: `> 0.0`."
                    ),
                ]
            )

        lines.append("")
        return "\n".join(lines)

    def to_json(self, metrics: list[StrategyMetrics]) -> str:
        """Serialise all metrics to a JSON string."""
        payload = [
            {
                "strategy": m.strategy,
                "return_pct": m.return_pct,
                "sharpe": m.sharpe,
                "sortino": m.sortino,
                "calmar": m.calmar,
                "max_drawdown_pct": m.max_drawdown_pct,
                "profit_factor": m.profit_factor,
                "win_rate": m.win_rate,
                "trade_count": m.trade_count,
                "avg_trade_pnl": m.avg_trade_pnl,
                "regime_breakdown": m.regime_breakdown,
                "risk_adjusted_score": m.risk_adjusted_score,
            }
            for m in metrics
        ]
        return json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "strategy_count": len(metrics),
                "metrics": payload,
            },
            indent=2,
        )

    def save(self, report_md: str, report_json: str, output_dir: str | Path) -> None:
        """Write markdown and JSON reports to output_dir."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        (out / f"strategy_perf_{timestamp}.md").write_text(report_md, encoding="utf-8")
        (out / f"strategy_perf_{timestamp}.json").write_text(report_json, encoding="utf-8")
