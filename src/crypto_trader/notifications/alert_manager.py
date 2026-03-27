from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from crypto_trader.notifications.telegram import Notifier

_log = logging.getLogger(__name__)


class TradeAlertManager:
    _ERROR_ALERT_COOLDOWN_SECONDS = 300
    _REJECTION_ALERT_COOLDOWN_SECONDS = 300
    _DAEMON_ALERT_COOLDOWN_SECONDS = 300

    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self._notifiers = list(notifiers)
        self._last_sent_at: dict[str, float] = {}

    def alert_trade(
        self,
        wallet_name: str,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        fee_paid: float,
        reason: str,
    ) -> None:
        message = (
            f"\U0001f514 TRADE | {wallet_name}\n"
            f"{side.upper()} {symbol} qty={quantity} @ {fill_price:,.0f}\n"
            f"Reason: {reason} | Fee: {fee_paid:,.0f} KRW"
        )
        self._send(message)

    def alert_rejection(
        self,
        wallet_name: str,
        symbol: str,
        side: str,
        reason: str,
    ) -> None:
        message = f"\u26a0\ufe0f REJECTED | {wallet_name}\n{side.upper()} {symbol} \u2014 {reason}"
        self._send_with_cooldown(
            f"rejection:{wallet_name}:{symbol}:{side}:{reason}",
            message,
            self._REJECTION_ALERT_COOLDOWN_SECONDS,
        )

    def alert_error(
        self,
        wallet_name: str,
        symbol: str,
        error_message: str,
    ) -> None:
        message = f"\u274c ERROR | {wallet_name}\n{symbol}: {error_message}"
        self._send_with_cooldown(
            f"error:{wallet_name}:{symbol}:{error_message}",
            message,
            self._ERROR_ALERT_COOLDOWN_SECONDS,
        )

    def alert_kill_switch(
        self,
        reason: str,
        portfolio_dd: float,
        daily_loss: float,
        consecutive_losses: int,
    ) -> None:
        message = (
            f"\U0001f6a8 KILL SWITCH TRIGGERED\n"
            f"Reason: {reason}\n"
            f"DD: {portfolio_dd:.1%} | Daily: {daily_loss:.1%} | Losses: {consecutive_losses}"
        )
        self._send(message)

    def alert_daemon_status(
        self,
        *,
        status: str,
        error_message: str,
        restart_count: int,
        next_retry_seconds: int,
        auto_restart_enabled: bool,
    ) -> None:
        action = "auto-restart enabled" if auto_restart_enabled else "manual intervention required"
        retry = (
            f"next retry in {next_retry_seconds}s"
            if next_retry_seconds > 0
            else "no further automatic retry scheduled"
        )
        message = (
            f"[DAEMON] {status.upper()}\n"
            f"Reason: {error_message}\n"
            f"Restarts: {restart_count} | {retry}\n"
            f"Recovery: {action}"
        )
        self._send_with_cooldown(
            f"daemon:{status}:{error_message}",
            message,
            self._DAEMON_ALERT_COOLDOWN_SECONDS,
        )

    def _send(self, message: str) -> None:
        for notifier in self._notifiers:
            try:
                notifier.send_message(message)
            except Exception as exc:
                _log.warning("Notification failed (%s): %s", type(notifier).__name__, exc)

    def _send_with_cooldown(self, key: str, message: str, cooldown_seconds: int) -> None:
        now = time.monotonic()
        last_sent = self._last_sent_at.get(key)
        if last_sent is not None and now - last_sent < cooldown_seconds:
            return
        self._last_sent_at[key] = now
        self._send(message)
