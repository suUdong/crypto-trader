"""Tests for portfolio_risk check plugin."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.checks.portfolio_risk import PortfolioRiskCheck
from crypto_trader.evaluator.models import EvalContext, Grade


def _make_ctx() -> EvalContext:
    return EvalContext(
        backtest_history_tail="",
        daemon_strategies=[],
        daemon_config_path=None,
        research_state=None,
        market_scan_state=None,
        checkpoint=None,
        journal_trades=[],
        prev_report=None,
    )


class TestPortfolioRiskCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.check = PortfolioRiskCheck()

    def test_name(self) -> None:
        self.assertEqual(self.check.name, "portfolio_risk")

    def test_skip_when_no_checkpoint(self) -> None:
        result = self.check.run(_make_ctx())
        self.assertEqual(result.grade, Grade.SKIP)

    def test_pass_diversified(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {"equity": 300_000, "strategy_type": "vpin"},
                "w2": {"equity": 300_000, "strategy_type": "momentum"},
                "w3": {"equity": 400_000, "strategy_type": "stealth_3gate"},
            },
        }
        ctx.daemon_strategies = ["vpin", "momentum", "stealth_3gate"]
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.PASS)

    def test_warn_concentrated(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {"equity": 900_000, "strategy_type": "vpin"},
                "w2": {"equity": 100_000, "strategy_type": "momentum"},
            },
        }
        ctx.daemon_strategies = ["vpin", "momentum"]
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.WARN)

    def test_warn_single_strategy(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {"equity": 1_000_000, "strategy_type": "vpin"},
            },
        }
        ctx.daemon_strategies = ["vpin"]
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.WARN)


if __name__ == "__main__":
    unittest.main()
