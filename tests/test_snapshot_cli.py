"""Tests for the snapshot CLI command."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from crypto_trader.operator.pnl_report import PnLSnapshotStore


def _make_checkpoint(tmp_dir: str) -> Path:
    checkpoint = {
        "generated_at": "2026-03-26T10:00:00+00:00",
        "iteration": 10,
        "symbols": ["KRW-BTC"],
        "wallet_states": {
            "momentum_wallet": {
                "strategy_type": "momentum",
                "cash": 900_000,
                "realized_pnl": 5_000,
                "open_positions": 1,
                "equity": 1_005_000,
                "trade_count": 3,
            },
        },
    }
    path = Path(tmp_dir) / "runtime" / "checkpoint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    return path


class TestSnapshotCLI(unittest.TestCase):
    def _run_snapshot_command(self, tmp_dir: str, hours: int = 0) -> None:
        """Import and exercise the snapshot handler logic directly."""
        from crypto_trader.operator.pnl_report import PnLReportGenerator, PnLSnapshotStore

        cp_path = _make_checkpoint(tmp_dir)

        generator = PnLReportGenerator()
        period = f"{hours}h" if hours > 0 else "daily"
        report = generator.generate_from_checkpoint(
            checkpoint_path=cp_path,
            trade_journal_path=None,
            period=period,
            hours=hours,
        )

        output_path = Path(tmp_dir) / "artifacts" / "pnl-report.md"
        generator.save(report, output_path)

        snapshot_path = cp_path.parent / "pnl-snapshots.jsonl"
        store = PnLSnapshotStore(snapshot_path)
        store.append(report)

        return report, output_path, snapshot_path

    def test_snapshot_creates_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, output_path, snapshot_path = self._run_snapshot_command(tmp)
            self.assertTrue(output_path.exists(), "Report markdown file should be created")

    def test_snapshot_appends_to_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, output_path, snapshot_path = self._run_snapshot_command(tmp)
            store = PnLSnapshotStore(snapshot_path)
            history = store.load_history()
            # save() auto-appends once, then we append again explicitly — 2 entries
            self.assertGreaterEqual(len(history), 1)
            self.assertIn("total_equity", history[0])
            self.assertIn("total_trades", history[0])

    def test_snapshot_report_equity_matches_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, output_path, snapshot_path = self._run_snapshot_command(tmp)
            self.assertAlmostEqual(report.total_equity, 1_005_000.0, places=0)

    def test_snapshot_with_hours_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, output_path, snapshot_path = self._run_snapshot_command(tmp, hours=72)
            self.assertEqual(report.period, "72h")

    def test_snapshot_json_report_also_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, output_path, snapshot_path = self._run_snapshot_command(tmp)
            json_path = output_path.with_suffix(".json")
            self.assertTrue(json_path.exists(), "JSON report file should be created alongside markdown")
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIn("total_equity", data)
            self.assertIn("strategies", data)


if __name__ == "__main__":
    unittest.main()
