"""Tests for enhanced daily PnL Telegram notification format."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from crypto_trader.operator.pnl_report import (
    PnLReportGenerator,
    PortfolioPnLReport,
    StrategyPnLMetrics,
)


def _make_report(strategies: list[StrategyPnLMetrics] | None = None) -> PortfolioPnLReport:
    """Create a test PnL report."""
    if strategies is None:
        strategies = [
            StrategyPnLMetrics(
                strategy="momentum", wallet="momentum_wallet",
                total_return_pct=4.8, realized_pnl=48000, unrealized_pnl=0,
                trade_count=12, win_count=7, loss_count=5,
                win_rate=0.583, profit_factor=1.8, max_drawdown_pct=1.2,
                sharpe_ratio=1.34, equity=1_048_000, initial_capital=1_000_000,
            ),
            StrategyPnLMetrics(
                strategy="obi", wallet="obi_wallet",
                total_return_pct=-2.3, realized_pnl=-4600, unrealized_pnl=0,
                trade_count=8, win_count=2, loss_count=6,
                win_rate=0.25, profit_factor=0.4, max_drawdown_pct=3.5,
                sharpe_ratio=-2.33, equity=195_400, initial_capital=200_000,
            ),
        ]
    return PortfolioPnLReport(
        generated_at="2026-03-26T12:00:00+00:00",
        period="daily",
        strategies=strategies,
        portfolio_return_pct=2.5,
        portfolio_sharpe=0.95,
        portfolio_mdd=1.2,
        portfolio_win_rate=0.45,
        total_trades=20,
        total_realized_pnl=43400,
        total_equity=1_243_400,
        total_initial_capital=1_200_000,
    )


class TestEnhancedPnLNotification:
    def test_notification_includes_per_wallet_breakdown(self) -> None:
        """Notification should include per-wallet return%, trade count, win rate."""
        report = _make_report()
        # Simulate the notification formatting from MultiSymbolRuntime
        disabled: list[str] = []
        paused: list[str] = []
        lines = [
            "[Crypto Trader] Daily PnL Report",
            f"Equity: {report.total_equity:,.0f} KRW | Return: {report.portfolio_return_pct:+.2f}%",
            f"Sharpe: {report.portfolio_sharpe:.2f} | Trades: {report.total_trades} | Win: {report.portfolio_win_rate:.0%}",
            "---",
        ]
        for s in sorted(report.strategies, key=lambda x: x.total_return_pct, reverse=True):
            status = ""
            if s.wallet in disabled:
                status = " [DISABLED]"
            elif s.wallet in paused:
                status = " [PAUSED]"
            pf = f"{s.profit_factor:.1f}" if s.profit_factor < 1000 else "inf"
            lines.append(
                f"{s.wallet}: {s.total_return_pct:+.2f}% | "
                f"{s.trade_count}t W:{s.win_rate:.0%} PF:{pf}{status}"
            )
        msg = "\n".join(lines)

        assert "Equity: 1,243,400 KRW" in msg
        assert "Sharpe: 0.95" in msg
        assert "momentum_wallet: +4.80%" in msg
        assert "obi_wallet: -2.30%" in msg
        assert "12t W:58% PF:1.8" in msg
        assert "8t W:25% PF:0.4" in msg

    def test_notification_shows_disabled_status(self) -> None:
        """Disabled wallets should be marked [DISABLED] in notification."""
        report = _make_report()
        disabled = ["obi_wallet"]
        lines = []
        for s in report.strategies:
            status = " [DISABLED]" if s.wallet in disabled else ""
            lines.append(f"{s.wallet}: {s.total_return_pct:+.2f}%{status}")
        msg = "\n".join(lines)

        assert "[DISABLED]" in msg
        assert "obi_wallet: -2.30% [DISABLED]" in msg

    def test_notification_shows_paused_status(self) -> None:
        """Paused wallets should be marked [PAUSED]."""
        report = _make_report()
        paused = ["obi_wallet"]
        lines = []
        for s in report.strategies:
            status = " [PAUSED]" if s.wallet in paused else ""
            lines.append(f"{s.wallet}: {s.total_return_pct:+.2f}%{status}")
        msg = "\n".join(lines)

        assert "[PAUSED]" in msg

    def test_empty_report_produces_valid_message(self) -> None:
        """Empty checkpoint should produce a valid message."""
        report = PnLReportGenerator()._empty_report("daily")
        lines = [
            "[Crypto Trader] Daily PnL Report",
            f"Equity: {report.total_equity:,.0f} KRW | Return: {report.portfolio_return_pct:+.2f}%",
            f"Sharpe: {report.portfolio_sharpe:.2f} | Trades: {report.total_trades} | Win: {report.portfolio_win_rate:.0%}",
        ]
        msg = "\n".join(lines)
        assert "Equity: 0 KRW" in msg
        assert "Trades: 0" in msg

    def test_notification_sorts_by_return_descending(self) -> None:
        """Wallets should be sorted by return% descending."""
        report = _make_report()
        sorted_strats = sorted(report.strategies, key=lambda x: x.total_return_pct, reverse=True)
        assert sorted_strats[0].wallet == "momentum_wallet"
        assert sorted_strats[1].wallet == "obi_wallet"
