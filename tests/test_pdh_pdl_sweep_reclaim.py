"""Parity tests for PdhPdlSweepReclaimStrategy.

Fixtures from auto-research-engine parity spec §5.
Tolerance: |score - expected| < 1e-6.
"""
from __future__ import annotations

from datetime import datetime

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction


def _ts(i: int) -> datetime:
    return datetime(2026, 1, 1, i % 24)


def _base_candle(i: int) -> Candle:
    return Candle(
        timestamp=_ts(i), open=100.0, high=100.3,
        low=99.7, close=100.05, volume=1000.0,
    )


def _pdl_candle(i: int) -> Candle:
    return Candle(
        timestamp=_ts(i), open=99.4, high=99.6,
        low=99.2, close=99.5, volume=1200.0,
    )


def _make_series(bar95_override: Candle | None = None) -> list[Candle]:
    """100-bar series with PDL dip at [60..70].

    If bar95_override is given, replace bar 95 with it.
    """
    bars = [_base_candle(i) for i in range(100)]
    for i in range(60, 71):
        bars[i] = _pdl_candle(i)
    if bar95_override is not None:
        bars[95] = bar95_override
    return bars


# Candidate A params
_PARAMS: dict[str, object] = dict(
    use_prev_day=True,
    n=22,
    eps=0.0018262133038232326,
    L=93,
    clv_min=0.6868883402451547,
    rvol_min=2.076067713758879,
    hold_bars=3,
)


class TestPdhPdlSignalParity:
    """Core signal parity -- no gates, no exit."""

    def test_fixture_1_buy_all_flags(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )

        bars = _make_series(Candle(
            timestamp=_ts(95), open=99.3, high=99.40,
            low=98.90, close=99.35, volume=2500.0,
        ))
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        assert sig[95].action == SignalAction.BUY
        assert abs(sig[95].score - 0.999447) < 1e-6

    def test_fixture_2_hold_reclaim_fails(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )

        bars = _make_series(Candle(
            timestamp=_ts(95), open=99.3, high=99.55,
            low=98.90, close=99.10, volume=2500.0,
        ))
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        assert sig[95].action == SignalAction.HOLD
        assert abs(sig[95].score - 0.075858) < 1e-6

    def test_fixture_3_hold_no_sweep(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )

        bars = _make_series()  # bar 95 = base candle, no sweep
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        assert sig[95].action == SignalAction.HOLD
        assert abs(sig[95].score - 0.000553) < 1e-6


class TestPdhPdlWarmup:
    """Warmup boundary: bar < 93 -> HOLD with score 0.0."""

    def test_bar_92_is_warmup(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )

        bars = _make_series()
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        assert sig[92].action == SignalAction.HOLD
        assert sig[92].score == 0.0

    def test_bar_93_is_first_computed(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )

        bars = _make_series()
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        # bar 93: base bar -> flags=1 (only reclaim) -> score ~0.000553
        assert sig[93].score != 0.0
        assert abs(sig[93].score - 0.000553) < 1e-6
