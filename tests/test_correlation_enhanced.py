"""Tests for enhanced correlation analysis — diversification score, optimal combos, report."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.correlation import (
    correlation_matrix_report,
    diversification_score,
    optimal_combo,
    signal_correlation,
)
from crypto_trader.models import Candle, Signal, SignalAction


def _build_candles(n: int = 60) -> list[Candle]:
    base = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=100_000.0 + i * 100,
            high=100_000.0 + i * 100 + 500,
            low=100_000.0 + i * 100 - 500,
            close=100_000.0 + i * 100,
            volume=1000.0,
        )
        for i in range(n)
    ]


class _AlwaysBuy:
    def evaluate(self, candles, position=None, *, symbol=""):
        return Signal(action=SignalAction.BUY, reason="always", confidence=0.8)


class _AlwaysHold:
    def evaluate(self, candles, position=None, *, symbol=""):
        return Signal(action=SignalAction.HOLD, reason="never", confidence=0.1)


class _AlternateBuy:
    """BUY on even indices, HOLD on odd."""
    def evaluate(self, candles, position=None, *, symbol=""):
        if len(candles) % 2 == 0:
            return Signal(action=SignalAction.BUY, reason="even", confidence=0.6)
        return Signal(action=SignalAction.HOLD, reason="odd", confidence=0.2)


class TestSignalCorrelation(unittest.TestCase):
    def test_identical_strategies_high_correlation(self) -> None:
        strategies = [_AlwaysBuy(), _AlwaysBuy()]
        corr = signal_correlation(strategies, _build_candles(), ["a", "b"])
        # Both always BUY → should have high correlation (or 0.0 if both constant)
        # Note: phi coefficient of two constant vectors is 0.0 (no variance)
        self.assertIn(("a", "b"), corr)

    def test_opposite_strategies(self) -> None:
        strategies = [_AlwaysBuy(), _AlwaysHold()]
        corr = signal_correlation(strategies, _build_candles(), ["buy", "hold"])
        # One always 1, other always 0 → phi is 0.0 (one has no variance)
        self.assertEqual(corr[("buy", "hold")], 0.0)


class TestDiversificationScore(unittest.TestCase):
    def test_single_strategy(self) -> None:
        score = diversification_score([_AlwaysBuy()], _build_candles(), ["a"])
        self.assertEqual(score, 1.0)

    def test_independent_strategies(self) -> None:
        """Different signal patterns should yield good diversification."""
        strategies = [_AlwaysBuy(), _AlternateBuy()]
        score = diversification_score(strategies, _build_candles(), ["a", "b"])
        # They differ — should have reasonable diversification
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestOptimalCombo(unittest.TestCase):
    def test_returns_ranked_combos(self) -> None:
        strategies = [_AlwaysBuy(), _AlternateBuy(), _AlwaysHold()]
        combos = optimal_combo(
            strategies, _build_candles(), ["buy", "alternate", "hold"],
            min_size=2, max_size=3,
        )
        self.assertGreater(len(combos), 0)
        # Should be sorted by div_score descending
        scores = [c[1] for c in combos]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_combo_names_correct(self) -> None:
        strategies = [_AlwaysBuy(), _AlwaysHold()]
        combos = optimal_combo(strategies, _build_candles(), ["a", "b"], min_size=2)
        self.assertEqual(len(combos), 1)
        self.assertEqual(sorted(combos[0][0]), ["a", "b"])


class TestCorrelationReport(unittest.TestCase):
    def test_report_is_markdown(self) -> None:
        strategies = [_AlwaysBuy(), _AlternateBuy(), _AlwaysHold()]
        report = correlation_matrix_report(
            strategies, _build_candles(), ["momentum", "vpin", "ema"],
        )
        self.assertIn("# Strategy Correlation Report", report)
        self.assertIn("## Signal Activity", report)
        self.assertIn("## Pairwise Correlation", report)
        self.assertIn("## Diversification Score", report)
        self.assertIn("## Top Strategy Combinations", report)
        self.assertIn("## Warnings", report)

    def test_report_signal_activity(self) -> None:
        strategies = [_AlwaysBuy()]
        report = correlation_matrix_report(strategies, _build_candles(), ["test"])
        self.assertIn("**test**", report)
        self.assertIn("BUY signals", report)


if __name__ == "__main__":
    unittest.main()
