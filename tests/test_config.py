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
