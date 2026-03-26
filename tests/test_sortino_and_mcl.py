"""Tests for Sortino ratio and max_consecutive_losses metrics."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.backtest.grid_wf import _approx_sharpe, _approx_sortino
from crypto_trader.config import BacktestConfig, RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import create_strategy


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


class TestApproxSortino(unittest.TestCase):
    def test_sortino_returns_zero_for_short_curve(self) -> None:
        self.assertEqual(_approx_sortino([100.0, 101.0]), 0.0)

    def test_sortino_returns_zero_for_empty(self) -> None:
        self.assertEqual(_approx_sortino([]), 0.0)

    def test_sortino_positive_for_uptrend(self) -> None:
        curve = [100.0 + i * 0.5 for i in range(50)]
        # Inject some small dips to create downside returns
        curve[10] = curve[9] - 0.1
        curve[20] = curve[19] - 0.1
        result = _approx_sortino(curve)
        self.assertGreater(result, 0.0)

    def test_sortino_negative_for_downtrend(self) -> None:
        curve = [100.0 - i * 0.5 for i in range(50)]
        result = _approx_sortino(curve)
        self.assertLess(result, 0.0)

    def test_sortino_inf_when_no_downside(self) -> None:
        # Monotonically increasing -> no negative returns
        curve = [100.0 + i for i in range(10)]
        result = _approx_sortino(curve)
        self.assertEqual(result, float("inf"))

    def test_sortino_greater_than_sharpe_for_asymmetric_returns(self) -> None:
        """Sortino should be higher than Sharpe when upside volatility dominates."""
        # Many small gains, few small losses
        curve = [100.0]
        for i in range(100):
            if i % 10 == 0:
                curve.append(curve[-1] * 0.999)  # small loss
            else:
                curve.append(curve[-1] * 1.002)  # small gain
        sharpe = _approx_sharpe(curve)
        sortino = _approx_sortino(curve)
        # Sortino penalizes only downside, so should be >= Sharpe
        self.assertGreaterEqual(sortino, sharpe)


class TestMaxConsecutiveLosses(unittest.TestCase):
    def test_max_consecutive_losses_with_trades(self) -> None:
        """Engine calculates max consecutive losses from trade log."""
        # Create candles with clear pattern to generate trades
        closes = [100.0] * 20
        # Add drops to trigger entries and losses
        for _ in range(3):
            closes.extend([95.0, 93.0, 91.0, 89.0, 92.0, 95.0, 98.0, 100.0])
        candles = _build_candles(closes)

        strategy = create_strategy(
            "momentum",
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                adx_threshold=0.0,
                volume_filter_mult=0.0,
            ),
            RegimeConfig(),
        )
        rm = RiskManager(RiskConfig(atr_stop_multiplier=0.0))
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=rm,
            config=BacktestConfig(),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        # Should be an integer >= 0
        self.assertIsInstance(result.max_consecutive_losses, int)
        self.assertGreaterEqual(result.max_consecutive_losses, 0)

    def test_max_consecutive_losses_zero_when_no_trades(self) -> None:
        """No trades means max_consecutive_losses = 0."""
        # Flat candles, no signal fires
        candles = _build_candles([100.0] * 50)
        strategy = create_strategy(
            "momentum",
            StrategyConfig(
                momentum_lookback=10,
                momentum_entry_threshold=0.5,  # Very high threshold
                adx_threshold=0.0,
                volume_filter_mult=0.0,
            ),
            RegimeConfig(),
        )
        rm = RiskManager(RiskConfig(atr_stop_multiplier=0.0))
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=rm,
            config=BacktestConfig(),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertEqual(result.max_consecutive_losses, 0)

    def test_backtest_result_has_mcl_field(self) -> None:
        """BacktestResult dataclass has max_consecutive_losses field."""
        from crypto_trader.models import BacktestResult
        self.assertTrue(hasattr(BacktestResult, "__dataclass_fields__"))
        self.assertIn("max_consecutive_losses", BacktestResult.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
