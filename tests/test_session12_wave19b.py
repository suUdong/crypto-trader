"""Tests for Session #12 Wave 19b: max drawdown duration, Keltner Channels."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine, _max_drawdown_duration
from crypto_trader.config import BacktestConfig, RiskConfig
from crypto_trader.models import Candle, Signal, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.indicators import keltner_channels


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


# ---------- Max drawdown duration ----------


class TestMaxDrawdownDuration(unittest.TestCase):
    def test_no_drawdown(self) -> None:
        curve = [100.0, 101.0, 102.0, 103.0, 104.0]
        self.assertEqual(_max_drawdown_duration(curve), 0)

    def test_single_drawdown(self) -> None:
        curve = [100.0, 99.0, 98.0, 97.0, 100.0, 101.0]
        self.assertEqual(_max_drawdown_duration(curve), 3)

    def test_two_drawdowns_returns_longest(self) -> None:
        curve = [100.0, 99.0, 100.0, 99.0, 98.0, 97.0, 96.0, 100.0]
        self.assertEqual(_max_drawdown_duration(curve), 4)

    def test_never_recovers(self) -> None:
        curve = [100.0, 99.0, 98.0, 97.0]
        self.assertEqual(_max_drawdown_duration(curve), 3)

    def test_flat_no_drawdown(self) -> None:
        curve = [100.0, 100.0, 100.0]
        self.assertEqual(_max_drawdown_duration(curve), 0)

    def test_empty_or_single(self) -> None:
        self.assertEqual(_max_drawdown_duration([]), 0)
        self.assertEqual(_max_drawdown_duration([100.0]), 0)

    def test_in_backtest_result(self) -> None:
        class BuyOnce:
            def __init__(self):
                self._done = False

            def evaluate(self, candles, position=None):
                if position is None and not self._done:
                    self._done = True
                    return Signal(action=SignalAction.BUY, reason="buy", confidence=0.8)
                return Signal(action=SignalAction.HOLD, reason="hold", confidence=0.5)

        prices = [100.0] * 20 + [95.0] * 10 + [100.0] * 10
        candles = _candles(prices)
        risk = RiskManager(
            RiskConfig(
                stop_loss_pct=0.1,
                take_profit_pct=0.15,
                min_entry_confidence=0.5,
            )
        )
        engine = BacktestEngine(
            strategy=BuyOnce(),
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertIsInstance(result.max_drawdown_duration_bars, int)
        self.assertGreaterEqual(result.max_drawdown_duration_bars, 0)


# ---------- Keltner Channels ----------


class TestKeltnerChannels(unittest.TestCase):
    def test_basic_calculation(self) -> None:
        closes = [100.0 + i * 0.1 for i in range(30)]
        highs = [c * 1.01 for c in closes]
        lows = [c * 0.99 for c in closes]
        upper, middle, lower = keltner_channels(highs, lows, closes)
        self.assertGreater(upper, middle)
        self.assertGreater(middle, lower)

    def test_flat_market_narrow(self) -> None:
        closes = [100.0] * 30
        highs = [100.5] * 30
        lows = [99.5] * 30
        upper, middle, lower = keltner_channels(highs, lows, closes)
        self.assertLess(upper - lower, 5.0)

    def test_multiplier_scales_width(self) -> None:
        closes = [100.0 + i * 0.1 for i in range(30)]
        highs = [c * 1.02 for c in closes]
        lows = [c * 0.98 for c in closes]
        u1, m1, l1 = keltner_channels(highs, lows, closes, atr_multiplier=1.0)
        u2, m2, l2 = keltner_channels(highs, lows, closes, atr_multiplier=2.0)
        self.assertAlmostEqual(m1, m2, places=5)
        self.assertGreater(u2 - l2, u1 - l1)

    def test_insufficient_data(self) -> None:
        with self.assertRaises(ValueError):
            keltner_channels([100.0] * 5, [100.0] * 5, [100.0] * 5)

    def test_symmetric_bands(self) -> None:
        closes = [100.0] * 30
        highs = [101.0] * 30
        lows = [99.0] * 30
        upper, middle, lower = keltner_channels(highs, lows, closes)
        self.assertAlmostEqual(upper - middle, middle - lower, places=5)


if __name__ == "__main__":
    unittest.main()
