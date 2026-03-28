from __future__ import annotations

import logging
import os
import socket


class SystemdNotifier:
    def __init__(self, notify_socket: str | None = None) -> None:
        self._notify_socket = notify_socket or os.getenv("NOTIFY_SOCKET")
        self._logger = logging.getLogger(__name__)

    @classmethod
    def from_env(cls) -> SystemdNotifier:
        return cls()

    def notify_ready(self, status: str) -> bool:
        return self._send("READY=1", f"STATUS={status}")

    def notify_watchdog(self, status: str) -> bool:
        return self._send("WATCHDOG=1", f"STATUS={status}")

    def notify_stopping(self, status: str) -> bool:
        return self._send("STOPPING=1", f"STATUS={status}")

    def _send(self, *messages: str) -> bool:
        if not self._notify_socket:
            return False
        target = self._notify_socket
        if target.startswith("@"):
            target = "\0" + target[1:]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.connect(target)
                sock.sendall("\n".join(messages).encode("utf-8"))
        except OSError as exc:
            self._logger.debug("systemd notification failed: %s", exc)
            return False
        return True
