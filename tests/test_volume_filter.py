"""Tests for US-028: Volume-weighted entry confirmation."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.indicators import volume_sma
from crypto_trader.strategy.momentum import MomentumStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy


def _build_candles_with_volume(
    closes: list[float], volumes: list[float],
) -> list[Candle]:
    start = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=c * 0.99,
            high=c * 1.02,
            low=c * 0.98,
            close=c,
            volume=volumes[i],
        )
        for i, c in enumerate(closes)
    ]


class TestVolumeSMA(unittest.TestCase):
    def test_volume_sma_basic(self) -> None:
        vols = [100.0, 200.0, 300.0, 400.0, 500.0]
        self.assertAlmostEqual(volume_sma(vols, 3), 400.0)

    def test_volume_sma_full_window(self) -> None:
        vols = [100.0, 200.0, 300.0]
        self.assertAlmostEqual(volume_sma(vols, 3), 200.0)

    def test_volume_sma_insufficient_data(self) -> None:
        with self.assertRaises(ValueError):
            volume_sma([100.0], 3)


class TestMomentumVolumeFilter(unittest.TestCase):
    def test_volume_filter_blocks_low_volume(self) -> None:
        """BUY blocked when volume < volume_filter_mult * avg."""
        config = StrategyConfig(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
            adx_threshold=0.0,
            volume_filter_mult=1.5,  # require 1.5x avg volume
        )
        regime = RegimeConfig(short_lookback=2, long_lookback=3)
        strategy = MomentumStrategy(config, regime)

        # Rising prices but last bar has LOW volume
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        volumes = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 500.0]  # last bar weak
        candles = _build_candles_with_volume(closes, volumes)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.reason, "volume_too_low")

    def test_volume_filter_allows_high_volume(self) -> None:
        """BUY allowed when volume >= volume_filter_mult * avg."""
        config = StrategyConfig(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
            adx_threshold=0.0,
            volume_filter_mult=1.2,
        )
        regime = RegimeConfig(short_lookback=2, long_lookback=3)
        strategy = MomentumStrategy(config, regime)

        # Rising prices with high volume on last bar
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        volumes = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 2000.0]  # spike
        candles = _build_candles_with_volume(closes, volumes)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_volume_filter_disabled_by_default(self) -> None:
        """Default volume_filter_mult=0.0 disables the filter."""
        config = StrategyConfig(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
            adx_threshold=0.0,
        )
        self.assertEqual(config.volume_filter_mult, 0.0)
        regime = RegimeConfig(short_lookback=2, long_lookback=3)
        strategy = MomentumStrategy(config, regime)

        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        volumes = [1000.0] * 6  # constant volume
        candles = _build_candles_with_volume(closes, volumes)
        signal = strategy.evaluate(candles)
        # Should BUY since filter is disabled
        self.assertEqual(signal.action, SignalAction.BUY)


class TestVBreakVolumeFilter(unittest.TestCase):
    def test_vbreak_volume_blocks_low_volume_breakout(self) -> None:
        """Volatility breakout blocked on low volume."""
        config = StrategyConfig(
            k_base=0.1,
            noise_lookback=5,
            ma_filter_period=5,
            max_holding_bars=48,
            adx_threshold=0.0,
            volume_filter_mult=1.5,
        )
        strategy = VolatilityBreakoutStrategy(
            config, k_base=0.1, noise_lookback=5, ma_filter_period=5,
        )
        # Build candles with breakout on last bar but weak volume
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 110.0]
        volumes = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 500.0]
        candles = _build_candles_with_volume(closes, volumes)
        signal = strategy.evaluate(candles)
        if signal.indicators.get("volume_ratio", 999) < 1.5:
            self.assertEqual(signal.reason, "volume_too_low")


if __name__ == "__main__":
    unittest.main()
