from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import (
    AppConfig,
    BacktestConfig,
    CredentialsConfig,
    DriftConfig,
    RegimeConfig,
    RiskConfig,
    RuntimeConfig,
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


class BrokenMarketData:
    def get_ohlcv(self, symbol: str, interval: str, count: int) -> list[Candle]:
        raise RuntimeError("upbit unavailable")


class RecorderNotifier(Notifier):
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, message: str) -> None:
        self.messages.append(message)


class RecordingRiskManager(RiskManager):
    def __init__(self, config: RiskConfig) -> None:
        super().__init__(config)
        self.starting_equities: list[float] = []

    def can_open(self, active_positions: int, realized_pnl: float, starting_equity: float) -> bool:
        self.starting_equities.append(starting_equity)
        return super().can_open(active_positions, realized_pnl, starting_equity)


class AtrRecordingRiskManager(RiskManager):
    def __init__(self, config: RiskConfig) -> None:
        super().__init__(config, atr_stop_multiplier=2.0)
        self.atr_updates = 0

    def update_atr_from_candles(self, candles: list[Candle], period: int = 14) -> None:
        self.atr_updates += 1
        super().update_atr_from_candles(candles, period)


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
            regime=RegimeConfig(),
            drift=DriftConfig(),
            risk=RiskConfig(),
            backtest=BacktestConfig(initial_capital=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            telegram=TelegramConfig(),
            runtime=RuntimeConfig(),
            credentials=CredentialsConfig(),
        )
        pipeline = TradingPipeline(
            config=config,
            market_data=FakeMarketData(candles),
            strategy=CompositeStrategy(config.strategy, config.regime),
            risk_manager=RiskManager(config.risk),
            broker=PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            notifier=RecorderNotifier(),
        )
        result = pipeline.run_once()
        self.assertIsNotNone(result.order)
        assert result.order is not None
        self.assertEqual(result.order.status, "filled")
        self.assertIn("signal=buy", result.message)

    def test_pipeline_returns_error_result_on_market_data_failure(self) -> None:
        config = AppConfig(
            trading=TradingConfig(symbol="KRW-BTC", candle_count=10),
            strategy=StrategyConfig(),
            regime=RegimeConfig(),
            drift=DriftConfig(),
            risk=RiskConfig(),
            backtest=BacktestConfig(initial_capital=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            telegram=TelegramConfig(),
            runtime=RuntimeConfig(),
            credentials=CredentialsConfig(),
        )
        notifier = RecorderNotifier()
        pipeline = TradingPipeline(
            config=config,
            market_data=BrokenMarketData(),
            strategy=CompositeStrategy(config.strategy, config.regime),
            risk_manager=RiskManager(config.risk),
            broker=PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            notifier=notifier,
        )
        result = pipeline.run_once()
        self.assertIsNotNone(result.error)
        self.assertIn("pipeline_error", result.message)
        self.assertEqual(len(notifier.messages), 1)

    def test_pipeline_uses_session_starting_equity_for_daily_loss_checks(self) -> None:
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
            regime=RegimeConfig(),
            drift=DriftConfig(),
            risk=RiskConfig(max_daily_loss_pct=0.05),
            backtest=BacktestConfig(initial_capital=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            telegram=TelegramConfig(),
            runtime=RuntimeConfig(),
            credentials=CredentialsConfig(),
        )
        broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0)
        risk_manager = RecordingRiskManager(config.risk)
        pipeline = TradingPipeline(
            config=config,
            market_data=FakeMarketData(candles),
            strategy=CompositeStrategy(config.strategy, config.regime),
            risk_manager=risk_manager,
            broker=broker,
            notifier=RecorderNotifier(),
        )
        broker.cash = 800.0
        broker.realized_pnl = -40.0
        pipeline.run_once()
        self.assertEqual(risk_manager.starting_equities, [1_000.0])

    def test_pipeline_updates_atr_from_live_candles(self) -> None:
        candles = build_candles([100.0 + i for i in range(20)])
        config = AppConfig(
            trading=TradingConfig(symbol="KRW-BTC", candle_count=len(candles)),
            strategy=StrategyConfig(),
            regime=RegimeConfig(),
            drift=DriftConfig(),
            risk=RiskConfig(),
            backtest=BacktestConfig(initial_capital=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            telegram=TelegramConfig(),
            runtime=RuntimeConfig(),
            credentials=CredentialsConfig(),
        )
        risk_manager = AtrRecordingRiskManager(config.risk)
        pipeline = TradingPipeline(
            config=config,
            market_data=FakeMarketData(candles),
            strategy=CompositeStrategy(config.strategy, config.regime),
            risk_manager=risk_manager,
            broker=PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0),
            notifier=RecorderNotifier(),
        )

        pipeline.run_once()

        self.assertEqual(risk_manager.atr_updates, 1)
        self.assertGreaterEqual(risk_manager._current_atr, 0.0)
