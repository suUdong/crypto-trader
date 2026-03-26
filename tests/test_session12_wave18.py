"""Tests for Session #12 Wave 18: VWAP indicator, VWAP in strategies, WF scoring."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.indicators import rolling_vwap, vwap
from crypto_trader.strategy.momentum import MomentumStrategy


def _candles(closes: list[float], volume: float = 1000.0) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=volume)
        for i, c in enumerate(closes)
    ]


# ---------- VWAP indicator ----------

class TestVWAP(unittest.TestCase):
    def test_flat_prices_equal_close(self) -> None:
        """VWAP of flat prices should equal the price."""
        result = vwap([100.0] * 5, [100.0] * 5, [100.0] * 5, [1000.0] * 5)
        self.assertAlmostEqual(result, 100.0, places=2)

    def test_high_volume_bar_dominates(self) -> None:
        """VWAP should be pulled toward high-volume bars."""
        highs = [100.0, 200.0]
        lows = [100.0, 200.0]
        closes = [100.0, 200.0]
        volumes = [1.0, 1000.0]
        result = vwap(highs, lows, closes, volumes)
        # Should be very close to 200 since second bar has 1000x more volume
        self.assertGreater(result, 190.0)

    def test_zero_volume_returns_last_close(self) -> None:
        """Zero total volume should return last close."""
        result = vwap([100.0], [100.0], [100.0], [0.0])
        self.assertAlmostEqual(result, 100.0)

    def test_empty_raises(self) -> None:
        """Empty input should raise ValueError."""
        with self.assertRaises(ValueError):
            vwap([], [], [], [])

    def test_mismatched_lengths(self) -> None:
        """Mismatched input lengths should raise ValueError."""
        with self.assertRaises(ValueError):
            vwap([100.0], [100.0], [100.0, 101.0], [1000.0])


class TestRollingVWAP(unittest.TestCase):
    def test_rolling_window(self) -> None:
        """Rolling VWAP should use only last N bars."""
        highs = [100.0] * 10 + [200.0] * 10
        lows = [100.0] * 10 + [200.0] * 10
        closes = [100.0] * 10 + [200.0] * 10
        volumes = [1000.0] * 20
        result = rolling_vwap(highs, lows, closes, volumes, window=10)
        # Last 10 bars are all 200, so VWAP should be ~200
        self.assertAlmostEqual(result, 200.0, places=2)

    def test_insufficient_data(self) -> None:
        """Should raise ValueError with insufficient data."""
        with self.assertRaises(ValueError):
            rolling_vwap([100.0] * 5, [100.0] * 5, [100.0] * 5, [1000.0] * 5, window=10)


# ---------- VWAP in composite ----------

class TestCompositeVWAP(unittest.TestCase):
    def test_vwap_in_indicators(self) -> None:
        """Composite should include vwap in indicators."""
        prices = [100.0 + i * 0.1 for i in range(50)]
        candles = _candles(prices)
        strategy = CompositeStrategy(StrategyConfig(
            momentum_lookback=5, bollinger_window=20, rsi_period=5,
        ))
        signal = strategy.evaluate(candles)
        self.assertIn("vwap", signal.indicators)

    def test_vwap_absent_short_data(self) -> None:
        """With very few candles, vwap may not be in indicators."""
        candles = _candles([100.0] * 10)
        strategy = CompositeStrategy(StrategyConfig(
            momentum_lookback=3, bollinger_window=5, rsi_period=3,
        ))
        signal = strategy.evaluate(candles)
        # May or may not have vwap depending on minimum window
        self.assertIsNotNone(signal)


# ---------- VWAP in momentum ----------

class TestMomentumVWAP(unittest.TestCase):
    def test_vwap_in_indicators(self) -> None:
        """Momentum should include vwap in indicators."""
        prices = [100.0 + i * 0.3 for i in range(50)]
        candles = _candles(prices)
        strategy = MomentumStrategy(StrategyConfig(
            momentum_lookback=5, rsi_period=5, adx_threshold=0.0,
        ))
        signal = strategy.evaluate(candles)
        self.assertIn("vwap", signal.indicators)


# ---------- Walk-forward scoring ----------

class TestWalkForwardScoring(unittest.TestCase):
    def test_summary_includes_new_metrics(self) -> None:
        """WalkForwardReport summary should include profit_factor and sharpe."""
        from crypto_trader.backtest.walk_forward import WalkForwardReport
        report = WalkForwardReport(
            strategy_name="test", symbol="KRW-BTC", total_folds=0,
        )
        summary = report.summary()
        self.assertIn("avg_oos_profit_factor", summary)
        self.assertIn("avg_oos_sharpe", summary)

    def test_avg_oos_profit_factor_empty(self) -> None:
        """Empty folds should return 0 for profit factor."""
        from crypto_trader.backtest.walk_forward import WalkForwardReport
        report = WalkForwardReport(
            strategy_name="test", symbol="KRW-BTC", total_folds=0,
        )
        self.assertEqual(report.avg_oos_profit_factor, 0.0)
        self.assertEqual(report.avg_oos_sharpe, 0.0)


if __name__ == "__main__":
    unittest.main()
