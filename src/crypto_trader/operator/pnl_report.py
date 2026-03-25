"""Automated PnL reporting with Sharpe, MDD, win rate calculations."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class StrategyPnLMetrics:
    strategy: str
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


class PnLReportGenerator:
    """Generates PnL reports from checkpoint and trade data."""

    def generate_from_checkpoint(
        self,
        checkpoint_path: str | Path,
        trade_journal_path: str | Path | None = None,
        period: str = "daily",
    ) -> PortfolioPnLReport:
        """Generate report from runtime checkpoint JSON."""
        cp_path = Path(checkpoint_path)
        if not cp_path.exists():
            return self._empty_report(period)

        checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
        wallet_states = checkpoint.get("wallet_states", {})

        # Load trade journal if available
        trades_by_wallet: dict[str, list[dict]] = {}
        if trade_journal_path:
            tj_path = Path(trade_journal_path)
            if tj_path.exists():
                for line in tj_path.read_text(encoding="utf-8").strip().split("\n"):
                    if not line.strip():
                        continue
                    trade = json.loads(line)
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
            sharpe = self._approx_sharpe_from_return(return_pct, period)

            metrics = StrategyPnLMetrics(
                strategy=strategy_type,
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
        portfolio_sharpe = self._approx_sharpe_from_return(portfolio_return, period)
        portfolio_mdd = max(0.0, -portfolio_return) if portfolio_return < 0 else 0.0
        portfolio_win_rate = total_wins / max(1, total_wins + total_losses)

        return PortfolioPnLReport(
            generated_at=datetime.now(UTC).isoformat(),
            period=period,
            strategies=strategies,
            portfolio_return_pct=portfolio_return,
            portfolio_sharpe=portfolio_sharpe,
            portfolio_mdd=portfolio_mdd,
            portfolio_win_rate=portfolio_win_rate,
            total_trades=total_trades,
            total_realized_pnl=total_realized,
            total_equity=total_equity,
            total_initial_capital=total_initial,
        )

    def to_markdown(self, report: PortfolioPnLReport) -> str:
        """Convert PnL report to markdown format."""
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
            "## Strategy Breakdown",
            "",
            "| Strategy | Return% | Equity | Realized | Trades | Win% | PF | Sharpe |",
            "|----------|---------|--------|----------|--------|------|-----|--------|",
        ]

        for s in sorted(report.strategies, key=lambda x: x.total_return_pct, reverse=True):
            pf = f"{s.profit_factor:.2f}" if s.profit_factor < 1000 else "inf"
            lines.append(
                f"| {s.strategy} | {s.total_return_pct:+.3f}% | "
                f"{s.equity:,.0f} | {s.realized_pnl:+,.0f} | "
                f"{s.trade_count} | {s.win_rate:.0%} | {pf} | "
                f"{s.sharpe_ratio:.2f} |"
            )

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
            "strategies": [
                {
                    "strategy": s.strategy,
                    "return_pct": s.total_return_pct,
                    "realized_pnl": s.realized_pnl,
                    "trade_count": s.trade_count,
                    "win_rate": s.win_rate,
                    "sharpe": s.sharpe_ratio,
                }
                for s in report.strategies
            ],
        }
        json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")

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
    def _approx_sharpe_from_return(return_pct: float, period: str) -> float:
        """Approximate annualized Sharpe from period return.

        Assumes volatility is proportional to return magnitude (rough estimate).
        """
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
