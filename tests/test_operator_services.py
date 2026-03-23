from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

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
from crypto_trader.models import Candle, StrategyRunRecord
from crypto_trader.notifications.telegram import Notifier
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.services import generate_operator_artifacts
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


class OperatorServicesTests(unittest.TestCase):
    def test_generate_operator_artifacts_writes_drift_promotion_and_memo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            config = AppConfig(
                trading=TradingConfig(symbol="KRW-BTC", candle_count=25),
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
                runtime=RuntimeConfig(
                    drift_report_path=str(base / "drift.json"),
                    promotion_gate_path=str(base / "promotion.json"),
                    daily_memo_path=str(base / "memo.md"),
                    strategy_run_journal_path=str(base / "runs.jsonl"),
                ),
                credentials=CredentialsConfig(),
            )
            StrategyRunJournal(config.runtime.strategy_run_journal_path).append(
                StrategyRunRecord(
                    recorded_at="2026-03-23T00:00:00Z",
                    symbol="KRW-BTC",
                    latest_price=100.0,
                    market_regime="sideways",
                    signal_action="hold",
                    signal_reason="noop",
                    signal_confidence=0.5,
                    order_status=None,
                    order_side=None,
                    session_starting_equity=1_000.0,
                    cash=1_020.0,
                    open_positions=0,
                    realized_pnl=20.0,
                    success=True,
                    error=None,
                    consecutive_failures=0,
                    verdict_status="continue_paper",
                    verdict_confidence=0.6,
                    verdict_reasons=["ok"],
                )
            )
            artifacts = generate_operator_artifacts(
                config=config,
                market_data=FakeMarketData(
                    build_candles([100.0] * 20 + [90.0, 89.0, 93.0, 96.0, 100.0])
                ),
                strategy=CompositeStrategy(config.strategy, config.regime),
                risk_manager=RiskManager(config.risk),
            )
            self.assertTrue(Path(config.runtime.drift_report_path).exists())
            self.assertTrue(Path(config.runtime.promotion_gate_path).exists())
            self.assertTrue(Path(config.runtime.daily_memo_path).exists())
            self.assertIn("Strategy Lab Daily Memo", artifacts.daily_memo)

    def test_generate_operator_artifacts_can_send_daily_memo_via_notifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            config = AppConfig(
                trading=TradingConfig(symbol="KRW-BTC", candle_count=25),
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
                runtime=RuntimeConfig(
                    drift_report_path=str(base / "drift.json"),
                    promotion_gate_path=str(base / "promotion.json"),
                    daily_memo_path=str(base / "memo.md"),
                    strategy_run_journal_path=str(base / "runs.jsonl"),
                ),
                credentials=CredentialsConfig(),
            )
            StrategyRunJournal(config.runtime.strategy_run_journal_path).append(
                StrategyRunRecord(
                    recorded_at="2026-03-23T00:00:00Z",
                    symbol="KRW-BTC",
                    latest_price=100.0,
                    market_regime="sideways",
                    signal_action="hold",
                    signal_reason="noop",
                    signal_confidence=0.5,
                    order_status=None,
                    order_side=None,
                    session_starting_equity=1_000.0,
                    cash=1_020.0,
                    open_positions=0,
                    realized_pnl=20.0,
                    success=True,
                    error=None,
                    consecutive_failures=0,
                    verdict_status="continue_paper",
                    verdict_confidence=0.6,
                    verdict_reasons=["ok"],
                )
            )
            notifier = RecorderNotifier()
            generate_operator_artifacts(
                config=config,
                market_data=FakeMarketData(
                    build_candles([100.0] * 20 + [90.0, 89.0, 93.0, 96.0, 100.0])
                ),
                strategy=CompositeStrategy(config.strategy, config.regime),
                risk_manager=RiskManager(config.risk),
                notifier=notifier,
                send_daily_memo=True,
            )
            self.assertEqual(len(notifier.messages), 1)
            self.assertIn("Strategy Lab Daily Memo", notifier.messages[0])
