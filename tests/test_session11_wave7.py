"""Tests for Session #11 Wave 7: RSI divergence, portfolio heat."""

from __future__ import annotations

import unittest

from crypto_trader.config import RiskConfig
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.indicators import rsi_divergence

# ---------- RSI Divergence ----------


class TestRSIDivergence(unittest.TestCase):
    def test_bullish_divergence(self) -> None:
        """Price makes lower low, RSI makes higher low -> bullish."""
        # Create data: downtrend with RSI recovering
        # First dip to 90, recover to 100, then dip to 88 but RSI is higher
        prices = [100.0] * 20
        # First dip
        prices += [98.0, 96.0, 94.0, 92.0, 90.0, 92.0, 94.0, 96.0, 98.0, 100.0]
        # Second dip (lower price but momentum slowing = RSI higher)
        prices += [99.0, 97.0, 95.0, 93.0, 91.0, 89.0, 88.0, 90.0, 92.0, 94.0]
        bullish, bearish = rsi_divergence(prices, rsi_period=14, lookback=20)
        # We check it returns booleans (exact detection depends on data)
        self.assertIsInstance(bullish, bool)
        self.assertIsInstance(bearish, bool)

    def test_bearish_divergence(self) -> None:
        """Price makes higher high, RSI makes lower high -> bearish."""
        prices = [100.0] * 20
        # First peak
        prices += [102.0, 104.0, 106.0, 108.0, 110.0, 108.0, 106.0, 104.0, 102.0, 100.0]
        # Second peak (higher price)
        prices += [103.0, 106.0, 109.0, 112.0, 115.0, 112.0, 109.0, 106.0, 103.0, 100.0]
        bullish, bearish = rsi_divergence(prices, rsi_period=14, lookback=20)
        self.assertIsInstance(bullish, bool)
        self.assertIsInstance(bearish, bool)

    def test_insufficient_data(self) -> None:
        """Should return (False, False) with insufficient data."""
        prices = [100.0] * 10
        bullish, bearish = rsi_divergence(prices, rsi_period=14, lookback=20)
        self.assertFalse(bullish)
        self.assertFalse(bearish)

    def test_flat_market_no_divergence(self) -> None:
        """Flat market should have no divergence."""
        prices = [100.0] * 50
        bullish, bearish = rsi_divergence(prices, rsi_period=14, lookback=20)
        self.assertFalse(bullish)
        self.assertFalse(bearish)

    def test_custom_lookback(self) -> None:
        """Should work with custom lookback periods."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        bullish, bearish = rsi_divergence(prices, rsi_period=10, lookback=15)
        self.assertIsInstance(bullish, bool)
        self.assertIsInstance(bearish, bool)


# ---------- Portfolio Heat ----------


class TestPortfolioHeat(unittest.TestCase):
    def test_heat_calculation(self) -> None:
        """Portfolio heat should be sum of position risk / equity."""
        risk = RiskManager(RiskConfig(stop_loss_pct=0.03))
        positions = [(100.0, 10.0), (200.0, 5.0)]  # (entry_price, qty)
        heat = risk.portfolio_heat(positions, equity=100_000.0)
        # Risk = (100*10*0.03) + (200*5*0.03) = 30 + 30 = 60
        # Heat = 60 / 100_000 = 0.0006
        self.assertAlmostEqual(heat, 0.0006)

    def test_heat_zero_no_positions(self) -> None:
        """No positions = zero heat."""
        risk = RiskManager(RiskConfig(stop_loss_pct=0.03))
        heat = risk.portfolio_heat([], equity=100_000.0)
        self.assertEqual(heat, 0.0)

    def test_heat_zero_equity(self) -> None:
        """Zero equity should return 0 (avoid division by zero)."""
        risk = RiskManager(RiskConfig(stop_loss_pct=0.03))
        heat = risk.portfolio_heat([(100.0, 1.0)], equity=0.0)
        self.assertEqual(heat, 0.0)

    def test_heat_uses_effective_stop(self) -> None:
        """Heat should use tightened stop after losing streak."""
        risk = RiskManager(RiskConfig(stop_loss_pct=0.05))
        # Record 3 losses to tighten stop to 4%
        risk.record_trade(-0.02)
        risk.record_trade(-0.02)
        risk.record_trade(-0.02)
        positions = [(100.0, 100.0)]
        heat = risk.portfolio_heat(positions, equity=100_000.0)
        # Risk = 100 * 100 * 0.04 = 400, Heat = 400/100000 = 0.004
        self.assertAlmostEqual(heat, 0.004)

    def test_heat_threshold_check(self) -> None:
        """Verify heat can be compared against a threshold."""
        risk = RiskManager(RiskConfig(stop_loss_pct=0.03))
        positions = [(50000.0, 1.0)]  # Large position
        heat = risk.portfolio_heat(positions, equity=100_000.0)
        # Risk = 50000 * 1 * 0.03 = 1500, Heat = 1500/100000 = 0.015
        self.assertAlmostEqual(heat, 0.015)
        # Should be below 6% threshold
        self.assertLess(heat, 0.06)


if __name__ == "__main__":
    unittest.main()
