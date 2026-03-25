from __future__ import annotations

import unittest

from crypto_trader.config import RiskConfig
from crypto_trader.risk.manager import RiskManager


def _make_manager() -> RiskManager:
    return RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.02))


class KellyFractionTests(unittest.TestCase):
    def test_kelly_fraction_insufficient_history(self) -> None:
        manager = _make_manager()
        for i in range(9):
            manager.record_trade(0.05 if i % 2 == 0 else -0.03)
        self.assertIsNone(manager.kelly_fraction())

    def test_kelly_fraction_all_wins(self) -> None:
        manager = _make_manager()
        for _ in range(10):
            manager.record_trade(0.05)
        self.assertIsNone(manager.kelly_fraction())

    def test_kelly_fraction_all_losses(self) -> None:
        manager = _make_manager()
        for _ in range(10):
            manager.record_trade(-0.03)
        self.assertIsNone(manager.kelly_fraction())

    def test_kelly_fraction_mixed_positive(self) -> None:
        # 60% win rate, avg_win=0.10, avg_loss=0.05 => payoff=2.0
        # Kelly = 0.6 - 0.4/2.0 = 0.6 - 0.2 = 0.4, half-kelly = 0.2
        manager = _make_manager()
        for _ in range(6):
            manager.record_trade(0.10)
        for _ in range(4):
            manager.record_trade(-0.05)
        result = manager.kelly_fraction()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result, 0.2, places=5)

    def test_kelly_fraction_capped_at_25_pct(self) -> None:
        # 90% win rate with 5:1 payoff => Kelly = 0.9 - 0.1/5 = 0.88, half=0.44 → capped at 0.25
        manager = _make_manager()
        for _ in range(9):
            manager.record_trade(0.50)
        for _ in range(1):
            manager.record_trade(-0.10)
        result = manager.kelly_fraction()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result, 0.25)

    def test_kelly_fraction_negative_returns_zero(self) -> None:
        # 30% win rate, avg_win=0.05, avg_loss=0.10 => payoff=0.5
        # Kelly = 0.3 - 0.7/0.5 = 0.3 - 1.4 = -1.1, half-kelly clamped to 0.0
        manager = _make_manager()
        for _ in range(3):
            manager.record_trade(0.05)
        for _ in range(7):
            manager.record_trade(-0.10)
        result = manager.kelly_fraction()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result, 0.0)

    def test_record_trade_accumulates(self) -> None:
        manager = _make_manager()
        self.assertEqual(len(manager._trade_history), 0)
        manager.record_trade(0.05)
        manager.record_trade(-0.03)
        manager.record_trade(0.02)
        self.assertEqual(len(manager._trade_history), 3)
        self.assertAlmostEqual(manager._trade_history[0], 0.05)
        self.assertAlmostEqual(manager._trade_history[1], -0.03)
        self.assertAlmostEqual(manager._trade_history[2], 0.02)


class KellySizePositionTests(unittest.TestCase):
    def test_size_position_falls_back_to_fixed(self) -> None:
        # With no history, uses fixed risk sizing
        manager = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.02))
        quantity = manager.size_position(equity=10_000.0, price=100.0)
        # risk_budget = 10000 * 0.01 = 100, stop_distance = 100 * 0.02 = 2, qty = 100/2 = 50
        self.assertAlmostEqual(quantity, 50.0, places=5)

    def test_size_position_uses_kelly_when_available(self) -> None:
        # 60% win rate, payoff=2.0 => half-kelly=0.2
        # Kelly sizing: qty = (10000 * 0.2) / 100 = 20
        # Fixed sizing: qty = (10000*0.01) / (100*0.02) = 50
        manager = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.02))
        for _ in range(6):
            manager.record_trade(0.10)
        for _ in range(4):
            manager.record_trade(-0.05)
        quantity = manager.size_position(equity=10_000.0, price=100.0)
        self.assertAlmostEqual(quantity, 20.0, places=5)

    def test_size_position_zero_kelly_falls_back_to_fixed(self) -> None:
        # Negative Kelly (bad strategy) is clamped to 0 → falls back to fixed
        manager = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.02))
        for _ in range(3):
            manager.record_trade(0.05)
        for _ in range(7):
            manager.record_trade(-0.10)
        # kelly_fraction returns 0.0 (clamped), so size_position uses fixed
        quantity = manager.size_position(equity=10_000.0, price=100.0)
        self.assertAlmostEqual(quantity, 50.0, places=5)

    def test_size_position_respects_macro_multiplier(self) -> None:
        # With Kelly available, macro_multiplier scales the result
        manager = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.02))
        for _ in range(6):
            manager.record_trade(0.10)
        for _ in range(4):
            manager.record_trade(-0.05)
        quantity_full = manager.size_position(equity=10_000.0, price=100.0, macro_multiplier=1.0)
        quantity_half = manager.size_position(equity=10_000.0, price=100.0, macro_multiplier=0.5)
        self.assertAlmostEqual(quantity_half, quantity_full * 0.5, places=5)
