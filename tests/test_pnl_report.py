"""Tests for the PnL report generator."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.operator.pnl_report import PnLReportGenerator


class PnLReportTests(unittest.TestCase):
    def _create_checkpoint(self, tmp_dir: str) -> Path:
        checkpoint = {
            "generated_at": "2026-03-25T10:00:00+00:00",
            "iteration": 100,
            "session_id": "session-abc",
            "config_path": "config/test.toml",
            "symbols": ["KRW-BTC"],
            "wallet_names": ["mean_reversion_wallet", "obi_wallet", "vpin_wallet"],
            "wallet_states": {
                "mean_reversion_wallet": {
                    "strategy_type": "mean_reversion",
                    "cash": 574_094,
                    "realized_pnl": 6_477,
                    "open_positions": 2,
                    "equity": 1_011_728,
                    "trade_count": 2,
                },
                "obi_wallet": {
                    "strategy_type": "obi",
                    "cash": 571_865,
                    "realized_pnl": 4_248,
                    "open_positions": 2,
                    "equity": 1_006_546,
                    "trade_count": 4,
                },
                "vpin_wallet": {
                    "strategy_type": "vpin",
                    "cash": 1_000_000,
                    "realized_pnl": 0,
                    "open_positions": 0,
                    "equity": 1_000_000,
                    "trade_count": 0,
                },
            },
        }
        path = Path(tmp_dir) / "checkpoint.json"
        path.write_text(json.dumps(checkpoint))
        return path

    def _create_heartbeat(
        self,
        tmp_dir: str,
        *,
        session_id: str = "session-abc",
        wallet_names: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> Path:
        heartbeat = {
            "last_heartbeat": "2026-03-25T10:00:05+00:00",
            "pid": 1234,
            "iteration": 100,
            "uptime_seconds": 60.0,
            "poll_interval_seconds": 60,
            "session_id": session_id,
            "config_path": "config/test.toml",
            "wallet_names": wallet_names or ["mean_reversion_wallet", "obi_wallet", "vpin_wallet"],
            "symbols": symbols or ["KRW-BTC"],
        }
        path = Path(tmp_dir) / "daemon-heartbeat.json"
        path.write_text(json.dumps(heartbeat))
        return path

    def test_generate_from_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp, period="daily")
            self.assertEqual(len(report.strategies), 3)
            self.assertGreater(report.portfolio_return_pct, 0)
            self.assertEqual(report.total_trades, 6)

    def test_to_markdown_contains_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp)
            md = gen.to_markdown(report)
            self.assertIn("Portfolio Summary", md)
            self.assertIn("Per-Wallet Breakdown", md)
            self.assertIn("mean_reversion", md)

    def test_save_creates_md_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp)
            out = Path(tmp) / "report.md"
            gen.save(report, out)
            self.assertTrue(out.exists())
            self.assertTrue(out.with_suffix(".json").exists())

    def test_empty_report_on_missing_checkpoint(self) -> None:
        gen = PnLReportGenerator()
        report = gen.generate_from_checkpoint("/nonexistent/path.json")
        self.assertEqual(report.total_trades, 0)
        self.assertEqual(len(report.strategies), 0)

    def test_cumulative_realized_pnl_in_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp)
            md = gen.to_markdown(report)
            self.assertIn("Cumulative Realized PnL", md)
            # Should contain total realized PnL
            self.assertIn("Total", md)

    def test_cumulative_realized_pnl_in_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp)
            out = Path(tmp) / "report.md"
            gen.save(report, out)
            json_path = out.with_suffix(".json")
            data = json.loads(json_path.read_text())
            # Each strategy should have cumulative_realized_pnl
            for s in data["strategies"]:
                self.assertIn("cumulative_realized_pnl", s)
            # Last cumulative should equal total
            if data["strategies"]:
                last_cumulative = data["strategies"][-1]["cumulative_realized_pnl"]
                total = sum(s["realized_pnl"] for s in data["strategies"])
                self.assertAlmostEqual(last_cumulative, total, places=2)

    def test_sharpe_positive_for_positive_return(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp)
            # Mean reversion has positive return, should have positive Sharpe
            mr = [s for s in report.strategies if s.strategy == "mean_reversion"][0]
            self.assertGreater(mr.sharpe_ratio, 0)

    def test_report_marks_missing_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp)
            self.assertEqual(report.artifact_consistency_status, "missing_heartbeat")
            self.assertEqual(report.source_session_id, "session-abc")

    def test_report_marks_consistent_when_heartbeat_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            self._create_heartbeat(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp)
            self.assertEqual(report.artifact_consistency_status, "consistent")
            self.assertEqual(report.heartbeat_session_id, "session-abc")

    def test_saved_json_contains_artifact_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cp = self._create_checkpoint(tmp)
            self._create_heartbeat(tmp)
            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp)
            out = Path(tmp) / "report.md"
            gen.save(report, out)
            data = json.loads(out.with_suffix(".json").read_text())
            self.assertIn("artifact_context", data)
            self.assertEqual(data["artifact_context"]["consistency_status"], "consistent")
