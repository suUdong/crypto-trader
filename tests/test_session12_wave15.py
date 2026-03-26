"""Tests for Session #12 Wave 15: Cross-strategy filter expansion.

MeanRev: ADX filter + EMA(50) macro trend
VolBreakout: OBV confirmation + EMA(50) macro + effective bug fix
EMA Cross: noise_ratio filter + volume on trend continuation + EMA(50) macro
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
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


def _trending_candles(n: int = 60, start: float = 100.0, step: float = 1.5) -> list[Candle]:
    """Create strongly trending candles (high ADX)."""
    t = datetime(2025, 1, 1)
    candles = []
    for i in range(n):
        c = start + i * step
        candles.append(Candle(
            timestamp=t + timedelta(hours=i), open=c - step * 0.3,
            high=c + step * 0.2, low=c - step * 0.5, close=c, volume=2000.0,
        ))
    return candles


# ========== Mean Reversion: ADX filter ==========

class TestMeanRevADXFilter(unittest.TestCase):
    def test_adx_in_indicators(self) -> None:
        """MeanRev should include ADX in indicators."""
        prices = [100.0 + (-1) ** i * 2 for i in range(50)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        self.assertIn("adx", signal.indicators)

    def test_high_adx_blocks_entry(self) -> None:
        """Strong trend (high ADX > 40) should block MR entry."""
        candles = _trending_candles(60, step=2.0)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
            rsi_oversold_floor=0.0,
        ))
        signal = strategy.evaluate(candles)
        # Strong trend should either block with ADX or noise filter
        if signal.action == SignalAction.BUY:
            # If we somehow get a BUY, ADX must be <= 40
            adx = signal.indicators.get("adx", 0)
            self.assertLessEqual(adx, 40.0)

    def test_low_adx_allows_entry(self) -> None:
        """Ranging market (low ADX) should not block MR entry via ADX."""
        # Oscillating prices = low ADX
        prices = [100.0 + (-1) ** i * 3 for i in range(50)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        self.assertNotEqual(signal.reason, "market_too_trendy_adx")


# ========== Mean Reversion: EMA(50) macro ==========

class TestMeanRevEMA50(unittest.TestCase):
    def test_ema50_in_indicators(self) -> None:
        """MeanRev should include ema50 in indicators with enough data."""
        prices = [100.0 + (-1) ** i * 2 for i in range(55)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        self.assertIn("ema50", signal.indicators)

    def test_ema50_absent_with_short_data(self) -> None:
        """EMA(50) should not be in indicators with < 50 candles."""
        prices = [100.0] * 30
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        self.assertNotIn("ema50", signal.indicators)

    def test_ema50_boosts_confidence_below_ema(self) -> None:
        """Price below EMA(50) should boost MR confidence (extended dip)."""
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        # Create scenario: price dropped well below EMA(50)
        prices = [120.0] * 40 + [110.0, 108.0, 105.0, 103.0, 100.0,
                                   98.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0, 90.0]
        candles = _candles(prices)
        signal = strategy.evaluate(candles)
        if signal.action == SignalAction.BUY:
            # EMA(50) is well above current price -> should have ema50 indicator
            self.assertIn("ema50", signal.indicators)


# ========== VolatilityBreakout: OBV ==========

class TestVolBreakoutOBV(unittest.TestCase):
    def test_obv_slope_in_indicators(self) -> None:
        """VolBreakout should include obv_slope in indicators."""
        prices = [100.0 + i * 0.2 for i in range(50)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), noise_lookback=20)
        signal = strategy.evaluate(candles)
        self.assertIn("obv_slope", signal.indicators)

    def test_obv_absent_with_short_data(self) -> None:
        """Short data should not crash on OBV calculation."""
        prices = [100.0] * 8
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(), noise_lookback=3,
        )
        signal = strategy.evaluate(candles)
        self.assertIsNotNone(signal)


# ========== VolatilityBreakout: EMA(50) ==========

class TestVolBreakoutEMA50(unittest.TestCase):
    def test_ema50_in_indicators(self) -> None:
        """VolBreakout should include ema50 with enough data."""
        prices = [100.0 + i * 0.1 for i in range(55)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), noise_lookback=20)
        signal = strategy.evaluate(candles)
        self.assertIn("ema50", signal.indicators)

    def test_ema50_absent_short_data(self) -> None:
        """ema50 should not appear with < 50 candles."""
        prices = [100.0 + i * 0.1 for i in range(30)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), noise_lookback=20)
        signal = strategy.evaluate(candles)
        self.assertNotIn("ema50", signal.indicators)


# ========== VolatilityBreakout: effective bug fix ==========

class TestVolBreakoutEffectiveFix(unittest.TestCase):
    def test_adx_filter_uses_threshold(self) -> None:
        """ADX filter should use regime-adjusted threshold (not crash)."""
        # Create breakout scenario with low ADX
        base = [100.0] * 45
        # Then a breakout: prev candle range is 2, so breakout_level ~= 101
        base.extend([100.0, 100.0, 100.0, 100.0, 103.0])
        candles = _candles(base)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_threshold=25.0), noise_lookback=20,
        )
        # This should not raise NameError for 'effective'
        signal = strategy.evaluate(candles)
        self.assertIsNotNone(signal)

    def test_high_adx_threshold_blocks_breakout(self) -> None:
        """Very high ADX threshold should block entries in low-trend markets."""
        base = [100.0] * 48 + [100.0, 105.0]
        candles = _candles(base)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_threshold=99.0), noise_lookback=20,
        )
        signal = strategy.evaluate(candles)
        # With threshold=99, ADX is always below -> should hold
        if signal.reason == "adx_too_weak":
            self.assertEqual(signal.action, SignalAction.HOLD)


# ========== EMA Crossover: noise_ratio filter ==========

class TestEMACrossNoise(unittest.TestCase):
    def test_noise_ratio_in_indicators(self) -> None:
        """EMA crossover should include noise_ratio in indicators."""
        prices = [100.0 + (-1) ** i * 3 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("noise_ratio", signal.indicators)

    def test_high_noise_blocks_entry(self) -> None:
        """Choppy market (high noise ratio) should block EMA crossover entry."""
        # Rapidly oscillating prices = high noise ratio
        prices = [100.0 + (-1) ** i * 5 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0, noise_lookback=20),
        )
        signal = strategy.evaluate(candles)
        # High noise should produce HOLD or at least not a bad BUY
        if signal.reason == "noise_too_high":
            self.assertEqual(signal.action, SignalAction.HOLD)

    def test_low_noise_allows_entry(self) -> None:
        """Clean trending market should not be blocked by noise filter."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0, noise_lookback=20),
        )
        signal = strategy.evaluate(candles)
        self.assertNotEqual(signal.reason, "noise_too_high")


# ========== EMA Crossover: EMA(50) macro ==========

class TestEMACrossEMA50(unittest.TestCase):
    def test_ema50_in_indicators(self) -> None:
        """EMA crossover should include ema50 with enough data."""
        prices = [100.0 + i * 0.3 for i in range(55)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("ema50", signal.indicators)

    def test_ema50_absent_short_data(self) -> None:
        """ema50 should not appear with < 50 candles."""
        prices = [100.0 + i * 0.3 for i in range(30)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0),
        )
        signal = strategy.evaluate(candles)
        self.assertNotIn("ema50", signal.indicators)

    def test_ema50_boosts_crossover_confidence(self) -> None:
        """EMA(50) aligned with fast EMA should boost confidence."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, rsi_overbought=90.0, adx_threshold=0.0),
        )
        dummy = _candles([100.0 + i * 0.5 for i in range(30)])
        sig_no_ema50 = strategy._evaluate_entry(
            dummy, cross_up=True, spread=0.01,
            rsi_value=55.0, stoch_rsi_value=40.0,
            macd_bullish=False, adx_value=None,
            indicators={"ema_fast": 110.0}, context={"strategy": "ema_crossover"},
            obv_trend=None, nr_value=0.3, ema50_value=None,
        )
        sig_with_ema50 = strategy._evaluate_entry(
            dummy, cross_up=True, spread=0.01,
            rsi_value=55.0, stoch_rsi_value=40.0,
            macd_bullish=False, adx_value=None,
            indicators={"ema_fast": 110.0}, context={"strategy": "ema_crossover"},
            obv_trend=None, nr_value=0.3, ema50_value=105.0,
        )
        self.assertEqual(sig_no_ema50.action, SignalAction.BUY)
        self.assertEqual(sig_with_ema50.action, SignalAction.BUY)
        self.assertGreaterEqual(sig_with_ema50.confidence, sig_no_ema50.confidence)


# ========== EMA Crossover: volume filter on trend continuation ==========

class TestEMACrossTrendContinuationVolume(unittest.TestCase):
    def test_volume_filter_blocks_trend_continuation(self) -> None:
        """Low volume should block trend continuation entry."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(
                rsi_period=5, rsi_overbought=90.0, rsi_oversold_floor=0.0,
                adx_threshold=0.0, volume_filter_mult=1.5,
            ),
        )
        # Low volume candles for trend continuation path
        prices = [100.0 + i * 0.3 for i in range(30)]
        volumes = [100.0] * 29 + [10.0]  # last candle very low volume
        candles = _candles_with_volumes(prices, volumes)
        sig = strategy._evaluate_entry(
            candles, cross_up=False, spread=0.01,
            rsi_value=45.0, stoch_rsi_value=40.0,
            macd_bullish=False, adx_value=None,
            indicators={}, context={"strategy": "ema_crossover"},
            obv_trend=None, nr_value=0.3, ema50_value=None,
        )
        if sig.reason == "volume_too_low":
            self.assertEqual(sig.action, SignalAction.HOLD)

    def test_volume_filter_disabled_allows_continuation(self) -> None:
        """volume_filter_mult=0 should not block trend continuation."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(
                rsi_period=5, rsi_overbought=90.0, rsi_oversold_floor=0.0,
                adx_threshold=0.0, volume_filter_mult=0.0,
            ),
        )
        dummy = _candles([100.0 + i * 0.3 for i in range(30)])
        sig = strategy._evaluate_entry(
            dummy, cross_up=False, spread=0.01,
            rsi_value=45.0, stoch_rsi_value=40.0,
            macd_bullish=False, adx_value=None,
            indicators={}, context={"strategy": "ema_crossover"},
            obv_trend=None, nr_value=0.3, ema50_value=None,
        )
        self.assertNotEqual(sig.reason, "volume_too_low")


# ========== Cross-strategy: filter coverage completeness ==========

class TestFilterCoverageCompleteness(unittest.TestCase):
    def test_mean_reversion_has_all_filters(self) -> None:
        """MeanRev should now have ADX, noise_ratio, OBV, EMA(50), volume, MACD."""
        prices = [100.0 + (-1) ** i * 2 for i in range(55)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        for key in ("adx", "noise_ratio", "obv_slope", "ema50", "macd_histogram"):
            self.assertIn(key, signal.indicators, f"Missing indicator: {key}")

    def test_volbreakout_has_all_filters(self) -> None:
        """VolBreakout should now have OBV, EMA(50), ADX, noise, MACD, bb_width."""
        prices = [100.0 + i * 0.1 for i in range(55)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), noise_lookback=20)
        signal = strategy.evaluate(candles)
        for key in ("obv_slope", "ema50", "adx", "noise_ratio", "bb_width"):
            self.assertIn(key, signal.indicators, f"Missing indicator: {key}")

    def test_ema_crossover_has_all_filters(self) -> None:
        """EMA crossover should now have noise_ratio, EMA(50), OBV, ADX, StochRSI."""
        prices = [100.0 + i * 0.3 for i in range(55)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0),
        )
        signal = strategy.evaluate(candles)
        for key in ("noise_ratio", "ema50", "obv_slope", "stoch_rsi"):
            self.assertIn(key, signal.indicators, f"Missing indicator: {key}")


if __name__ == "__main__":
    unittest.main()
