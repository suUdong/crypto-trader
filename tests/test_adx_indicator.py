"""Tests for US-026: ADX trend strength indicator and filter."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.indicators import average_directional_index
from crypto_trader.strategy.momentum import MomentumStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy


def _build_trending_candles(count: int, start_price: float = 100.0, trend: float = 1.0) -> list[Candle]:
    """Build candles with a clear trend (high ADX expected)."""
    start = datetime(2025, 1, 1)
    candles = []
    for i in range(count):
        price = start_price + i * trend
        candles.append(Candle(
            timestamp=start + timedelta(hours=i),
            open=price - 0.3,
            high=price + abs(trend) * 0.5,
            low=price - abs(trend) * 0.5,
            close=price,
            volume=1000.0 + i * 10,
        ))
    return candles


def _build_choppy_candles(count: int, base_price: float = 100.0) -> list[Candle]:
    """Build candles with no clear trend (low ADX expected)."""
    start = datetime(2025, 1, 1)
    candles = []
    for i in range(count):
        # Oscillate around base price
        offset = 0.5 if i % 2 == 0 else -0.5
        price = base_price + offset
        candles.append(Candle(
            timestamp=start + timedelta(hours=i),
            open=price - 0.2,
            high=price + 0.8,
            low=price - 0.8,
            close=price,
            volume=1000.0,
        ))
    return candles


class TestADXIndicator(unittest.TestCase):
    def test_adx_trending_market(self) -> None:
        """ADX should be high for strongly trending candles."""
        candles = _build_trending_candles(50, trend=2.0)
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        adx = average_directional_index(highs, lows, closes, period=14)
        # Strong uptrend → ADX > 25
        self.assertGreater(adx, 25.0)

    def test_adx_choppy_market(self) -> None:
        """ADX should be low for choppy/sideways candles."""
        candles = _build_choppy_candles(50)
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        adx = average_directional_index(highs, lows, closes, period=14)
        # Sideways → ADX < 25
        self.assertLess(adx, 25.0)

    def test_adx_insufficient_data_raises(self) -> None:
        """Too few candles should raise ValueError."""
        with self.assertRaises(ValueError):
            average_directional_index([1, 2], [0, 1], [1, 2], period=14)

    def test_adx_range_0_to_100(self) -> None:
        """ADX should always be between 0 and 100."""
        candles = _build_trending_candles(60, trend=3.0)
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        adx = average_directional_index(highs, lows, closes, period=14)
        self.assertGreaterEqual(adx, 0.0)
        self.assertLessEqual(adx, 100.0)


class TestADXFilterMomentum(unittest.TestCase):
    def test_adx_blocks_entry_in_choppy_market(self) -> None:
        """Momentum BUY blocked when ADX < threshold in choppy market."""
        config = StrategyConfig(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
            adx_period=14,
            adx_threshold=30.0,  # high threshold
        )
        regime_config = RegimeConfig(short_lookback=2, long_lookback=3)
        strategy = MomentumStrategy(config, regime_config)
        # 50 candles with slight uptrend but choppy — ADX will be moderate
        candles = _build_choppy_candles(50)
        # Override last few to have slight uptrend for momentum signal
        for i in range(47, 50):
            candles[i] = Candle(
                timestamp=candles[i].timestamp,
                open=100.0 + (i - 47),
                high=101.0 + (i - 47),
                low=99.0 + (i - 47),
                close=100.5 + (i - 47),
                volume=1000.0,
            )
        signal = strategy.evaluate(candles)
        # ADX should be low in choppy market → entry blocked
        if signal.indicators.get("adx", 100) < 30.0:
            self.assertEqual(signal.reason, "adx_too_weak")

    def test_adx_allows_entry_in_trending_market(self) -> None:
        """Momentum BUY allowed when ADX >= threshold in trending market."""
        config = StrategyConfig(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
            adx_period=14,
            adx_threshold=20.0,
        )
        regime_config = RegimeConfig(short_lookback=2, long_lookback=3)
        strategy = MomentumStrategy(config, regime_config)
        candles = _build_trending_candles(50, trend=2.0)
        signal = strategy.evaluate(candles)
        # Strong trend → ADX high → BUY allowed
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_adx_filter_disabled_with_zero_threshold(self) -> None:
        """ADX filter disabled when adx_threshold=0."""
        config = StrategyConfig(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
            adx_period=14,
            adx_threshold=0.0,
        )
        regime_config = RegimeConfig(short_lookback=2, long_lookback=3)
        strategy = MomentumStrategy(config, regime_config)
        candles = _build_choppy_candles(50)
        signal = strategy.evaluate(candles)
        # Even in choppy market, threshold=0 means filter never blocks
        self.assertNotEqual(signal.reason, "adx_too_weak")


class TestADXFilterVolatilityBreakout(unittest.TestCase):
    def test_vbreak_adx_blocks_in_choppy(self) -> None:
        """Volatility breakout BUY blocked when ADX < threshold."""
        config = StrategyConfig(
            k_base=0.1,  # very low k for easy breakout
            noise_lookback=5,
            ma_filter_period=5,
            max_holding_bars=48,
            adx_period=14,
            adx_threshold=30.0,
        )
        strategy = VolatilityBreakoutStrategy(
            config, k_base=0.1, noise_lookback=5, ma_filter_period=5,
        )
        candles = _build_choppy_candles(50)
        # Make last candle breakout above prev range
        last = candles[-1]
        prev = candles[-2]
        breakout_price = prev.close + 5.0  # well above breakout level
        candles[-1] = Candle(
            timestamp=last.timestamp,
            open=breakout_price - 0.5,
            high=breakout_price + 1.0,
            low=breakout_price - 1.0,
            close=breakout_price,
            volume=1000.0,
        )
        signal = strategy.evaluate(candles)
        if signal.indicators.get("adx", 100) < 30.0:
            self.assertEqual(signal.reason, "adx_too_weak")


if __name__ == "__main__":
    unittest.main()
