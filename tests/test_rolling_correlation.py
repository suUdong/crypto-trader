"""Tests for rolling_correlation indicator."""
from __future__ import annotations

import unittest

from crypto_trader.strategy.indicators import rolling_correlation


class RollingCorrelationTests(unittest.TestCase):
    def test_perfect_positive_correlation(self) -> None:
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertAlmostEqual(rolling_correlation(a, b, 5), 1.0, places=5)

    def test_perfect_negative_correlation(self) -> None:
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [50.0, 40.0, 30.0, 20.0, 10.0]
        self.assertAlmostEqual(rolling_correlation(a, b, 5), -1.0, places=5)

    def test_zero_correlation_constant_series(self) -> None:
        a = [5.0, 5.0, 5.0, 5.0]
        b = [1.0, 2.0, 3.0, 4.0]
        # constant series has std=0, should return 0
        self.assertAlmostEqual(rolling_correlation(a, b, 4), 0.0)

    def test_uses_last_n_values(self) -> None:
        # First 3 values are noise, last 5 are perfectly correlated
        a = [99.0, 99.0, 99.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        b = [0.0, 0.0, 0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertAlmostEqual(rolling_correlation(a, b, 5), 1.0, places=5)

    def test_insufficient_data_raises(self) -> None:
        with self.assertRaises(ValueError):
            rolling_correlation([1.0, 2.0], [3.0, 4.0], 5)

    def test_moderate_correlation(self) -> None:
        a = [1.0, 2.0, 1.5, 3.0, 2.5]
        b = [10.0, 15.0, 12.0, 20.0, 18.0]
        corr = rolling_correlation(a, b, 5)
        self.assertGreater(corr, 0.8)
        self.assertLess(corr, 1.0)
