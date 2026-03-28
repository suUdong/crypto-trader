"""Tests for broker selection logic in build_wallets."""

from __future__ import annotations

from unittest.mock import patch

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
)
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.wallet import build_wallets


def _make_config(
    paper_trading: bool = True,
    go_live_wallets: list[str] | None = None,
    has_credentials: bool = False,
) -> AppConfig:
    return AppConfig(
        trading=TradingConfig(
            paper_trading=paper_trading,
            go_live_wallets=go_live_wallets or [],
        ),
        strategy=StrategyConfig(),
        regime=RegimeConfig(),
        drift=DriftConfig(),
        risk=RiskConfig(),
        backtest=BacktestConfig(),
        telegram=TelegramConfig(),
        runtime=RuntimeConfig(),
        credentials=CredentialsConfig(
            upbit_access_key="key" if has_credentials else "",
            upbit_secret_key="secret" if has_credentials else "",
        ),
        slack=SlackConfig(),
        macro=MacroConfig(),
        kill_switch=KillSwitchCfg(),
        wallets=[
            WalletConfig(name="wallet_a", strategy="momentum", initial_capital=100_000.0),
            WalletConfig(name="wallet_b", strategy="momentum", initial_capital=50_000.0),
        ],
    )


def test_paper_trading_uses_paper_broker():
    config = _make_config(paper_trading=True)
    wallets = build_wallets(config)
    assert all(isinstance(w.broker, PaperBroker) for w in wallets)


def test_live_no_credentials_uses_paper_broker():
    config = _make_config(paper_trading=False, has_credentials=False)
    wallets = build_wallets(config)
    assert all(isinstance(w.broker, PaperBroker) for w in wallets)


@patch("crypto_trader.execution.live.pyupbit.Upbit")
def test_live_with_credentials_uses_live_broker(mock_upbit):
    from crypto_trader.execution.live import LiveBroker

    config = _make_config(paper_trading=False, has_credentials=True)
    wallets = build_wallets(config)
    assert all(isinstance(w.broker, LiveBroker) for w in wallets)


@patch("crypto_trader.execution.live.pyupbit.Upbit")
def test_staged_rollout_only_listed_wallets_go_live(mock_upbit):
    from crypto_trader.execution.live import LiveBroker

    config = _make_config(
        paper_trading=False,
        has_credentials=True,
        go_live_wallets=["wallet_b"],
    )
    wallets = build_wallets(config)
    wallet_a = next(w for w in wallets if w.name == "wallet_a")
    wallet_b = next(w for w in wallets if w.name == "wallet_b")
    assert isinstance(wallet_a.broker, PaperBroker)
    assert isinstance(wallet_b.broker, LiveBroker)


@patch("crypto_trader.execution.live.pyupbit.Upbit")
def test_empty_go_live_wallets_all_go_live(mock_upbit):
    from crypto_trader.execution.live import LiveBroker

    config = _make_config(
        paper_trading=False,
        has_credentials=True,
        go_live_wallets=[],
    )
    wallets = build_wallets(config)
    assert all(isinstance(w.broker, LiveBroker) for w in wallets)
