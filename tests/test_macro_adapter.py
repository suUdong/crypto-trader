from __future__ import annotations

import unittest

from crypto_trader.macro.adapter import MacroRegimeAdapter
from crypto_trader.macro.client import MacroSnapshot


def _make_snapshot(**overrides: object) -> MacroSnapshot:
    defaults = dict(
        overall_regime="neutral",
        overall_confidence=0.5,
        us_regime="neutral",
        us_confidence=0.5,
        kr_regime="neutral",
        kr_confidence=0.5,
        crypto_regime="neutral",
        crypto_confidence=0.5,
        crypto_signals={},
        btc_dominance=55.0,
        kimchi_premium=2.0,
        fear_greed_index=50,
    )
    defaults.update(overrides)
    return MacroSnapshot(**defaults)  # type: ignore[arg-type]


class TestMacroRegimeAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MacroRegimeAdapter()

    def test_none_snapshot_returns_default(self) -> None:
        adj = self.adapter.compute(None)
        self.assertAlmostEqual(adj.position_size_multiplier, 1.0)
        self.assertAlmostEqual(adj.risk_per_trade_multiplier, 1.0)
        self.assertIn("no macro data", adj.reasons[0])

    def test_expansionary_regime_aggressive(self) -> None:
        snapshot = _make_snapshot(overall_regime="expansionary")
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 1.5)
        self.assertIn("expansionary", adj.reasons[0])

    def test_contractionary_regime_defensive(self) -> None:
        snapshot = _make_snapshot(overall_regime="contractionary")
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 0.5)
        self.assertIn("contractionary", adj.reasons[0])

    def test_expansion_alias_maps_to_expansionary(self) -> None:
        snapshot = _make_snapshot(overall_regime="expansion")
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 1.5)
        self.assertIn("expansionary", adj.reasons[0])

    def test_contraction_alias_maps_to_contractionary(self) -> None:
        snapshot = _make_snapshot(overall_regime="contraction")
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 0.5)
        self.assertIn("contractionary", adj.reasons[0])

    def test_neutral_regime_baseline(self) -> None:
        snapshot = _make_snapshot(overall_regime="neutral")
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 1.0)

    def test_alias_regime_names_are_normalized(self) -> None:
        snapshot = _make_snapshot(overall_regime="expansion")
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 1.5)
        self.assertIn("expansionary", adj.reasons[0])

    def test_extreme_greed_reduces_multiplier(self) -> None:
        snapshot = _make_snapshot(overall_regime="expansionary", fear_greed_index=85)
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 1.4)
        self.assertTrue(any("extreme greed" in r for r in adj.reasons))

    def test_extreme_fear_reduces_multiplier(self) -> None:
        snapshot = _make_snapshot(overall_regime="neutral", fear_greed_index=15)
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 0.9)
        self.assertTrue(any("extreme fear" in r for r in adj.reasons))

    def test_high_kimchi_premium_reduces_multiplier(self) -> None:
        snapshot = _make_snapshot(overall_regime="expansionary", kimchi_premium=7.5)
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 1.35)
        self.assertTrue(any("kimchi premium" in r for r in adj.reasons))

    def test_high_btc_dominance_reduces_multiplier(self) -> None:
        snapshot = _make_snapshot(overall_regime="neutral", btc_dominance=68.0)
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 0.9)
        self.assertTrue(any("BTC dominance" in r for r in adj.reasons))

    def test_combined_adjustments_contractionary_with_signals(self) -> None:
        snapshot = _make_snapshot(
            overall_regime="contractionary",
            fear_greed_index=15,
            kimchi_premium=8.0,
            btc_dominance=70.0,
        )
        adj = self.adapter.compute(snapshot)
        # 0.5 - 0.1 (fear) - 0.15 (kimchi) - 0.1 (btc dom) = 0.15, clamped to 0.25
        self.assertAlmostEqual(adj.position_size_multiplier, 0.25)

    def test_multiplier_clamped_to_max(self) -> None:
        snapshot = _make_snapshot(overall_regime="expansionary")
        adj = self.adapter.compute(snapshot)
        self.assertLessEqual(adj.position_size_multiplier, 2.0)

    def test_multiplier_clamped_to_min(self) -> None:
        snapshot = _make_snapshot(
            overall_regime="contractionary",
            fear_greed_index=10,
            kimchi_premium=10.0,
            btc_dominance=70.0,
        )
        adj = self.adapter.compute(snapshot)
        self.assertGreaterEqual(adj.position_size_multiplier, 0.25)

    def test_risk_multiplier_follows_position_multiplier(self) -> None:
        snapshot = _make_snapshot(overall_regime="expansionary")
        adj = self.adapter.compute(snapshot)
        # risk_mult = 0.5 + 1.5 * 0.5 = 1.25
        self.assertAlmostEqual(adj.risk_per_trade_multiplier, 1.25)

    def test_none_crypto_signals_no_crash(self) -> None:
        snapshot = _make_snapshot(
            btc_dominance=None,
            kimchi_premium=None,
            fear_greed_index=None,
        )
        adj = self.adapter.compute(snapshot)
        self.assertAlmostEqual(adj.position_size_multiplier, 1.0)

    def test_allocation_edge_score_reflects_macro_and_market_regime(self) -> None:
        score = self.adapter.allocation_edge_score(
            "momentum",
            "expansionary",
            "bull",
        )
        self.assertAlmostEqual(score, 1.82)


if __name__ == "__main__":
    unittest.main()
