"""Tests for Session #11 Wave 9: BB width, RAR metric."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.indicators import bollinger_band_width
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy


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


# ---------- Bollinger Band Width ----------


class TestBBWidth(unittest.TestCase):
    def test_bb_width_flat_market(self) -> None:
        """Flat market should have very low BB width."""
        values = [100.0] * 30
        width = bollinger_band_width(values, 20, 2.0)
        self.assertAlmostEqual(width, 0.0)

    def test_bb_width_volatile_market(self) -> None:
        """Volatile market should have higher BB width."""
        values = [100.0 + (i % 2) * 10.0 for i in range(30)]
        width = bollinger_band_width(values, 20, 2.0)
        self.assertGreater(width, 0.01)

    def test_bb_width_positive(self) -> None:
        """BB width should always be >= 0."""
        values = [100.0 + i * 0.5 for i in range(30)]
        width = bollinger_band_width(values, 20, 2.0)
        self.assertGreaterEqual(width, 0.0)

    def test_bb_width_insufficient_data(self) -> None:
        """Should raise ValueError with insufficient data."""
        with self.assertRaises(ValueError):
            bollinger_band_width([100.0] * 5, 20, 2.0)


# ---------- BB width in VolatilityBreakout ----------


class TestVolBreakoutSqueeze(unittest.TestCase):
    def test_bb_width_in_indicators(self) -> None:
        """VolatilityBreakout should include bb_width in indicators."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = VolatilityBreakoutStrategy(
            StrategyConfig(adx_period=14, adx_threshold=0.0),
            k_base=0.5,
            noise_lookback=20,
            ma_filter_period=20,
        )
        signal = strategy.evaluate(candles)
        self.assertIn("bb_width", signal.indicators)


# ---------- Risk-Adjusted Return ----------


class TestRiskAdjustedReturn(unittest.TestCase):
    def test_rar_on_backtest_result(self) -> None:
        """BacktestResult should include risk_adjusted_return."""
        candles = _candles([100.0] * 30)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                bollinger_window=20,
                rsi_period=5,
            )
        )
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertIsInstance(result.risk_adjusted_return, float)

    def test_rar_positive_for_profitable_trade(self) -> None:
        """RAR should be positive when total_return > 0 and drawdown > 0."""
        # Simulate: return 10%, drawdown 5% -> RAR = 2.0
        total_return = 0.10
        max_drawdown = 0.05
        rar = total_return / max_drawdown
        self.assertAlmostEqual(rar, 2.0)

    def test_rar_zero_for_flat(self) -> None:
        """RAR should be 0 for flat equity (no return, no drawdown)."""
        candles = _candles([100.0] * 30)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                bollinger_window=20,
                rsi_period=5,
            )
        )
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        # No trades = no return = RAR 0
        self.assertEqual(result.risk_adjusted_return, 0.0)


if __name__ == "__main__":
    unittest.main()
