"""Tests for TradeAlertManager."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from crypto_trader.notifications.alert_manager import TradeAlertManager
from crypto_trader.notifications.telegram import Notifier


class _RecordingNotifier(Notifier):
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, message: str) -> None:
        self.messages.append(message)


class TestTradeAlertManager(unittest.TestCase):
    def setUp(self) -> None:
        self.notifier = _RecordingNotifier()
        self.manager = TradeAlertManager([self.notifier])

    def test_alert_trade_sends_message(self) -> None:
        self.manager.alert_trade(
            wallet_name="momentum_wallet",
            symbol="KRW-BTC",
            side="buy",
            quantity=0.001,
            fill_price=90_000_000.0,
            fee_paid=45_000.0,
            reason="breakout",
        )
        self.assertEqual(len(self.notifier.messages), 1)
        msg = self.notifier.messages[0]
        self.assertIn("TRADE", msg)
        self.assertIn("momentum_wallet", msg)
        self.assertIn("KRW-BTC", msg)
        self.assertIn("BUY", msg)
        self.assertIn("breakout", msg)

    def test_alert_rejection_sends_message(self) -> None:
        self.manager.alert_rejection(
            wallet_name="obi_wallet",
            symbol="KRW-ETH",
            side="buy",
            reason="cooldown_active",
        )
        self.assertEqual(len(self.notifier.messages), 1)
        msg = self.notifier.messages[0]
        self.assertIn("REJECTED", msg)
        self.assertIn("obi_wallet", msg)
        self.assertIn("cooldown_active", msg)

    def test_alert_error_sends_message(self) -> None:
        self.manager.alert_error(
            wallet_name="test_wallet",
            symbol="KRW-BTC",
            error_message="API timeout",
        )
        self.assertEqual(len(self.notifier.messages), 1)
        msg = self.notifier.messages[0]
        self.assertIn("ERROR", msg)
        self.assertIn("API timeout", msg)

    def test_alert_kill_switch_sends_message(self) -> None:
        self.manager.alert_kill_switch(
            reason="max_portfolio_drawdown",
            portfolio_dd=0.16,
            daily_loss=0.03,
            consecutive_losses=4,
        )
        self.assertEqual(len(self.notifier.messages), 1)
        msg = self.notifier.messages[0]
        self.assertIn("KILL SWITCH", msg)
        self.assertIn("max_portfolio_drawdown", msg)

    def test_multiple_notifiers_all_receive(self) -> None:
        notifier2 = _RecordingNotifier()
        manager = TradeAlertManager([self.notifier, notifier2])
        manager.alert_trade(
            wallet_name="w",
            symbol="KRW-BTC",
            side="sell",
            quantity=1.0,
            fill_price=100.0,
            fee_paid=0.0,
            reason="tp",
        )
        self.assertEqual(len(self.notifier.messages), 1)
        self.assertEqual(len(notifier2.messages), 1)

    def test_failing_notifier_does_not_block_others(self) -> None:
        failing = MagicMock(spec=Notifier)
        failing.send_message.side_effect = RuntimeError("network error")
        notifier2 = _RecordingNotifier()
        manager = TradeAlertManager([failing, notifier2])
        manager.alert_trade(
            wallet_name="w",
            symbol="KRW-BTC",
            side="buy",
            quantity=1.0,
            fill_price=100.0,
            fee_paid=0.0,
            reason="entry",
        )
        # Second notifier should still receive
        self.assertEqual(len(notifier2.messages), 1)

    def test_empty_notifiers_no_error(self) -> None:
        manager = TradeAlertManager([])
        # Should not raise
        manager.alert_trade(
            wallet_name="w",
            symbol="KRW-BTC",
            side="buy",
            quantity=1.0,
            fill_price=100.0,
            fee_paid=0.0,
            reason="entry",
        )


if __name__ == "__main__":
    unittest.main()
