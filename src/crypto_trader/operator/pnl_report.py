"""Automated PnL reporting with Sharpe, MDD, win rate calculations."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(slots=True)
class StrategyPnLMetrics:
    strategy: str
    wallet: str
    total_return_pct: float
    realized_pnl: float
    unrealized_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    equity: float
    initial_capital: float


@dataclass(slots=True)
class PortfolioPnLReport:
    generated_at: str
    period: str
    strategies: list[StrategyPnLMetrics]
    portfolio_return_pct: float
    portfolio_sharpe: float
    portfolio_mdd: float
    portfolio_win_rate: float
    total_trades: int
    total_realized_pnl: float
    total_equity: float
    total_initial_capital: float
    source_generated_at: str = ""
    source_session_id: str = ""
    source_config_path: str = ""
    source_wallet_names: list[str] = field(default_factory=list)
    source_symbols: list[str] = field(default_factory=list)
    heartbeat_generated_at: str = ""
    heartbeat_session_id: str = ""
    heartbeat_poll_interval_seconds: int = 0
    artifact_consistency_status: str = "unknown"
    artifact_consistency_reason: str = ""


class PnLReportGenerator:
    """Generates PnL reports from checkpoint and trade data."""

    def generate_from_checkpoint(
        self,
        checkpoint_path: str | Path,
        trade_journal_path: str | Path | None = None,
        period: str = "daily",
        hours: int = 0,
    ) -> PortfolioPnLReport:
        """Generate report from runtime checkpoint JSON.

        Args:
            checkpoint_path: Path to runtime checkpoint.
            trade_journal_path: Path to paper trade journal (JSONL).
            period: Label for the report period.
            hours: If > 0, only include trades from the last N hours.
        """
        cp_path = Path(checkpoint_path)
        if not cp_path.exists():
            return self._empty_report(period)

        checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
        wallet_states = checkpoint.get("wallet_states", {})
        source_generated_at = str(checkpoint.get("generated_at", ""))
        source_session_id = str(checkpoint.get("session_id", ""))
        source_config_path = str(checkpoint.get("config_path", ""))
        source_wallet_names = list(checkpoint.get("wallet_names", wallet_states.keys()))
        source_symbols = list(checkpoint.get("symbols", []))
        (
            heartbeat_generated_at,
            heartbeat_session_id,
            heartbeat_poll_interval_seconds,
            artifact_consistency_status,
            artifact_consistency_reason,
        ) = self._resolve_artifact_consistency(
            checkpoint_path=cp_path,
            checkpoint_session_id=source_session_id,
            checkpoint_wallet_names=source_wallet_names,
            checkpoint_symbols=source_symbols,
        )

        # Load trade journal if available, with optional time filtering
        trades_by_wallet: dict[str, list[dict]] = {}
        cutoff: datetime | None = None
        if hours > 0:
            cutoff = datetime.now(UTC) - timedelta(hours=hours)

        if trade_journal_path:
            tj_path = Path(trade_journal_path)
            if tj_path.exists():
                for line in tj_path.read_text(encoding="utf-8").strip().split("\n"):
                    if not line.strip():
                        continue
                    trade = json.loads(line)
                    # Time filtering
                    if cutoff is not None:
                        exit_time_str = trade.get("exit_time", "")
                        try:
                            exit_time = datetime.fromisoformat(exit_time_str)
                            if exit_time.tzinfo is None:
                                exit_time = exit_time.replace(tzinfo=UTC)
                            if exit_time < cutoff:
                                continue
                        except (ValueError, TypeError):
                            continue
                    wallet = trade.get("wallet", "unknown")
                    trades_by_wallet.setdefault(wallet, []).append(trade)

        strategies: list[StrategyPnLMetrics] = []
        total_equity = 0.0
        total_initial = 0.0
        total_trades = 0
        total_wins = 0
        total_losses = 0
        total_realized = 0.0

        for wallet_name, state in wallet_states.items():
            initial_capital = 1_000_000.0  # Default per wallet
            equity = state.get("equity", initial_capital)
            realized = state.get("realized_pnl", 0.0)
            trade_count = state.get("trade_count", 0)
            strategy_type = state.get("strategy_type", "unknown")

            # Compute metrics from trades if available
            wallet_trades = trades_by_wallet.get(wallet_name, [])
            wins = sum(1 for t in wallet_trades if t.get("pnl", 0) > 0)
            losses = sum(1 for t in wallet_trades if t.get("pnl", 0) <= 0)

            # When filtering by time, use journal trade count
            if hours > 0:
                trade_count = len(wallet_trades)
                realized = sum(t.get("pnl", 0) for t in wallet_trades)

            if trade_count > 0 and not wallet_trades:
                # Estimate from realized PnL
                wins = trade_count if realized > 0 else 0
                losses = trade_count - wins

            win_rate = wins / max(1, wins + losses)
            gross_profit = sum(t.get("pnl", 0) for t in wallet_trades if t.get("pnl", 0) > 0)
            gross_loss = abs(sum(t.get("pnl", 0) for t in wallet_trades if t.get("pnl", 0) <= 0))
            pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

            return_pct = (equity / initial_capital - 1.0) * 100.0
            unrealized = equity - initial_capital - realized

            # Approximate MDD from single snapshot (limited data)
            mdd = max(0.0, -return_pct) if return_pct < 0 else 0.0

            # Approximate Sharpe (annualized from period return)
            effective_period = period
            if hours > 0:
                effective_period = f"{hours}h"
            sharpe = self._approx_sharpe_from_return(return_pct, effective_period)

            metrics = StrategyPnLMetrics(
                strategy=strategy_type,
                wallet=wallet_name,
                total_return_pct=return_pct,
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                trade_count=trade_count,
                win_count=wins,
                loss_count=losses,
                win_rate=win_rate,
                profit_factor=pf,
                max_drawdown_pct=mdd,
                sharpe_ratio=sharpe,
                equity=equity,
                initial_capital=initial_capital,
            )
            strategies.append(metrics)

            total_equity += equity
            total_initial += initial_capital
            total_trades += trade_count
            total_wins += wins
            total_losses += losses
            total_realized += realized

        portfolio_return = (total_equity / max(1, total_initial) - 1.0) * 100.0
        effective_period = f"{hours}h" if hours > 0 else period
        portfolio_sharpe = self._approx_sharpe_from_return(portfolio_return, effective_period)
        portfolio_mdd = max(0.0, -portfolio_return) if portfolio_return < 0 else 0.0
        portfolio_win_rate = total_wins / max(1, total_wins + total_losses)

        return PortfolioPnLReport(
            generated_at=datetime.now(UTC).isoformat(),
            period=effective_period,
            strategies=strategies,
            portfolio_return_pct=portfolio_return,
            portfolio_sharpe=portfolio_sharpe,
            portfolio_mdd=portfolio_mdd,
            portfolio_win_rate=portfolio_win_rate,
            total_trades=total_trades,
            total_realized_pnl=total_realized,
            total_equity=total_equity,
            total_initial_capital=total_initial,
            source_generated_at=source_generated_at,
            source_session_id=source_session_id,
            source_config_path=source_config_path,
            source_wallet_names=source_wallet_names,
            source_symbols=source_symbols,
            heartbeat_generated_at=heartbeat_generated_at,
            heartbeat_session_id=heartbeat_session_id,
            heartbeat_poll_interval_seconds=heartbeat_poll_interval_seconds,
            artifact_consistency_status=artifact_consistency_status,
            artifact_consistency_reason=artifact_consistency_reason,
        )

    def to_markdown(self, report: PortfolioPnLReport) -> str:
        """Convert PnL report to markdown format."""
        health = None
        try:
            from crypto_trader.operator.artifact_health import summarize_artifact_health

            health = summarize_artifact_health(report)
        except Exception:
            health = None

        lines = [
            f"# PnL Report ({report.period.title()})",
            "",
            f"**Generated**: {report.generated_at}",
            f"**Period**: {report.period}",
            "",
            "## Portfolio Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Equity | {report.total_equity:,.0f} KRW |",
            f"| Total Return | {report.portfolio_return_pct:+.3f}% |",
            f"| Sharpe Ratio | {report.portfolio_sharpe:.2f} |",
            f"| Max Drawdown | {report.portfolio_mdd:.3f}% |",
            f"| Win Rate | {report.portfolio_win_rate:.1%} |",
            f"| Total Trades | {report.total_trades} |",
            f"| Realized PnL | {report.total_realized_pnl:+,.0f} KRW |",
            "",
            "## Artifact Context",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Checkpoint Generated | {report.source_generated_at or 'n/a'} |",
            f"| Checkpoint Session | {report.source_session_id or 'n/a'} |",
            f"| Config Path | {report.source_config_path or 'n/a'} |",
            f"| Wallets | {', '.join(report.source_wallet_names) or 'n/a'} |",
            f"| Symbols | {', '.join(report.source_symbols) or 'n/a'} |",
            f"| Heartbeat Generated | {report.heartbeat_generated_at or 'n/a'} |",
            f"| Heartbeat Session | {report.heartbeat_session_id or 'n/a'} |",
            f"| Heartbeat Poll Interval | {report.heartbeat_poll_interval_seconds or 'n/a'} |",
            f"| Consistency | {report.artifact_consistency_status} |",
            f"| Consistency Reason | {report.artifact_consistency_reason or 'n/a'} |",
            "",
            "## Per-Wallet Breakdown",
            "",
            "| Wallet | Strategy | Return% | Equity | Realized | Trades | Win% | PF | Sharpe |",
            "|--------|----------|---------|--------|----------|--------|------|-----|--------|",
        ]

        if health is not None:
            lines[lines.index("## Per-Wallet Breakdown"):lines.index("## Per-Wallet Breakdown")] = [
                f"| Checkpoint Age | {health['checkpoint_age_display']} ({health['checkpoint_freshness']}) |",
                f"| Heartbeat Age | {health['heartbeat_age_display']} ({health['heartbeat_freshness']}) |",
                f"| Freshness Status | {health['freshness_status']} |",
                f"| Freshness Reason | {health['freshness_reason']} |",
                f"| Artifact Health | {'healthy' if health['healthy'] else 'warning'} |",
                "",
            ]

        for s in sorted(report.strategies, key=lambda x: x.total_return_pct, reverse=True):
            pf = f"{s.profit_factor:.2f}" if s.profit_factor < 1000 else "inf"
            lines.append(
                f"| {s.wallet} | {s.strategy} | {s.total_return_pct:+.3f}% | "
                f"{s.equity:,.0f} | {s.realized_pnl:+,.0f} | "
                f"{s.trade_count} | {s.win_rate:.0%} | {pf} | "
                f"{s.sharpe_ratio:.2f} |"
            )

        lines.extend([
            "",
            "## Cumulative Realized PnL",
            "",
            "| Wallet | Strategy | Cumulative Realized PnL |",
            "|--------|----------|------------------------|",
        ])
        cumulative = 0.0
        for s in sorted(report.strategies, key=lambda x: x.realized_pnl, reverse=True):
            cumulative += s.realized_pnl
            lines.append(f"| {s.wallet} | {s.strategy} | {cumulative:+,.0f} KRW |")
        lines.append(f"| | **Total** | **{report.total_realized_pnl:+,.0f} KRW** |")

        lines.extend(["", "*Auto-generated PnL report*"])
        return "\n".join(lines)

    def save(self, report: PortfolioPnLReport, path: str | Path) -> None:
        """Save report as both JSON and markdown."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        md_content = self.to_markdown(report)
        target.write_text(md_content, encoding="utf-8")

        json_path = target.with_suffix(".json")
        json_data = {
            "generated_at": report.generated_at,
            "period": report.period,
            "portfolio_return_pct": report.portfolio_return_pct,
            "portfolio_sharpe": report.portfolio_sharpe,
            "portfolio_mdd": report.portfolio_mdd,
            "portfolio_win_rate": report.portfolio_win_rate,
            "total_trades": report.total_trades,
            "total_realized_pnl": report.total_realized_pnl,
            "total_equity": report.total_equity,
            "artifact_context": {
                "checkpoint_generated_at": report.source_generated_at,
                "checkpoint_session_id": report.source_session_id,
                "config_path": report.source_config_path,
                "wallet_names": report.source_wallet_names,
                "symbols": report.source_symbols,
                "heartbeat_generated_at": report.heartbeat_generated_at,
                "heartbeat_session_id": report.heartbeat_session_id,
                "heartbeat_poll_interval_seconds": report.heartbeat_poll_interval_seconds,
                "consistency_status": report.artifact_consistency_status,
                "consistency_reason": report.artifact_consistency_reason,
                "freshness_status": "unknown",
                "freshness_reason": "not computed",
            },
            "strategies": [],
        }
        try:
            from crypto_trader.operator.artifact_health import summarize_artifact_health

            health = summarize_artifact_health(report)
            json_data["artifact_context"].update({
                "healthy": health["healthy"],
                "headline_status": health["headline_status"],
                "checkpoint_age_seconds": health["checkpoint_age_seconds"],
                "heartbeat_age_seconds": health["heartbeat_age_seconds"],
                "checkpoint_age_display": health["checkpoint_age_display"],
                "heartbeat_age_display": health["heartbeat_age_display"],
                "checkpoint_freshness": health["checkpoint_freshness"],
                "heartbeat_freshness": health["heartbeat_freshness"],
                "freshness_status": health["freshness_status"],
                "freshness_reason": health["freshness_reason"],
            })
        except Exception:
            pass
        cumulative = 0.0
        for s in sorted(report.strategies, key=lambda x: x.realized_pnl, reverse=True):
            cumulative += s.realized_pnl
            json_data["strategies"].append({
                "wallet": s.wallet,
                "strategy": s.strategy,
                "return_pct": s.total_return_pct,
                "realized_pnl": s.realized_pnl,
                "cumulative_realized_pnl": cumulative,
                "trade_count": s.trade_count,
                "win_rate": s.win_rate,
                "sharpe": s.sharpe_ratio,
            })
        json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")

        # Auto-append to snapshot history
        snapshot_path = target.parent / "pnl-snapshots.jsonl"
        PnLSnapshotStore(snapshot_path).append(report)

    def _empty_report(self, period: str) -> PortfolioPnLReport:
        return PortfolioPnLReport(
            generated_at=datetime.now(UTC).isoformat(),
            period=period,
            strategies=[],
            portfolio_return_pct=0.0,
            portfolio_sharpe=0.0,
            portfolio_mdd=0.0,
            portfolio_win_rate=0.0,
            total_trades=0,
            total_realized_pnl=0.0,
            total_equity=0.0,
            total_initial_capital=0.0,
        )

    @staticmethod
    def _resolve_artifact_consistency(
        checkpoint_path: Path,
        checkpoint_session_id: str,
        checkpoint_wallet_names: list[str],
        checkpoint_symbols: list[str],
    ) -> tuple[str, str, int, str, str]:
        heartbeat_path = checkpoint_path.parent / "daemon-heartbeat.json"
        if not checkpoint_session_id:
            return "", "", 0, "legacy_checkpoint", "checkpoint missing session metadata"
        if not heartbeat_path.exists():
            return "", "", 0, "missing_heartbeat", "heartbeat artifact missing"

        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "", "", 0, "invalid_heartbeat", "heartbeat JSON is invalid"
        heartbeat_generated_at = str(heartbeat.get("last_heartbeat", ""))
        heartbeat_session_id = str(heartbeat.get("session_id", ""))
        heartbeat_poll_interval_seconds = int(heartbeat.get("poll_interval_seconds", 0) or 0)
        heartbeat_wallet_names = list(heartbeat.get("wallet_names", []))
        heartbeat_symbols = list(heartbeat.get("symbols", []))

        if heartbeat_session_id != checkpoint_session_id:
            return (
                heartbeat_generated_at,
                heartbeat_session_id,
                heartbeat_poll_interval_seconds,
                "session_mismatch",
                "checkpoint and heartbeat session ids differ",
            )
        if checkpoint_wallet_names and heartbeat_wallet_names and checkpoint_wallet_names != heartbeat_wallet_names:
            return (
                heartbeat_generated_at,
                heartbeat_session_id,
                heartbeat_poll_interval_seconds,
                "wallet_mismatch",
                "checkpoint and heartbeat wallet sets differ",
            )
        if checkpoint_symbols and heartbeat_symbols and checkpoint_symbols != heartbeat_symbols:
            return (
                heartbeat_generated_at,
                heartbeat_session_id,
                heartbeat_poll_interval_seconds,
                "symbol_mismatch",
                "checkpoint and heartbeat symbol sets differ",
            )
        return (
            heartbeat_generated_at,
            heartbeat_session_id,
            heartbeat_poll_interval_seconds,
            "consistent",
            "checkpoint and heartbeat align",
        )

    @staticmethod
    def _approx_sharpe_from_return(return_pct: float, period: str) -> float:
        """Approximate annualized Sharpe from period return."""
        # Parse hours-based periods like "72h", "24h"
        if period.endswith("h") and period[:-1].isdigit():
            period_days = int(period[:-1]) / 24.0
        else:
            period_days = {"daily": 1, "weekly": 7, "monthly": 30, "48h": 2}.get(period, 1)
        if period_days == 0:
            return 0.0
        daily_return = return_pct / period_days
        # Assume daily vol ~ 2x daily return for crypto (rough heuristic)
        daily_vol = max(abs(daily_return) * 2, 0.1)
        annualized_return = daily_return * 365
        annualized_vol = daily_vol * math.sqrt(365)
        if annualized_vol == 0:
            return 0.0
        return annualized_return / annualized_vol


class PnLSnapshotStore:
    """Append-only JSONL store for historical PnL snapshots."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def append(self, report: PortfolioPnLReport) -> None:
        """Append a single snapshot line from a PnL report."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": report.generated_at,
            "period": report.period,
            "portfolio_return_pct": round(report.portfolio_return_pct, 4),
            "portfolio_sharpe": round(report.portfolio_sharpe, 2),
            "total_equity": round(report.total_equity, 0),
            "total_realized_pnl": round(report.total_realized_pnl, 0),
            "total_trades": report.total_trades,
            "portfolio_win_rate": round(report.portfolio_win_rate, 4),
            "source_session_id": report.source_session_id,
            "artifact_consistency_status": report.artifact_consistency_status,
            "artifact_freshness_status": "unknown",
            "wallets": [
                {
                    "wallet": s.wallet,
                    "strategy": s.strategy,
                    "return_pct": round(s.total_return_pct, 4),
                    "equity": round(s.equity, 0),
                    "realized_pnl": round(s.realized_pnl, 0),
                    "sharpe": round(s.sharpe_ratio, 2),
                }
                for s in report.strategies
            ],
        }
        try:
            from crypto_trader.operator.artifact_health import summarize_artifact_health

            health = summarize_artifact_health(report)
            entry["artifact_freshness_status"] = health["freshness_status"]
        except Exception:
            pass
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def load_history(self) -> list[dict]:
        """Load all historical snapshots."""
        if not self._path.exists():
            return []
        entries = []
        for line in self._path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))
        return entries
