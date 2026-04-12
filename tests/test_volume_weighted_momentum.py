"""Parity tests for VolumeWeightedMomentumStrategy.

Fixtures from auto-research-engine parity spec §5.
Tolerance: |score - expected| < 1e-6.
"""
from __future__ import annotations

from datetime import datetime

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction


def _ts(i: int) -> datetime:
    return datetime(2026, 1, 1, i % 24)


def _make_fixture_1() -> list[Candle]:
    """30 bars, +0.1%/bar, volume=1000."""
    bars: list[Candle] = []
    prev = 100.0
    for i in range(30):
        cl = prev * 1.001
        bars.append(Candle(
            timestamp=_ts(i), open=prev, high=cl + 0.05,
            low=prev - 0.05, close=cl, volume=1000.0,
        ))
        prev = cl
    return bars


def _make_fixture_2() -> list[Candle]:
    """30 bars, flat close=100, volume=1000."""
    return [
        Candle(
            timestamp=_ts(i), open=100.0, high=100.0,
            low=100.0, close=100.0, volume=1000.0,
        )
        for i in range(30)
    ]


def _make_fixture_3() -> list[Candle]:
    """30 bars, -0.1%/bar, volume=1000."""
    bars: list[Candle] = []
    prev = 100.0
    for i in range(30):
        cl = prev * 0.999
        bars.append(Candle(
            timestamp=_ts(i), open=prev, high=prev + 0.05,
            low=cl - 0.05, close=cl, volume=1000.0,
        ))
        prev = cl
    return bars


def _make_fixture_4() -> list[Candle]:
    """24 bars alternating (-0.1% vol=10000, +0.3% vol=100), then 6 bars +0.1% vol=1000."""
    bars: list[Candle] = []
    prev = 100.0
    for i in range(24):
        if i % 2 == 0:
            cl = prev * 0.999
            vol = 10000.0
        else:
            cl = prev * 1.003
            vol = 100.0
        bars.append(Candle(
            timestamp=_ts(i), open=prev, high=max(cl, prev) + 0.05,
            low=min(cl, prev) - 0.05, close=cl, volume=vol,
        ))
        prev = cl
    for i in range(24, 30):
        cl = prev * 1.001
        bars.append(Candle(
            timestamp=_ts(i), open=prev, high=cl + 0.05,
            low=prev - 0.05, close=cl, volume=1000.0,
        ))
        prev = cl
    return bars


class TestVWMSignalParity:
    """Core signal parity tests — no gates, no exit."""

    def test_fixture_1_buy_positive_vwm(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )

        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_1())
        assert sig[24].action == SignalAction.BUY
        assert abs(sig[24].score - 0.565838) < 1e-6

    def test_fixture_2_hold_zero_vwm(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )

        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_2())
        assert sig[24].action == SignalAction.HOLD
        assert sig[24].score == 0.5

    def test_fixture_3_hold_negative_vwm(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )

        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_3())
        assert sig[24].action == SignalAction.HOLD
        assert abs(sig[24].score - 0.434162) < 1e-6

    def test_fixture_4_hold_volume_weighted_asymmetry(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )

        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_4())
        assert sig[24].action == SignalAction.HOLD
        assert abs(sig[24].score - 0.438110) < 1e-6


class TestVWMWarmup:
    """Warmup boundary: i < period -> HOLD with score 0.0."""

    def test_bar_23_is_warmup(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )

        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_1())
        assert sig[23].action == SignalAction.HOLD
        assert sig[23].score == 0.0

    def test_bar_24_is_first_signal(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )

        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_1())
        assert sig[24].score != 0.0
