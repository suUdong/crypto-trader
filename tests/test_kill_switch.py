"""Tests for the kill switch module."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.risk.kill_switch import KillSwitch, KillSwitchConfig


class KillSwitchTests(unittest.TestCase):
    def test_no_trigger_within_limits(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_portfolio_drawdown_pct=0.05))
        state = ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0)
        self.assertFalse(state.triggered)

    def test_portfolio_drawdown_triggers(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_portfolio_drawdown_pct=0.05))
        # Build up peak
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0)
        # Drop 6% from peak
        state = ks.check(current_equity=940_000, starting_equity=1_000_000, realized_pnl=-60_000)
        self.assertTrue(state.triggered)
        self.assertIn("drawdown", state.trigger_reason)

    def test_daily_loss_triggers(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_daily_loss_pct=0.03))
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0)
        state = ks.check(current_equity=960_000, starting_equity=1_000_000, realized_pnl=-40_000)
        self.assertTrue(state.triggered)
        self.assertIn("Daily loss", state.trigger_reason)

    def test_consecutive_losses_triggers(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_consecutive_losses=3))
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0, trade_won=False)
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0, trade_won=False)
        state = ks.check(
            current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0, trade_won=False
        )
        self.assertTrue(state.triggered)
        self.assertIn("max_consecutive_losses_exceeded", state.trigger_reason)

    def test_consecutive_losses_reset_on_win(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_consecutive_losses=3))
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0, trade_won=False)
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0, trade_won=False)
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0, trade_won=True)
        self.assertFalse(ks.is_triggered)
        self.assertEqual(ks.state.consecutive_losses, 0)

    def test_reset_clears_trigger(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_portfolio_drawdown_pct=0.01))
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0)
        ks.check(current_equity=980_000, starting_equity=1_000_000, realized_pnl=-20_000)
        self.assertTrue(ks.is_triggered)
        ks.reset()
        self.assertFalse(ks.is_triggered)

    def test_save_and_load(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_consecutive_losses=2))
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0, trade_won=False)
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0, trade_won=False)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kill-switch.json"
            ks.save(path)
            data = json.loads(path.read_text())
            self.assertTrue(data["triggered"])

            ks2 = KillSwitch()
            ks2.load(path)
            self.assertTrue(ks2.is_triggered)

    def test_stays_triggered_once_triggered(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_portfolio_drawdown_pct=0.01))
        ks.check(current_equity=1_000_000, starting_equity=1_000_000, realized_pnl=0)
        ks.check(current_equity=980_000, starting_equity=1_000_000, realized_pnl=-20_000)
        self.assertTrue(ks.is_triggered)
        # Even with recovery, stays triggered
        state = ks.check(current_equity=1_100_000, starting_equity=1_000_000, realized_pnl=100_000)
        self.assertTrue(state.triggered)
