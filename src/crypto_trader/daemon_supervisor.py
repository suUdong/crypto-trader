from __future__ import annotations

import json
import logging
import os
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError

from crypto_trader.notifications.alert_manager import TradeAlertManager


class SupportsRun(Protocol):
    def run(self) -> None: ...


class DaemonSupervisor:
    def __init__(
        self,
        runtime_factory: Callable[[int, str | None], SupportsRun],
        alert_manager: TradeAlertManager,
        healthcheck_path: str | Path,
        config_path: str,
        *,
        auto_restart_enabled: bool = True,
        restart_backoff_seconds: int = 15,
        max_restart_attempts: int = 0,
        daemon_alert_cooldown_seconds: int = 300,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._alert_manager = alert_manager
        self._healthcheck_path = Path(healthcheck_path)
        self._config_path = config_path
        self._auto_restart_enabled = auto_restart_enabled
        self._restart_backoff_seconds = restart_backoff_seconds
        self._max_restart_attempts = max_restart_attempts
        self._restart_count = 0
        self._last_restart_at: str | None = None
        self._daemon_alert_cooldown_seconds = daemon_alert_cooldown_seconds
        self._last_restart_alert_at: float | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def restart_count(self) -> int:
        return self._restart_count

    @property
    def last_restart_at(self) -> str | None:
        return self._last_restart_at

    def run(self) -> None:
        while True:
            runtime = self._runtime_factory(self._restart_count, self._last_restart_at)
            try:
                runtime.run()
                return
            except Exception as exc:
                self._logger.exception("Daemon runtime crashed")
                if not self._auto_restart_enabled:
                    self._write_supervisor_health("down", exc, recovery_delay_seconds=0)
                    self._emit_daemon_alert(
                        status="down",
                        error_message=str(exc),
                        restart_count=self._restart_count,
                        next_retry_seconds=0,
                        auto_restart_enabled=False,
                    )
                    raise

                self._restart_count += 1
                self._last_restart_at = datetime.now(UTC).isoformat()
                exhausted = (
                    self._max_restart_attempts > 0
                    and self._restart_count > self._max_restart_attempts
                )
                if exhausted:
                    self._write_supervisor_health("down", exc, recovery_delay_seconds=0)
                    self._emit_daemon_alert(
                        status="down",
                        error_message=str(exc),
                        restart_count=self._restart_count,
                        next_retry_seconds=0,
                        auto_restart_enabled=True,
                    )
                    raise

                self._write_supervisor_health(
                    "restarting",
                    exc,
                    recovery_delay_seconds=self._restart_backoff_seconds,
                )
                self._emit_daemon_alert(
                    status="restarting",
                    error_message=str(exc),
                    restart_count=self._restart_count,
                    next_retry_seconds=self._restart_backoff_seconds,
                    auto_restart_enabled=True,
                )
                time.sleep(self._restart_backoff_seconds)

    def _emit_daemon_alert(
        self,
        *,
        status: str,
        error_message: str,
        restart_count: int,
        next_retry_seconds: int,
        auto_restart_enabled: bool,
    ) -> None:
        now = time.monotonic()
        if status == "restarting":
            if (
                self._last_restart_alert_at is not None
                and now - self._last_restart_alert_at < self._daemon_alert_cooldown_seconds
            ):
                return
            self._last_restart_alert_at = now
        self._alert_manager.alert_daemon_status(
            status=status,
            error_message=error_message,
            restart_count=restart_count,
            next_retry_seconds=next_retry_seconds,
            auto_restart_enabled=auto_restart_enabled,
        )

    def _write_supervisor_health(
        self,
        status: str,
        exc: Exception,
        *,
        recovery_delay_seconds: int,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        previous = self._load_previous_health()
        payload = {
            "updated_at": now,
            "success": False,
            "status": status,
            "degraded": True,
            "consecutive_failures": int(previous.get("consecutive_failures", 0) or 0) + 1,
            "failure_streak": int(previous.get("failure_streak", 0) or 0) + 1,
            "last_error": str(exc),
            "last_error_type": type(exc).__name__,
            "last_signal": previous.get("last_signal", "hold"),
            "last_order_status": previous.get("last_order_status"),
            "cash": previous.get("cash", 0.0),
            "open_positions": previous.get("open_positions", 0),
            "total_equity": previous.get("total_equity", 0.0),
            "wallet_count": previous.get("wallet_count", 0),
            "mode": "multi_symbol",
            "recoverable_error": self._is_recoverable_error(exc),
            "recovery_delay_seconds": recovery_delay_seconds,
            "last_success_at": previous.get("last_success_at"),
            "last_failure_at": now,
            "tick_started_at": previous.get("tick_started_at"),
            "tick_completed_at": previous.get("tick_completed_at"),
            "tick_duration_seconds": previous.get("tick_duration_seconds"),
            "successful_results": previous.get("successful_results", 0),
            "failed_results": previous.get("failed_results", 0),
            "restart_count": self._restart_count,
            "last_restart_at": self._last_restart_at,
            "supervisor_active": True,
            "auto_restart_enabled": self._auto_restart_enabled,
            "config_path": self._config_path,
        }
        self._healthcheck_path.parent.mkdir(parents=True, exist_ok=True)
        self._healthcheck_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._write_supervisor_heartbeat(status, exc, now, recovery_delay_seconds)

    def _load_previous_health(self) -> dict[str, object]:
        if not self._healthcheck_path.exists():
            return {}
        try:
            return json.loads(self._healthcheck_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_supervisor_heartbeat(
        self,
        status: str,
        exc: Exception,
        now: str,
        recovery_delay_seconds: int,
    ) -> None:
        heartbeat_path = self._healthcheck_path.parent / "daemon-heartbeat.json"
        previous: dict[str, object] = {}
        if heartbeat_path.exists():
            try:
                previous = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            except Exception:
                previous = {}
        payload = {
            "last_heartbeat": now,
            "pid": os.getpid(),
            "status": status,
            "failure_streak": previous.get("failure_streak", 0),
            "last_error": str(exc),
            "last_error_type": type(exc).__name__,
            "last_success_at": previous.get("last_success_at"),
            "last_failure_at": now,
            "recoverable_error": self._is_recoverable_error(exc),
            "recovery_delay_seconds": recovery_delay_seconds,
            "restart_count": self._restart_count,
            "last_restart_at": self._last_restart_at,
            "supervisor_active": True,
            "config_path": self._config_path,
        }
        heartbeat_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _is_recoverable_error(self, exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError, socket.timeout, URLError)):
            return True
        if isinstance(exc, HTTPError):
            return exc.code >= 500 or exc.code == 429
        message = str(exc).lower()
        transient_markers = (
            "timeout",
            "timed out",
            "temporarily unavailable",
            "temporary failure",
            "connection reset",
            "connection aborted",
            "connection refused",
            "broken pipe",
            "network",
            "remote end closed connection",
            "name or service not known",
        )
        return any(marker in message for marker in transient_markers)
