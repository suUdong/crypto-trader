"""Parity tests for volume_weighted_momentum strategy.

Fixtures from: auto-research-engine/docs/specs/2026-04-12-crypto-trader-vwm-parity-spec.md
Tolerance: 1e-6 absolute score error.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.volume_weighted_momentum import (
    VolumeWeightedMomentumStrategy,
)

TOLERANCE = 1e-6
# Candidate A alpha from parity spec
CANDIDATE_ALPHA = 264.8908943094896


def _make_config() -> StrategyConfig:
    return StrategyConfig()


def _make_strategy() -> VolumeWeightedMomentumStrategy:
    """Candidate A params: period=24, alpha=264.89."""
    return VolumeWeightedMomentumStrategy(
        _make_config(),
        period=24,
        alpha=CANDIDATE_ALPHA,
    )


def _ts() -> datetime:
    return datetime(2025, 1, 1)


class TestVwmParityFixtures:
    """§5 parity test fixtures from ARE spec."""

    def test_fixture1_buy_positive_momentum(self) -> None:
        """§5.1: +0.1% per bar → BUY, score ≈ 0.565838."""
        bars: list[Candle] = []
        prev = 100.0
        for _ in range(30):
            cl = prev * 1.001
            bars.append(Candle(
                timestamp=_ts(), open=prev, high=cl + 0.05,
                low=prev - 0.05, close=cl, volume=1000.0,
            ))
            prev = cl

        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        assert signals[24].action == SignalAction.BUY
        assert abs(signals[24].score - 0.565838) < TOLERANCE

        # Steady state: bars 25-29 should also be BUY with same score
        for i in range(25, 30):
            assert signals[i].action == SignalAction.BUY
            assert abs(signals[i].score - 0.565838) < TOLERANCE

    def test_fixture2_hold_zero_momentum(self) -> None:
        """§5.2: flat close=100 → HOLD, score = 0.5 exactly."""
        bars = [
            Candle(timestamp=_ts(), open=100.0, high=100.0,
                   low=100.0, close=100.0, volume=1000.0)
            for _ in range(30)
        ]

        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        assert signals[24].action == SignalAction.HOLD
        assert signals[24].score == 0.5

    def test_fixture3_hold_negative_momentum(self) -> None:
        """§5.3: -0.1% per bar → HOLD, score ≈ 0.434162."""
        bars: list[Candle] = []
        prev = 100.0
        for _ in range(30):
            cl = prev * 0.999
            bars.append(Candle(
                timestamp=_ts(), open=prev, high=prev + 0.05,
                low=cl - 0.05, close=cl, volume=1000.0,
            ))
            prev = cl

        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        assert signals[24].action == SignalAction.HOLD
        assert abs(signals[24].score - 0.434162) < TOLERANCE

    def test_fixture4_hold_volume_asymmetry(self) -> None:
        """§5.4: volume-weighted asymmetry → HOLD, score ≈ 0.438110."""
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
                timestamp=_ts(), open=prev,
                high=max(cl, prev) + 0.05,
                low=min(cl, prev) - 0.05,
                close=cl, volume=vol,
            ))
            prev = cl
        for _ in range(24, 30):
            cl = prev * 1.001
            bars.append(Candle(
                timestamp=_ts(), open=prev, high=cl + 0.05,
                low=prev - 0.05, close=cl, volume=1000.0,
            ))
            prev = cl

        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        assert signals[24].action == SignalAction.HOLD
        assert abs(signals[24].score - 0.438110) < TOLERANCE

    def test_warmup_bars_are_hold(self) -> None:
        """Bars 0..23 should all be HOLD with score 0.0."""
        bars = [
            Candle(timestamp=_ts(), open=100.0, high=100.0,
                   low=100.0, close=100.0, volume=1000.0)
            for _ in range(30)
        ]
        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        for i in range(24):
            assert signals[i].action == SignalAction.HOLD
            assert signals[i].score == 0.0

    def test_signal_count_matches_bars(self) -> None:
        """generate_signals returns exactly len(candles) signals."""
        bars = [
            Candle(timestamp=_ts(), open=100.0, high=100.0,
                   low=100.0, close=100.0, volume=1000.0)
            for _ in range(30)
        ]
        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)
        assert len(signals) == 30
