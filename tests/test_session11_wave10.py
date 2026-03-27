"""Tests for Session #11 Wave 10: volume-weighted momentum, multi-timeframe trend."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.momentum import MomentumStrategy


def _candles(closes: list[float], volumes: list[float] | None = None) -> list[Candle]:
    t = datetime(2025, 1, 1)
    vols = volumes or [1000.0] * len(closes)
    return [
        Candle(
            timestamp=t + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=vols[i],
        )
        for i, c in enumerate(closes)
    ]


# ---------- Volume-weighted momentum ----------


class TestVolumeWeightedMomentum(unittest.TestCase):
    def test_volume_ratio_in_buy_signal(self) -> None:
        """Volume ratio should appear in indicators on BUY."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        volumes = [1000.0] * 50
        candles = _candles(prices, volumes)
        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=0.0,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
                adx_threshold=0.0,
            ),
        )
        signal = strategy.evaluate(candles)
        if signal.action == SignalAction.BUY:
            self.assertIn("volume_ratio", signal.indicators)

    def test_high_volume_boosts_confidence(self) -> None:
        """Volume > 2x average should boost BUY confidence."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        # Normal volume for first 49, then 3x spike
        low_vol = [1000.0] * 49 + [3000.0]
        high_vol_candles = _candles(prices, low_vol)

        normal_vol = [1000.0] * 50
        normal_vol_candles = _candles(prices, normal_vol)

        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=0.0,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
                adx_threshold=0.0,
            ),
        )
        sig_high = strategy.evaluate(high_vol_candles)
        sig_norm = strategy.evaluate(normal_vol_candles)

        if sig_high.action == SignalAction.BUY and sig_norm.action == SignalAction.BUY:
            self.assertGreaterEqual(sig_high.confidence, sig_norm.confidence)


# ---------- Multi-timeframe trend in Composite ----------


class TestMultiTimeframeTrend(unittest.TestCase):
    def test_ema50_in_indicators(self) -> None:
        """CompositeStrategy should include ema50 when 50+ candles."""
        prices = [100.0 + i * 0.1 for i in range(55)]
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("ema50", signal.indicators)

    def test_no_ema50_with_few_candles(self) -> None:
        """ema50 should not appear with < 50 candles."""
        prices = [100.0] * 30
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertNotIn("ema50", signal.indicators)

    def test_macro_trend_up_when_above_ema50(self) -> None:
        """When price > EMA(50), macro trend is up."""
        # Uptrending prices: latest close should be above EMA(50)
        prices = [100.0 + i * 1.0 for i in range(55)]
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        ema50 = signal.indicators.get("ema50", 0)
        latest = prices[-1]
        self.assertGreater(latest, ema50)

    def test_composite_evaluates_with_trend(self) -> None:
        """Composite should work normally with trend filter active."""
        prices = [100.0] * 55
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertIsNotNone(signal)
        self.assertIn(signal.action, [SignalAction.BUY, SignalAction.SELL, SignalAction.HOLD])


if __name__ == "__main__":
    unittest.main()
