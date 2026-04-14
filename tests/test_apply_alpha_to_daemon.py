from __future__ import annotations

from pathlib import Path

from scripts import apply_alpha_to_daemon as aad


def test_apply_alpha_to_daemon_uses_only_active_accumulation_wallets(
    tmp_path: Path,
) -> None:
    config = tmp_path / "daemon.toml"
    config.write_text(
        """
[[wallets]]
name = "accumulation_dood_wallet"
strategy = "accumulation_breakout"
symbols = ["KRW-OLD"]

# [[wallets]]
# name = "accumulation_tree_wallet"
# strategy = "accumulation_breakout"
# symbols = ["KRW-SHOULD_STAY_COMMENTED"]

[[wallets]]
name = "momentum_wallet"
strategy = "momentum"
symbols = ["KRW-BTC"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    old_daemon_config = aad.DAEMON_CONFIG
    try:
        aad.DAEMON_CONFIG = config
        aad.apply_alpha_to_daemon(["KRW-NEW"], cycle=233)
    finally:
        aad.DAEMON_CONFIG = old_daemon_config

    updated = config.read_text(encoding="utf-8")
    assert 'name = "accumulation_dood_wallet"' in updated
    assert 'symbols = ["KRW-NEW"]' in updated
    assert 'name = "momentum_wallet"' in updated
    assert 'symbols = ["KRW-BTC"]' in updated
    assert '# symbols = ["KRW-SHOULD_STAY_COMMENTED"]' in updated
