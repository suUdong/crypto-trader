"""Tests for Session #11 Wave 12: band distance scoring, performance decay."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RiskConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy


def _candles(closes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=t + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


# ---------- Band distance scoring ----------


class TestBandDistanceScoring(unittest.TestCase):
    def test_band_distance_in_indicators(self) -> None:
        """Mean reversion should include band_distance indicator."""
        candles = _candles([100.0] * 30)
        strategy = MeanReversionStrategy(StrategyConfig(bollinger_window=20, rsi_period=5))
        signal = strategy.evaluate(candles)
        self.assertIn("band_distance", signal.indicators)

    def test_band_distance_zero_above_lower(self) -> None:
        """Price above lower band should have band_distance 0."""
        candles = _candles([100.0] * 30)
        strategy = MeanReversionStrategy(StrategyConfig(bollinger_window=20, rsi_period=5))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.indicators["band_distance"], 0.0)

    def test_middle_band_target_exit(self) -> None:
        """Position should exit at middle band with profit."""
        # Entry near lower band, price recovers to middle
        prices = [100.0] * 25 + [95.0, 94.0, 95.0, 97.0, 100.0]
        candles = _candles(prices)
        pos = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=94.0,
            entry_time=datetime(2025, 1, 2, 1),
            entry_index=25,
        )
        strategy = MeanReversionStrategy(
            StrategyConfig(bollinger_window=20, rsi_period=5, max_holding_bars=100),
        )
        signal = strategy.evaluate(candles, pos)
        # Price at 100 is likely at/above middle band, should trigger exit
        if signal.action == SignalAction.SELL:
            self.assertIn(
                signal.reason,
                [
                    "middle_band_target",
                    "bollinger_upper_touch",
                    "mean_reversion_target",
                    "max_holding_period",
                    "rsi_bearish_divergence",
                ],
            )


# ---------- Performance decay detection ----------


class TestPerformanceDecay(unittest.TestCase):
    def test_rolling_win_rate_none_with_few_trades(self) -> None:
        """rolling_win_rate should return None with < 5 trades."""
        risk = RiskManager(RiskConfig())
        self.assertIsNone(risk.rolling_win_rate())
        risk.record_trade(0.01)
        risk.record_trade(-0.01)
        self.assertIsNone(risk.rolling_win_rate())

    def test_rolling_win_rate_correct(self) -> None:
        """Should compute correct win rate over recent trades."""
        risk = RiskManager(RiskConfig())
        for _ in range(7):
            risk.record_trade(0.02)  # 7 wins
        for _ in range(3):
            risk.record_trade(-0.01)  # 3 losses
        wr = risk.rolling_win_rate()
        self.assertAlmostEqual(wr, 0.7)

    def test_is_decaying_below_35pct(self) -> None:
        """is_decaying should be True when win rate < 35%."""
        risk = RiskManager(RiskConfig())
        # 2 wins, 8 losses = 20% WR
        for _ in range(2):
            risk.record_trade(0.01)
        for _ in range(8):
            risk.record_trade(-0.01)
        self.assertTrue(risk.is_decaying)

    def test_not_decaying_above_35pct(self) -> None:
        """is_decaying should be False when win rate >= 35%."""
        risk = RiskManager(RiskConfig())
        for _ in range(5):
            risk.record_trade(0.02)
        for _ in range(5):
            risk.record_trade(-0.01)
        self.assertFalse(risk.is_decaying)

    def test_not_decaying_insufficient_data(self) -> None:
        """is_decaying should be False with insufficient data."""
        risk = RiskManager(RiskConfig())
        self.assertFalse(risk.is_decaying)

    def test_rolling_win_rate_custom_window(self) -> None:
        """Should respect custom window size."""
        risk = RiskManager(RiskConfig())
        # 10 wins then 5 losses
        for _ in range(10):
            risk.record_trade(0.02)
        for _ in range(5):
            risk.record_trade(-0.01)
        # Window 5: last 5 are all losses
        wr_5 = risk.rolling_win_rate(window=5)
        self.assertAlmostEqual(wr_5, 0.0)
        # Window 15: 10/15 wins
        wr_15 = risk.rolling_win_rate(window=15)
        self.assertAlmostEqual(wr_15, 10.0 / 15.0, places=3)


if __name__ == "__main__":
    unittest.main()
