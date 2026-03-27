"""Tests for Session #11 Wave 16: confidence analysis, exit reason distribution."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy


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


class TestConfidenceAnalysis(unittest.TestCase):
    def test_avg_entry_confidence_on_result(self) -> None:
        """BacktestResult should have avg_entry_confidence."""
        candles = _candles([100.0] * 30)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5)
        )
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertIsInstance(result.avg_entry_confidence, float)
        self.assertGreaterEqual(result.avg_entry_confidence, 0.0)

    def test_high_low_confidence_win_rates(self) -> None:
        """BacktestResult should have high/low confidence win rates."""
        candles = _candles([100.0] * 30)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5)
        )
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertIsInstance(result.high_confidence_win_rate, float)
        self.assertIsInstance(result.low_confidence_win_rate, float)
        self.assertGreaterEqual(result.high_confidence_win_rate, 0.0)
        self.assertLessEqual(result.high_confidence_win_rate, 1.0)

    def test_confidence_with_trades(self) -> None:
        """With actual trades, confidence metrics should be populated."""
        prices = [100.0] * 20 + [90.0, 89.0, 93.0, 96.0, 100.0, 105.0]
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                bollinger_window=20,
                bollinger_stddev=1.5,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
            )
        )
        risk = RiskManager(RiskConfig(stop_loss_pct=0.15, take_profit_pct=0.30, cooldown_bars=0))
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        if result.trade_log:
            self.assertGreater(result.avg_entry_confidence, 0.0)


class TestExitReasonDistribution(unittest.TestCase):
    def test_exit_reason_counts_on_result(self) -> None:
        """BacktestResult should have exit_reason_counts dict."""
        candles = _candles([100.0] * 30)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5)
        )
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertIsInstance(result.exit_reason_counts, dict)
        self.assertIsInstance(result.exit_reason_avg_pnl, dict)

    def test_exit_reasons_match_trades(self) -> None:
        """Exit reason counts should sum to total trade count."""
        prices = [100.0] * 20 + [90.0, 89.0, 93.0, 96.0, 100.0, 105.0, 95.0, 90.0]
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                bollinger_window=20,
                bollinger_stddev=1.5,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
            )
        )
        risk = RiskManager(RiskConfig(stop_loss_pct=0.15, take_profit_pct=0.30, cooldown_bars=0))
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        total_from_counts = sum(result.exit_reason_counts.values())
        self.assertEqual(total_from_counts, len(result.trade_log))

    def test_exit_avg_pnl_keys_match_counts(self) -> None:
        """exit_reason_avg_pnl keys should match exit_reason_counts keys."""
        prices = [100.0] * 20 + [90.0, 89.0, 93.0, 100.0, 105.0]
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                bollinger_window=20,
                bollinger_stddev=1.5,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
            )
        )
        risk = RiskManager(RiskConfig(stop_loss_pct=0.15, take_profit_pct=0.30, cooldown_bars=0))
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertEqual(
            set(result.exit_reason_counts.keys()), set(result.exit_reason_avg_pnl.keys())
        )


if __name__ == "__main__":
    unittest.main()
