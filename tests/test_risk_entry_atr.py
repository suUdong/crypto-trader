"""Tests that ATR stop-loss uses frozen entry_atr, not live _current_atr."""

from __future__ import annotations

import unittest
from datetime import datetime

from crypto_trader.config import RiskConfig
from crypto_trader.models import Position
from crypto_trader.risk.manager import RiskManager


def _make_position(
    entry_price: float = 100.0,
    entry_atr: float = 0.0,
) -> Position:
    return Position(
        symbol="KRW-BTC",
        quantity=1.0,
        entry_price=entry_price,
        entry_time=datetime(2026, 1, 1),
        entry_atr=entry_atr,
    )


class TestAtrStopUsesEntryAtr(unittest.TestCase):
    def test_atr_stop_uses_entry_atr_not_current(self) -> None:
        """entry_atr=5.0 frozen at entry, current_atr shrunk to 1.0.

        With sl_multiplier=2.0, stop distance = 5.0 * 2.0 = 10.0.
        Entry at 100 -> stop at 90.  Price 91 should NOT trigger; 89 should.
        """
        cfg = RiskConfig(
            atr_tp_multiplier=4.0,
            atr_sl_multiplier=2.0,
        )
        rm = RiskManager(cfg)
        # Simulate ATR update with a very small current ATR
        rm._current_atr = 1.0

        pos = _make_position(entry_price=100.0, entry_atr=5.0)

        # Price 91: above the 90 stop -> no exit
        result_safe = rm.exit_reason(pos, price=91.0)
        self.assertIsNone(result_safe)

        # Price 89: below 90 stop -> atr_stop_loss
        pos_fresh = _make_position(entry_price=100.0, entry_atr=5.0)
        result_stop = rm.exit_reason(pos_fresh, price=89.0)
        self.assertEqual(result_stop, "atr_stop_loss")

    def test_atr_stop_falls_back_to_current_atr_when_entry_atr_zero(self) -> None:
        """entry_atr=0.0 (legacy position). Should fall back to _current_atr."""
        cfg = RiskConfig(
            atr_tp_multiplier=4.0,
            atr_sl_multiplier=2.0,
        )
        rm = RiskManager(cfg)
        rm._current_atr = 5.0

        pos = _make_position(entry_price=100.0, entry_atr=0.0)

        # stop distance = 5.0 * 2.0 = 10.0 -> stop at 90
        result_safe = rm.exit_reason(pos, price=91.0)
        self.assertIsNone(result_safe)

        pos_fresh = _make_position(entry_price=100.0, entry_atr=0.0)
        result_stop = rm.exit_reason(pos_fresh, price=89.0)
        self.assertEqual(result_stop, "atr_stop_loss")


if __name__ == "__main__":
    unittest.main()
