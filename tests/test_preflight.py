"""Tests for go-live preflight safety checks."""

from __future__ import annotations

from crypto_trader.config import (
    AppConfig,
    BacktestConfig,
    CredentialsConfig,
    DriftConfig,
    KillSwitchCfg,
    MacroConfig,
    RegimeConfig,
    RiskConfig,
    RuntimeConfig,
    SlackConfig,
    StrategyConfig,
    TelegramConfig,
    TradingConfig,
    WalletConfig,
    preflight_check,
)


def _make_config(**overrides) -> AppConfig:
    defaults = dict(
        trading=TradingConfig(paper_trading=False),
        strategy=StrategyConfig(),
        regime=RegimeConfig(),
        drift=DriftConfig(),
        risk=RiskConfig(),
        backtest=BacktestConfig(),
        telegram=TelegramConfig(),
        runtime=RuntimeConfig(),
        credentials=CredentialsConfig(upbit_access_key="key", upbit_secret_key="secret"),
        slack=SlackConfig(),
        macro=MacroConfig(),
        kill_switch=KillSwitchCfg(),
        wallets=[WalletConfig(name="test_wallet", strategy="momentum")],
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


def test_all_pass():
    config = _make_config(
        telegram=TelegramConfig(bot_token="tok", chat_id="123"),
    )
    results = preflight_check(config)
    assert len(results) == 0


def test_missing_credentials():
    config = _make_config(
        credentials=CredentialsConfig(),
    )
    results = preflight_check(config)
    errors = [msg for lvl, msg in results if lvl == "ERROR"]
    assert any("credentials" in e.lower() for e in errors)


def test_telegram_not_configured_warning():
    config = _make_config()
    results = preflight_check(config)
    warnings = [msg for lvl, msg in results if lvl == "WARNING"]
    assert any("telegram" in w.lower() for w in warnings)


def test_kill_switch_exceeds_daily_loss_cap():
    config = _make_config(
        kill_switch=KillSwitchCfg(max_daily_loss_pct=0.10),
        telegram=TelegramConfig(bot_token="tok", chat_id="123"),
    )
    results = preflight_check(config)
    errors = [msg for lvl, msg in results if lvl == "ERROR"]
    assert any("daily_loss" in e for e in errors)


def test_kill_switch_exceeds_consecutive_losses_cap():
    config = _make_config(
        kill_switch=KillSwitchCfg(max_consecutive_losses=10),
        telegram=TelegramConfig(bot_token="tok", chat_id="123"),
    )
    results = preflight_check(config)
    errors = [msg for lvl, msg in results if lvl == "ERROR"]
    assert any("consecutive_losses" in e for e in errors)


def test_go_live_wallets_unknown_name():
    config = _make_config(
        trading=TradingConfig(paper_trading=False, go_live_wallets=["nonexistent"]),
        telegram=TelegramConfig(bot_token="tok", chat_id="123"),
    )
    results = preflight_check(config)
    errors = [msg for lvl, msg in results if lvl == "ERROR"]
    assert any("nonexistent" in e for e in errors)


def test_go_live_wallets_valid_name():
    config = _make_config(
        trading=TradingConfig(paper_trading=False, go_live_wallets=["test_wallet"]),
        telegram=TelegramConfig(bot_token="tok", chat_id="123"),
    )
    results = preflight_check(config)
    errors = [msg for lvl, msg in results if lvl == "ERROR"]
    assert len(errors) == 0


def test_max_position_pct_exceeds_limit():
    config = _make_config(
        risk=RiskConfig(max_position_pct=0.20),
        telegram=TelegramConfig(bot_token="tok", chat_id="123"),
    )
    results = preflight_check(config)
    errors = [msg for lvl, msg in results if lvl == "ERROR"]
    assert any("max_position_pct" in e for e in errors)


def test_paper_trading_skips_credential_check():
    config = _make_config(
        trading=TradingConfig(paper_trading=True),
        credentials=CredentialsConfig(),
    )
    results = preflight_check(config)
    errors = [msg for lvl, msg in results if lvl == "ERROR"]
    # No credential error when paper trading
    assert not any("credentials" in e.lower() for e in errors)
