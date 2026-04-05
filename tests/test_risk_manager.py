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
                realized_pnl=-25.0,
                starting_equity=1_000.0,
            ),
            2,
        )
        self.assertFalse(
            manager.can_open(
                active_positions=2,
                realized_pnl=-25.0,
                starting_equity=1_000.0,
            )
        )

    def test_unrealized_drawdown_reduces_allowed_concurrency(self) -> None:
        manager = RiskManager(
            RiskConfig(
                max_daily_loss_pct=0.10,
                max_concurrent_positions=4,
            )
        )
        self.assertEqual(
            manager.allowed_concurrent_positions(
                realized_pnl=0.0,
                starting_equity=1_000.0,
                current_equity=975.0,
            ),
            2,
        )
        self.assertFalse(
            manager.can_open(
                active_positions=2,
                realized_pnl=0.0,
                starting_equity=1_000.0,
                current_equity=975.0,
            )
        )

    def test_consecutive_loss_streak_blocks_new_positions(self) -> None:
        manager = RiskManager(RiskConfig(max_daily_loss_pct=0.05))
        for _ in range(3):
            manager.record_trade(-0.02)
        self.assertFalse(
            manager.can_open(
                active_positions=0,
                realized_pnl=0.0,
                starting_equity=1_000.0,
                current_equity=1_000.0,
            )
        )

    def test_winning_trade_resets_consecutive_loss_stop(self) -> None:
        manager = RiskManager(RiskConfig(max_daily_loss_pct=0.05))
        for _ in range(3):
            manager.record_trade(-0.02)
        manager.record_trade(0.01)
        self.assertTrue(
            manager.can_open(
                active_positions=0,
                realized_pnl=0.0,
                starting_equity=1_000.0,
                current_equity=1_000.0,
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

    def test_vol_regime_hv_size_mult_reduces_position(self) -> None:
        cfg = RiskConfig(
            risk_per_trade_pct=0.001,
            stop_loss_pct=0.02,
            max_position_pct=1.0,
            vol_regime_lookback=10,
            vol_regime_threshold=70,
            hv_size_mult=0.5,
        )
        manager = RiskManager(cfg)
        # Directly test: when is_high_vol=False, full size; when True, half size
        normal_qty = manager.size_position(equity=10_000.0, price=100.0)
        self.assertGreater(normal_qty, 0.0)
        self.assertFalse(manager.is_high_vol)

        # Force high vol state
        manager._is_high_vol = True
        hv_qty = manager.size_position(equity=10_000.0, price=100.0)
        self.assertGreater(hv_qty, 0.0)
        self.assertAlmostEqual(hv_qty / normal_qty, 0.5, places=2)

    def test_vol_regime_disabled_by_default(self) -> None:
        """hv_size_mult=1.0 (default) should not change sizing."""
        cfg = RiskConfig(
            risk_per_trade_pct=0.001, stop_loss_pct=0.02, max_position_pct=1.0,
        )
        manager = RiskManager(cfg)
        normal_qty = manager.size_position(equity=10_000.0, price=100.0)
        manager._is_high_vol = True
        hv_qty = manager.size_position(equity=10_000.0, price=100.0)
        self.assertAlmostEqual(hv_qty, normal_qty, places=6)
