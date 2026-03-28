"""Tests for wallet-level circuit breaker (daily loss limit force-exit)."""

from __future__ import annotations

import unittest

from crypto_trader.config import RiskConfig
from crypto_trader.risk.manager import RiskManager


class CircuitBreakerTests(unittest.TestCase):
    def _make_manager(self, max_daily_loss_pct: float = 0.05) -> RiskManager:
        config = RiskConfig(max_daily_loss_pct=max_daily_loss_pct)
        return RiskManager(config)

    def test_no_force_exit_when_within_limit(self) -> None:
        rm = self._make_manager(0.05)
        # Lost 4% of 1M = 40K, limit is 5% = 50K
        self.assertFalse(rm.should_force_exit(-40_000, 1_000_000))

    def test_force_exit_when_at_limit(self) -> None:
        rm = self._make_manager(0.05)
        # Lost exactly 5% = 50K
        self.assertTrue(rm.should_force_exit(-50_000, 1_000_000))

    def test_force_exit_when_beyond_limit(self) -> None:
        rm = self._make_manager(0.05)
        # Lost 6% = 60K
        self.assertTrue(rm.should_force_exit(-60_000, 1_000_000))

    def test_no_force_exit_with_zero_equity(self) -> None:
        rm = self._make_manager(0.05)
        self.assertFalse(rm.should_force_exit(-100, 0))

    def test_no_force_exit_when_profitable(self) -> None:
        rm = self._make_manager(0.05)
        self.assertFalse(rm.should_force_exit(10_000, 1_000_000))

    def test_force_exit_on_mark_to_market_drawdown(self) -> None:
        rm = self._make_manager(0.05)
        self.assertTrue(
            rm.should_force_exit(
                realized_pnl=-10_000,
                starting_equity=1_000_000,
                current_equity=940_000,
            )
        )

    def test_hard_daily_loss_cap_applies_when_config_is_looser(self) -> None:
        rm = self._make_manager(0.20)
        self.assertTrue(
            rm.should_force_exit(
                realized_pnl=-60_000,
                starting_equity=1_000_000,
            )
        )
