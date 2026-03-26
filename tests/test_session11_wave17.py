"""Tests for Session #11 Wave 17: OBV indicator and integration."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.indicators import obv_slope, on_balance_volume
from crypto_trader.strategy.momentum import MomentumStrategy


def _candles(closes: list[float], volumes: list[float] | None = None) -> list[Candle]:
    t = datetime(2025, 1, 1)
    vols = volumes or [1000.0] * len(closes)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=vols[i])
        for i, c in enumerate(closes)
    ]


# ---------- OBV Indicator ----------

class TestOBV(unittest.TestCase):
    def test_obv_rising_on_up_moves(self) -> None:
        """OBV should rise when price goes up."""
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        volumes = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]
        obv = on_balance_volume(closes, volumes)
        self.assertEqual(len(obv), 5)
        # All up moves: OBV should be strictly increasing
        for i in range(1, len(obv)):
            self.assertGreater(obv[i], obv[i - 1])

    def test_obv_falling_on_down_moves(self) -> None:
        """OBV should fall when price goes down."""
        closes = [100.0, 99.0, 98.0, 97.0]
        volumes = [1000.0, 1000.0, 1000.0, 1000.0]
        obv = on_balance_volume(closes, volumes)
        for i in range(1, len(obv)):
            self.assertLess(obv[i], obv[i - 1])

    def test_obv_flat_on_no_change(self) -> None:
        """OBV should be flat when price doesn't change."""
        closes = [100.0, 100.0, 100.0]
        volumes = [1000.0, 1000.0, 1000.0]
        obv = on_balance_volume(closes, volumes)
        self.assertEqual(obv[0], obv[1])
        self.assertEqual(obv[1], obv[2])

    def test_obv_length_matches_input(self) -> None:
        closes = [100.0 + i for i in range(20)]
        volumes = [1000.0] * 20
        obv = on_balance_volume(closes, volumes)
        self.assertEqual(len(obv), 20)

    def test_obv_mismatched_lengths(self) -> None:
        with self.assertRaises(ValueError):
            on_balance_volume([100.0, 101.0], [1000.0])

    def test_obv_empty(self) -> None:
        self.assertEqual(on_balance_volume([], []), [])


# ---------- OBV Slope ----------

class TestOBVSlope(unittest.TestCase):
    def test_positive_slope_on_accumulation(self) -> None:
        """Rising prices = positive OBV slope (accumulation)."""
        closes = [100.0 + i * 1.0 for i in range(30)]
        volumes = [1000.0] * 30
        slope = obv_slope(closes, volumes, lookback=10)
        self.assertGreater(slope, 0)

    def test_negative_slope_on_distribution(self) -> None:
        """Falling prices = negative OBV slope (distribution)."""
        closes = [200.0 - i * 1.0 for i in range(30)]
        volumes = [1000.0] * 30
        slope = obv_slope(closes, volumes, lookback=10)
        self.assertLess(slope, 0)

    def test_zero_slope_on_flat(self) -> None:
        """Flat prices = zero OBV slope."""
        closes = [100.0] * 30
        volumes = [1000.0] * 30
        slope = obv_slope(closes, volumes, lookback=10)
        self.assertAlmostEqual(slope, 0.0)

    def test_insufficient_data(self) -> None:
        with self.assertRaises(ValueError):
            obv_slope([100.0] * 5, [1000.0] * 5, lookback=10)


# ---------- OBV in Strategies ----------

class TestOBVInStrategies(unittest.TestCase):
    def test_obv_slope_in_composite_indicators(self) -> None:
        """CompositeStrategy should include obv_slope in indicators."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("obv_slope", signal.indicators)

    def test_obv_slope_in_momentum_indicators(self) -> None:
        """MomentumStrategy should include obv_slope in indicators."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = MomentumStrategy(
            StrategyConfig(momentum_lookback=3, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("obv_slope", signal.indicators)


if __name__ == "__main__":
    unittest.main()
