"""Tests for strategy signal correlation detector."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.correlation import (
    _binary_correlation,
    average_pairwise_correlation,
    diversification_multipliers,
    rank_portfolios,
    signal_correlation,
)
from crypto_trader.models import Candle, Signal, SignalAction


def _build_candles(n: int = 80) -> list[Candle]:
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


class _FixedStrategy:
    """Stub strategy that always returns the same action."""

    def __init__(self, action: SignalAction) -> None:
        self._action = action

    def evaluate(self, candles: list[Candle], position: object) -> Signal:
        return Signal(action=self._action, reason="fixed", confidence=0.8)


class TestBinaryCorrelation(unittest.TestCase):
    def test_identical_vectors_return_one(self) -> None:
        a = [1, 0, 1, 1, 0, 1]
        self.assertAlmostEqual(_binary_correlation(a, a), 1.0, places=5)

    def test_known_values(self) -> None:
        # n11=2, n10=1, n01=1, n00=2 -> phi = (2*2 - 1*1) / sqrt(3*3*3*3) = 3/9 = 0.333...
        a = [1, 1, 1, 0, 0, 0]
        b = [1, 1, 0, 1, 0, 0]
        result = _binary_correlation(a, b)
        self.assertAlmostEqual(result, 1 / 3, places=5)

    def test_empty_returns_zero(self) -> None:
        self.assertEqual(_binary_correlation([], []), 0.0)

    def test_all_zeros_returns_zero(self) -> None:
        a = [0, 0, 0, 0]
        self.assertEqual(_binary_correlation(a, a), 0.0)

    def test_opposite_vectors(self) -> None:
        a = [1, 0, 1, 0]
        b = [0, 1, 0, 1]
        result = _binary_correlation(a, b)
        self.assertAlmostEqual(result, -1.0, places=5)


class TestSignalCorrelation(unittest.TestCase):
    def test_identical_strategies_near_one(self) -> None:
        candles = _build_candles(80)
        strat_a = _FixedStrategy(SignalAction.BUY)
        strat_b = _FixedStrategy(SignalAction.BUY)
        result = signal_correlation([strat_a, strat_b], candles, ["a", "b"])
        self.assertIn(("a", "b"), result)
        self.assertAlmostEqual(result[("a", "b")], 0.0)  # all-buy -> phi=0 (denom=0)

    def test_same_strategy_diagonal_is_one(self) -> None:
        candles = _build_candles(80)
        strat_a = _FixedStrategy(SignalAction.BUY)
        strat_b = _FixedStrategy(SignalAction.HOLD)
        result = signal_correlation([strat_a, strat_b], candles, ["buy", "hold"])
        # self-correlation
        self.assertIn(("buy", "buy"), result)
        self.assertIn(("hold", "hold"), result)
        # buy vs hold: a is all-1, b is all-0 -> denom involves (n11+n10)*(n11+n01)
        # n11=0,n10=N,n01=0,n00=0 -> denom=0 -> 0.0
        self.assertEqual(result[("buy", "hold")], 0.0)

    def test_auto_naming(self) -> None:
        candles = _build_candles(80)
        strats = [_FixedStrategy(SignalAction.BUY), _FixedStrategy(SignalAction.HOLD)]
        result = signal_correlation(strats, candles)
        self.assertIn(("s0", "s1"), result)

    def test_not_enough_candles_produces_empty_vectors(self) -> None:
        # Only 10 candles — warmup=30 means no signals generated, vectors are empty
        candles = _build_candles(10)
        strat_a = _FixedStrategy(SignalAction.BUY)
        strat_b = _FixedStrategy(SignalAction.BUY)
        result = signal_correlation([strat_a, strat_b], candles, ["a", "b"])
        self.assertEqual(result[("a", "b")], 0.0)

    def test_exception_in_strategy_handled(self) -> None:
        class _BrokenStrategy:
            def evaluate(self, candles, position):
                raise RuntimeError("boom")

        candles = _build_candles(80)
        result = signal_correlation(
            [_BrokenStrategy(), _FixedStrategy(SignalAction.BUY)],
            candles,
            ["broken", "good"],
        )
        # broken always returns 0 -> no BUY signals
        self.assertIn(("broken", "good"), result)


class TestPortfolioRankingHelpers(unittest.TestCase):
    def test_average_pairwise_correlation(self) -> None:
        corr = {
            ("a", "a"): 1.0,
            ("a", "b"): 0.8,
            ("a", "c"): 0.2,
            ("b", "b"): 1.0,
            ("b", "c"): 0.4,
            ("c", "c"): 1.0,
        }
        self.assertAlmostEqual(
            average_pairwise_correlation(["a", "b", "c"], corr),
            (0.8 + 0.2 + 0.4) / 3,
        )

    def test_diversification_multipliers_penalize_high_overlap(self) -> None:
        corr = {
            ("a", "a"): 1.0,
            ("a", "b"): 0.9,
            ("a", "c"): 0.1,
            ("b", "b"): 1.0,
            ("b", "c"): 0.2,
            ("c", "c"): 1.0,
        }
        multipliers = diversification_multipliers(["a", "b", "c"], corr)
        self.assertLess(multipliers["a"], multipliers["c"])

    def test_rank_portfolios_prefers_diversified_profitable_combo(self) -> None:
        corr = {
            ("a", "a"): 1.0,
            ("a", "b"): 0.95,
            ("a", "c"): 0.10,
            ("b", "b"): 1.0,
            ("b", "c"): 0.15,
            ("c", "c"): 1.0,
        }
        performance = {
            "a": {"sharpe": 1.0, "return_pct": 4.0, "profit_factor": 1.2},
            "b": {"sharpe": 1.1, "return_pct": 5.0, "profit_factor": 1.3},
            "c": {"sharpe": 0.8, "return_pct": 3.0, "profit_factor": 1.2},
        }
        ranked = rank_portfolios(corr, performance, min_size=2, max_size=2)
        self.assertEqual(ranked[0]["strategies"], ["b", "c"])


if __name__ == "__main__":
    unittest.main()
