from __future__ import annotations

import unittest
from datetime import datetime

from crypto_trader.config import RiskConfig
from crypto_trader.models import Position
from crypto_trader.risk.manager import RiskManager


class RiskManagerTests(unittest.TestCase):
    def test_position_sizing_caps_by_available_cash(self) -> None:
        manager = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.02))
        quantity = manager.size_position(equity=1_000.0, price=100.0)
        self.assertLessEqual(quantity, 10.0)
        self.assertGreater(quantity, 0.0)

    def test_daily_loss_limit_blocks_new_positions(self) -> None:
        manager = RiskManager(RiskConfig(max_daily_loss_pct=0.05))
        self.assertFalse(
            manager.can_open(
                active_positions=0,
                realized_pnl=-60.0,
                starting_equity=1_000.0,
            )
        )

    def test_drawdown_reduces_allowed_concurrency(self) -> None:
        manager = RiskManager(
            RiskConfig(
                max_daily_loss_pct=0.10,
                max_concurrent_positions=4,
            )
        )
        self.assertEqual(
            manager.allowed_concurrent_positions(
                realized_pnl=-50.0,
                starting_equity=1_000.0,
            ),
            2,
        )
        self.assertFalse(
            manager.can_open(
                active_positions=2,
                realized_pnl=-50.0,
                starting_equity=1_000.0,
            )
        )

    def test_exit_reason_prefers_risk_limits(self) -> None:
        manager = RiskManager(
            RiskConfig(stop_loss_pct=0.02, take_profit_pct=0.04, partial_tp_pct=0.0)
        )
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1, 0, 0, 0),
        )
        self.assertEqual(manager.exit_reason(position, 97.0), "stop_loss")
        self.assertEqual(manager.exit_reason(position, 104.0), "take_profit")
