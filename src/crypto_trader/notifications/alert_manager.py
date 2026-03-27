from __future__ import annotations

import logging
from collections.abc import Sequence

from crypto_trader.notifications.telegram import Notifier

_log = logging.getLogger(__name__)


class TradeAlertManager:
    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self._notifiers = list(notifiers)

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
        self._send(message)

    def alert_error(
        self,
        wallet_name: str,
        symbol: str,
        error_message: str,
    ) -> None:
        message = f"\u274c ERROR | {wallet_name}\n{symbol}: {error_message}"
        self._send(message)

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
        self._send(message)

    def _send(self, message: str) -> None:
        for notifier in self._notifiers:
            try:
                notifier.send_message(message)
            except Exception as exc:
                _log.warning("Notification failed (%s): %s", type(notifier).__name__, exc)
