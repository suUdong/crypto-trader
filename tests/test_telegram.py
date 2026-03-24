from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from crypto_trader.config import TelegramConfig
from crypto_trader.notifications.telegram import Notifier, NullNotifier, TelegramNotifier


class TestNotifierBase(unittest.TestCase):
    def test_notifier_base_raises(self) -> None:
        with self.assertRaises(NotImplementedError):
            Notifier().send_message("test")


class TestNullNotifier(unittest.TestCase):
    def test_null_notifier_returns_none(self) -> None:
        result = NullNotifier().send_message("test")
        self.assertIsNone(result)


class TestTelegramNotifier(unittest.TestCase):
    def test_telegram_skips_when_disabled(self) -> None:
        config = TelegramConfig(bot_token="", chat_id="")
        notifier = TelegramNotifier(config)
        with patch("urllib.request.urlopen") as mock_urlopen:
            notifier.send_message("hello")
            mock_urlopen.assert_not_called()

    def test_telegram_sends_correct_payload(self) -> None:
        config = TelegramConfig(bot_token="mytoken", chat_id="mychat")
        notifier = TelegramNotifier(config)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            notifier.send_message("hello world")

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertIn("mytoken", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "mychat")
        self.assertEqual(payload["text"], "hello world")

    def test_telegram_raises_on_http_error(self) -> None:
        config = TelegramConfig(bot_token="mytoken", chat_id="mychat")
        notifier = TelegramNotifier(config)

        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with self.assertRaises(RuntimeError):
                notifier.send_message("fail")


if __name__ == "__main__":
    unittest.main()
