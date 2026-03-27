"""Tests for US-032: Trailing stop auto-activation after partial take-profit."""

from __future__ import annotations

import unittest
from datetime import datetime

from crypto_trader.config import RiskConfig
from crypto_trader.models import Position
from crypto_trader.risk.manager import RiskManager


def _pos(entry_price: float = 100.0) -> Position:
    return Position(
        symbol="KRW-BTC",
        quantity=1.0,
        entry_price=entry_price,
        entry_time=datetime(2025, 1, 1),
    )


class TestTrailingAfterPartialTP(unittest.TestCase):
    def test_trailing_activates_after_partial_tp(self) -> None:
        """After partial TP, trailing stop at 2% auto-activates."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.20, partial_tp_pct=0.0),
            trailing_stop_pct=0.0,  # no trailing by default
        )
        pos = _pos(entry_price=100.0)
        pos.partial_tp_taken = True

        # Set high watermark at 115
        rm.exit_reason(pos, 115.0)
        self.assertEqual(pos.high_watermark, 115.0)

        # 2% pullback from 115 = 112.7 → trailing stop
        reason = rm.exit_reason(pos, 112.0)
        self.assertEqual(reason, "trailing_stop")

    def test_no_trailing_without_partial_tp(self) -> None:
        """Without partial TP taken, no auto-trailing."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.20, partial_tp_pct=0.0),
            trailing_stop_pct=0.0,
        )
        pos = _pos(entry_price=100.0)
        pos.partial_tp_taken = False

        rm.exit_reason(pos, 115.0)  # watermark = 115
        reason = rm.exit_reason(pos, 112.0)  # 2.6% pullback
        # profit_lock_trailing fires: 15% gain, 1.5% trail from 115 = 113.275, 112 < 113.275
        self.assertEqual(reason, "profit_lock_trailing")

    def test_explicit_trailing_overrides_auto(self) -> None:
        """If trailing_stop_pct already set, it's used instead of auto 2%."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.20, partial_tp_pct=0.0),
            trailing_stop_pct=0.05,  # 5% trailing
        )
        pos = _pos(entry_price=100.0)
        pos.partial_tp_taken = True

        rm.exit_reason(pos, 115.0)  # watermark = 115
        # 5% trailing from 115 = 109.25 → at 112 no trigger (only 2.6% drop)
        reason = rm.exit_reason(pos, 112.0)
        self.assertIsNone(reason)
        # At 109 → 5.2% drop → triggers
        reason = rm.exit_reason(pos, 109.0)
        self.assertEqual(reason, "trailing_stop")

    def test_trailing_needs_watermark_above_entry(self) -> None:
        """Trailing stop only triggers when watermark is above entry price."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.20, partial_tp_pct=0.0),
            trailing_stop_pct=0.0,
        )
        pos = _pos(entry_price=100.0)
        pos.partial_tp_taken = True

        # Price never goes above entry
        reason = rm.exit_reason(pos, 99.0)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
