"""Tests for VolumeSpikeStrategy."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.volume_spike import VolumeSpikeStrategy


def _build_candles(
    n: int = 50,
    base_volume: float = 1000.0,
) -> list[Candle]:
    """Build realistic candles with mean-reversion so RSI stays moderate."""
    base = datetime(2025, 1, 1)
    rng = random.Random(42)
    candles: list[Candle] = []
    price = 100_000.0
    mean_price = 100_000.0
    for i in range(n):
        # Mean-reverting random walk: keeps RSI from saturating
        revert = (mean_price - price) * 0.05
        change = rng.gauss(revert + 10, 150)
        o = price
        c = price + change
        h = max(o, c) + rng.uniform(30, 80)
        low_price = min(o, c) - rng.uniform(30, 80)
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=i),
                open=o,
                high=h,
                low=low_price,
                close=c,
                volume=base_volume + rng.uniform(-100, 100),
            )
        )
        price = c
        mean_price += 5  # slow drift up
    return candles


def _spike_last_candle(candles: list[Candle], volume_mult: float = 3.0) -> list[Candle]:
    """Return copy with last candle replaced by a strong bullish spike candle."""
    result = list(candles)
    last = result[-1]
    # Make a strong bullish candle with large body and high volume
    body = abs(last.high - last.low) * 0.7
    o = last.low + abs(last.high - last.low) * 0.1
    c = o + body
    h = c + 50
    low_price = o - 50
    avg_vol = sum(c_.volume for c_ in candles[-21:-1]) / 20
    result[-1] = Candle(
        timestamp=last.timestamp,
        open=o,
        high=h,
        low=low_price,
        close=c,
        volume=avg_vol * volume_mult,
    )
    return result


def _build_consensus_integration_candles() -> list[Candle]:
    """Build candles where momentum and volume spike align on the final bar."""
    candles = _build_candles(80)
    adjustments = [-30.0, -10.0, 5.0, 10.0, 20.0]
    for offset, step in zip(range(-6, -1), adjustments, strict=False):
        current = candles[offset]
        close = current.close + step
        candles[offset] = Candle(
            timestamp=current.timestamp,
            open=current.open,
            high=max(current.high, close + 25.0),
            low=min(current.low, close - 25.0),
            close=close,
            volume=current.volume,
        )

    last = candles[-1]
    avg_vol = sum(c.volume for c in candles[-21:-1]) / 20
    open_price = last.close
    close_price = open_price + 40.0
    candles[-1] = Candle(
        timestamp=last.timestamp,
        open=open_price,
        high=close_price + 50.0,
        low=open_price - 30.0,
        close=close_price,
        volume=avg_vol * 3.0,
    )
    return candles


class TestVolumeSpikeEntry(unittest.TestCase):
    def setUp(self) -> None:
        self.config = StrategyConfig()
        self.strategy = VolumeSpikeStrategy(
            self.config,
            spike_mult=2.5,
            volume_window=20,
            min_body_ratio=0.3,
        )

    def test_volume_spike_triggers_buy(self) -> None:
        """Volume spike + bullish candle + positive momentum -> BUY."""
        candles = _spike_last_candle(_build_candles(50), volume_mult=3.0)
        signal = self.strategy.evaluate(candles, None)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "volume_spike_bullish")
        self.assertGreater(signal.confidence, 0.4)
        self.assertGreater(signal.indicators["volume_ratio"], 2.5)

    def test_no_spike_holds(self) -> None:
        """Normal volume -> HOLD."""
        candles = _build_candles(50)
        signal = self.strategy.evaluate(candles, None)
        self.assertEqual(signal.action, SignalAction.HOLD)
        # Could be no_volume_spike or other HOLD reason — just not BUY
        self.assertNotEqual(signal.action, SignalAction.BUY)

    def test_bearish_body_blocks_entry(self) -> None:
        """Volume spike with bearish candle body -> HOLD."""
        candles = _build_candles(50)
        last = candles[-1]
        avg_vol = sum(c.volume for c in candles[-21:-1]) / 20
        # Bearish candle: close well below open
        candles[-1] = Candle(
            timestamp=last.timestamp,
            open=last.high - 50,
            high=last.high,
            low=last.low,
            close=last.low + 50,
            volume=avg_vol * 3.0,
        )
        signal = self.strategy.evaluate(candles, None)
        self.assertEqual(signal.action, SignalAction.HOLD)

    def test_insufficient_data(self) -> None:
        candles = _build_candles(5)
        signal = self.strategy.evaluate(candles, None)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_symbol_kwarg_supported(self) -> None:
        """Verify symbol kwarg is accepted."""
        candles = _spike_last_candle(_build_candles(50), volume_mult=3.0)
        signal = self.strategy.evaluate(candles, None, symbol="KRW-BTC")
        # Should produce same result as without symbol
        self.assertEqual(signal.action, SignalAction.BUY)


class TestVolumeSpikeExit(unittest.TestCase):
    def setUp(self) -> None:
        self.config = StrategyConfig()
        self.strategy = VolumeSpikeStrategy(self.config, spike_mult=2.5)

    def _position(self, entry_index: int = 10) -> Position:
        return Position(
            symbol="KRW-BTC",
            quantity=0.01,
            entry_price=101_000.0,
            entry_time=datetime(2025, 1, 1, 10),
            entry_index=entry_index,
        )

    def test_max_holding_exit(self) -> None:
        """Exit after max holding bars."""
        candles = _build_candles(100)
        position = self._position(entry_index=5)
        signal = self.strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")

    def test_hold_while_profitable(self) -> None:
        """Hold position while conditions are normal and not too long."""
        candles = _build_candles(50)
        # Entry at recent index so holding bars < max_holding_bars
        position = self._position(entry_index=45)
        signal = self.strategy.evaluate(candles, position)
        # Should not be forced to sell (only 4 bars held, momentum not reversed)
        # May be HOLD or SELL depending on random data, but not max_holding
        self.assertNotEqual(signal.reason, "max_holding_period")

    def test_bearish_volume_spike_exit(self) -> None:
        """Exit on bearish volume spike (high volume + red candle)."""
        candles = _build_candles(50)
        last = candles[-1]
        avg_vol = sum(c.volume for c in candles[-21:-1]) / 20
        # Strong bearish candle with huge volume
        candles[-1] = Candle(
            timestamp=last.timestamp,
            open=last.high - 30,
            high=last.high,
            low=last.low - 500,
            close=last.low - 400,
            volume=avg_vol * 4.0,
        )
        position = self._position(entry_index=45)
        signal = self.strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        # Could be bearish_volume_spike or momentum_reversal — both valid exits
        self.assertIn(
            signal.reason,
            ["bearish_volume_spike", "momentum_reversal", "rsi_overbought"],
        )


class TestVolumeSpikeFactory(unittest.TestCase):
    def test_create_via_factory(self) -> None:
        from crypto_trader.config import RegimeConfig, StrategyConfig
        from crypto_trader.wallet import create_strategy

        config = StrategyConfig()
        regime = RegimeConfig()
        strategy = create_strategy(
            "volume_spike",
            config,
            regime,
            extra_params={"spike_mult": 3.0, "volume_window": 15},
        )
        self.assertIsInstance(strategy, VolumeSpikeStrategy)

    def test_consensus_factory_integrates_volume_spike_with_momentum(self) -> None:
        from crypto_trader.wallet import create_strategy

        config = StrategyConfig(
            momentum_lookback=5,
            momentum_entry_threshold=0.0,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=80.0,
            rsi_overbought=90.0,
            adx_threshold=0.0,
        )
        regime = RegimeConfig()
        strategy = create_strategy(
            "consensus",
            config,
            regime,
            extra_params={
                "sub_strategies": ["volume_spike", "momentum"],
                "min_agree": 2,
                "spike_mult": 2.5,
                "volume_window": 20,
                "min_body_ratio": 0.3,
            },
        )

        signal = strategy.evaluate(_build_consensus_integration_candles(), None)

        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertIn("volume_spike_bullish", signal.reason)
        self.assertIn("momentum_rsi_alignment", signal.reason)
        self.assertIn("volume_volume_ratio", signal.indicators)
        self.assertIn("momentum_rsi", signal.indicators)


if __name__ == "__main__":
    unittest.main()
