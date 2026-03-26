"""Tests for regime-aware strategy weight auto-adjustment."""
from __future__ import annotations

import unittest

from crypto_trader.macro.adapter import MacroRegimeAdapter


class RegimeWeightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MacroRegimeAdapter()

    def test_sideways_boosts_mean_reversion(self) -> None:
        w = self.adapter.strategy_weight("mean_reversion", "sideways")
        self.assertGreater(w, 1.0)

    def test_sideways_reduces_momentum(self) -> None:
        w = self.adapter.strategy_weight("momentum", "sideways")
        self.assertLess(w, 1.0)

    def test_bull_boosts_momentum(self) -> None:
        w = self.adapter.strategy_weight("momentum", "bull")
        self.assertGreater(w, 1.0)

    def test_bull_reduces_mean_reversion(self) -> None:
        w = self.adapter.strategy_weight("mean_reversion", "bull")
        self.assertLess(w, 1.0)

    def test_bear_reduces_momentum(self) -> None:
        w = self.adapter.strategy_weight("momentum", "bear")
        self.assertLess(w, 1.0)

    def test_unknown_strategy_returns_default(self) -> None:
        w = self.adapter.strategy_weight("unknown_strategy", "sideways")
        self.assertEqual(w, 1.0)

    def test_unknown_regime_returns_default(self) -> None:
        w = self.adapter.strategy_weight("momentum", "unknown_regime")
        self.assertEqual(w, 1.0)

    def test_all_regimes_have_all_strategies(self) -> None:
        strategies = [
            "momentum", "mean_reversion", "obi", "vpin",
            "composite", "kimchi_premium", "volatility_breakout", "consensus",
        ]
        for regime in ["bull", "sideways", "bear"]:
            for strategy in strategies:
                w = self.adapter.strategy_weight(strategy, regime)
                self.assertGreater(w, 0.0, f"{strategy}/{regime} should be > 0")
                self.assertLessEqual(w, 2.0, f"{strategy}/{regime} should be <= 2.0")

    def test_bear_reduces_volatility_breakout(self) -> None:
        w = self.adapter.strategy_weight("volatility_breakout", "bear")
        self.assertLess(w, 0.5)

    def test_bull_boosts_volatility_breakout(self) -> None:
        w = self.adapter.strategy_weight("volatility_breakout", "bull")
        self.assertGreater(w, 1.0)

    def test_bear_reduces_consensus(self) -> None:
        w = self.adapter.strategy_weight("consensus", "bear")
        self.assertLess(w, 1.0)

    def test_bull_boosts_consensus(self) -> None:
        w = self.adapter.strategy_weight("consensus", "bull")
        self.assertGreater(w, 1.0)
