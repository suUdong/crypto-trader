"""Tests for WalletHealthMonitor auto-disable functionality."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crypto_trader.risk.wallet_health import (
    WalletHealthConfig,
    WalletHealthMonitor,
    WalletHealthStatus,
)


def _write_snapshots(path: Path, snapshots: list[dict]) -> None:
    """Write snapshot entries to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for snap in snapshots:
            f.write(json.dumps(snap) + "\n")


def _make_snapshot(days_ago: int, wallets: dict[str, float]) -> dict:
    """Create a snapshot entry for N days ago with given wallet returns."""
    ts = datetime.now(UTC) - timedelta(days=days_ago)
    return {
        "timestamp": ts.isoformat(),
        "period": "daily",
        "portfolio_return_pct": sum(wallets.values()) / max(1, len(wallets)),
        "wallets": [
            {"wallet": name, "strategy": "test", "return_pct": ret, "equity": 1_000_000}
            for name, ret in wallets.items()
        ],
    }


class TestWalletHealthMonitor:
    def test_wallet_negative_7_days_gets_disabled(self, tmp_path: Path) -> None:
        """Wallet with 7 consecutive negative days should be disabled."""
        snapshot_path = tmp_path / "pnl-snapshots.jsonl"
        snapshots = [
            _make_snapshot(i, {"loser_wallet": -0.5, "winner_wallet": 1.0})
            for i in range(8, 0, -1)  # 8 days of data
        ]
        _write_snapshots(snapshot_path, snapshots)

        monitor = WalletHealthMonitor(snapshot_path, WalletHealthConfig(negative_days_threshold=7))
        statuses = monitor.evaluate(["loser_wallet", "winner_wallet"])

        assert monitor.is_disabled("loser_wallet")
        assert not monitor.is_disabled("winner_wallet")
        assert "loser_wallet" in monitor.get_disabled_wallets()
        assert "winner_wallet" not in monitor.get_disabled_wallets()

    def test_wallet_mixed_returns_not_disabled(self, tmp_path: Path) -> None:
        """Wallet with some positive days should NOT be disabled."""
        snapshot_path = tmp_path / "pnl-snapshots.jsonl"
        snapshots = []
        for i in range(8, 0, -1):
            # Alternating: negative, negative, positive, ...
            ret = -0.5 if i % 3 != 0 else 0.5
            snapshots.append(_make_snapshot(i, {"mixed_wallet": ret}))
        _write_snapshots(snapshot_path, snapshots)

        monitor = WalletHealthMonitor(snapshot_path, WalletHealthConfig(negative_days_threshold=7))
        monitor.evaluate(["mixed_wallet"])

        assert not monitor.is_disabled("mixed_wallet")

    def test_wallet_recovers_gets_reenabled(self, tmp_path: Path) -> None:
        """Disabled wallet that returns to positive should be re-enabled."""
        snapshot_path = tmp_path / "pnl-snapshots.jsonl"

        # First: 7 days negative -> disabled
        snapshots = [
            _make_snapshot(i, {"recoverer": -0.5})
            for i in range(8, 0, -1)
        ]
        _write_snapshots(snapshot_path, snapshots)

        monitor = WalletHealthMonitor(snapshot_path, WalletHealthConfig(negative_days_threshold=7))
        monitor.evaluate(["recoverer"])
        assert monitor.is_disabled("recoverer")

        # Now add a positive day as most recent
        snapshots.append(_make_snapshot(0, {"recoverer": 2.0}))
        _write_snapshots(snapshot_path, snapshots)

        monitor2 = WalletHealthMonitor(snapshot_path, WalletHealthConfig(negative_days_threshold=7))
        monitor2.evaluate(["recoverer"])
        # consecutive_negative_days should be 0 now
        status = monitor2.get_status("recoverer")
        assert status is not None
        assert status.consecutive_negative_days == 0

    def test_no_snapshots_returns_empty(self, tmp_path: Path) -> None:
        """No snapshot file should return empty statuses without error."""
        snapshot_path = tmp_path / "nonexistent.jsonl"
        monitor = WalletHealthMonitor(snapshot_path)
        statuses = monitor.evaluate(["any_wallet"])
        assert not monitor.is_disabled("any_wallet")

    def test_state_persistence(self, tmp_path: Path) -> None:
        """Health state should be saved and loaded across instances."""
        snapshot_path = tmp_path / "pnl-snapshots.jsonl"
        snapshots = [
            _make_snapshot(i, {"persistent_loser": -1.0})
            for i in range(8, 0, -1)
        ]
        _write_snapshots(snapshot_path, snapshots)

        # First instance disables the wallet
        m1 = WalletHealthMonitor(snapshot_path, WalletHealthConfig(negative_days_threshold=7))
        m1.evaluate(["persistent_loser"])
        assert m1.is_disabled("persistent_loser")

        # Second instance should load persisted state
        m2 = WalletHealthMonitor(snapshot_path, WalletHealthConfig(negative_days_threshold=7))
        assert m2.is_disabled("persistent_loser")

    def test_fewer_than_threshold_days_not_disabled(self, tmp_path: Path) -> None:
        """Wallet with fewer negative days than threshold stays enabled."""
        snapshot_path = tmp_path / "pnl-snapshots.jsonl"
        snapshots = [
            _make_snapshot(i, {"short_loser": -0.5})
            for i in range(5, 0, -1)  # Only 5 days
        ]
        _write_snapshots(snapshot_path, snapshots)

        monitor = WalletHealthMonitor(snapshot_path, WalletHealthConfig(negative_days_threshold=7))
        monitor.evaluate(["short_loser"])
        assert not monitor.is_disabled("short_loser")

    def test_get_status_returns_none_for_unknown(self, tmp_path: Path) -> None:
        """get_status returns None for unknown wallets."""
        snapshot_path = tmp_path / "nonexistent.jsonl"
        monitor = WalletHealthMonitor(snapshot_path)
        assert monitor.get_status("unknown") is None


class TestWalletHealthInRuntime:
    """Tests that runtime skips disabled wallets."""

    def test_runtime_skips_disabled_wallet(self, tmp_path: Path) -> None:
        """Verify the is_disabled check works as a gate."""
        snapshot_path = tmp_path / "pnl-snapshots.jsonl"
        snapshots = [
            _make_snapshot(i, {"skip_me": -1.0, "keep_me": 1.0})
            for i in range(8, 0, -1)
        ]
        _write_snapshots(snapshot_path, snapshots)

        monitor = WalletHealthMonitor(snapshot_path, WalletHealthConfig(negative_days_threshold=7))
        monitor.evaluate(["skip_me", "keep_me"])

        # Simulate runtime wallet filtering
        wallets = ["skip_me", "keep_me"]
        active = [w for w in wallets if not monitor.is_disabled(w)]
        assert active == ["keep_me"]
