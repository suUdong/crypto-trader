"""Tests for daemon heartbeat mechanism."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from crypto_trader.models import Candle
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
        config.runtime.position_snapshot_path = f"{artifacts_dir}/positions.json"
        config.runtime.healthcheck_path = f"{artifacts_dir}/health.json"
        config.runtime.daily_performance_path = f"{artifacts_dir}/daily-performance.json"
        config.runtime.promotion_gate_path = f"{artifacts_dir}/promotion-gate.json"
        config.runtime.regime_report_path = f"{artifacts_dir}/regime-report.json"
        config.runtime.operator_report_path = f"{artifacts_dir}/operator-report.md"
        config.runtime.drift_report_path = f"{artifacts_dir}/drift-report.json"
        config.runtime.drift_calibration_path = f"{artifacts_dir}/drift-calibration.json"
        config.runtime.daily_memo_path = f"{artifacts_dir}/daily-memo.md"
        config.runtime.strategy_report_path = f"{artifacts_dir}/strategy-report.md"
        config.runtime.backtest_baseline_path = f"{artifacts_dir}/backtest-baseline.json"
        config.runtime.paper_trade_journal_path = f"{artifacts_dir}/paper-trades.jsonl"
        config.runtime.strategy_run_journal_path = f"{artifacts_dir}/strategy-runs.jsonl"
        config.runtime.network_recovery_backoff_seconds = 15
        config.source_config_path = "config/test-daemon.toml"
        config.macro.enabled = False
        config.slack.enabled = False
        config.regime.short_lookback = 10
        config.regime.long_lookback = 30
        config.regime.bull_threshold_pct = 0.03
        config.regime.bear_threshold_pct = -0.03
        config.kill_switch.max_portfolio_drawdown_pct = 0.15
        config.kill_switch.max_daily_loss_pct = 0.05
        config.kill_switch.max_consecutive_losses = 5
        config.kill_switch.max_strategy_drawdown_pct = 0.1
        config.kill_switch.cooldown_minutes = 60
        config.kill_switch.warn_threshold_pct = 0.5
        config.kill_switch.reduce_threshold_pct = 0.75
        config.kill_switch.reduce_position_factor = 0.5

        wallet = MagicMock()
        wallet.name = "test_wallet"
        wallet.strategy_type = "momentum"
        wallet.session_starting_equity = 1_000_000.0
        wallet.allowed_symbols = []
        wallet.broker.cash = 1_000_000.0
        wallet.broker.realized_pnl = 0.0
        wallet.broker.positions = {}
        wallet.broker.closed_trades = []
        wallet.broker.equity.return_value = 1_000_000.0

        result = MagicMock()
        result.latest_price = 50_000_000.0
        result.symbol = "KRW-BTC"
        result.error = None
        result.message = "hold"
        result.order = None
        result.signal.action.value = "hold"
        result.signal.reason = "entry_conditions_not_met"
        result.signal.confidence = 0.2
        result.signal.indicators = {}
        result.signal.context = {}
        wallet.run_once.return_value = result

        market_data = MagicMock()
        market_data.get_ohlcv.return_value = [
            Candle(
                timestamp=datetime(2026, 3, 27, 0, 0, 0) + timedelta(hours=i),
                open=50_000_000.0,
                high=50_500_000.0,
                low=49_500_000.0,
                close=50_000_000.0,
                volume=1.0 + i,
            )
            for i in range(220)
        ]

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
            self.assertIn("status", data)
            self.assertIn("failure_streak", data)
            self.assertIn("last_success_at", data)
            self.assertIn("restart_count", data)
            self.assertIn("supervisor_active", data)
            self.assertEqual(data["iteration"], 1)
            self.assertEqual(data["poll_interval_seconds"], 60)
            self.assertEqual(data["config_path"], "config/test-daemon.toml")
            self.assertEqual(data["wallet_names"], ["test_wallet"])
            self.assertEqual(data["symbols"], ["KRW-BTC"])
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["failure_streak"], 0)
            self.assertEqual(data["restart_count"], 0)
            self.assertFalse(data["supervisor_active"])
            self.assertIsInstance(data["pid"], int)
            self.assertGreaterEqual(data["uptime_seconds"], 0)

    def test_heartbeat_timestamp_is_valid_iso8601_utc(self) -> None:
        from datetime import datetime

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

    def test_checkpoint_overwrites_stale_dashboard_artifacts_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            health_path = Path(tmpdir) / "health.json"
            positions_path = Path(tmpdir) / "positions.json"
            daily_path = Path(tmpdir) / "daily-performance.json"
            health_path.write_text(json.dumps({"wallet_count": 15, "open_positions": 9}))
            positions_path.write_text(
                json.dumps(
                    {
                        "count": 2,
                        "positions": [
                            {"wallet": "legacy_wallet", "symbol": "KRW-BTC", "qty": 1.0}
                        ],
                    }
                )
            )
            daily_path.write_text(json.dumps({"trade_count": 99, "mode": "legacy"}))

            runtime = self._make_runtime(tmpdir)
            results = runtime._run_tick(["KRW-BTC"])
            runtime._save_checkpoint(results)
            runtime._refresh_runtime_artifacts()

            health = json.loads(health_path.read_text())
            positions = json.loads(positions_path.read_text())
            daily = json.loads(daily_path.read_text())

            self.assertEqual(health["wallet_count"], 1)
            self.assertEqual(health["open_positions"], 0)
            self.assertEqual(positions["count"], 0)
            self.assertEqual(positions["positions"], [])
            self.assertEqual(daily["trade_count"], 0)
            self.assertEqual(daily["mode"], "multi_symbol")

    def test_promotion_gate_refreshes_on_first_tick(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_runtime(tmpdir)
            with (
                patch.object(runtime, "_refresh_portfolio_promotion") as refresh_promo,
                patch.object(runtime, "_refresh_extended_artifacts") as refresh_extended,
            ):
                runtime._iteration = 0
                runtime._maybe_refresh_artifacts()
            refresh_promo.assert_called_once()
            refresh_extended.assert_called_once()

    def test_promotion_gate_skips_non_boundary_ticks_after_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_runtime(tmpdir)
            with (
                patch.object(runtime, "_refresh_portfolio_promotion") as refresh_promo,
                patch.object(runtime, "_refresh_extended_artifacts") as refresh_extended,
            ):
                runtime._iteration = 1
                runtime._maybe_refresh_artifacts()
            refresh_promo.assert_not_called()
            refresh_extended.assert_not_called()

    def test_runtime_sends_systemd_ready_watchdog_and_stopping_notifications(self) -> None:
        class _RecordingNotifier:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def notify_ready(self, status: str) -> bool:
                self.calls.append(("ready", status))
                return True

            def notify_watchdog(self, status: str) -> bool:
                self.calls.append(("watchdog", status))
                return True

            def notify_stopping(self, status: str) -> bool:
                self.calls.append(("stopping", status))
                return True

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_runtime(tmpdir)
            runtime._systemd_notifier = _RecordingNotifier()
            with (
                patch.object(runtime, "_refresh_runtime_artifacts"),
                patch.object(runtime, "_maybe_refresh_artifacts"),
                patch.object(runtime, "_maybe_send_pnl_notify"),
                patch.object(runtime, "_maybe_alert_runtime_status"),
            ):
                runtime.run()

            calls = runtime._systemd_notifier.calls
            self.assertEqual(calls[0][0], "ready")
            self.assertEqual(calls[-1][0], "stopping")
            self.assertTrue(any(name == "watchdog" for name, _ in calls))
            watchdog_statuses = [status for name, status in calls if name == "watchdog"]
            self.assertTrue(
                any("iteration=1" in status for status in watchdog_statuses),
                "watchdog status should describe the completed tick",
            )


if __name__ == "__main__":
    unittest.main()
