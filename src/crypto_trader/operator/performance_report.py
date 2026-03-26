"""72-hour performance report helpers with micro-live readiness checks."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.operator.artifact_health import summarize_artifact_health
from crypto_trader.operator.pnl_report import PnLReportGenerator, PortfolioPnLReport
from crypto_trader.operator.promotion import MicroLiveCriteria


def build_artifact_health_section(report: PortfolioPnLReport) -> str:
    """Summarize whether performance artifacts describe the same runtime session."""
    health = summarize_artifact_health(report)
    headline = (
        "**Artifact status: HEALTHY**"
        if health["healthy"]
        else f"**Artifact status: WARNING ({health['headline_status']})**"
    )
    lines = [
        "## Artifact Health",
        "",
        headline,
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Checkpoint generated | {report.source_generated_at or 'n/a'} |",
        f"| Checkpoint age | {health['checkpoint_age_display']} ({health['checkpoint_freshness']}) |",
        f"| Checkpoint session | {report.source_session_id or 'n/a'} |",
        f"| Heartbeat generated | {report.heartbeat_generated_at or 'n/a'} |",
        f"| Heartbeat age | {health['heartbeat_age_display']} ({health['heartbeat_freshness']}) |",
        f"| Heartbeat session | {report.heartbeat_session_id or 'n/a'} |",
        f"| Heartbeat poll interval | {report.heartbeat_poll_interval_seconds or 'n/a'} |",
        f"| Consistency status | {health['consistency_status']} |",
        f"| Consistency reason | {health['consistency_reason']} |",
        f"| Freshness status | {health['freshness_status']} |",
        f"| Freshness reason | {health['freshness_reason']} |",
    ]
    if not health["healthy"]:
        lines.extend([
            "",
            "This report should be treated as a point-in-time diagnostic summary, not a clean executive performance narrative.",
        ])
    return "\n".join(lines)


def compute_paper_days(checkpoint_path: Path, journal_path: Path) -> int:
    """Estimate paper trading days from first trade timestamp or checkpoint age."""
    if journal_path.exists():
        first_ts: str | None = None
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            trade = json.loads(line)
            ts = trade.get("timestamp") or trade.get("time") or trade.get("created_at")
            if ts:
                first_ts = ts
                break
        if first_ts:
            try:
                first_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                delta = datetime.now(UTC) - first_dt
                return max(0, delta.days)
            except ValueError:
                pass

    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            generated_at = checkpoint.get("generated_at", "")
            if generated_at:
                checkpoint_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                delta = datetime.now(UTC) - checkpoint_dt
                return max(0, delta.days)
        except (ValueError, KeyError):
            pass

    return 0


def compute_profit_factor(journal_path: Path) -> float:
    """Compute gross_profit / gross_loss from trade journal."""
    if not journal_path.exists():
        return 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        trade = json.loads(line)
        pnl = trade.get("pnl", 0.0)
        if pnl > 0:
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)
    if gross_loss > 0:
        return gross_profit / gross_loss
    return float("inf") if gross_profit > 0 else 0.0


def build_readiness_section(
    report: PortfolioPnLReport,
    checkpoint_path: Path,
    journal_path: Path,
) -> str:
    """Build the micro-live readiness markdown section."""
    paper_days = compute_paper_days(checkpoint_path, journal_path)
    total_trades = report.total_trades
    win_rate = report.portfolio_win_rate
    max_drawdown = report.portfolio_mdd / 100.0
    profit_factor = compute_profit_factor(journal_path)
    positive_strategies = sum(1 for strategy in report.strategies if strategy.total_return_pct > 0)
    positive_strategies_pass = (
        positive_strategies >= MicroLiveCriteria.MINIMUM_POSITIVE_STRATEGIES
    )

    ready, reasons = MicroLiveCriteria.evaluate(
        paper_days=paper_days,
        total_trades=total_trades,
        win_rate=win_rate,
        max_drawdown=max_drawdown,
        profit_factor=profit_factor,
        positive_strategies=positive_strategies,
    )

    status_line = "**Status: READY**" if ready else "**Status: NOT READY**"
    lines = [
        "## Micro-Live Readiness",
        "",
        status_line,
        "",
        "| Criterion | Value | Threshold | Pass |",
        "|-----------|-------|-----------|------|",
        (
            f"| Paper days | {paper_days}d | {MicroLiveCriteria.MINIMUM_PAPER_DAYS}d | "
            f"{'YES' if paper_days >= MicroLiveCriteria.MINIMUM_PAPER_DAYS else 'NO'} |"
        ),
        (
            f"| Total trades | {total_trades} | {MicroLiveCriteria.MINIMUM_TRADES}+ | "
            f"{'YES' if total_trades >= MicroLiveCriteria.MINIMUM_TRADES else 'NO'} |"
        ),
        (
            f"| Win rate | {win_rate:.1%} | {MicroLiveCriteria.MINIMUM_WIN_RATE:.0%} | "
            f"{'YES' if win_rate >= MicroLiveCriteria.MINIMUM_WIN_RATE else 'NO'} |"
        ),
        (
            f"| Max drawdown | {max_drawdown:.1%} | {MicroLiveCriteria.MAXIMUM_DRAWDOWN:.0%} | "
            f"{'YES' if max_drawdown <= MicroLiveCriteria.MAXIMUM_DRAWDOWN else 'NO'} |"
        ),
        (
            f"| Profit factor | {profit_factor:.2f} | "
            f"{MicroLiveCriteria.MINIMUM_PROFIT_FACTOR:.1f} | "
            f"{'YES' if profit_factor >= MicroLiveCriteria.MINIMUM_PROFIT_FACTOR else 'NO'} |"
        ),
        (
            f"| Positive strategies | {positive_strategies} | "
            f"{MicroLiveCriteria.MINIMUM_POSITIVE_STRATEGIES}+ | "
            f"{'YES' if positive_strategies_pass else 'NO'} |"
        ),
        "",
        "### Details",
        "",
    ]
    for reason in reasons:
        lines.append(f"- {reason}")

    return "\n".join(lines)


def generate_performance_report(checkpoint_path: Path, journal_path: Path) -> str:
    """Generate the full performance report as markdown."""
    generator = PnLReportGenerator()
    report = generator.generate_from_checkpoint(
        checkpoint_path=checkpoint_path,
        trade_journal_path=journal_path if journal_path.exists() else None,
        period="72h",
    )

    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    sections = [
        "## 72-Hour Performance Report",
        "",
        f"**Generated**: {now_str}",
        "",
        build_artifact_health_section(report),
        "",
        generator.to_markdown(report),
        "",
        build_readiness_section(report, checkpoint_path, journal_path),
    ]
    return "\n".join(sections)
