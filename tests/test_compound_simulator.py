"""Tests for the compound return simulator."""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, "scripts")
from compound_simulator import generate_report, simulate_compound  # noqa: E402


class CompoundSimulatorTests(unittest.TestCase):
    def test_zero_return_keeps_capital(self) -> None:
        result = simulate_compound(1_000_000, 0.0, 30)
        self.assertAlmostEqual(result.final_equity, 1_000_000, places=0)

    def test_positive_daily_compounds(self) -> None:
        result = simulate_compound(1_000_000, 1.0, 30)
        # 1.01^30 ~ 1.3478
        self.assertGreater(result.final_equity, 1_300_000)
        self.assertLess(result.final_equity, 1_400_000)

    def test_negative_daily_decreases(self) -> None:
        result = simulate_compound(1_000_000, -1.0, 30)
        self.assertLess(result.final_equity, 1_000_000)

    def test_equity_curve_length(self) -> None:
        result = simulate_compound(1_000_000, 0.5, 10)
        self.assertEqual(len(result.equity_curve), 11)  # start + 10 days

    def test_generate_report_contains_sections(self) -> None:
        report = generate_report(6_000_000, 0.332)
        self.assertIn("Compound Return Simulation", report)
        self.assertIn("Conservative", report)
        self.assertIn("Base", report)
        self.assertIn("Optimistic", report)
        self.assertIn("Key Milestones", report)
        self.assertIn("Portfolio Scaling", report)

    def test_generate_report_negative_return(self) -> None:
        report = generate_report(6_000_000, -0.5)
        self.assertIn("not positive", report)
