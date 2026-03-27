from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_trader.daemon_supervisor import DaemonSupervisor
from crypto_trader.notifications.alert_manager import TradeAlertManager
from crypto_trader.notifications.telegram import Notifier


class _RecordingNotifier(Notifier):
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, message: str) -> None:
        self.messages.append(message)


class _CrashThenRecoverRuntime:
    def __init__(self, should_crash: bool) -> None:
        self._should_crash = should_crash

    def run(self) -> None:
        if self._should_crash:
            raise RuntimeError("upbit network down")


class TestDaemonSupervisor(unittest.TestCase):
    def test_restarts_after_runtime_crash_and_sends_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            health_path = Path(temp_dir) / "health.json"
            notifier = _RecordingNotifier()
            starts: list[int] = []

            def factory(
                restart_count: int,
                last_restart_at: str | None,
            ) -> _CrashThenRecoverRuntime:
                starts.append(restart_count)
                return _CrashThenRecoverRuntime(should_crash=restart_count == 0)

            supervisor = DaemonSupervisor(
                runtime_factory=factory,
                alert_manager=TradeAlertManager([notifier]),
                healthcheck_path=health_path,
                config_path="config/daemon.toml",
                auto_restart_enabled=True,
                restart_backoff_seconds=3,
                max_restart_attempts=0,
            )

            with patch("crypto_trader.daemon_supervisor.time.sleep") as sleep:
                supervisor.run()

            self.assertEqual(starts, [0, 1])
            sleep.assert_called_once_with(3)
            self.assertEqual(supervisor.restart_count, 1)
            self.assertEqual(len(notifier.messages), 1)
            self.assertIn("RESTARTING", notifier.messages[0])
            payload = json.loads(health_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "restarting")
            self.assertEqual(payload["restart_count"], 1)
            self.assertIn("upbit network down", payload["last_error"])
            heartbeat = json.loads((Path(temp_dir) / "daemon-heartbeat.json").read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "restarting")
            self.assertTrue(heartbeat["recoverable_error"])

    def test_marks_down_when_restart_budget_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            health_path = Path(temp_dir) / "health.json"
            notifier = _RecordingNotifier()

            supervisor = DaemonSupervisor(
                runtime_factory=lambda restart_count, last_restart_at: _CrashThenRecoverRuntime(
                    should_crash=True
                ),
                alert_manager=TradeAlertManager([notifier]),
                healthcheck_path=health_path,
                config_path="config/daemon.toml",
                auto_restart_enabled=True,
                restart_backoff_seconds=1,
                max_restart_attempts=1,
            )

            with patch("crypto_trader.daemon_supervisor.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "upbit network down"):
                    supervisor.run()

            payload = json.loads(health_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "down")
            self.assertEqual(payload["restart_count"], 2)
            self.assertEqual(len(notifier.messages), 2)
            self.assertIn("DOWN", notifier.messages[-1])

    def test_restart_alerts_are_throttled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            health_path = Path(temp_dir) / "health.json"
            notifier = _RecordingNotifier()
            attempt = {"count": 0}

            def factory(restart_count: int, last_restart_at: str | None) -> _CrashThenRecoverRuntime:
                attempt["count"] += 1
                if attempt["count"] >= 4:
                    return _CrashThenRecoverRuntime(should_crash=False)
                return _CrashThenRecoverRuntime(should_crash=True)

            supervisor = DaemonSupervisor(
                runtime_factory=factory,
                alert_manager=TradeAlertManager([notifier]),
                healthcheck_path=health_path,
                config_path="config/daemon.toml",
                auto_restart_enabled=True,
                restart_backoff_seconds=1,
                max_restart_attempts=0,
                daemon_alert_cooldown_seconds=60,
            )

            with patch("crypto_trader.daemon_supervisor.time.sleep"), patch(
                "crypto_trader.daemon_supervisor.time.monotonic",
                side_effect=[0.0, 5.0, 10.0, 15.0, 20.0],
            ):
                supervisor.run()

            self.assertEqual(supervisor.restart_count, 3)
            self.assertEqual(len(notifier.messages), 1)
            self.assertIn("RESTARTING", notifier.messages[0])


if __name__ == "__main__":
    unittest.main()
