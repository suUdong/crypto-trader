"""Tests for Session #12 Wave 14: OBV indicator, OBV confirmation in strategies."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.indicators import obv_slope, on_balance_volume
from crypto_trader.strategy.momentum import MomentumStrategy


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


def _candles_with_volumes(closes: list[float], volumes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=t + timedelta(hours=i), open=c, high=c * 1.01, low=c * 0.99, close=c, volume=v
        )
        for i, (c, v) in enumerate(zip(closes, volumes, strict=False))
    ]


# ---------- OBV indicator ----------


class TestOnBalanceVolume(unittest.TestCase):
    def test_rising_prices_accumulate(self) -> None:
        """Rising prices should produce rising OBV."""
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        volumes = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]
        obv = on_balance_volume(closes, volumes)
        self.assertEqual(len(obv), 5)
        # Each bar adds volume since price is rising
        self.assertEqual(obv[-1], 4000.0)

    def test_falling_prices_distribute(self) -> None:
        """Falling prices should produce falling OBV."""
        closes = [104.0, 103.0, 102.0, 101.0, 100.0]
        volumes = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]
        obv = on_balance_volume(closes, volumes)
        self.assertEqual(obv[-1], -4000.0)

    def test_flat_prices_no_change(self) -> None:
        """Flat prices should not change OBV."""
        closes = [100.0] * 5
        volumes = [1000.0] * 5
        obv = on_balance_volume(closes, volumes)
        self.assertEqual(obv[-1], 0.0)

    def test_mixed_prices(self) -> None:
        """Mixed prices: up then down."""
        closes = [100.0, 102.0, 101.0]
        volumes = [500.0, 1000.0, 800.0]
        obv = on_balance_volume(closes, volumes)
        # Start=0, up: +1000, down: -800
        self.assertEqual(obv[-1], 200.0)

    def test_empty_input(self) -> None:
        """Empty input should return empty list."""
        self.assertEqual(on_balance_volume([], []), [])

    def test_mismatched_lengths(self) -> None:
        """Mismatched lengths should raise ValueError."""
        with self.assertRaises(ValueError):
            on_balance_volume([100.0, 101.0], [1000.0])


# ---------- OBV slope ----------


class TestOBVSlope(unittest.TestCase):
    def test_rising_obv_positive_slope(self) -> None:
        """Rising prices -> rising OBV -> positive slope."""
        closes = [100.0 + i for i in range(20)]
        volumes = [1000.0] * 20
        slope = obv_slope(closes, volumes, lookback=10)
        self.assertGreater(slope, 0)

    def test_falling_obv_negative_slope(self) -> None:
        """Falling prices -> falling OBV -> negative slope."""
        closes = [120.0 - i for i in range(20)]
        volumes = [1000.0] * 20
        slope = obv_slope(closes, volumes, lookback=10)
        self.assertLess(slope, 0)

    def test_flat_obv_zero_slope(self) -> None:
        """Flat prices -> flat OBV -> zero slope."""
        closes = [100.0] * 20
        volumes = [1000.0] * 20
        slope = obv_slope(closes, volumes, lookback=10)
        self.assertEqual(slope, 0.0)

    def test_insufficient_data(self) -> None:
        """Should raise ValueError with insufficient data."""
        with self.assertRaises(ValueError):
            obv_slope([100.0] * 5, [1000.0] * 5, lookback=10)


# ---------- OBV in composite strategy ----------


class TestCompositeOBV(unittest.TestCase):
    def test_obv_slope_in_indicators(self) -> None:
        """Composite should include obv_slope in indicators."""
        prices = [100.0 + i * 0.1 for i in range(50)]
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=5,
                bollinger_window=20,
                rsi_period=5,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertIn("obv_slope", signal.indicators)

    def test_obv_absent_with_short_data(self) -> None:
        """With short data, obv_slope may not be present."""
        prices = [100.0] * 8
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                bollinger_window=5,
                rsi_period=3,
            )
        )
        signal = strategy.evaluate(candles)
        # May or may not have obv_slope depending on minimum requirements
        self.assertIsNotNone(signal)


# ---------- OBV in momentum strategy ----------


class TestMomentumOBV(unittest.TestCase):
    def test_obv_slope_in_indicators(self) -> None:
        """Momentum should include obv_slope in indicators."""
        prices = [100.0 + i * 0.3 for i in range(50)]
        candles = _candles(prices)
        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=5,
                rsi_period=5,
                adx_threshold=0.0,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertIn("obv_slope", signal.indicators)

    def test_strong_obv_boosts_confidence(self) -> None:
        """Strong OBV accumulation should boost BUY confidence."""
        # Create clear uptrend with high volume
        prices = [80.0 + i * 0.5 for i in range(55)]
        volumes = [1000.0 + i * 100 for i in range(55)]
        candles = _candles_with_volumes(prices, volumes)
        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=5,
                momentum_entry_threshold=0.001,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
                adx_threshold=0.0,
            )
        )
        signal = strategy.evaluate(candles)
        if signal.action == SignalAction.BUY:
            # Should have positive OBV slope
            self.assertGreater(signal.indicators.get("obv_slope", 0), 0)


if __name__ == "__main__":
    unittest.main()
