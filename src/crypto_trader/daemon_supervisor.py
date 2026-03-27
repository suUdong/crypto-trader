from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

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
                    self._alert_manager.alert_daemon_status(
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
                    self._alert_manager.alert_daemon_status(
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
                self._alert_manager.alert_daemon_status(
                    status="restarting",
                    error_message=str(exc),
                    restart_count=self._restart_count,
                    next_retry_seconds=self._restart_backoff_seconds,
                    auto_restart_enabled=True,
                )
                time.sleep(self._restart_backoff_seconds)

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
            "recoverable_error": self._auto_restart_enabled,
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

    def _load_previous_health(self) -> dict[str, object]:
        if not self._healthcheck_path.exists():
            return {}
        try:
            return json.loads(self._healthcheck_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
