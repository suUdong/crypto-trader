"""Tests for go-live preflight safety checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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

LIVE_ENV: dict[str, str] = {"LIVE_TRADING_ENABLED": "true"}
FIXED_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def _write_confirmation(tmp_path: Path, *, age: timedelta = timedelta(hours=1)) -> Path:
    target = tmp_path / "live-confirmed.json"
    target.write_text(
        json.dumps({"confirmed_at": (FIXED_NOW - age).isoformat()}),
        encoding="utf-8",
    )
    return target


def _make_config(
    tmp_path: Path | None = None,
    *,
    paper_trading: bool = False,
    **overrides,
) -> AppConfig:
    """Build a live-ready (or paper) AppConfig for preflight tests.

    When `trading` is not explicitly overridden and we're live, the helper
    auto-writes a fresh confirmation marker so default-positive tests pass.
    Callers supplying their own `trading=` override must point its
    `live_confirmation_path` at a real (or deliberately missing) marker.
    """
    if "trading" not in overrides and not paper_trading and tmp_path is not None:
        trading_obj = TradingConfig(
            paper_trading=paper_trading,
            live_confirmation_path=str(_write_confirmation(tmp_path)),
        )
    else:
        trading_obj = TradingConfig(paper_trading=paper_trading)
    defaults = dict(
        trading=trading_obj,
        strategy=StrategyConfig(),
        regime=RegimeConfig(),
        drift=DriftConfig(),
        # Live-safe risk defaults: the dataclass default max_position_pct is the
        # paper-mode cap (0.50) which trips the live preflight (0.10) — set
        # explicitly so each test only fails on the dimension it is exercising.
        risk=RiskConfig(max_position_pct=0.10),
        backtest=BacktestConfig(),
        telegram=TelegramConfig(bot_token="tok", chat_id="123"),
        runtime=RuntimeConfig(),
        credentials=CredentialsConfig(upbit_access_key="key", upbit_secret_key="secret"),
        slack=SlackConfig(),
        macro=MacroConfig(),
        kill_switch=KillSwitchCfg(),
        wallets=[WalletConfig(name="test_wallet", strategy="momentum")],
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


def _run(config: AppConfig, *, env: dict[str, str] | None = None) -> list[tuple[str, str]]:
    return preflight_check(
        config,
        env=env if env is not None else LIVE_ENV,
        now=FIXED_NOW,
    )


def test_all_pass(tmp_path):
    config = _make_config(tmp_path)
    results = _run(config)
    assert results == []


def test_missing_credentials(tmp_path):
    config = _make_config(tmp_path, credentials=CredentialsConfig())
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("credentials" in e.lower() for e in errors)


def test_telegram_not_configured_warning(tmp_path):
    # Paper mode: missing telegram is only a warning.
    config = _make_config(tmp_path, paper_trading=True, telegram=TelegramConfig())
    warnings = [msg for lvl, msg in _run(config) if lvl == "WARNING"]
    assert any("telegram" in w.lower() for w in warnings)


def test_telegram_not_configured_error_in_live(tmp_path):
    config = _make_config(tmp_path, telegram=TelegramConfig())
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("telegram" in e.lower() for e in errors)


def test_kill_switch_exceeds_daily_loss_cap(tmp_path):
    config = _make_config(tmp_path, kill_switch=KillSwitchCfg(max_daily_loss_pct=0.10))
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("daily_loss" in e for e in errors)


def test_kill_switch_exceeds_consecutive_losses_cap(tmp_path):
    config = _make_config(tmp_path, kill_switch=KillSwitchCfg(max_consecutive_losses=10))
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("consecutive_losses" in e for e in errors)


def test_go_live_wallets_unknown_name(tmp_path):
    confirm = _write_confirmation(tmp_path)
    config = _make_config(
        tmp_path,
        trading=TradingConfig(
            paper_trading=False,
            go_live_wallets=["nonexistent"],
            live_confirmation_path=str(confirm),
        ),
    )
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("nonexistent" in e for e in errors)


def test_go_live_wallets_valid_name(tmp_path):
    confirm = _write_confirmation(tmp_path)
    config = _make_config(
        tmp_path,
        trading=TradingConfig(
            paper_trading=False,
            go_live_wallets=["test_wallet"],
            live_confirmation_path=str(confirm),
        ),
    )
    assert _run(config) == []


def test_max_position_pct_exceeds_limit(tmp_path):
    config = _make_config(tmp_path, risk=RiskConfig(max_position_pct=0.60))
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("max_position_pct" in e for e in errors)


def test_paper_trading_skips_credential_check(tmp_path):
    config = _make_config(tmp_path, paper_trading=True, credentials=CredentialsConfig())
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    # No credential error when paper trading
    assert not any("credentials" in e.lower() for e in errors)


# ─── live opt-in / confirmation gates ──────────────────────────────────────────


def test_live_requires_env_opt_in(tmp_path):
    """LIVE_TRADING_ENABLED env var must be set to start live trading."""
    config = _make_config(tmp_path)
    errors = [msg for lvl, msg in _run(config, env={}) if lvl == "ERROR"]
    assert any("LIVE_TRADING_ENABLED" in e for e in errors)


def test_live_env_opt_in_accepts_truthy_variants(tmp_path):
    config = _make_config(tmp_path)
    for value in ["true", "TRUE", "1", "yes", "on"]:
        errors = [
            msg for lvl, msg in _run(config, env={"LIVE_TRADING_ENABLED": value})
            if lvl == "ERROR"
        ]
        assert not any("LIVE_TRADING_ENABLED" in e for e in errors), value


def test_live_env_opt_in_rejects_falsy(tmp_path):
    config = _make_config(tmp_path)
    for value in ["false", "0", "no", "off", ""]:
        errors = [
            msg for lvl, msg in _run(config, env={"LIVE_TRADING_ENABLED": value})
            if lvl == "ERROR"
        ]
        assert any("LIVE_TRADING_ENABLED" in e for e in errors), value


def test_paper_mode_does_not_require_env_opt_in(tmp_path):
    config = _make_config(tmp_path, paper_trading=True)
    errors = [msg for lvl, msg in _run(config, env={}) if lvl == "ERROR"]
    assert not any("LIVE_TRADING_ENABLED" in e for e in errors)


def test_live_requires_confirmation_marker_present(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    config = _make_config(
        tmp_path,
        trading=TradingConfig(
            paper_trading=False,
            live_confirmation_path=str(missing),
        ),
    )
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("confirmation marker missing" in e for e in errors)


def test_live_confirmation_marker_stale(tmp_path):
    confirm = _write_confirmation(tmp_path, age=timedelta(hours=48))
    config = _make_config(
        tmp_path,
        trading=TradingConfig(
            paper_trading=False,
            live_confirmation_path=str(confirm),
        ),
    )
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("stale" in e for e in errors)


def test_live_confirmation_marker_future_timestamp_blocked(tmp_path):
    confirm = tmp_path / "live-confirmed.json"
    confirm.write_text(
        json.dumps({"confirmed_at": (FIXED_NOW + timedelta(hours=2)).isoformat()}),
        encoding="utf-8",
    )
    config = _make_config(
        tmp_path,
        trading=TradingConfig(
            paper_trading=False,
            live_confirmation_path=str(confirm),
        ),
    )
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("future" in e for e in errors)


def test_live_confirmation_marker_invalid_json(tmp_path):
    confirm = tmp_path / "live-confirmed.json"
    confirm.write_text("not json at all", encoding="utf-8")
    config = _make_config(
        tmp_path,
        trading=TradingConfig(
            paper_trading=False,
            live_confirmation_path=str(confirm),
        ),
    )
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("unreadable" in e for e in errors)


def test_live_auto_revert_loss_pct_exceeds_hard_cap_blocked(tmp_path):
    confirm = _write_confirmation(tmp_path)
    config = _make_config(
        tmp_path,
        trading=TradingConfig(
            paper_trading=False,
            live_confirmation_path=str(confirm),
            live_auto_revert_loss_pct=0.50,  # 50% > 5% hard cap
        ),
    )
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("live_auto_revert_loss_pct" in e for e in errors)


def test_live_auto_revert_loss_pct_negative_blocked(tmp_path):
    confirm = _write_confirmation(tmp_path)
    config = _make_config(
        tmp_path,
        trading=TradingConfig(
            paper_trading=False,
            live_confirmation_path=str(confirm),
            live_auto_revert_loss_pct=-0.01,
        ),
    )
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert any("live_auto_revert_loss_pct" in e for e in errors)


def test_paper_mode_skips_confirmation_marker(tmp_path):
    # No marker file written, paper mode — must not error on confirmation.
    config = _make_config(tmp_path, paper_trading=True)
    errors = [msg for lvl, msg in _run(config) if lvl == "ERROR"]
    assert not any("confirmation marker" in e for e in errors)


# ─── unit tests for helpers ────────────────────────────────────────────────────


def test_env_flag_true_accepts_extras():
    from crypto_trader.config import _env_flag_true

    assert _env_flag_true({"FOO": "true"}, "FOO") is True
    assert _env_flag_true({"FOO": "TRUE"}, "FOO") is True
    assert _env_flag_true({"FOO": "1"}, "FOO") is True
    assert _env_flag_true({"FOO": "false"}, "FOO") is False
    assert _env_flag_true({}, "FOO") is False
    # Multiple aliases — any one matches
    assert _env_flag_true({"B": "yes"}, "A", "B") is True


def test_check_live_confirmation_fresh_returns_none(tmp_path):
    from crypto_trader.config import _check_live_confirmation

    path = _write_confirmation(tmp_path, age=timedelta(minutes=30))
    assert _check_live_confirmation(path, timedelta(hours=24), FIXED_NOW) is None


def test_check_live_confirmation_handles_naive_timestamp(tmp_path):
    from crypto_trader.config import _check_live_confirmation

    path = tmp_path / "live-confirmed.json"
    path.write_text(
        json.dumps({"confirmed_at": "2026-05-11T11:00:00"}),
        encoding="utf-8",
    )
    # 1h old, naive → assumed UTC
    assert _check_live_confirmation(path, timedelta(hours=24), FIXED_NOW) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
