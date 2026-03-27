"""Tests for US-033: backtest-all CLI command."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import create_strategy


def _build_candles(count: int = 200, base_price: float = 100.0) -> list[Candle]:
    start = datetime(2025, 1, 1)
    candles = []
    for i in range(count):
        # Slight uptrend with oscillation
        price = base_price + i * 0.1 + (2.0 if i % 7 < 3 else -1.0)
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=i),
                open=price - 0.5,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=1000.0 + i * 5,
            )
        )
    return candles


class TestBacktestAllStrategies(unittest.TestCase):
    """Integration test: run backtest for each strategy to verify they all work."""

    def test_all_strategies_backtest_without_error(self) -> None:
        strategies = [
            "momentum",
            "bollinger_rsi",
            "mean_reversion",
            "vpin",
            "volatility_breakout",
        ]
        candles = _build_candles(200)
        for strat_name in strategies:
            with self.subTest(strategy=strat_name):
                strat_config = StrategyConfig(adx_threshold=0.0, volume_filter_mult=0.0)
                regime_config = RegimeConfig()
                strategy = create_strategy(strat_name, strat_config, regime_config)
                risk_config = RiskConfig(atr_stop_multiplier=0.0)
                rm = RiskManager(risk_config)
                engine = BacktestEngine(
                    strategy=strategy,
                    risk_manager=rm,
                    config=BacktestConfig(),
                    symbol="KRW-BTC",
                )
                result = engine.run(candles)
                self.assertGreater(result.final_equity, 0)
                self.assertIsInstance(result.equity_curve, list)
                self.assertGreaterEqual(len(result.equity_curve), len(candles))

    def test_backtest_results_serializable(self) -> None:
        """Backtest results can be serialized to JSON."""
        candles = _build_candles(100)
        strat_config = StrategyConfig(adx_threshold=0.0, volume_filter_mult=0.0)
        strategy = create_strategy("momentum", strat_config, RegimeConfig())
        rm = RiskManager(RiskConfig(atr_stop_multiplier=0.0))
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=rm,
            config=BacktestConfig(),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)

        from crypto_trader.backtest.grid_wf import _approx_sharpe

        data = {
            "strategy": "momentum",
            "return_pct": result.total_return_pct * 100,
            "sharpe": _approx_sharpe(result.equity_curve),
            "max_drawdown_pct": result.max_drawdown * 100,
            "trade_count": len(result.trade_log),
        }
        # Should not raise
        serialized = json.dumps(data)
        parsed = json.loads(serialized)
        self.assertIn("strategy", parsed)
        self.assertEqual(parsed["strategy"], "momentum")

    def test_backtest_all_export_metrics_include_expected_value_recovery_and_tail(self) -> None:
        candles = _build_candles(120)
        strat_config = StrategyConfig(adx_threshold=0.0, volume_filter_mult=0.0)
        strategy = create_strategy("momentum", strat_config, RegimeConfig())
        rm = RiskManager(RiskConfig(atr_stop_multiplier=0.0))
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=rm,
            config=BacktestConfig(),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)

        from crypto_trader.backtest.grid_wf import _approx_sharpe

        export_row = {
            "strategy": "momentum",
            "return_pct": result.total_return_pct * 100,
            "sharpe": _approx_sharpe(result.equity_curve),
            "max_drawdown_pct": result.max_drawdown * 100,
            "trade_count": len(result.trade_log),
            "expected_value_per_trade": result.expected_value_per_trade,
            "recovery_factor": result.recovery_factor,
            "tail_ratio": result.tail_ratio,
        }

        payload = json.loads(json.dumps(export_row))
        self.assertIn("expected_value_per_trade", payload)
        self.assertIn("recovery_factor", payload)
        self.assertIn("tail_ratio", payload)
        self.assertIsInstance(payload["expected_value_per_trade"], float)
        self.assertIsInstance(payload["recovery_factor"], float)
        self.assertIsInstance(payload["tail_ratio"], float)


if __name__ == "__main__":
    unittest.main()
