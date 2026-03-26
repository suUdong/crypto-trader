from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import request

from crypto_trader.config import SlackConfig, TelegramConfig


class Notifier:
    def send_message(self, message: str) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class NullNotifier(Notifier):
    def send_message(self, message: str) -> None:
        return None


class TelegramNotifier(Notifier):
    def __init__(self, config: TelegramConfig) -> None:
        self._config = config

    def send_message(self, message: str) -> None:
        if not self._config.enabled:
            return
        url = f"https://api.telegram.org/bot{self._config.bot_token}/sendMessage"
        payload = json.dumps({"chat_id": self._config.chat_id, "text": message}).encode("utf-8")
        req = request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:
            if response.status >= 400:
                raise RuntimeError(f"Telegram notification failed with status {response.status}")


class SlackNotifier(Notifier):
    def __init__(self, config: SlackConfig) -> None:
        self._config = config

    def send_message(self, message: str) -> None:
        if not self._config.enabled:
            return
        payload = json.dumps({"text": message}).encode("utf-8")
        req = request.Request(
            self._config.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:
            if response.status >= 400:
                raise RuntimeError(f"Slack notification failed with status {response.status}")
