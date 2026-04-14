from __future__ import annotations

from pathlib import Path

from scripts import wallet_auto_updater as wau


def test_update_symbols_returns_none_when_wallet_missing(tmp_path: Path) -> None:
    config = tmp_path / "daemon.toml"
    config.write_text(
        """
[[wallets]]
name = "existing_wallet"
symbols = ["KRW-BTC"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    original = config.read_text(encoding="utf-8")
    old_path = wau.DAEMON_CONFIG
    try:
        wau.DAEMON_CONFIG = config
        diff = wau.update_symbols("missing_wallet", "KRW-SOL")
    finally:
        wau.DAEMON_CONFIG = old_path

    assert diff is None
    assert config.read_text(encoding="utf-8") == original


def test_update_symbols_updates_existing_wallet(tmp_path: Path) -> None:
    config = tmp_path / "daemon.toml"
    config.write_text(
        """
[[wallets]]
name = "existing_wallet"
symbols = ["KRW-BTC"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    old_path = wau.DAEMON_CONFIG
    try:
        wau.DAEMON_CONFIG = config
        diff = wau.update_symbols("existing_wallet", "KRW-SOL")
    finally:
        wau.DAEMON_CONFIG = old_path

    assert diff == {"before": "KRW-BTC", "after": "KRW-SOL"}
    assert 'symbols = ["KRW-SOL"]' in config.read_text(encoding="utf-8")


def test_update_symbols_ignores_commented_wallet_block(tmp_path: Path) -> None:
    config = tmp_path / "daemon.toml"
    config.write_text(
        """
# [[wallets]]
# name = "accumulation_tree_wallet"
# strategy = "accumulation_breakout"
# symbols = ["KRW-OLD"]

[[wallets]]
name = "momentum_wallet"
symbols = ["KRW-BTC"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    original = config.read_text(encoding="utf-8")
    old_path = wau.DAEMON_CONFIG
    try:
        wau.DAEMON_CONFIG = config
        diff = wau.update_symbols("accumulation_tree_wallet", "KRW-SOL")
    finally:
        wau.DAEMON_CONFIG = old_path

    assert diff is None
    assert config.read_text(encoding="utf-8") == original
