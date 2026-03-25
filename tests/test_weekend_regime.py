from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.regime import (
    KST,
    WEEKEND_POSITION_MULTIPLIER,
    MarketRegime,
    RegimeDetector,
    is_weekend_kst,
)


def _build_candles_at(
    dt: datetime, count: int = 40, close: float = 100_000.0,
) -> list[Candle]:
    """Build candles ending at the given datetime."""
    return [
        Candle(
            timestamp=dt - timedelta(hours=count - 1 - i),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=1000.0,
        )
        for i in range(count)
    ]


class TestIsWeekendKST(unittest.TestCase):
    def test_saturday_morning_is_weekend(self) -> None:
        sat_morning = datetime(2026, 3, 28, 3, 0, tzinfo=KST)  # Saturday 3AM KST
        self.assertTrue(is_weekend_kst(sat_morning))

    def test_sunday_afternoon_is_weekend(self) -> None:
        sun_pm = datetime(2026, 3, 29, 15, 0, tzinfo=KST)  # Sunday 3PM KST
        self.assertTrue(is_weekend_kst(sun_pm))

    def test_monday_before_9am_is_weekend(self) -> None:
        mon_early = datetime(2026, 3, 30, 8, 0, tzinfo=KST)  # Monday 8AM KST
        self.assertTrue(is_weekend_kst(mon_early))

    def test_monday_after_9am_is_not_weekend(self) -> None:
        mon_open = datetime(2026, 3, 30, 9, 0, tzinfo=KST)  # Monday 9AM KST
        self.assertFalse(is_weekend_kst(mon_open))

    def test_wednesday_is_not_weekend(self) -> None:
        wed = datetime(2026, 3, 25, 14, 0, tzinfo=KST)  # Wednesday 2PM KST
        self.assertFalse(is_weekend_kst(wed))

    def test_friday_evening_is_not_weekend(self) -> None:
        fri_eve = datetime(2026, 3, 27, 23, 0, tzinfo=KST)  # Friday 11PM KST
        self.assertFalse(is_weekend_kst(fri_eve))

    def test_utc_conversion_saturday(self) -> None:
        # Saturday 00:30 KST = Friday 15:30 UTC
        utc_time = datetime(2026, 3, 27, 15, 30, tzinfo=UTC)
        self.assertTrue(is_weekend_kst(utc_time))


class TestRegimeAnalysisWeekend(unittest.TestCase):
    def test_analyze_detects_weekend(self) -> None:
        detector = RegimeDetector(RegimeConfig())
        sat = datetime(2026, 3, 28, 12, 0, tzinfo=KST)
        candles = _build_candles_at(sat)
        analysis = detector.analyze(candles)
        self.assertTrue(analysis.is_weekend)

    def test_analyze_detects_weekday(self) -> None:
        detector = RegimeDetector(RegimeConfig())
        wed = datetime(2026, 3, 25, 12, 0, tzinfo=KST)
        candles = _build_candles_at(wed)
        analysis = detector.analyze(candles)
        self.assertFalse(analysis.is_weekend)


class TestWeekendAdjust(unittest.TestCase):
    def test_weekend_tightens_parameters(self) -> None:
        detector = RegimeDetector(RegimeConfig())
        base = StrategyConfig()
        adjusted = detector.adjust(base, MarketRegime.SIDEWAYS, is_weekend=True)
        self.assertGreater(adjusted.momentum_entry_threshold, base.momentum_entry_threshold)
        self.assertLess(adjusted.rsi_recovery_ceiling, base.rsi_recovery_ceiling)
        self.assertLess(adjusted.max_holding_bars, base.max_holding_bars)

    def test_weekday_sideways_unchanged(self) -> None:
        detector = RegimeDetector(RegimeConfig())
        base = StrategyConfig()
        adjusted = detector.adjust(base, MarketRegime.SIDEWAYS, is_weekend=False)
        self.assertEqual(adjusted, base)

    def test_weekend_bull_combines_adjustments(self) -> None:
        detector = RegimeDetector(RegimeConfig())
        base = StrategyConfig()
        bull_only = detector.adjust(base, MarketRegime.BULL, is_weekend=False)
        bull_weekend = detector.adjust(base, MarketRegime.BULL, is_weekend=True)
        self.assertGreater(
            bull_weekend.momentum_entry_threshold,
            bull_only.momentum_entry_threshold,
        )
        self.assertLess(bull_weekend.max_holding_bars, bull_only.max_holding_bars)

    def test_weekend_multiplier_is_half(self) -> None:
        self.assertEqual(WEEKEND_POSITION_MULTIPLIER, 0.5)


if __name__ == "__main__":
    unittest.main()
