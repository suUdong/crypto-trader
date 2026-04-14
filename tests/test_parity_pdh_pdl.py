"""Parity tests for pdh_pdl_sweep_reclaim strategy.

Fixtures from: auto-research-engine/docs/specs/2026-04-12-crypto-trader-pdh-pdl-parity-spec.md
Tolerance: 1e-6 absolute score error.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
    PdhPdlSweepReclaimStrategy,
)

TOLERANCE = 1e-6


def _make_config() -> StrategyConfig:
    return StrategyConfig()


def _base_candle() -> Candle:
    return Candle(
        timestamp=datetime(2025, 1, 1),
        open=100.0, high=100.3, low=99.7, close=100.05, volume=1000.0,
    )


def _pdl_candle() -> Candle:
    return Candle(
        timestamp=datetime(2025, 1, 1),
        open=99.4, high=99.6, low=99.2, close=99.5, volume=1200.0,
    )


def _build_100bar_series(bar95_override: Candle | None = None) -> list[Candle]:
    """100-bar series with PDL dip at 60..70, optional bar 95 override."""
    bars: list[Candle] = []
    for i in range(100):
        if 60 <= i <= 70:
            bars.append(_pdl_candle())
        elif i == 95 and bar95_override is not None:
            bars.append(bar95_override)
        else:
            bars.append(_base_candle())
    return bars


def _make_strategy() -> PdhPdlSweepReclaimStrategy:
    """Candidate A params (defaults match spec)."""
    return PdhPdlSweepReclaimStrategy(_make_config())


class TestPdhPdlParityFixtures:
    """§5 parity test fixtures from ARE spec."""

    def test_fixture1_buy_all_flags(self) -> None:
        """§5.1: all 4 flags fire at bar 95 → BUY, score ≈ 0.999447."""
        bar95 = Candle(
            timestamp=datetime(2025, 1, 1),
            open=99.3, high=99.40, low=98.90, close=99.35, volume=2500.0,
        )
        bars = _build_100bar_series(bar95_override=bar95)
        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        assert signals[95].action == SignalAction.BUY
        assert abs(signals[95].score - 0.999447) < TOLERANCE

        # Surrounding bars should be HOLD
        assert signals[93].action == SignalAction.HOLD
        assert signals[94].action == SignalAction.HOLD
        assert signals[96].action == SignalAction.HOLD

    def test_fixture2_hold_reclaim_fails(self) -> None:
        """§5.2: close below ref_low → reclaim fails, score ≈ 0.075858."""
        bar95 = Candle(
            timestamp=datetime(2025, 1, 1),
            open=99.3, high=99.55, low=98.90, close=99.10, volume=2500.0,
        )
        bars = _build_100bar_series(bar95_override=bar95)
        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        assert signals[95].action == SignalAction.HOLD
        assert abs(signals[95].score - 0.075858) < TOLERANCE

    def test_fixture3_hold_no_sweep(self) -> None:
        """§5.3: base bar at 95, no sweep → score ≈ 0.000553."""
        bars = _build_100bar_series(bar95_override=None)
        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        assert signals[95].action == SignalAction.HOLD
        assert abs(signals[95].score - 0.000553) < TOLERANCE

    def test_warmup_bars_are_hold(self) -> None:
        """Bars 0..92 should all be HOLD with score 0.0."""
        bars = _build_100bar_series()
        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)

        for i in range(93):
            assert signals[i].action == SignalAction.HOLD
            assert signals[i].score == 0.0

    def test_signal_count_matches_bars(self) -> None:
        """generate_signals returns exactly len(candles) signals."""
        bars = _build_100bar_series()
        strategy = _make_strategy()
        signals = strategy.generate_signals(bars)
        assert len(signals) == 100
