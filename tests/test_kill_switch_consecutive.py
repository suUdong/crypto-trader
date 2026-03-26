"""Tests for consecutive losses detection in KillSwitch (US-022)."""
from __future__ import annotations

import unittest

from crypto_trader.risk.kill_switch import KillSwitch, KillSwitchConfig

EQUITY = 1_000_000
BASE_KWARGS = dict(current_equity=EQUITY, starting_equity=EQUITY, realized_pnl=0)


def _loss(ks: KillSwitch) -> None:
    ks.check(**BASE_KWARGS, trade_won=False)


def _win(ks: KillSwitch) -> None:
    ks.check(**BASE_KWARGS, trade_won=True)


class ConsecutiveLossesTests(unittest.TestCase):
    def _ks(self, max_consecutive_losses: int = 5) -> KillSwitch:
        return KillSwitch(KillSwitchConfig(max_consecutive_losses=max_consecutive_losses))

    def test_four_consecutive_losses_does_not_trigger(self) -> None:
        ks = self._ks()
        for _ in range(4):
            _loss(ks)
        self.assertFalse(ks.is_triggered)
        self.assertEqual(ks.state.consecutive_losses, 4)

    def test_five_consecutive_losses_triggers(self) -> None:
        ks = self._ks()
        for _ in range(5):
            _loss(ks)
        self.assertTrue(ks.is_triggered)
        self.assertIn("max_consecutive_losses_exceeded", ks.state.trigger_reason)

    def test_win_resets_counter(self) -> None:
        ks = self._ks()
        for _ in range(4):
            _loss(ks)
        _win(ks)
        self.assertFalse(ks.is_triggered)
        self.assertEqual(ks.state.consecutive_losses, 0)

    def test_loss_win_then_five_losses_triggers(self) -> None:
        """loss → win → loss×5 should trigger (counter resets on win)."""
        ks = self._ks()
        _loss(ks)
        _win(ks)
        self.assertEqual(ks.state.consecutive_losses, 0)
        for _ in range(5):
            _loss(ks)
        self.assertTrue(ks.is_triggered)


if __name__ == "__main__":
    unittest.main()
