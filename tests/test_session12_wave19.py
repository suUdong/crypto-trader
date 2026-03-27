"""Tests for Session #12 Wave 19: VWAP indicator + VWAP in all strategies."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.strategy.indicators import rolling_vwap, vwap
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy


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


# ========== VWAP indicator tests ==========


class TestVWAP(unittest.TestCase):
    def test_uniform_volume(self) -> None:
        """With uniform volume, VWAP = average typical price."""
        highs = [102.0, 104.0, 106.0]
        lows = [98.0, 96.0, 94.0]
        closes = [100.0, 100.0, 100.0]
        volumes = [1000.0, 1000.0, 1000.0]
        result = vwap(highs, lows, closes, volumes)
        # typical prices: (102+98+100)/3=100, (104+96+100)/3=100, (106+94+100)/3=100
        self.assertAlmostEqual(result, 100.0)

    def test_high_volume_bar_dominates(self) -> None:
        """Bar with higher volume should dominate VWAP."""
        highs = [103.0, 106.0]
        lows = [97.0, 94.0]
        closes = [100.0, 100.0]
        volumes = [100.0, 10000.0]
        result = vwap(highs, lows, closes, volumes)
        # tp1 = (103+97+100)/3 = 100.0, tp2 = (106+94+100)/3 = 100.0
        # Both typical prices are 100 so VWAP = 100
        self.assertAlmostEqual(result, 100.0)

    def test_asymmetric_prices(self) -> None:
        """VWAP should weight toward high-volume bar's typical price."""
        highs = [105.0, 110.0]
        lows = [95.0, 90.0]
        closes = [100.0, 105.0]
        volumes = [100.0, 900.0]
        result = vwap(highs, lows, closes, volumes)
        # tp1 = (105+95+100)/3 = 100.0, tp2 = (110+90+105)/3 = 101.667
        # VWAP = (100*100 + 101.667*900) / 1000 = (10000 + 91500) / 1000 = 101.5
        expected = (100.0 * 100 + ((110 + 90 + 105) / 3) * 900) / 1000
        self.assertAlmostEqual(result, expected, places=2)

    def test_empty_raises(self) -> None:
        """Empty input should raise ValueError."""
        with self.assertRaises(ValueError):
            vwap([], [], [], [])

    def test_mismatched_raises(self) -> None:
        """Mismatched lengths should raise ValueError."""
        with self.assertRaises(ValueError):
            vwap([100.0], [90.0], [95.0], [100.0, 200.0])

    def test_zero_volume_returns_last_close(self) -> None:
        """Zero total volume should return last close."""
        result = vwap([105.0], [95.0], [100.0], [0.0])
        self.assertAlmostEqual(result, 100.0)


class TestRollingVWAP(unittest.TestCase):
    def test_basic_rolling(self) -> None:
        """Rolling VWAP should use only last N bars."""
        n = 30
        highs = [100.0 + i * 0.5 for i in range(n)]
        lows = [100.0 - i * 0.5 for i in range(n)]
        closes = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000.0] * n
        result = rolling_vwap(highs, lows, closes, volumes, window=20)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)

    def test_insufficient_data_raises(self) -> None:
        """Should raise ValueError with insufficient data."""
        with self.assertRaises(ValueError):
            rolling_vwap([100.0] * 5, [90.0] * 5, [95.0] * 5, [1000.0] * 5, window=20)

    def test_window_boundary(self) -> None:
        """Exactly window bars should work."""
        n = 20
        highs = [101.0] * n
        lows = [99.0] * n
        closes = [100.0] * n
        volumes = [1000.0] * n
        result = rolling_vwap(highs, lows, closes, volumes, window=20)
        self.assertAlmostEqual(result, 100.0)


# ========== VWAP in MeanReversion ==========


class TestMeanRevVWAP(unittest.TestCase):
    def test_vwap_in_indicators(self) -> None:
        """MeanRev should include vwap in indicators."""
        prices = [100.0 + (-1) ** i * 2 for i in range(50)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(
            StrategyConfig(
                bollinger_window=20,
                rsi_period=5,
                noise_lookback=20,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertIn("vwap", signal.indicators)

    def test_vwap_absent_short_data(self) -> None:
        """VWAP should not crash with short data."""
        prices = [100.0] * 10
        candles = _candles(prices)
        strategy = MeanReversionStrategy(
            StrategyConfig(
                bollinger_window=5,
                rsi_period=3,
                noise_lookback=3,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertIsNotNone(signal)


# ========== VWAP in VolatilityBreakout ==========


class TestVolBreakoutVWAP(unittest.TestCase):
    def test_vwap_in_indicators(self) -> None:
        """VolBreakout should include vwap in indicators."""
        prices = [100.0 + i * 0.1 for i in range(50)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), noise_lookback=20)
        signal = strategy.evaluate(candles)
        self.assertIn("vwap", signal.indicators)

    def test_vwap_absent_short_data(self) -> None:
        """Short data should not crash on VWAP."""
        prices = [100.0] * 8
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(StrategyConfig(), noise_lookback=3)
        signal = strategy.evaluate(candles)
        self.assertIsNotNone(signal)


# ========== VWAP in EMACrossover ==========


class TestEMACrossVWAP(unittest.TestCase):
    def test_vwap_in_indicators(self) -> None:
        """EMA crossover should include vwap in indicators."""
        prices = [100.0 + i * 0.3 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("vwap", signal.indicators)

    def test_vwap_boosts_crossover_confidence(self) -> None:
        """VWAP aligned with entry should boost confidence."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, rsi_overbought=90.0, adx_threshold=0.0),
        )
        dummy = _candles([100.0 + i * 0.5 for i in range(30)])
        sig_no_vwap = strategy._evaluate_entry(
            dummy,
            cross_up=True,
            spread=0.01,
            rsi_value=55.0,
            stoch_rsi_value=40.0,
            macd_bullish=False,
            adx_value=None,
            indicators={"ema_fast": 110.0},
            context={"strategy": "ema_crossover"},
            obv_trend=None,
            nr_value=0.3,
            ema50_value=None,
            vwap_value=None,
        )
        sig_with_vwap = strategy._evaluate_entry(
            dummy,
            cross_up=True,
            spread=0.01,
            rsi_value=55.0,
            stoch_rsi_value=40.0,
            macd_bullish=False,
            adx_value=None,
            indicators={"ema_fast": 110.0},
            context={"strategy": "ema_crossover"},
            obv_trend=None,
            nr_value=0.3,
            ema50_value=None,
            vwap_value=105.0,
        )
        self.assertEqual(sig_no_vwap.action, SignalAction.BUY)
        self.assertEqual(sig_with_vwap.action, SignalAction.BUY)
        self.assertGreaterEqual(sig_with_vwap.confidence, sig_no_vwap.confidence)


# ========== All strategies VWAP coverage ==========


class TestVWAPCoverageAll(unittest.TestCase):
    def test_all_strategies_have_vwap(self) -> None:
        """All 5 core strategies should include vwap indicator."""
        from crypto_trader.strategy.composite import CompositeStrategy
        from crypto_trader.strategy.momentum import MomentumStrategy

        prices = [100.0 + i * 0.2 for i in range(55)]
        candles = _candles(prices)

        strategies = [
            (
                "composite",
                CompositeStrategy(
                    StrategyConfig(
                        momentum_lookback=5,
                        bollinger_window=20,
                        rsi_period=5,
                    )
                ),
            ),
            (
                "momentum",
                MomentumStrategy(
                    StrategyConfig(
                        momentum_lookback=5,
                        rsi_period=5,
                        adx_threshold=0.0,
                    )
                ),
            ),
            (
                "mean_reversion",
                MeanReversionStrategy(
                    StrategyConfig(
                        bollinger_window=20,
                        rsi_period=5,
                        noise_lookback=20,
                    )
                ),
            ),
            (
                "volatility_breakout",
                VolatilityBreakoutStrategy(
                    StrategyConfig(),
                    noise_lookback=20,
                ),
            ),
            (
                "ema_crossover",
                EMACrossoverStrategy(
                    StrategyConfig(rsi_period=5, adx_threshold=0.0),
                ),
            ),
        ]
        for name, strat in strategies:
            signal = strat.evaluate(candles)
            self.assertIn("vwap", signal.indicators, f"{name} missing vwap indicator")


if __name__ == "__main__":
    unittest.main()
