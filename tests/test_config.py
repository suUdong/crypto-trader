from __future__ import annotations

import os
import tempfile
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

    def test_live_trading_requires_credentials(self) -> None:
        with self.assertRaisesRegex(ValueError, "credentials"):
            load_config(
                ROOT / "config" / "example.toml",
                {
                    "CT_PAPER_TRADING": "false",
                    "CT_UPBIT_ACCESS_KEY": "",
                    "CT_UPBIT_SECRET_KEY": "",
                },
            )

    def test_live_trading_accepted_with_credentials(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {
                "CT_PAPER_TRADING": "false",
                "CT_UPBIT_ACCESS_KEY": "access",
                "CT_UPBIT_SECRET_KEY": "secret",
            },
        )
        self.assertFalse(config.trading.paper_trading)
        self.assertTrue(config.credentials.has_upbit_credentials)

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

    def test_loads_extended_strategy_and_risk_fields(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {
                "CT_K_BASE": "0.7",
                "CT_NOISE_LOOKBACK": "15",
                "CT_MA_FILTER_PERIOD": "15",
                "CT_TRAILING_STOP_PCT": "0.04",
                "CT_ATR_STOP_MULTIPLIER": "3.0",
            },
        )
        self.assertEqual(config.strategy.k_base, 0.7)
        self.assertEqual(config.strategy.noise_lookback, 15)
        self.assertEqual(config.strategy.ma_filter_period, 15)
        self.assertEqual(config.risk.trailing_stop_pct, 0.04)
        self.assertEqual(config.risk.atr_stop_multiplier, 3.0)

    def test_loads_wallet_specific_overrides(self) -> None:
        toml_content = """
[trading]
symbol = "KRW-BTC"
symbols = ["KRW-BTC"]
paper_trading = true

[strategy]
[regime]
[drift]
[risk]
[backtest]
[telegram]
[runtime]
[credentials]

[[wallets]]
name = "momentum_wallet"
strategy = "momentum"
initial_capital = 1000000.0

[wallets.strategy_overrides]
momentum_lookback = 15
momentum_entry_threshold = 0.003

[wallets.risk_overrides]
stop_loss_pct = 0.03
take_profit_pct = 0.04
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name, {})
            finally:
                os.unlink(f.name)

        momentum_wallet = config.wallets[0]
        self.assertEqual(momentum_wallet.strategy_overrides["momentum_lookback"], 15)
        self.assertEqual(momentum_wallet.risk_overrides["take_profit_pct"], 0.04)
