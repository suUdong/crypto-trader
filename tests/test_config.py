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
        self.assertEqual(config.macro.base_url, "http://127.0.0.1:8000")

    def test_environment_overrides_file_values(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {
                "CT_SYMBOL": "KRW-ETH",
                "CT_TELEGRAM_BOT_TOKEN": "token",
                "CT_TELEGRAM_CHAT_ID": "123",
                "CT_MACRO_BASE_URL": "http://macro.internal:8000",
            },
        )
        self.assertEqual(config.trading.symbol, "KRW-ETH")
        self.assertTrue(config.telegram.enabled)
        self.assertEqual(config.macro.base_url, "http://macro.internal:8000")

    def test_macro_timeout_env_override(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {"CT_MACRO_TIMEOUT_SECONDS": "2.5"},
        )
        self.assertEqual(config.macro.timeout_seconds, 2.5)

    def test_runtime_restart_settings_env_override(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {
                "CT_AUTO_RESTART_ENABLED": "true",
                "CT_RESTART_BACKOFF_SECONDS": "9",
                "CT_MAX_RESTART_ATTEMPTS": "3",
                "CT_NETWORK_RECOVERY_BACKOFF_SECONDS": "12",
                "CT_DAEMON_ALERT_COOLDOWN_SECONDS": "45",
            },
        )
        self.assertTrue(config.runtime.auto_restart_enabled)
        self.assertEqual(config.runtime.restart_backoff_seconds, 9)
        self.assertEqual(config.runtime.max_restart_attempts, 3)
        self.assertEqual(config.runtime.network_recovery_backoff_seconds, 12)
        self.assertEqual(config.runtime.daemon_alert_cooldown_seconds, 45)

    def test_paper_trade_sqlite_path_defaults_empty_and_env_override(self) -> None:
        config = load_config(ROOT / "config" / "example.toml", {})
        self.assertEqual(config.runtime.paper_trade_sqlite_path, "")
        config = load_config(
            ROOT / "config" / "example.toml",
            {"CT_PAPER_TRADE_SQLITE_PATH": "artifacts/paper-trades.db"},
        )
        self.assertEqual(
            config.runtime.paper_trade_sqlite_path,
            "artifacts/paper-trades.db",
        )

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

    def test_read_only_load_can_skip_live_credential_requirement(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {
                "CT_PAPER_TRADING": "false",
                "CT_UPBIT_ACCESS_KEY": "",
                "CT_UPBIT_SECRET_KEY": "",
            },
            allow_missing_live_credentials=True,
        )
        self.assertFalse(config.trading.paper_trading)

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

    def test_loads_session7_strategy_fields(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {
                "CT_ADX_PERIOD": "10",
                "CT_ADX_THRESHOLD": "25.0",
                "CT_VOLUME_FILTER_MULT": "1.2",
            },
        )
        self.assertEqual(config.strategy.adx_period, 10)
        self.assertEqual(config.strategy.adx_threshold, 25.0)
        self.assertEqual(config.strategy.volume_filter_mult, 1.2)

    def test_loads_session7_risk_fields(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {
                "CT_PARTIAL_TP_PCT": "0.3",
                "CT_COOLDOWN_BARS": "5",
            },
        )
        self.assertEqual(config.risk.partial_tp_pct, 0.3)
        self.assertEqual(config.risk.cooldown_bars, 5)

    def test_optimized_toml_loads_all_wallets(self) -> None:
        config = load_config(ROOT / "config" / "optimized.toml", {})
        self.assertEqual(len(config.wallets), 8)
        names = {w.name for w in config.wallets}
        self.assertIn("momentum_wallet", names)
        self.assertIn("bollinger_rsi_wallet", names)
        self.assertIn("kimchi_premium_wallet", names)
        # Verify new fields are parsed at global level
        self.assertEqual(config.strategy.adx_period, 14)
        self.assertEqual(config.strategy.adx_threshold, 20.0)
        self.assertEqual(config.risk.partial_tp_pct, 0.5)
        self.assertEqual(config.risk.cooldown_bars, 3)
        self.assertEqual(config.risk.atr_stop_multiplier, 0.0)

    def test_optimized_toml_loads_kill_switch_config(self) -> None:
        config = load_config(ROOT / "config" / "optimized.toml", {})
        self.assertEqual(config.kill_switch.max_portfolio_drawdown_pct, 0.15)
        self.assertEqual(config.kill_switch.max_daily_loss_pct, 0.05)
        self.assertEqual(config.kill_switch.max_consecutive_losses, 5)
        self.assertEqual(config.kill_switch.max_strategy_drawdown_pct, 0.10)
        self.assertEqual(config.kill_switch.cooldown_minutes, 60)

    def test_kill_switch_env_override(self) -> None:
        config = load_config(
            ROOT / "config" / "example.toml",
            {"CT_KS_MAX_PORTFOLIO_DD": "0.20", "CT_KS_MAX_CONSEC_LOSSES": "10"},
        )
        self.assertEqual(config.kill_switch.max_portfolio_drawdown_pct, 0.20)
        self.assertEqual(config.kill_switch.max_consecutive_losses, 10)

    def test_runtime_risk_caps_are_sanitized_when_file_is_looser(self) -> None:
        toml_content = """
[trading]
symbol = "KRW-BTC"
symbols = ["KRW-BTC"]
paper_trading = true

[strategy]
[regime]
[drift]

[risk]
max_daily_loss_pct = 0.20
max_position_pct = 0.25

[kill_switch]
max_daily_loss_pct = 0.20

[backtest]
[telegram]
[runtime]
[credentials]

[[wallets]]
name = "momentum_wallet"
strategy = "momentum"
initial_capital = 1000000.0

[wallets.risk_overrides]
max_daily_loss_pct = 0.20
max_position_pct = 0.25
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name, {})
            finally:
                os.unlink(f.name)

        self.assertEqual(config.risk.max_daily_loss_pct, 0.05)
        self.assertEqual(config.risk.max_position_pct, 0.10)
        self.assertEqual(config.kill_switch.max_daily_loss_pct, 0.05)
        self.assertEqual(config.wallets[0].risk_overrides["max_daily_loss_pct"], 0.05)
        self.assertEqual(config.wallets[0].risk_overrides["max_position_pct"], 0.10)

    def test_optimized_toml_bollinger_wallet_has_extra_params(self) -> None:
        config = load_config(ROOT / "config" / "optimized.toml", {})
        bollinger = [w for w in config.wallets if w.strategy == "bollinger_rsi"][0]
        self.assertEqual(
            bollinger.strategy_overrides["bollinger_window"],
            14,
        )
        self.assertEqual(bollinger.strategy_overrides["rsi_overbought"], 65.0)
        self.assertEqual(bollinger.risk_overrides["stop_loss_pct"], 0.02)

    def test_consensus_wallet_accepts_weights_override(self) -> None:
        toml_content = """
[trading]
[strategy]
[regime]
[drift]
[risk]
[backtest]
[telegram]
[runtime]
[credentials]

[[wallets]]
name = "consensus_wallet"
strategy = "consensus"
initial_capital = 1000000.0

[wallets.strategy_overrides]
sub_strategies = ["momentum", "kimchi_premium", "volume_spike"]
min_agree = 2
min_confidence_sum = 1.0
weights = [2.0, 1.0, 0.5]
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name, {})
            finally:
                os.unlink(f.name)

        consensus_wallet = config.wallets[0]
        self.assertEqual(consensus_wallet.strategy_overrides["weights"], [2.0, 1.0, 0.5])

    def test_volume_spike_wallet_accepts_strategy_specific_overrides(self) -> None:
        toml_content = """
[trading]
[strategy]
[regime]
[drift]
[risk]
[backtest]
[telegram]
[runtime]
[credentials]

[[wallets]]
name = "volume_spike_wallet"
strategy = "volume_spike"
initial_capital = 1000000.0

[wallets.strategy_overrides]
spike_mult = 2.8
volume_window = 24
min_body_ratio = 0.55
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name, {})
            finally:
                os.unlink(f.name)

        volume_spike_wallet = config.wallets[0]
        self.assertEqual(volume_spike_wallet.strategy_overrides["spike_mult"], 2.8)
        self.assertEqual(volume_spike_wallet.strategy_overrides["volume_window"], 24)
        self.assertEqual(volume_spike_wallet.strategy_overrides["min_body_ratio"], 0.55)

    def test_vpin_wallet_accepts_strategy_specific_overrides(self) -> None:
        toml_content = """
[trading]
[strategy]
[regime]
[drift]
[risk]
[backtest]
[telegram]
[runtime]
[credentials]

[[wallets]]
name = "vpin_wallet"
strategy = "vpin"
initial_capital = 1000000.0

[wallets.strategy_overrides]
bucket_count = 24
vpin_high_threshold = 0.75
vpin_low_threshold = 0.40
vpin_momentum_threshold = 0.02
vpin_rsi_ceiling = 72.0
vpin_rsi_floor = 24.0
ema_trend_period = 20
adx_threshold = 15.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name, {})
            finally:
                os.unlink(f.name)

        vpin_wallet = config.wallets[0]
        self.assertEqual(vpin_wallet.strategy_overrides["bucket_count"], 24)
        self.assertEqual(vpin_wallet.strategy_overrides["vpin_high_threshold"], 0.75)
        self.assertEqual(vpin_wallet.strategy_overrides["vpin_low_threshold"], 0.40)
        self.assertEqual(vpin_wallet.strategy_overrides["vpin_momentum_threshold"], 0.02)
        self.assertEqual(vpin_wallet.strategy_overrides["vpin_rsi_ceiling"], 72.0)
        self.assertEqual(vpin_wallet.strategy_overrides["vpin_rsi_floor"], 24.0)
        self.assertEqual(vpin_wallet.strategy_overrides["ema_trend_period"], 20)
        self.assertEqual(vpin_wallet.strategy_overrides["adx_threshold"], 15.0)
