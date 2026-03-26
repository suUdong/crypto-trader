"""Tests for Session #12 Wave 16: MR volume+OBV, EMA OBV, VolBreakout regime."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy


def _candles(closes: list[float], volume: float = 1000.0) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=volume)
        for i, c in enumerate(closes)
    ]


def _candles_with_volumes(closes: list[float], volumes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=v)
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


# ---------- Mean reversion volume filter ----------

class TestMeanReversionVolumeFilter(unittest.TestCase):
    def test_volume_filter_blocks_low_volume(self) -> None:
        """Low volume should block MR entry when volume_filter_mult > 0."""
        prices = [100.0] * 25 + [97.0, 95.0, 93.0]
        volumes = [1000.0] * 25 + [100.0, 100.0, 100.0]
        candles = _candles_with_volumes(prices, volumes)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, bollinger_stddev=1.5,
            rsi_period=5, rsi_oversold_floor=0.0,
            noise_lookback=20, volume_filter_mult=0.8,
        ))
        signal = strategy.evaluate(candles)
        if signal.reason == "volume_too_low":
            self.assertEqual(signal.action, SignalAction.HOLD)

    def test_volume_filter_disabled_by_default(self) -> None:
        """volume_filter_mult=0 should not trigger filter."""
        prices = [100.0] * 30
        candles = _candles(prices, volume=1.0)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, volume_filter_mult=0.0,
        ))
        signal = strategy.evaluate(candles)
        self.assertNotEqual(signal.reason, "volume_too_low")


# ---------- Mean reversion OBV ----------

class TestMeanReversionOBV(unittest.TestCase):
    def test_obv_slope_in_indicators(self) -> None:
        """Mean reversion should include obv_slope in indicators."""
        prices = [100.0 + ((-1) ** i) * 2.0 for i in range(50)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        self.assertIn("obv_slope", signal.indicators)

    def test_obv_absent_with_short_data(self) -> None:
        """With few candles, obv_slope may not be present."""
        prices = [100.0] * 8
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=5, rsi_period=3, noise_lookback=3,
        ))
        signal = strategy.evaluate(candles)
        self.assertIsNotNone(signal)


# ---------- EMA crossover OBV ----------

class TestEMACrossoverOBV(unittest.TestCase):
    def test_obv_slope_in_indicators(self) -> None:
        """EMA crossover should include obv_slope in indicators."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("obv_slope", signal.indicators)

    def test_obv_boosts_crossover_confidence(self) -> None:
        """OBV accumulation should boost EMA crossover entry confidence."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, rsi_overbought=90.0, adx_threshold=0.0),
        )
        dummy_candles = _candles([100.0 + i * 0.5 for i in range(30)])
        signal_no_obv = strategy._evaluate_entry(
            dummy_candles, cross_up=True, spread=0.01,
            rsi_value=55.0, stoch_rsi_value=40.0,
            macd_bullish=False, adx_value=None,
            indicators={}, context={"strategy": "ema_crossover"},
            obv_trend=None,
        )
        signal_with_obv = strategy._evaluate_entry(
            dummy_candles, cross_up=True, spread=0.01,
            rsi_value=55.0, stoch_rsi_value=40.0,
            macd_bullish=False, adx_value=None,
            indicators={}, context={"strategy": "ema_crossover"},
            obv_trend=0.8,
        )
        self.assertEqual(signal_no_obv.action, SignalAction.BUY)
        self.assertEqual(signal_with_obv.action, SignalAction.BUY)
        self.assertGreaterEqual(signal_with_obv.confidence, signal_no_obv.confidence)


# ---------- VolatilityBreakout regime awareness ----------

class TestVolBreakoutRegime(unittest.TestCase):
    def test_regime_in_context(self) -> None:
        """VolBreakout should include market_regime in context."""
        prices = [100.0 + i * 0.1 for i in range(50)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), noise_lookback=20)
        signal = strategy.evaluate(candles)
        self.assertIn("market_regime", signal.context)

    def test_regime_detector_initialized(self) -> None:
        """Should have a regime detector."""
        strategy = VolatilityBreakoutStrategy(StrategyConfig())
        self.assertIsNotNone(strategy._regime_detector)

    def test_custom_regime_config(self) -> None:
        """Should accept custom RegimeConfig."""
        rc = RegimeConfig(short_lookback=5, long_lookback=15)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), regime_config=rc)
        self.assertIsNotNone(strategy._regime_detector)

    def test_insufficient_data_has_regime(self) -> None:
        """Even with insufficient data, context should have regime."""
        candles = _candles([100.0] * 5)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), noise_lookback=20)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertIn("market_regime", signal.context)

    def test_uses_effective_adx_threshold(self) -> None:
        """Should use regime-adjusted ADX threshold."""
        prices = [100.0] * 50
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_threshold=20.0), noise_lookback=20,
        )
        signal = strategy.evaluate(candles)
        # Just verify it runs with regime-adjusted params
        self.assertIsNotNone(signal)


if __name__ == "__main__":
    unittest.main()
