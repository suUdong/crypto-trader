"""Tests for micro-live promotion criteria."""
from __future__ import annotations

import unittest

from crypto_trader.operator.promotion import MicroLiveCriteria


class MicroLiveCriteriaTests(unittest.TestCase):
    def test_all_criteria_met(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertTrue(ready)
        self.assertIn("All micro-live criteria met", reasons[0])

    def test_insufficient_paper_days(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=3,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("7d" in r for r in reasons))

    def test_low_win_rate(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.30,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("Win rate" in r for r in reasons))

    def test_high_drawdown(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.15,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("MDD" in r for r in reasons))

    def test_insufficient_trades(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=5,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("trades" in r for r in reasons))

    def test_low_profit_factor(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=0.9,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("Profit factor" in r for r in reasons))

    def test_too_few_positive_strategies(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=1,
        )
        self.assertFalse(ready)
        self.assertTrue(any("profitable strategies" in r for r in reasons))

    def test_multiple_failures(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=1,
            total_trades=2,
            win_rate=0.2,
            max_drawdown=0.20,
            profit_factor=0.5,
            positive_strategies=0,
        )
        self.assertFalse(ready)
        self.assertGreater(len(reasons), 3)
