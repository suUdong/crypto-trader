from __future__ import annotations

import unittest
from typing import Any

from crypto_trader.config import RiskConfig
from crypto_trader.risk.manager import RiskManager


class DrawdownSizingTests(unittest.TestCase):
    def _make_manager(self, **kwargs: Any) -> RiskManager:
        defaults: dict[str, Any] = dict(
            risk_per_trade_pct=0.01,
            stop_loss_pct=0.02,
            max_daily_loss_pct=0.05,
            max_position_pct=1.0,
        )
        defaults.update(kwargs)
        return RiskManager(RiskConfig(**defaults))

    def test_no_drawdown_scale_is_one(self) -> None:
        manager = self._make_manager()
        # First call sets peak; no drawdown since equity == peak
        qty1 = manager.size_position(equity=100_000.0, price=1000.0)
        qty2 = manager.size_position(equity=100_000.0, price=1000.0)
        # Both calls at same equity (no drawdown) should produce identical quantity
        self.assertAlmostEqual(qty1, qty2)
        self.assertGreater(qty2, 0.0)

    def test_drawdown_reduces_position_size(self) -> None:
        manager = self._make_manager()
        # Establish peak at 100_000
        normal_qty = manager.size_position(equity=100_000.0, price=1000.0)
        # Now equity drops — drawdown active
        reduced_qty = manager.size_position(equity=97_500.0, price=1000.0)
        self.assertLess(reduced_qty, normal_qty)

    def test_deep_drawdown_clamped_to_floor(self) -> None:
        manager = self._make_manager(max_daily_loss_pct=0.05, drawdown_reduction_pct=0.5)
        # Establish peak
        manager.size_position(equity=100_000.0, price=1000.0)
        # Drop equity far below peak (much more than max_daily_loss_pct)
        floor_qty = manager.size_position(equity=50_000.0, price=1000.0)
        # Compute what 10% floor of this equity would be
        manager2 = self._make_manager(max_daily_loss_pct=0.05, drawdown_reduction_pct=0.5)
        # Fresh manager at same (lower) equity with no drawdown
        no_drawdown_qty = manager2.size_position(equity=50_000.0, price=1000.0)
        # floor_qty should be 10% of no_drawdown_qty (scale clamped at 0.1)
        self.assertAlmostEqual(floor_qty, no_drawdown_qty * 0.1, places=6)

    def test_default_drawdown_reduction_pct(self) -> None:
        config = RiskConfig()
        self.assertEqual(config.drawdown_reduction_pct, 0.5)

    def test_half_daily_loss_drawdown_halves_reduction(self) -> None:
        # Effective daily loss is hard-capped at 5%, so 2.5% drawdown is the halfway point.
        manager = self._make_manager(max_daily_loss_pct=0.10)
        # Establish peak
        manager.size_position(equity=100_000.0, price=1000.0)
        # 2.5% drawdown = half of effective 5% limit -> dd_ratio=0.5
        scaled_qty = manager.size_position(equity=97_500.0, price=1000.0)
        # scale = (1 - 0.5)^2 = 0.25; compare against fresh manager at 95k
        manager2 = self._make_manager(max_daily_loss_pct=0.10)
        base_at_97_5k = manager2.size_position(equity=97_500.0, price=1000.0)
        expected = base_at_97_5k * 0.25
        self.assertAlmostEqual(scaled_qty, expected, places=6)

    def test_drawdown_reduction_pct_controls_scaling_curve(self) -> None:
        soft = self._make_manager(max_daily_loss_pct=0.10, drawdown_reduction_pct=0.0)
        hard = self._make_manager(max_daily_loss_pct=0.10, drawdown_reduction_pct=1.0)
        soft.size_position(equity=100_000.0, price=1000.0)
        hard.size_position(equity=100_000.0, price=1000.0)
        soft_qty = soft.size_position(equity=97_500.0, price=1000.0)
        hard_qty = hard.size_position(equity=97_500.0, price=1000.0)
        self.assertGreater(soft_qty, hard_qty)
