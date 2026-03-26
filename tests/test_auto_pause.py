"""Tests for wallet auto-pause based on rolling profit factor."""
from __future__ import annotations

import unittest

from crypto_trader.config import RiskConfig
from crypto_trader.risk.manager import RiskManager


class AutoPauseTests(unittest.TestCase):
    def _make_manager(self) -> RiskManager:
        return RiskManager(RiskConfig())

    def test_not_paused_with_insufficient_trades(self) -> None:
        rm = self._make_manager()
        for _ in range(5):
            rm.record_trade(-0.02)
        self.assertFalse(rm.is_auto_paused)

    def test_not_paused_when_profitable(self) -> None:
        rm = self._make_manager()
        for _ in range(10):
            rm.record_trade(0.03)
        self.assertFalse(rm.is_auto_paused)

    def test_paused_when_profit_factor_below_threshold(self) -> None:
        rm = self._make_manager()
        # 3 wins of 1%, 12 losses of 1% -> PF = 3/12 = 0.25
        for _ in range(3):
            rm.record_trade(0.01)
        for _ in range(12):
            rm.record_trade(-0.01)
        self.assertTrue(rm.is_auto_paused)

    def test_resumes_when_profit_factor_recovers(self) -> None:
        rm = self._make_manager()
        # First build a losing history to trigger pause
        for _ in range(3):
            rm.record_trade(0.01)
        for _ in range(12):
            rm.record_trade(-0.01)
        self.assertTrue(rm.is_auto_paused)
        # Now add enough wins to bring PF above 0.8 in last 20
        for _ in range(15):
            rm.record_trade(0.02)
        self.assertFalse(rm.is_auto_paused)

    def test_not_paused_when_all_losses_zero(self) -> None:
        rm = self._make_manager()
        # All break-even (0.0 counts as loss bucket but PF is 0/0)
        for _ in range(10):
            rm.record_trade(0.0)
        self.assertFalse(rm.is_auto_paused)

    def test_hysteresis_prevents_flapping(self) -> None:
        rm = self._make_manager()
        # Build PF just below 0.7 -> paused
        # 4 wins * 0.01 = 0.04, 10 losses * 0.01 = 0.10 -> PF = 0.4
        for _ in range(4):
            rm.record_trade(0.01)
        for _ in range(10):
            rm.record_trade(-0.01)
        self.assertTrue(rm.is_auto_paused)
        # Add wins to bring PF to ~0.75 (between 0.7 and 0.8) -> still paused
        rm.record_trade(0.01)
        rm.record_trade(0.01)
        # Now recent 20: 6 wins, 10 losses -> PF = 6/10 = 0.6 still paused
        self.assertTrue(rm.is_auto_paused)
