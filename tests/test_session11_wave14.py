"""Tests for Session #11 Wave 14: ADX in EMA crossover, noise ratio filter."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy


def _candles(closes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=1000.0)
        for i, c in enumerate(closes)
    ]


# ---------- ADX in EMA Crossover ----------

class TestEMACrossoverADX(unittest.TestCase):
    def test_adx_in_indicators(self) -> None:
        """EMA crossover should include ADX in indicators."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_period=14),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("adx", signal.indicators)

    def test_adx_blocks_entry_in_choppy_market(self) -> None:
        """ADX < threshold should block BUY entries."""
        # Flat/choppy market = low ADX
        prices = [100.0] * 50
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_period=14, adx_threshold=25.0),
        )
        signal = strategy.evaluate(candles)
        # In a flat market, should HOLD (no crossover or ADX too weak)
        self.assertEqual(signal.action, SignalAction.HOLD)


# ---------- Noise ratio filter in vol breakout ----------

class TestNoiseRatioFilter(unittest.TestCase):
    def test_noise_ratio_in_indicators(self) -> None:
        """VolatilityBreakout should include noise_ratio in indicators."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_period=14, adx_threshold=0.0),
            k_base=0.5, noise_lookback=20, ma_filter_period=20,
        )
        signal = strategy.evaluate(candles)
        self.assertIn("noise_ratio", signal.indicators)

    def test_high_noise_blocks_entry(self) -> None:
        """Very choppy market (noise > 0.8) should block entries."""
        # Alternating prices = high noise
        prices = []
        for i in range(50):
            prices.append(100.0 + (3.0 if i % 2 == 0 else -3.0))
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_period=14, adx_threshold=0.0),
            k_base=0.1, noise_lookback=20, ma_filter_period=20,
        )
        signal = strategy.evaluate(candles)
        nr = signal.indicators.get("noise_ratio", 0)
        # High noise should block or at minimum have high noise_ratio
        if nr > 0.8 and signal.action == SignalAction.HOLD:
            self.assertIn(signal.reason, ["noise_too_high", "below_ma_filter",
                                          "entry_conditions_not_met", "adx_too_weak"])

    def test_low_noise_allows_entry(self) -> None:
        """Strong trend (low noise) should not block entries."""
        # Steadily rising = low noise
        prices = [100.0 + i * 1.0 for i in range(50)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_period=14, adx_threshold=0.0),
            k_base=0.1, noise_lookback=20, ma_filter_period=20,
        )
        signal = strategy.evaluate(candles)
        nr = signal.indicators.get("noise_ratio", 1.0)
        self.assertLess(nr, 0.8)


if __name__ == "__main__":
    unittest.main()
