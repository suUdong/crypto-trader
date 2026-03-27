"""Tests for Session #12 Wave 20: CMF indicator, Keltner parity across strategies."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.indicators import chaikin_money_flow


def _candles(
    closes: list[float],
    volume: float = 1000.0,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=t + timedelta(hours=i),
            open=c,
            high=highs[i] if highs else c * 1.01,
            low=lows[i] if lows else c * 0.99,
            close=c,
            volume=volume,
        )
        for i, c in enumerate(closes)
    ]


# ---------- CMF indicator ----------


class TestChaikinMoneyFlow(unittest.TestCase):
    def test_all_closes_at_high(self) -> None:
        """When close == high, CMF should be positive (max buying pressure)."""
        n = 25
        highs = [100.0] * n
        lows = [98.0] * n
        closes = [100.0] * n  # close at high
        volumes = [1000.0] * n
        cmf = chaikin_money_flow(highs, lows, closes, volumes, period=20)
        self.assertGreater(cmf, 0.0)
        self.assertAlmostEqual(cmf, 1.0, places=2)

    def test_all_closes_at_low(self) -> None:
        """When close == low, CMF should be negative (max selling pressure)."""
        n = 25
        highs = [100.0] * n
        lows = [98.0] * n
        closes = [98.0] * n  # close at low
        volumes = [1000.0] * n
        cmf = chaikin_money_flow(highs, lows, closes, volumes, period=20)
        self.assertLess(cmf, 0.0)
        self.assertAlmostEqual(cmf, -1.0, places=2)

    def test_closes_at_midpoint(self) -> None:
        """When close is at midpoint of high-low range, CMF should be ~0."""
        n = 25
        highs = [102.0] * n
        lows = [98.0] * n
        closes = [100.0] * n  # midpoint
        volumes = [1000.0] * n
        cmf = chaikin_money_flow(highs, lows, closes, volumes, period=20)
        self.assertAlmostEqual(cmf, 0.0, places=5)

    def test_insufficient_data(self) -> None:
        with self.assertRaises(ValueError):
            chaikin_money_flow([100.0] * 5, [99.0] * 5, [100.0] * 5, [1000.0] * 5, period=20)

    def test_zero_range_bars(self) -> None:
        """When high == low (zero range), MF multiplier should be 0."""
        n = 25
        highs = [100.0] * n
        lows = [100.0] * n
        closes = [100.0] * n
        volumes = [1000.0] * n
        cmf = chaikin_money_flow(highs, lows, closes, volumes, period=20)
        self.assertAlmostEqual(cmf, 0.0, places=5)

    def test_cmf_range(self) -> None:
        """CMF should always be in [-1, 1]."""
        import random

        random.seed(42)
        n = 30
        for _ in range(10):
            base = [100.0 + random.uniform(-5, 5) for _ in range(n)]
            highs = [b + random.uniform(0.5, 3.0) for b in base]
            lows = [b - random.uniform(0.5, 3.0) for b in base]
            closes = [
                low + random.uniform(0, high - low)
                for high, low in zip(highs, lows, strict=False)
            ]
            volumes = [random.uniform(100, 5000) for _ in range(n)]
            cmf = chaikin_money_flow(highs, lows, closes, volumes, period=20)
            self.assertGreaterEqual(cmf, -1.0 - 1e-9)
            self.assertLessEqual(cmf, 1.0 + 1e-9)


# ---------- Keltner in MeanRev ----------


class TestMeanRevKeltner(unittest.TestCase):
    def test_keltner_lower_in_indicators(self) -> None:
        from crypto_trader.strategy.mean_reversion import MeanReversionStrategy

        cfg = StrategyConfig()
        strategy = MeanReversionStrategy(cfg)
        # Create enough candles for Keltner (need 21+)
        closes = [100.0 + i * 0.1 for i in range(50)]
        candles = _candles(closes)
        signal = strategy.evaluate(candles)
        self.assertIn("keltner_lower", signal.indicators)


# ---------- Keltner in VolBreakout ----------


class TestVolBreakoutKeltner(unittest.TestCase):
    def test_keltner_upper_in_indicators(self) -> None:
        from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy

        cfg = StrategyConfig()
        strategy = VolatilityBreakoutStrategy(cfg)
        closes = [100.0 + i * 0.1 for i in range(50)]
        candles = _candles(closes)
        signal = strategy.evaluate(candles)
        self.assertIn("keltner_upper", signal.indicators)


# ---------- Keltner in EMACross ----------


class TestEMACrossKeltner(unittest.TestCase):
    def test_keltner_upper_in_indicators(self) -> None:
        from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy

        cfg = StrategyConfig()
        strategy = EMACrossoverStrategy(cfg)
        closes = [100.0 + i * 0.1 for i in range(50)]
        candles = _candles(closes)
        signal = strategy.evaluate(candles)
        self.assertIn("keltner_upper", signal.indicators)


if __name__ == "__main__":
    unittest.main()
