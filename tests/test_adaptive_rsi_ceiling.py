"""Tests for US-023: Adaptive RSI ceiling in MomentumStrategy."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.momentum import MomentumStrategy


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


def _make_strategy(**kwargs: object) -> MomentumStrategy:
    config = StrategyConfig(**kwargs)  # type: ignore[arg-type]
    regime_config = RegimeConfig(short_lookback=2, long_lookback=3)
    return MomentumStrategy(config, regime_config)


class TestAdaptiveRSICeiling(unittest.TestCase):
    def test_strong_momentum_widens_rsi_ceiling(self) -> None:
        """Strong momentum should widen the RSI ceiling above the base 60."""
        strategy = _make_strategy(
            momentum_lookback=3,
            momentum_entry_threshold=0.005,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=60.0,
            adx_threshold=0.0,  # disable ADX for this test
        )
        # Mix of ups and downs ending with uptrend: gives moderate RSI (~65)
        # while still having positive momentum
        closes = [100.0, 99.0, 100.5, 99.5, 101.0, 102.0]
        signal = strategy.evaluate(_build_candles(closes))
        # The ceiling should widen above 60
        self.assertIn("rsi_ceiling", signal.indicators)
        self.assertGreater(signal.indicators["rsi_ceiling"], 60.0)
        # If RSI falls within the widened range, BUY should trigger
        rsi_val = signal.indicators.get("rsi", 0)
        ceiling = signal.indicators["rsi_ceiling"]
        if rsi_val <= ceiling:
            self.assertEqual(signal.action, SignalAction.BUY)

    def test_weak_momentum_keeps_base_ceiling(self) -> None:
        """Weak momentum should not widen the RSI ceiling."""
        strategy = _make_strategy(
            momentum_lookback=3,
            momentum_entry_threshold=0.10,  # high threshold
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=60.0,
            adx_threshold=0.0,
        )
        # Flat prices: momentum near 0, won't exceed 0.10 threshold
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
        signal = strategy.evaluate(_build_candles(closes))
        self.assertEqual(signal.action, SignalAction.HOLD)
        # Ceiling stays at base 60 since momentum < threshold
        self.assertAlmostEqual(signal.indicators.get("rsi_ceiling", 60.0), 60.0)

    def test_ceiling_caps_at_80(self) -> None:
        """Even with extreme momentum, ceiling should not exceed 80."""
        strategy = _make_strategy(
            momentum_lookback=3,
            momentum_entry_threshold=0.001,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=50.0,
            adx_threshold=0.0,
        )
        # Strongly rising: momentum will be large
        closes = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        signal = strategy.evaluate(_build_candles(closes))
        self.assertLessEqual(signal.indicators.get("rsi_ceiling", 0), 80.0)

    def test_high_base_ceiling_not_reduced(self) -> None:
        """If base ceiling is already > 80, widening should not reduce it."""
        strategy = _make_strategy(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
            adx_threshold=0.0,
        )
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        signal = strategy.evaluate(_build_candles(closes))
        # Should BUY — base ceiling 100 is not reduced
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.indicators.get("rsi_ceiling"), 100.0)


if __name__ == "__main__":
    unittest.main()
