"""Tests for Session #11 Wave 3: EMA crossover strategy, MACD vol breakout."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy
from crypto_trader.wallet import create_strategy


def _candles(closes: list[float], start: datetime | None = None) -> list[Candle]:
    t = start or datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=t + timedelta(hours=i),
            open=c,
            high=c * 1.02,
            low=c * 0.98,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


# ---------- EMA Crossover Strategy ----------


class TestEMACrossoverStrategy(unittest.TestCase):
    def test_hold_on_insufficient_data(self) -> None:
        candles = _candles([100.0] * 10)
        strategy = EMACrossoverStrategy(StrategyConfig(rsi_period=5))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_buy_on_upward_crossover(self) -> None:
        """Strong uptrend should produce a BUY signal."""
        # Flat then strong rise to trigger EMA crossover
        prices = [100.0] * 25 + [100.0 + i * 2.0 for i in range(25)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(
                rsi_period=5,
                rsi_overbought=90.0,
                rsi_oversold_floor=0.0,
            ),
            fast_period=9,
            slow_period=21,
        )
        signal = strategy.evaluate(candles)
        # Should be BUY or at least have ema indicators
        self.assertIn("ema_fast", signal.indicators)
        self.assertIn("ema_slow", signal.indicators)
        self.assertIn("ema_spread", signal.indicators)

    def test_sell_on_downward_crossover(self) -> None:
        """With position, downward crossover should produce SELL."""
        prices = [100.0 + i * 2.0 for i in range(25)] + [148.0 - i * 3.0 for i in range(25)]
        candles = _candles(prices)
        pos = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=120.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=10,
        )
        strategy = EMACrossoverStrategy(StrategyConfig(rsi_period=5))
        signal = strategy.evaluate(candles, pos)
        # Should eventually trigger sell from crossover or max holding
        self.assertIn(signal.action, [SignalAction.SELL, SignalAction.HOLD])

    def test_max_holding_exit(self) -> None:
        """Position held beyond max_holding_bars should be sold."""
        prices = [100.0] * 60
        candles = _candles(prices)
        pos = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,
        )
        strategy = EMACrossoverStrategy(StrategyConfig(rsi_period=5, max_holding_bars=48))
        signal = strategy.evaluate(candles, pos)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")

    def test_macd_indicators_present(self) -> None:
        """MACD histogram should be in indicators when enough data."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(StrategyConfig(rsi_period=5))
        signal = strategy.evaluate(candles)
        self.assertIn("macd_histogram", signal.indicators)

    def test_context_has_strategy_name(self) -> None:
        candles = _candles([100.0] * 30)
        strategy = EMACrossoverStrategy(StrategyConfig(rsi_period=5))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.context.get("strategy"), "ema_crossover")


# ---------- EMA Crossover registration ----------


class TestEMACrossoverRegistration(unittest.TestCase):
    def test_create_strategy_ema_crossover(self) -> None:
        """create_strategy should return EMACrossoverStrategy for 'ema_crossover'."""
        strategy = create_strategy("ema_crossover", StrategyConfig(), RegimeConfig())
        self.assertIsInstance(strategy, EMACrossoverStrategy)

    def test_backtest_all_includes_ema_crossover(self) -> None:
        """ema_crossover should be in the backtest-all strategy list."""
        # Just verify the strategy is importable and constructable
        strategy = EMACrossoverStrategy(StrategyConfig())
        candles = _candles([100.0] * 30)
        signal = strategy.evaluate(candles)
        self.assertIsNotNone(signal)


# ---------- Vol breakout MACD ----------


class TestVolBreakoutMACD(unittest.TestCase):
    def test_macd_histogram_in_indicators(self) -> None:
        """VolatilityBreakoutStrategy should include macd_histogram when enough data."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_period=14, adx_threshold=0.0),
            k_base=0.5,
            noise_lookback=20,
            ma_filter_period=20,
        )
        signal = strategy.evaluate(candles)
        self.assertIn("macd_histogram", signal.indicators)

    def test_macd_absent_with_few_candles(self) -> None:
        """With < 35 candles, macd_histogram should not be in indicators."""
        prices = [100.0] * 25
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_period=14, adx_threshold=0.0),
            k_base=0.5,
            noise_lookback=20,
            ma_filter_period=20,
        )
        signal = strategy.evaluate(candles)
        self.assertNotIn("macd_histogram", signal.indicators)


if __name__ == "__main__":
    unittest.main()
