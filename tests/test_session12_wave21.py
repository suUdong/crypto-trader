"""Tests for Session #12 Wave 21: CMF integration across all strategies."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle


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


class TestCompositeCMF(unittest.TestCase):
    def test_cmf_in_indicators(self) -> None:
        from crypto_trader.strategy.composite import CompositeStrategy

        cfg = StrategyConfig()
        strategy = CompositeStrategy(cfg)
        closes = [100.0 + i * 0.1 for i in range(50)]
        signal = strategy.evaluate(_candles(closes))
        self.assertIn("cmf", signal.indicators)


class TestMomentumCMF(unittest.TestCase):
    def test_cmf_in_indicators(self) -> None:
        from crypto_trader.strategy.momentum import MomentumStrategy

        cfg = StrategyConfig()
        strategy = MomentumStrategy(cfg)
        closes = [100.0 + i * 0.1 for i in range(50)]
        signal = strategy.evaluate(_candles(closes))
        self.assertIn("cmf", signal.indicators)


class TestMeanRevCMF(unittest.TestCase):
    def test_cmf_in_indicators(self) -> None:
        from crypto_trader.strategy.mean_reversion import MeanReversionStrategy

        cfg = StrategyConfig()
        strategy = MeanReversionStrategy(cfg)
        closes = [100.0 + i * 0.1 for i in range(50)]
        signal = strategy.evaluate(_candles(closes))
        self.assertIn("cmf", signal.indicators)


class TestVolBreakoutCMF(unittest.TestCase):
    def test_cmf_in_indicators(self) -> None:
        from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy

        cfg = StrategyConfig()
        strategy = VolatilityBreakoutStrategy(cfg)
        closes = [100.0 + i * 0.1 for i in range(50)]
        signal = strategy.evaluate(_candles(closes))
        self.assertIn("cmf", signal.indicators)


class TestEMACrossCMF(unittest.TestCase):
    def test_cmf_in_indicators(self) -> None:
        from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy

        cfg = StrategyConfig()
        strategy = EMACrossoverStrategy(cfg)
        closes = [100.0 + i * 0.1 for i in range(50)]
        signal = strategy.evaluate(_candles(closes))
        self.assertIn("cmf", signal.indicators)


if __name__ == "__main__":
    unittest.main()
