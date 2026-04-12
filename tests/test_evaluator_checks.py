"""Tests for evaluator check plugins."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.checks.backtest_quality import BacktestQualityCheck
from crypto_trader.evaluator.models import EvalContext, Grade


def _make_ctx(history_tail: str = "") -> EvalContext:
    return EvalContext(
        backtest_history_tail=history_tail,
        daemon_strategies=[],
        daemon_config_path=None,
        research_state=None,
        market_scan_state=None,
        checkpoint=None,
        journal_trades=[],
        prev_report=None,
    )


class TestBacktestQualityCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.check = BacktestQualityCheck()

    def test_name(self) -> None:
        self.assertEqual(self.check.name, "backtest_quality")

    def test_skip_when_no_data(self) -> None:
        result = self.check.run(_make_ctx(""))
        self.assertEqual(result.grade, Grade.SKIP)

    def test_pass_sufficient_trades_and_sharpe(self) -> None:
        lines = [
            "| 2026-04-10 | c250 | bb_squeeze | n=86 | WR=55% | Sharpe=+7.15 | OOS효율=0.65 | 유효 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertEqual(result.grade, Grade.PASS)
        self.assertGreater(result.score, 0.7)

    def test_warn_low_n_trades(self) -> None:
        lines = [
            "| 2026-04-10 | c251 | momentum | n=20 | WR=60% | Sharpe=+5.0 | OOS효율=0.50 | 통계부족 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertIn(result.grade, (Grade.WARN, Grade.FAIL))

    def test_fail_very_low_n_trades(self) -> None:
        lines = [
            "| 2026-04-10 | c252 | vpin | n=5 | WR=80% | Sharpe=+20.0 | OOS효율=0.40 | 부족 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertEqual(result.grade, Grade.FAIL)

    def test_warn_low_oos_efficiency(self) -> None:
        lines = [
            "| 2026-04-10 | c253 | stealth | n=50 | WR=45% | Sharpe=+3.0 | OOS효율=0.20 | 낮음 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertIn(result.grade, (Grade.WARN, Grade.FAIL))

    def test_multiple_entries_uses_worst(self) -> None:
        lines = [
            "| 2026-04-10 | c250 | bb_squeeze | n=86 | WR=55% | Sharpe=+7.15 | OOS효율=0.65 | 유효 |",
            "| 2026-04-10 | c251 | momentum | n=5 | WR=60% | Sharpe=+5.0 | OOS효율=0.50 | 부족 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertNotEqual(result.grade, Grade.PASS)


if __name__ == "__main__":
    unittest.main()
