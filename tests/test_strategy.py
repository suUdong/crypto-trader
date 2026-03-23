from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.indicators import bollinger_bands, momentum, rsi


def build_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1, 0, 0, 0)
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=index),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=1.0 + index,
            )
        )
    return candles


class IndicatorTests(unittest.TestCase):
    def test_indicator_outputs(self) -> None:
        values = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        upper, middle, lower = bollinger_bands(values, 5, 2.0)
        self.assertGreater(upper, middle)
        self.assertLess(lower, middle)
        self.assertGreater(momentum(values, 3), 0.0)
        self.assertGreaterEqual(rsi(values, 5), 50.0)


class CompositeStrategyTests(unittest.TestCase):
    def test_generates_buy_signal_when_components_align(self) -> None:
        closes = [100.0] * 20 + [90.0, 89.0]
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                bollinger_window=20,
                bollinger_stddev=1.5,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
            )
        )
        signal = strategy.evaluate(build_candles(closes))
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_generates_sell_signal_for_max_holding_period(self) -> None:
        closes = [100.0] * 24
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                bollinger_window=5,
                rsi_period=3,
                max_holding_bars=2,
            )
        )
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1, 0, 0, 0),
            entry_index=0,
        )
        signal = strategy.evaluate(build_candles(closes), position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")
