from __future__ import annotations

import unittest
from pathlib import Path

from crypto_trader.config import load_config

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_loads_example_config(self) -> None:
        config = load_config(ROOT / "config" / "example.toml", {})
        self.assertEqual(config.trading.exchange, "upbit")
        self.assertEqual(config.trading.symbol, "KRW-BTC")
        self.assertTrue(config.trading.paper_trading)

    def test_environment_overrides_file_values(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {
                "CT_SYMBOL": "KRW-ETH",
                "CT_TELEGRAM_BOT_TOKEN": "token",
                "CT_TELEGRAM_CHAT_ID": "123",
            },
        )
        self.assertEqual(config.trading.symbol, "KRW-ETH")
        self.assertTrue(config.telegram.enabled)

    def test_live_trading_mode_is_rejected_until_implemented(self) -> None:
        with self.assertRaisesRegex(ValueError, "not implemented"):
            load_config(
                ROOT / "config" / "example.toml",
                {
                    "CT_PAPER_TRADING": "false",
                    "CT_UPBIT_ACCESS_KEY": "access",
                    "CT_UPBIT_SECRET_KEY": "secret",
                },
            )

    def test_invalid_percentage_and_path_values_raise_clear_errors(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "risk.take_profit_pct must be greater than risk.stop_loss_pct",
        ):
            load_config(
                ROOT / "config" / "example.toml",
                {
                    "CT_STOP_LOSS_PCT": "0.05",
                    "CT_TAKE_PROFIT_PCT": "0.03",
                    "CT_DAILY_MEMO_PATH": "",
                },
            )

    def test_invalid_regime_values_raise_clear_errors(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "regime.long_lookback must be greater than regime.short_lookback",
        ):
            load_config(
                ROOT / "config" / "example.toml",
                {
                    "CT_REGIME_SHORT_LOOKBACK": "30",
                    "CT_REGIME_LONG_LOOKBACK": "10",
                    "CT_REGIME_BEAR_THRESHOLD": "0.01",
                },
            )

    def test_invalid_candle_count_and_fee_values_raise_clear_errors(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "trading.candle_count must be greater than 1",
        ):
            load_config(
                ROOT / "config" / "example.toml",
                {
                    "CT_CANDLE_COUNT": "1",
                    "CT_FEE_RATE": "1.2",
                },
            )
