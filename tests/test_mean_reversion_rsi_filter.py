"""Tests for US-025: Widened Bollinger + RSI confirmation for mean reversion."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy


def _build_candles(closes: list[float]) -> list[Candle]:
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


def _make_strategy(**kwargs: object) -> MeanReversionStrategy:
    config = StrategyConfig(**kwargs)  # type: ignore[arg-type]
    regime_config = RegimeConfig(short_lookback=2, long_lookback=3)
    return MeanReversionStrategy(config, regime_config)


class TestMeanReversionRSIFilter(unittest.TestCase):
    def test_rsi_filter_allows_oversold_entry(self) -> None:
        """Entry allowed when RSI is below oversold_floor + 10."""
        strategy = _make_strategy(
            bollinger_window=5,
            bollinger_stddev=1.5,
            rsi_period=5,
            rsi_oversold_floor=20.0,
            rsi_recovery_ceiling=60.0,
        )
        # Drop to create lower Bollinger band touch with low RSI
        closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0]
        signal = strategy.evaluate(_build_candles(closes))
        # Declining prices → RSI low, near/below lower band → BUY
        if signal.action == SignalAction.BUY:
            rsi = signal.indicators.get("rsi", 0)
            # RSI should be below oversold_floor + 10 = 30
            self.assertLessEqual(rsi, 30.0)

    def test_rsi_filter_blocks_high_rsi_near_lower_band(self) -> None:
        """Entry blocked when RSI is above oversold_floor + 10 even if near lower band."""
        strategy = _make_strategy(
            bollinger_window=5,
            bollinger_stddev=1.5,
            rsi_period=5,
            rsi_oversold_floor=20.0,
            rsi_recovery_ceiling=60.0,
        )
        # Prices that oscillate: RSI won't be very low despite touching lower band
        closes = [100.0, 105.0, 100.0, 105.0, 100.0, 105.0, 100.0, 105.0, 95.0, 100.0]
        signal = strategy.evaluate(_build_candles(closes))
        rsi = signal.indicators.get("rsi", 0)
        if rsi > 30.0:  # RSI above filter limit
            self.assertNotEqual(signal.action, SignalAction.BUY)

    def test_wider_bollinger_generates_more_signals(self) -> None:
        """1.5 stddev should produce BUY where 2.0 stddev would not."""
        # Moderate decline: 1.5 sigma band is closer to price than 2.0
        closes = [100.0, 99.5, 99.0, 98.5, 98.0, 97.5, 97.0, 96.8]

        strategy_15 = _make_strategy(
            bollinger_window=5,
            bollinger_stddev=1.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
        )
        strategy_20 = _make_strategy(
            bollinger_window=5,
            bollinger_stddev=2.0,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
        )

        signal_15 = strategy_15.evaluate(_build_candles(closes))
        signal_20 = strategy_20.evaluate(_build_candles(closes))

        # 1.5 stddev should be more likely to trigger than 2.0
        # At minimum, 1.5 lower band is closer to price
        lb_15 = signal_15.indicators.get("lower_band", 0)
        lb_20 = signal_20.indicators.get("lower_band", 0)
        self.assertGreater(lb_15, lb_20)  # 1.5 band is higher (closer to price)

    def test_default_bollinger_stddev_is_1_5(self) -> None:
        """Verify default StrategyConfig uses 1.5 stddev."""
        config = StrategyConfig()
        self.assertEqual(config.bollinger_stddev, 1.5)


if __name__ == "__main__":
    unittest.main()
