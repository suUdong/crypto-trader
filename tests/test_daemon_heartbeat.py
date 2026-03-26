"""Tests for daemon heartbeat mechanism."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from crypto_trader.multi_runtime import MultiSymbolRuntime


class TestDaemonHeartbeat(unittest.TestCase):
    def _make_runtime(self, artifacts_dir: str) -> MultiSymbolRuntime:
        config = MagicMock()
        config.trading.symbols = ["KRW-BTC"]
        config.trading.interval = "minute60"
        config.trading.candle_count = 200
        config.runtime.max_iterations = 1
        config.runtime.daemon_mode = False
        config.runtime.poll_interval_seconds = 60
        config.runtime.runtime_checkpoint_path = f"{artifacts_dir}/runtime-checkpoint.json"
        config.source_config_path = "config/test-daemon.toml"

        wallet = MagicMock()
        wallet.name = "test_wallet"
        wallet.strategy_type = "momentum"
        wallet.broker.cash = 1_000_000.0
        wallet.broker.realized_pnl = 0.0
        wallet.broker.positions = []
        wallet.broker.closed_trades = []
        wallet.broker.equity.return_value = 1_000_000.0

        result = MagicMock()
        result.latest_price = 50_000_000.0
        result.symbol = "KRW-BTC"
        result.error = None
        result.message = "hold"
        wallet.run_once.return_value = result

        market_data = MagicMock()
        market_data.get_ohlcv.return_value = [MagicMock()]

        runtime = MultiSymbolRuntime(
            wallets=[wallet],
            market_data=market_data,
            config=config,
        )
        runtime._config_path = "config/test-daemon.toml"
        return runtime

    def test_heartbeat_written_on_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_runtime(tmpdir)
            # Simulate one tick + checkpoint
            results = runtime._run_tick(["KRW-BTC"])
            runtime._save_checkpoint(results)

            heartbeat_path = Path(tmpdir) / "daemon-heartbeat.json"
            self.assertTrue(heartbeat_path.exists(), "heartbeat file should be created")

            data = json.loads(heartbeat_path.read_text())
            self.assertIn("last_heartbeat", data)
            self.assertIn("pid", data)
            self.assertIn("iteration", data)
            self.assertIn("uptime_seconds", data)
            self.assertIn("poll_interval_seconds", data)
            self.assertIn("session_id", data)
            self.assertIn("config_path", data)
            self.assertIn("wallet_names", data)
            self.assertIn("symbols", data)
            self.assertEqual(data["iteration"], 1)
            self.assertEqual(data["poll_interval_seconds"], 60)
            self.assertEqual(data["config_path"], "config/test-daemon.toml")
            self.assertEqual(data["wallet_names"], ["test_wallet"])
            self.assertEqual(data["symbols"], ["KRW-BTC"])
            self.assertIsInstance(data["pid"], int)
            self.assertGreaterEqual(data["uptime_seconds"], 0)

    def test_heartbeat_timestamp_is_valid_iso8601_utc(self) -> None:
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_runtime(tmpdir)
            results = runtime._run_tick(["KRW-BTC"])
            runtime._save_checkpoint(results)

            heartbeat_path = Path(tmpdir) / "daemon-heartbeat.json"
            data = json.loads(heartbeat_path.read_text())

            ts = data["last_heartbeat"]
            # Must parse as ISO8601
            parsed = datetime.fromisoformat(ts)
            # Must be UTC (offset-aware with +00:00)
            self.assertIsNotNone(parsed.tzinfo)
            self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_heartbeat_updates_on_subsequent_ticks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_runtime(tmpdir)

            # First tick
            results = runtime._run_tick(["KRW-BTC"])
            runtime._save_checkpoint(results)
            runtime._iteration += 1

            heartbeat_path = Path(tmpdir) / "daemon-heartbeat.json"
            data1 = json.loads(heartbeat_path.read_text())

            # Second tick
            results = runtime._run_tick(["KRW-BTC"])
            runtime._save_checkpoint(results)

            data2 = json.loads(heartbeat_path.read_text())
            self.assertEqual(data2["iteration"], 2)
            self.assertGreaterEqual(data2["uptime_seconds"], data1["uptime_seconds"])


if __name__ == "__main__":
    unittest.main()
