"""Tests for Session #12 Wave 22: Williams %R indicator + strategy integration."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.indicators import williams_percent_r


def _candles(closes: list[float], volume: float = 1000.0) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=t + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=volume,
        )
        for i, c in enumerate(closes)
    ]


class TestWilliamsPercentR(unittest.TestCase):
    def test_close_at_high_is_zero(self) -> None:
        """Close at highest high = 0 (most overbought)."""
        highs = [100.0, 105.0, 103.0, 108.0, 106.0, 110.0] + [105.0] * 10
        lows = [95.0, 98.0, 97.0, 100.0, 99.0, 103.0] + [98.0] * 10
        closes = [97.0, 102.0, 100.0, 105.0, 103.0, 110.0] + [102.0] * 9 + [110.0]
        # Override: close[-1] = highest high in last 14
        highs_14 = highs[-14:]
        closes[-1] = max(highs_14)
        wpr = williams_percent_r(highs, lows, closes, period=14)
        self.assertAlmostEqual(wpr, 0.0, places=1)

    def test_close_at_low_is_minus100(self) -> None:
        """Close at lowest low = -100 (most oversold)."""
        n = 20
        highs = [110.0] * n
        lows = [90.0] * n
        closes = [100.0] * (n - 1) + [90.0]  # close at lowest low
        wpr = williams_percent_r(highs, lows, closes, period=14)
        self.assertAlmostEqual(wpr, -100.0, places=1)

    def test_range_bounds(self) -> None:
        """Williams %R should always be in [-100, 0]."""
        import random

        random.seed(42)
        for _ in range(20):
            n = 20
            base = [100 + random.uniform(-10, 10) for _ in range(n)]
            highs = [b + random.uniform(1, 5) for b in base]
            lows = [b - random.uniform(1, 5) for b in base]
            closes = [
                low + random.uniform(0, high - low)
                for high, low in zip(highs, lows, strict=False)
            ]
            wpr = williams_percent_r(highs, lows, closes, period=14)
            self.assertGreaterEqual(wpr, -100.0 - 1e-9)
            self.assertLessEqual(wpr, 0.0 + 1e-9)

    def test_insufficient_data(self) -> None:
        with self.assertRaises(ValueError):
            williams_percent_r([100.0] * 5, [99.0] * 5, [100.0] * 5, period=14)

    def test_flat_market(self) -> None:
        """When high == low == close, should return -50."""
        n = 20
        wpr = williams_percent_r([100.0] * n, [100.0] * n, [100.0] * n, period=14)
        self.assertAlmostEqual(wpr, -50.0, places=1)


class TestWilliamsRInStrategies(unittest.TestCase):
    def test_mean_rev_has_williams_r(self) -> None:
        from crypto_trader.strategy.mean_reversion import MeanReversionStrategy

        cfg = StrategyConfig()
        s = MeanReversionStrategy(cfg)
        signal = s.evaluate(_candles([100.0 + i * 0.1 for i in range(50)]))
        self.assertIn("williams_r", signal.indicators)

    def test_momentum_has_williams_r(self) -> None:
        from crypto_trader.strategy.momentum import MomentumStrategy

        cfg = StrategyConfig()
        s = MomentumStrategy(cfg)
        signal = s.evaluate(_candles([100.0 + i * 0.1 for i in range(50)]))
        self.assertIn("williams_r", signal.indicators)

    def test_ema_cross_has_williams_r(self) -> None:
        from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy

        cfg = StrategyConfig()
        s = EMACrossoverStrategy(cfg)
        signal = s.evaluate(_candles([100.0 + i * 0.1 for i in range(50)]))
        self.assertIn("williams_r", signal.indicators)


if __name__ == "__main__":
    unittest.main()
