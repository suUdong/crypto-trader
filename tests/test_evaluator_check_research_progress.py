"""Tests for research_progress check plugin."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.checks.research_progress import ResearchProgressCheck
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


class TestResearchProgressCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.check = ResearchProgressCheck()

    def test_name(self) -> None:
        self.assertEqual(self.check.name, "research_progress")

    def test_skip_when_no_state(self) -> None:
        result = self.check.run(_make_ctx())
        self.assertEqual(result.grade, Grade.SKIP)

    def test_pass_with_active_research(self) -> None:
        ctx = _make_ctx()
        ctx.research_state = {
            "cycle": 366,
            "done": ["c250_test", "c251_test", "c252_test"],
        }
        result = self.check.run(ctx)
        self.assertIn(result.grade, (Grade.PASS, Grade.WARN))
        self.assertIn("entries_completed", result.metrics)

    def test_pass_with_market_scan(self) -> None:
        ctx = _make_ctx()
        ctx.research_state = {"cycle": 10, "done": ["a"]}
        ctx.market_scan_state = {"current_cycle": 233}
        result = self.check.run(ctx)
        self.assertIn("market_scan_cycle", result.metrics)

    def test_weight_is_lower(self) -> None:
        self.assertLess(self.check.weight, 1.0)


if __name__ == "__main__":
    unittest.main()
