"""Tests for US-035: Post-loss cooldown to prevent revenge trading."""

from __future__ import annotations

import unittest

from crypto_trader.config import RiskConfig
from crypto_trader.risk.manager import RiskManager


class TestCooldown(unittest.TestCase):
    def test_cooldown_blocks_after_loss(self) -> None:
        """Entry blocked during cooldown period after losing trade."""
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        rm.record_trade(-0.02)  # loss
        self.assertTrue(rm.in_cooldown)
        rm.tick_cooldown()  # bar 1
        self.assertTrue(rm.in_cooldown)
        rm.tick_cooldown()  # bar 2
        self.assertTrue(rm.in_cooldown)

    def test_cooldown_expires(self) -> None:
        """Entry allowed after cooldown period expires."""
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        rm.record_trade(-0.02)  # loss
        for _ in range(3):
            rm.tick_cooldown()
        self.assertFalse(rm.in_cooldown)

    def test_win_no_cooldown(self) -> None:
        """Winning trade does not trigger cooldown."""
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        rm.record_trade(0.05)  # win
        self.assertFalse(rm.in_cooldown)

    def test_no_trades_no_cooldown(self) -> None:
        """No trades means no cooldown."""
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        self.assertFalse(rm.in_cooldown)

    def test_cooldown_resets_on_new_loss(self) -> None:
        """New loss resets cooldown counter."""
        rm = RiskManager(RiskConfig(cooldown_bars=3))
        rm.record_trade(-0.02)
        rm.tick_cooldown()
        rm.tick_cooldown()
        # About to expire, but new loss resets
        rm.record_trade(-0.01)
        self.assertTrue(rm.in_cooldown)
        rm.tick_cooldown()
        self.assertTrue(rm.in_cooldown)

    def test_cooldown_zero_disables(self) -> None:
        """cooldown_bars=0 means no cooldown."""
        rm = RiskManager(RiskConfig(cooldown_bars=0))
        rm.record_trade(-0.02)
        self.assertFalse(rm.in_cooldown)


if __name__ == "__main__":
    unittest.main()
