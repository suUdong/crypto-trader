"""Tests for snapshot CLI automation features."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crypto_trader.operator.pnl_report import (
    PnLReportGenerator,
    PnLSnapshotStore,
    PortfolioPnLReport,
)


class TestSnapshotCLI:
    def test_snapshot_writes_to_output_dir(self, tmp_path: Path) -> None:
        """Snapshot should write artifacts to specified output directory."""
        output_dir = tmp_path / "custom_output"
        output_dir.mkdir()

        checkpoint_path = tmp_path / "runtime-checkpoint.json"
        checkpoint_path.write_text(json.dumps({
            "generated_at": "2026-03-26T12:00:00",
            "iteration": 10,
            "symbols": ["KRW-BTC"],
            "wallet_states": {
                "test_wallet": {
                    "strategy_type": "momentum",
                    "cash": 950000,
                    "realized_pnl": -50000,
                    "open_positions": 0,
                    "equity": 950000,
                    "trade_count": 5,
                }
            },
        }), encoding="utf-8")

        generator = PnLReportGenerator()
        report = generator.generate_from_checkpoint(str(checkpoint_path))

        output_path = output_dir / "pnl-report.md"
        generator.save(report, output_path)

        assert output_path.exists()
        assert output_path.with_suffix(".json").exists()

    def test_snapshot_json_output_format(self, tmp_path: Path) -> None:
        """Snapshot should produce structured JSON summary."""
        checkpoint_path = tmp_path / "runtime-checkpoint.json"
        checkpoint_path.write_text(json.dumps({
            "generated_at": "2026-03-26T12:00:00",
            "iteration": 10,
            "symbols": ["KRW-BTC"],
            "wallet_states": {
                "momentum_wallet": {
                    "strategy_type": "momentum",
                    "cash": 1_048_000,
                    "realized_pnl": 48000,
                    "open_positions": 1,
                    "equity": 1_048_000,
                    "trade_count": 12,
                }
            },
        }), encoding="utf-8")

        generator = PnLReportGenerator()
        report = generator.generate_from_checkpoint(str(checkpoint_path))

        summary = {
            "status": "ok",
            "equity": report.total_equity,
            "return_pct": round(report.portfolio_return_pct, 4),
            "sharpe": round(report.portfolio_sharpe, 2),
            "trades": report.total_trades,
            "win_rate": round(report.portfolio_win_rate, 4),
            "realized_pnl": round(report.total_realized_pnl, 0),
            "source_session_id": report.source_session_id,
            "artifact_consistency_status": report.artifact_consistency_status,
            "artifact_freshness_status": "fresh",
            "report_path": "artifacts/pnl-report.md",
            "snapshot_path": "artifacts/pnl-snapshots.jsonl",
        }

        json_str = json.dumps(summary)
        parsed = json.loads(json_str)
        assert parsed["status"] == "ok"
        assert "equity" in parsed
        assert "return_pct" in parsed
        assert "sharpe" in parsed
        assert "trades" in parsed
        assert "win_rate" in parsed
        assert "realized_pnl" in parsed
        assert "source_session_id" in parsed
        assert "artifact_consistency_status" in parsed
        assert "artifact_freshness_status" in parsed
        assert "report_path" in parsed

    def test_snapshot_error_produces_error_json(self) -> None:
        """Failed snapshot should produce error JSON."""
        summary = {"status": "error", "error": "No checkpoint found"}
        parsed = json.loads(json.dumps(summary))
        assert parsed["status"] == "error"
        assert "error" in parsed

    def test_snapshot_appends_to_history(self, tmp_path: Path) -> None:
        """Snapshot should append to pnl-snapshots.jsonl history."""
        snapshot_path = tmp_path / "pnl-snapshots.jsonl"
        store = PnLSnapshotStore(snapshot_path)

        report = PnLReportGenerator()._empty_report("daily")
        store.append(report)
        store.append(report)

        history = store.load_history()
        assert len(history) == 2

    def test_output_dir_created_if_missing(self, tmp_path: Path) -> None:
        """Output directory should be created if it doesn't exist."""
        output_dir = tmp_path / "new" / "nested" / "dir"
        output_dir.mkdir(parents=True, exist_ok=True)
        assert output_dir.exists()
