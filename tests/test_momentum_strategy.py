from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.momentum import MomentumStrategy


def build_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


class MomentumStrategyTests(unittest.TestCase):
    def _make_strategy(self, **kwargs: object) -> MomentumStrategy:
        """Build a MomentumStrategy with a neutral RegimeConfig (no regime shifts)."""
        config = StrategyConfig(**kwargs)  # type: ignore[arg-type]
        # Use a large long_lookback so regime detection stays sideways for small candle sets
        regime_config = RegimeConfig(short_lookback=2, long_lookback=3)
        return MomentumStrategy(config, regime_config)

    def test_insufficient_data_returns_hold(self) -> None:
        """Too few candles → HOLD with reason insufficient_data."""
        strategy = self._make_strategy(momentum_lookback=10, rsi_period=14)
        candles = build_candles([100.0, 101.0, 102.0])
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_buy_signal_when_momentum_and_rsi_align(self) -> None:
        """Rising prices with permissive RSI window and low threshold → BUY."""
        strategy = self._make_strategy(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
        )
        # Steadily rising prices: momentum > -0.5 and RSI will be ~100 (all gains)
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        signal = strategy.evaluate(build_candles(closes))
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "momentum_rsi_alignment")

    def test_hold_when_conditions_not_met(self) -> None:
        """Flat prices with strict positive threshold → momentum near 0, no BUY."""
        strategy = self._make_strategy(
            momentum_lookback=3,
            momentum_entry_threshold=0.10,  # requires 10% gain — flat prices won't meet this
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
        )
        closes = [100.0] * 10
        signal = strategy.evaluate(build_candles(closes))
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "entry_conditions_not_met")

    def test_sell_on_max_holding_bars(self) -> None:
        """Position entered at index 0 with max_holding_bars=2 → SELL after enough candles."""
        strategy = self._make_strategy(
            momentum_lookback=3,
            rsi_period=3,
            max_holding_bars=2,
        )
        closes = [100.0] * 10
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,
        )
        # len(candles)=10, entry_index=0 → holding_bars = 10 - 0 - 1 = 9 >= 2
        signal = strategy.evaluate(build_candles(closes), position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")

    def test_sell_on_momentum_reversal(self) -> None:
        """Falling prices cause negative momentum <= exit_threshold → SELL."""
        strategy = self._make_strategy(
            momentum_lookback=3,
            momentum_exit_threshold=-0.001,  # any drop triggers exit
            rsi_period=3,
            max_holding_bars=100,
        )
        # Prices falling: momentum will be negative
        closes = [105.0, 104.0, 103.0, 102.0, 101.0, 100.0]
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=105.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,
        )
        signal = strategy.evaluate(build_candles(closes), position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "momentum_reversal")

    def test_sell_on_rsi_overbought(self) -> None:
        """With rsi_overbought=30 and rising prices (RSI near 100), position → SELL."""
        strategy = self._make_strategy(
            momentum_lookback=3,
            momentum_exit_threshold=-1.0,  # very lenient — won't trigger momentum exit
            rsi_period=3,
            rsi_overbought=30.0,  # low threshold so rising prices breach it
            max_holding_bars=100,
        )
        # Rising prices → RSI will be 100.0 (all gains, no losses) > 30
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,
        )
        signal = strategy.evaluate(build_candles(closes), position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "rsi_overbought")


if __name__ == "__main__":
    unittest.main()
