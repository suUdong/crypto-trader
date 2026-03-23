from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy


def build_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1, 0, 0, 0)
    return [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=1_000.0,
        )
        for index, close in enumerate(closes)
    ]


class BacktestEngineTests(unittest.TestCase):
    def test_backtest_trade_log_pnl_sum_matches_fee_adjusted_final_equity(self) -> None:
        candles = build_candles([100.0] * 20 + [90.0, 89.0, 93.0, 96.0, 100.0])
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
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=RiskManager(RiskConfig(stop_loss_pct=0.02, take_profit_pct=0.03)),
            config=BacktestConfig(initial_capital=1_000.0, fee_rate=0.01, slippage_pct=0.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertAlmostEqual(
            sum(trade.pnl for trade in result.trade_log),
            result.final_equity - result.initial_capital,
        )
