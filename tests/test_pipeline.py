from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import (
    AppConfig,
    BacktestConfig,
    RiskConfig,
    StrategyConfig,
    TelegramConfig,
    TradingConfig,
)
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import Candle
from crypto_trader.notifications.telegram import Notifier
from crypto_trader.pipeline import TradingPipeline
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy


class FakeMarketData:
    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def get_ohlcv(self, symbol: str, interval: str, count: int) -> list[Candle]:
        return self._candles[-count:]


class RecorderNotifier(Notifier):
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, message: str) -> None:
        self.messages.append(message)


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


class TradingPipelineTests(unittest.TestCase):
    def test_pipeline_places_paper_order_and_sends_notification(self) -> None:
        candles = build_candles([100.0] * 20 + [90.0, 89.0])
        config = AppConfig(
            trading=TradingConfig(symbol="KRW-BTC", candle_count=len(candles)),
            strategy=StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                bollinger_window=20,
                bollinger_stddev=1.5,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
            ),
            risk=RiskConfig(),
            backtest=BacktestConfig(initial_capital=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            telegram=TelegramConfig(),
        )
        pipeline = TradingPipeline(
            config=config,
            market_data=FakeMarketData(candles),
            strategy=CompositeStrategy(config.strategy),
            risk_manager=RiskManager(config.risk),
            broker=PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            notifier=RecorderNotifier(),
        )
        result = pipeline.run_once()
        self.assertIsNotNone(result.order)
        assert result.order is not None
        self.assertEqual(result.order.status, "filled")
        self.assertIn("signal=buy", result.message)
