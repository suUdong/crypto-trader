"""Tests for US-030: Time-decay exit for stale underwater positions."""

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
        entry_index=0,
    )


class TestTimeDecayExit(unittest.TestCase):
    def test_underwater_position_exits_at_75pct_bars(self) -> None:
        """Position at 80% of max bars with negative PnL triggers time_decay_exit."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50, partial_tp_pct=0.0),
            max_holding_bars=48,
        )
        pos = _pos(entry_price=100.0)
        # At 80% of 48 bars = 38.4, holding 39 bars, price=99 (underwater)
        reason = rm.exit_reason(pos, 99.0, holding_bars=39)
        self.assertEqual(reason, "time_decay_exit")

    def test_profitable_position_not_forced_out(self) -> None:
        """Position at 80% bars with positive PnL does NOT trigger time_decay."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50, partial_tp_pct=0.0),
            max_holding_bars=48,
        )
        pos = _pos(entry_price=100.0)
        # Profitable at 101, holding 39 bars
        reason = rm.exit_reason(pos, 101.0, holding_bars=39)
        self.assertIsNone(reason)

    def test_early_underwater_not_forced_out(self) -> None:
        """Underwater but only at 50% of max bars → no time_decay exit."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50, partial_tp_pct=0.0),
            max_holding_bars=48,
        )
        pos = _pos(entry_price=100.0)
        # Only 24 bars (50%) with negative PnL
        reason = rm.exit_reason(pos, 99.0, holding_bars=24)
        self.assertIsNone(reason)

    def test_time_decay_at_exact_75pct(self) -> None:
        """Position at exactly 75% of max bars + underwater triggers."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50, partial_tp_pct=0.0),
            max_holding_bars=48,
        )
        pos = _pos(entry_price=100.0)
        # 36 bars = exactly 75%
        reason = rm.exit_reason(pos, 99.0, holding_bars=36)
        self.assertEqual(reason, "time_decay_exit")

    def test_time_decay_with_zero_holding_bars(self) -> None:
        """holding_bars=0 → no time_decay check."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50, partial_tp_pct=0.0),
            max_holding_bars=48,
        )
        pos = _pos(entry_price=100.0)
        reason = rm.exit_reason(pos, 99.0, holding_bars=0)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
