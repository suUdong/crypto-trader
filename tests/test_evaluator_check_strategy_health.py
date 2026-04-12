"""Tests for strategy_health check plugin."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.checks.strategy_health import StrategyHealthCheck
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


class TestStrategyHealthCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.check = StrategyHealthCheck()

    def test_name(self) -> None:
        self.assertEqual(self.check.name, "strategy_health")

    def test_skip_when_no_checkpoint(self) -> None:
        ctx = _make_ctx()
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.SKIP)

    def test_pass_healthy_wallets(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {
                    "equity": 1_100_000,
                    "initial_capital": 1_000_000,
                    "realized_pnl": 100_000,
                    "trade_count": 15,
                    "strategy_type": "vpin",
                },
            },
        }
        ctx.daemon_strategies = ["vpin"]
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.PASS)

    def test_warn_high_drawdown(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {
                    "equity": 850_000,
                    "initial_capital": 1_000_000,
                    "realized_pnl": -150_000,
                    "trade_count": 20,
                    "strategy_type": "momentum",
                },
            },
        }
        ctx.daemon_strategies = ["momentum"]
        result = self.check.run(ctx)
        self.assertIn(result.grade, (Grade.WARN, Grade.FAIL))

    def test_fail_extreme_drawdown(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {
                    "equity": 700_000,
                    "initial_capital": 1_000_000,
                    "realized_pnl": -300_000,
                    "trade_count": 30,
                    "strategy_type": "stealth",
                },
            },
        }
        ctx.daemon_strategies = ["stealth"]
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.FAIL)

    def test_warn_idle_strategy(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {
                    "equity": 1_000_000,
                    "initial_capital": 1_000_000,
                    "realized_pnl": 0,
                    "trade_count": 0,
                    "strategy_type": "vpin",
                },
            },
        }
        ctx.daemon_strategies = ["vpin"]
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.WARN)


if __name__ == "__main__":
    unittest.main()
