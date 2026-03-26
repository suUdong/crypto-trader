"""Tests for micro-live promotion criteria."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crypto_trader.operator.promotion import MicroLiveCriteria


class MicroLiveCriteriaTests(unittest.TestCase):
    def test_all_criteria_met(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertTrue(ready)
        self.assertIn("All micro-live criteria met", reasons[0])

    def test_insufficient_paper_days(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=3,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("7d" in r for r in reasons))

    def test_low_win_rate(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.30,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("Win rate" in r for r in reasons))

    def test_high_drawdown(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.15,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("MDD" in r for r in reasons))

    def test_insufficient_trades(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=5,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("trades" in r for r in reasons))

    def test_low_profit_factor(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=0.9,
            positive_strategies=3,
        )
        self.assertFalse(ready)
        self.assertTrue(any("Profit factor" in r for r in reasons))

    def test_too_few_positive_strategies(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=10,
            total_trades=20,
            win_rate=0.55,
            max_drawdown=0.05,
            profit_factor=1.5,
            positive_strategies=1,
        )
        self.assertFalse(ready)
        self.assertTrue(any("profitable strategies" in r for r in reasons))

    def test_multiple_failures(self) -> None:
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=1,
            total_trades=2,
            win_rate=0.2,
            max_drawdown=0.20,
            profit_factor=0.5,
            positive_strategies=0,
        )
        self.assertFalse(ready)
        self.assertGreater(len(reasons), 3)


    def test_exact_boundary_values_pass(self) -> None:
        """Exact minimum thresholds (7d, 10 trades, 45%WR, 10%MDD, 1.2PF) must pass."""
        ready, reasons = MicroLiveCriteria.evaluate(
            paper_days=7,
            total_trades=10,
            win_rate=0.45,
            max_drawdown=0.10,
            profit_factor=1.2,
            positive_strategies=2,
        )
        self.assertTrue(ready)

    def test_just_below_boundary_fails(self) -> None:
        """One tick below each threshold must fail."""
        # paper_days=6 (below 7)
        ready, _ = MicroLiveCriteria.evaluate(
            paper_days=6, total_trades=10, win_rate=0.45,
            max_drawdown=0.10, profit_factor=1.2, positive_strategies=2,
        )
        self.assertFalse(ready)

        # total_trades=9 (below 10)
        ready, _ = MicroLiveCriteria.evaluate(
            paper_days=7, total_trades=9, win_rate=0.45,
            max_drawdown=0.10, profit_factor=1.2, positive_strategies=2,
        )
        self.assertFalse(ready)

        # win_rate=0.449 (below 0.45)
        ready, _ = MicroLiveCriteria.evaluate(
            paper_days=7, total_trades=10, win_rate=0.449,
            max_drawdown=0.10, profit_factor=1.2, positive_strategies=2,
        )
        self.assertFalse(ready)

        # max_drawdown=0.101 (above 0.10)
        ready, _ = MicroLiveCriteria.evaluate(
            paper_days=7, total_trades=10, win_rate=0.45,
            max_drawdown=0.101, profit_factor=1.2, positive_strategies=2,
        )
        self.assertFalse(ready)

        # profit_factor=1.19 (below 1.2)
        ready, _ = MicroLiveCriteria.evaluate(
            paper_days=7, total_trades=10, win_rate=0.45,
            max_drawdown=0.10, profit_factor=1.19, positive_strategies=2,
        )
        self.assertFalse(ready)

    def test_hardcoded_constants_match_spec(self) -> None:
        """MicroLiveCriteria constants must match the spec exactly."""
        self.assertEqual(MicroLiveCriteria.MINIMUM_PAPER_DAYS, 7)
        self.assertEqual(MicroLiveCriteria.MINIMUM_TRADES, 10)
        self.assertAlmostEqual(MicroLiveCriteria.MINIMUM_WIN_RATE, 0.45)
        self.assertAlmostEqual(MicroLiveCriteria.MAXIMUM_DRAWDOWN, 0.10)
        self.assertAlmostEqual(MicroLiveCriteria.MINIMUM_PROFIT_FACTOR, 1.2)


class MicroLiveCriteriaArtifactTests(unittest.TestCase):
    def _make_checkpoint(self, path: Path, wallet_states: dict, generated_at: str | None = None) -> None:
        ts = generated_at or datetime.now(UTC).isoformat()
        data = {"generated_at": ts, "wallet_states": wallet_states}
        path.write_text(json.dumps(data), encoding="utf-8")

    def _make_journal(self, path: Path, trades: list[dict]) -> None:
        lines = [json.dumps(t) for t in trades]
        path.write_text("\n".join(lines), encoding="utf-8")

    def test_evaluate_from_artifacts_passing(self, tmp_path=None) -> None:
        if tmp_path is None:
            import tempfile
            tmp_path = Path(tempfile.mkdtemp())
        cp = tmp_path / "checkpoint.json"
        journal = tmp_path / "trades.jsonl"

        # 3 wallets all profitable
        wallet_states = {
            "w1": {"equity": 1_100_000.0, "trade_count": 5},
            "w2": {"equity": 1_050_000.0, "trade_count": 5},
            "w3": {"equity": 1_020_000.0, "trade_count": 5},
        }
        self._make_checkpoint(cp, wallet_states)

        # 15 trades, 10 winning (win_rate=0.667), profit_factor > 1.2
        first_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        trades = []
        for i in range(10):
            trades.append({"pnl": 5000.0, "timestamp": first_ts if i == 0 else datetime.now(UTC).isoformat()})
        for _ in range(5):
            trades.append({"pnl": -2000.0, "timestamp": datetime.now(UTC).isoformat()})
        self._make_journal(journal, trades)

        ready, reasons, metrics = MicroLiveCriteria.evaluate_from_artifacts(cp, journal)

        self.assertTrue(ready)
        self.assertEqual(metrics["positive_strategies"], 3)
        self.assertGreaterEqual(metrics["win_rate"], 0.45)
        self.assertGreaterEqual(metrics["paper_days"], 10)
        self.assertEqual(metrics["total_trades"], 15)

    def test_evaluate_from_artifacts_no_trades(self, tmp_path=None) -> None:
        if tmp_path is None:
            import tempfile
            tmp_path = Path(tempfile.mkdtemp())
        cp = tmp_path / "checkpoint.json"
        journal = tmp_path / "trades.jsonl"

        wallet_states = {
            "w1": {"equity": 1_000_000.0, "trade_count": 0},
        }
        # generated_at 2 days ago — too few paper days
        generated_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        self._make_checkpoint(cp, wallet_states, generated_at=generated_at)
        journal.write_text("", encoding="utf-8")

        ready, reasons, metrics = MicroLiveCriteria.evaluate_from_artifacts(cp, journal)

        self.assertFalse(ready)
        self.assertEqual(metrics["total_trades"], 0)
        self.assertEqual(metrics["win_rate"], 0.0)
        self.assertTrue(any("trades" in r for r in reasons))

    def test_evaluate_from_artifacts_missing_checkpoint(self, tmp_path=None) -> None:
        if tmp_path is None:
            import tempfile
            tmp_path = Path(tempfile.mkdtemp())
        missing = tmp_path / "nonexistent.json"

        ready, reasons, metrics = MicroLiveCriteria.evaluate_from_artifacts(missing)

        self.assertFalse(ready)
        self.assertTrue(any("not found" in r.lower() or "checkpoint" in r.lower() for r in reasons))
        self.assertEqual(metrics, {})
