"""Tests for US-024: Partial take-profit (scale-out) in RiskManager."""

from __future__ import annotations

import unittest
from datetime import datetime

from crypto_trader.config import RiskConfig
from crypto_trader.models import Position
from crypto_trader.risk.manager import RiskManager


def _pos(entry_price: float = 100.0, quantity: float = 1.0) -> Position:
    return Position(
        symbol="KRW-BTC",
        quantity=quantity,
        entry_price=entry_price,
        entry_time=datetime(2025, 1, 1),
    )


class TestPartialTakeProfit(unittest.TestCase):
    def test_partial_tp_triggers_at_half_target(self) -> None:
        """Partial TP triggers at 50% of TP target (3% if TP is 6%)."""
        rm = RiskManager(
            RiskConfig(
                stop_loss_pct=0.03,
                take_profit_pct=0.06,
                partial_tp_pct=0.5,
            )
        )
        pos = _pos(entry_price=100.0)
        # At 103 (3% gain = half of 6% TP)
        reason = rm.exit_reason(pos, 103.0)
        self.assertEqual(reason, "partial_take_profit")

    def test_partial_tp_not_retriggered(self) -> None:
        """After partial TP taken, it should not re-trigger."""
        rm = RiskManager(
            RiskConfig(
                stop_loss_pct=0.03,
                take_profit_pct=0.06,
                partial_tp_pct=0.5,
            )
        )
        pos = _pos(entry_price=100.0)
        pos.partial_tp_taken = True
        # At 103 — partial already taken, should not trigger
        reason = rm.exit_reason(pos, 103.0)
        self.assertIsNone(reason)

    def test_full_tp_still_triggers(self) -> None:
        """Full TP triggers at 106 even after partial TP taken."""
        rm = RiskManager(
            RiskConfig(
                stop_loss_pct=0.03,
                take_profit_pct=0.06,
                partial_tp_pct=0.5,
            )
        )
        pos = _pos(entry_price=100.0)
        pos.partial_tp_taken = True
        reason = rm.exit_reason(pos, 106.0)
        self.assertEqual(reason, "take_profit")

    def test_stop_loss_still_works_with_partial_tp(self) -> None:
        """Stop loss triggers normally regardless of partial TP."""
        rm = RiskManager(
            RiskConfig(
                stop_loss_pct=0.03,
                take_profit_pct=0.06,
                partial_tp_pct=0.5,
            )
        )
        pos = _pos(entry_price=100.0)
        reason = rm.exit_reason(pos, 96.0)
        self.assertEqual(reason, "stop_loss")

    def test_partial_tp_disabled_when_zero(self) -> None:
        """partial_tp_pct=0.0 disables partial take-profit."""
        rm = RiskManager(
            RiskConfig(
                stop_loss_pct=0.03,
                take_profit_pct=0.06,
                partial_tp_pct=0.0,
            )
        )
        pos = _pos(entry_price=100.0)
        # At 103 — no partial TP since disabled
        reason = rm.exit_reason(pos, 103.0)
        self.assertIsNone(reason)
        # Full TP still works at 106
        reason = rm.exit_reason(pos, 106.0)
        self.assertEqual(reason, "take_profit")


if __name__ == "__main__":
    unittest.main()
