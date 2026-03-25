"""Tests for scripts/micro_live_check.py."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from micro_live_check import format_human, run_check


def _write_checkpoint(path: Path, wallet_states: dict, generated_at: str | None = None) -> None:
    ts = generated_at or datetime.now(UTC).isoformat()
    data = {"generated_at": ts, "wallet_states": wallet_states}
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_journal(path: Path, trades: list[dict]) -> None:
    lines = [json.dumps(t) for t in trades]
    path.write_text("\n".join(lines), encoding="utf-8")


class TestRunCheck(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cp = self.tmp / "checkpoint.json"
        self.journal = self.tmp / "trades.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ready_when_all_criteria_met(self) -> None:
        wallet_states = {
            "w1": {"equity": 1_100_000.0, "trade_count": 5, "strategy_type": "momentum"},
            "w2": {"equity": 1_050_000.0, "trade_count": 5, "strategy_type": "mean_reversion"},
            "w3": {"equity": 1_020_000.0, "trade_count": 5, "strategy_type": "composite"},
        }
        _write_checkpoint(self.cp, wallet_states)

        first_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        trades = [
            {"pnl": 5000.0, "timestamp": first_ts},
            *[{"pnl": 5000.0, "timestamp": datetime.now(UTC).isoformat()} for _ in range(9)],
            *[{"pnl": -2000.0, "timestamp": datetime.now(UTC).isoformat()} for _ in range(5)],
        ]
        _write_journal(self.journal, trades)

        result = run_check(self.cp, self.journal)

        self.assertTrue(result["ready"])
        self.assertIn("criteria", result)
        self.assertEqual(len(result["criteria"]), 6)
        self.assertTrue(all(c["pass"] for c in result["criteria"]))
        self.assertEqual(result["score"], "6/6")

    def test_not_ready_when_no_trades(self) -> None:
        wallet_states = {
            "w1": {"equity": 1_000_000.0, "trade_count": 0, "strategy_type": "momentum"},
        }
        generated_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        _write_checkpoint(self.cp, wallet_states, generated_at=generated_at)
        self.journal.write_text("", encoding="utf-8")

        result = run_check(self.cp, self.journal)

        self.assertFalse(result["ready"])
        self.assertIn("metrics", result)
        self.assertEqual(result["metrics"]["total_trades"], 0)

    def test_missing_checkpoint_not_ready(self) -> None:
        result = run_check(self.tmp / "missing.json", self.journal)

        self.assertFalse(result["ready"])
        self.assertEqual(result["criteria"], [])
        self.assertEqual(result["metrics"], {})

    def test_result_has_checked_at(self) -> None:
        wallet_states = {"w1": {"equity": 1_000_000.0, "trade_count": 0}}
        _write_checkpoint(self.cp, wallet_states)

        result = run_check(self.cp, self.journal)

        self.assertIn("checked_at", result)
        # Should be a valid ISO timestamp
        datetime.fromisoformat(result["checked_at"])

    def test_partial_criteria_score(self) -> None:
        """Some criteria pass, some fail."""
        wallet_states = {
            "w1": {"equity": 1_050_000.0, "trade_count": 3, "strategy_type": "momentum"},
            "w2": {"equity": 1_020_000.0, "trade_count": 2, "strategy_type": "mean_reversion"},
        }
        first_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        _write_checkpoint(self.cp, wallet_states)
        trades = [
            {"pnl": 5000.0, "timestamp": first_ts},
            {"pnl": 3000.0, "timestamp": datetime.now(UTC).isoformat()},
            {"pnl": -1000.0, "timestamp": datetime.now(UTC).isoformat()},
        ]
        _write_journal(self.journal, trades)

        result = run_check(self.cp, self.journal)

        self.assertFalse(result["ready"])
        passed = sum(1 for c in result["criteria"] if c["pass"])
        failed = sum(1 for c in result["criteria"] if not c["pass"])
        self.assertGreater(passed, 0)
        self.assertGreater(failed, 0)

    def test_result_serializable_to_json(self) -> None:
        wallet_states = {"w1": {"equity": 1_000_000.0, "trade_count": 0}}
        _write_checkpoint(self.cp, wallet_states)

        result = run_check(self.cp, self.journal)
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)

        self.assertEqual(deserialized["ready"], result["ready"])


class TestFormatHuman(unittest.TestCase):
    def test_ready_format(self) -> None:
        result = {
            "checked_at": "2026-03-26T10:00:00+00:00",
            "ready": True,
            "score": "6/6",
            "criteria": [
                {"criterion": "paper_days", "value": 10, "threshold": ">= 7d", "pass": True},
            ],
            "reasons": ["All micro-live criteria met. Ready for transition."],
            "metrics": {},
        }
        output = format_human(result)
        self.assertIn("READY", output)
        self.assertIn("6/6", output)
        self.assertIn("[PASS]", output)

    def test_not_ready_format(self) -> None:
        result = {
            "checked_at": "2026-03-26T10:00:00+00:00",
            "ready": False,
            "score": "2/6",
            "criteria": [
                {"criterion": "total_trades", "value": 2, "threshold": ">= 10", "pass": False},
            ],
            "reasons": ["Need 10+ trades (have 2)"],
            "metrics": {},
        }
        output = format_human(result)
        self.assertIn("NOT READY", output)
        self.assertIn("[FAIL]", output)


if __name__ == "__main__":
    unittest.main()
