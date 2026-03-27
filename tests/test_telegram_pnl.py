from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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
    WalletConfig,
)
from crypto_trader.data.base import MarketDataClient
from crypto_trader.models import Candle
from crypto_trader.multi_runtime import MultiSymbolRuntime
from crypto_trader.notifications.telegram import NullNotifier
from crypto_trader.wallet import build_wallets


def _make_config(
    bot_token: str = "",
    chat_id: str = "",
    checkpoint_path: str = "artifacts/runtime-checkpoint.json",
) -> AppConfig:
    with tempfile.TemporaryDirectory() as tmp:
        str(Path(tmp) / "checkpoint.json")
    return AppConfig(
        trading=TradingConfig(
            symbols=["KRW-BTC"],
            symbol="KRW-BTC",
            candle_count=200,
        ),
        strategy=StrategyConfig(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            bollinger_window=5,
            bollinger_stddev=1.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
        ),
        regime=RegimeConfig(),
        drift=DriftConfig(),
        risk=RiskConfig(max_concurrent_positions=5),
        backtest=BacktestConfig(initial_capital=1_000_000.0),
        telegram=TelegramConfig(bot_token=bot_token, chat_id=chat_id),
        runtime=RuntimeConfig(
            poll_interval_seconds=0,
            max_iterations=1,
            daemon_mode=False,
            runtime_checkpoint_path=checkpoint_path,
        ),
        credentials=CredentialsConfig(),
        wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
    )


def _write_checkpoint(path: str) -> None:
    checkpoint = {
        "generated_at": "2026-03-25T10:00:00+00:00",
        "iteration": 5,
        "symbols": ["KRW-BTC"],
        "wallet_states": {
            "momentum_wallet": {
                "strategy_type": "momentum",
                "cash": 900_000.0,
                "realized_pnl": 10_000.0,
                "open_positions": 1,
                "equity": 1_050_000.0,
                "trade_count": 3,
            },
        },
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(checkpoint), encoding="utf-8")


class FakeMarketData(MarketDataClient):
    def get_ohlcv(self, symbol: str, interval: str = "minute60", count: int = 200) -> list[Candle]:
        return []


def _make_runtime(config: AppConfig) -> MultiSymbolRuntime:
    wallets = build_wallets(config)
    return MultiSymbolRuntime(
        wallets=wallets,
        market_data=FakeMarketData(),
        config=config,
    )


class TestPnLMessageFormat(unittest.TestCase):
    def test_pnl_message_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp_path = str(Path(tmp) / "checkpoint.json")
            _write_checkpoint(cp_path)
            config = _make_config(checkpoint_path=cp_path)
            runtime = _make_runtime(config)
            runtime._last_pnl_notify = 0.0

            sent_messages: list[str] = []
            runtime._notifier = NullNotifier()
            with patch.object(runtime._notifier, "send_message", side_effect=sent_messages.append):
                runtime._maybe_send_pnl_notify()

            self.assertEqual(len(sent_messages), 1)
            msg = sent_messages[0]
            self.assertIn("[Crypto Trader] Daily PnL Report", msg)
            self.assertIn("Equity:", msg)
            self.assertIn("Trades:", msg)
            self.assertIn("Win:", msg)
            self.assertIn("---", msg)


class TestThrottle24h(unittest.TestCase):
    def test_throttle_24h(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp_path = str(Path(tmp) / "checkpoint.json")
            _write_checkpoint(cp_path)
            config = _make_config(checkpoint_path=cp_path)
            runtime = _make_runtime(config)
            runtime._last_pnl_notify = 0.0

            call_count = 0

            def counting_send(msg: str) -> None:
                nonlocal call_count
                call_count += 1

            runtime._notifier = NullNotifier()
            with patch.object(runtime._notifier, "send_message", side_effect=counting_send):
                runtime._maybe_send_pnl_notify()
                runtime._maybe_send_pnl_notify()  # second call should be throttled

            self.assertEqual(call_count, 1)


class TestNoCrashOnMissingCheckpoint(unittest.TestCase):
    def test_no_crash_on_missing_checkpoint(self) -> None:
        config = _make_config(checkpoint_path="/nonexistent/path/checkpoint.json")
        runtime = _make_runtime(config)
        runtime._last_pnl_notify = 0.0
        # Should not raise even though checkpoint doesn't exist
        runtime._maybe_send_pnl_notify()


class TestTelegramDisabled(unittest.TestCase):
    def test_telegram_disabled_uses_null_notifier(self) -> None:
        config = _make_config(bot_token="", chat_id="")
        runtime = _make_runtime(config)
        self.assertIsInstance(runtime._notifier, NullNotifier)

    def test_telegram_enabled_uses_telegram_notifier(self) -> None:
        from crypto_trader.notifications.telegram import TelegramNotifier

        config = _make_config(bot_token="sometoken", chat_id="somechat")
        runtime = _make_runtime(config)
        self.assertIsInstance(runtime._notifier, TelegramNotifier)


class TestPnLMessageContent(unittest.TestCase):
    def test_pnl_message_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp_path = str(Path(tmp) / "checkpoint.json")
            _write_checkpoint(cp_path)
            config = _make_config(checkpoint_path=cp_path)
            runtime = _make_runtime(config)
            runtime._last_pnl_notify = 0.0

            sent_messages: list[str] = []
            runtime._notifier = NullNotifier()
            with patch.object(runtime._notifier, "send_message", side_effect=sent_messages.append):
                runtime._maybe_send_pnl_notify()

            self.assertEqual(len(sent_messages), 1)
            msg = sent_messages[0]
            # Portfolio return should appear as percentage
            self.assertIn("%", msg)
            # Strategy breakdown line
            self.assertIn("momentum", msg)
            # Trade count from fixture is 3 (new format: "3t")
            self.assertIn("3t", msg)

    def test_pnl_timestamp_updated_after_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp_path = str(Path(tmp) / "checkpoint.json")
            _write_checkpoint(cp_path)
            config = _make_config(checkpoint_path=cp_path)
            runtime = _make_runtime(config)
            runtime._last_pnl_notify = 0.0

            before = time.time()
            runtime._notifier = NullNotifier()
            with patch.object(runtime._notifier, "send_message"):
                runtime._maybe_send_pnl_notify()

            self.assertGreaterEqual(runtime._last_pnl_notify, before)


if __name__ == "__main__":
    unittest.main()
