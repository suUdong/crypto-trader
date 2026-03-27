"""Tests for walk-forward CLI integration."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.walk_forward import WalkForwardValidator
from crypto_trader.config import BacktestConfig, RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.wallet import create_strategy


def _make_candles(count: int, base_price: float = 100.0) -> list[Candle]:
    base = datetime(2025, 1, 1)
    candles = []
    for i in range(count):
        price = base_price + i * 0.1
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=i),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=1000.0 + i,
            )
        )
    return candles


class TestWalkForwardCLIIntegration(unittest.TestCase):
    def test_walk_forward_momentum_produces_report(self) -> None:
        candles = _make_candles(200)
        validator = WalkForwardValidator(
            backtest_config=BacktestConfig(),
            risk_config=RiskConfig(),
            n_folds=3,
            train_pct=0.7,
        )
        strategy_config = StrategyConfig()
        regime_config = RegimeConfig()

        report = validator.validate(
            strategy_factory=lambda: create_strategy("momentum", strategy_config, regime_config),
            candles=candles,
            symbol="KRW-BTC",
            strategy_name="momentum",
        )

        self.assertGreaterEqual(report.total_folds, 2)
        summary = report.summary()
        self.assertIn("passed", summary)
        self.assertIn("avg_test_return_pct", summary)

    def test_walk_forward_kimchi_premium_with_mock_premium(self) -> None:
        candles = _make_candles(200, base_price=100_000_000.0)
        validator = WalkForwardValidator(
            backtest_config=BacktestConfig(),
            risk_config=RiskConfig(),
            n_folds=3,
            train_pct=0.7,
        )
        strategy_config = StrategyConfig()
        regime_config = RegimeConfig()

        def kimchi_factory():
            from unittest.mock import MagicMock as MM

            strat = create_strategy("kimchi_premium", strategy_config, regime_config)
            strat._cached_premium = 0.02  # 2% premium
            strat._binance = MM()
            strat._fx = MM()
            strat._binance.get_btc_usdt_price.return_value = None
            strat._fx.get_usd_krw_rate.return_value = None
            return strat

        report = validator.validate(
            strategy_factory=kimchi_factory,
            candles=candles,
            symbol="KRW-BTC",
            strategy_name="kimchi_premium",
        )

        self.assertGreaterEqual(report.total_folds, 2)
        summary = report.summary()
        self.assertEqual(summary["strategy"], "kimchi_premium")

    def test_walk_forward_all_strategy_types_run(self) -> None:
        """Verify supported strategy types can be instantiated and run through walk-forward."""
        candles = _make_candles(200)
        validator = WalkForwardValidator(
            backtest_config=BacktestConfig(),
            risk_config=RiskConfig(),
            n_folds=2,
            train_pct=0.7,
        )
        strategy_config = StrategyConfig()
        regime_config = RegimeConfig()
        strategy_types = [
            "momentum",
            "momentum_pullback",
            "bollinger_rsi",
            "mean_reversion",
            "composite",
            "obi",
            "vpin",
            "volatility_breakout",
        ]

        for st in strategy_types:
            report = validator.validate(
                strategy_factory=lambda s=st: create_strategy(s, strategy_config, regime_config),
                candles=candles,
                symbol="KRW-BTC",
                strategy_name=st,
            )
            self.assertGreaterEqual(report.total_folds, 1, f"{st} should have at least 1 fold")


if __name__ == "__main__":
    unittest.main()
