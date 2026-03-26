"""Tests for PnL snapshot store."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.operator.pnl_report import (
    PnLReportGenerator,
    PnLSnapshotStore,
    PortfolioPnLReport,
    StrategyPnLMetrics,
)


def _make_report(equity: float = 3_000_000.0, realized: float = 1500.0) -> PortfolioPnLReport:
    return PortfolioPnLReport(
        generated_at="2026-03-26T10:00:00+00:00",
        period="daily",
        strategies=[
            StrategyPnLMetrics(
                strategy="momentum",
                wallet="momentum_btc_wallet",
                total_return_pct=0.15,
                realized_pnl=realized,
                unrealized_pnl=-200.0,
                trade_count=3,
                win_count=2,
                loss_count=1,
                win_rate=0.667,
                profit_factor=2.5,
                max_drawdown_pct=0.5,
                sharpe_ratio=1.8,
                equity=equity,
                initial_capital=1_000_000.0,
            ),
        ],
        portfolio_return_pct=0.15,
        portfolio_sharpe=1.8,
        portfolio_mdd=0.5,
        portfolio_win_rate=0.667,
        total_trades=3,
        total_realized_pnl=realized,
        total_equity=equity,
        total_initial_capital=1_000_000.0,
    )


class TestPnLSnapshotStore(unittest.TestCase):
    def test_append_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PnLSnapshotStore(Path(tmp) / "snapshots.jsonl")
            report1 = _make_report(equity=3_000_000.0, realized=1500.0)
            report2 = _make_report(equity=3_010_000.0, realized=2000.0)
            store.append(report1)
            store.append(report2)

            history = store.load_history()
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["total_equity"], 3_000_000.0)
            self.assertEqual(history[1]["total_equity"], 3_010_000.0)

    def test_snapshot_contains_wallet_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PnLSnapshotStore(Path(tmp) / "snapshots.jsonl")
            store.append(_make_report())

            history = store.load_history()
            self.assertEqual(len(history[0]["wallets"]), 1)
            w = history[0]["wallets"][0]
            self.assertEqual(w["wallet"], "momentum_btc_wallet")
            self.assertEqual(w["strategy"], "momentum")

    def test_load_history_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PnLSnapshotStore(Path(tmp) / "nonexistent.jsonl")
            self.assertEqual(store.load_history(), [])

    def test_save_auto_appends_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Create checkpoint for generate
            checkpoint = {
                "generated_at": "2026-03-26T10:00:00+00:00",
                "iteration": 100,
                "symbols": ["KRW-BTC"],
                "wallet_states": {
                    "test_wallet": {
                        "strategy_type": "momentum",
                        "cash": 1_000_000,
                        "realized_pnl": 500,
                        "open_positions": 0,
                        "equity": 1_000_500,
                        "trade_count": 2,
                    },
                },
            }
            cp_path = Path(tmp) / "checkpoint.json"
            cp_path.write_text(json.dumps(checkpoint))

            gen = PnLReportGenerator()
            report = gen.generate_from_checkpoint(cp_path)
            out = Path(tmp) / "report.md"
            gen.save(report, out)

            # Check snapshot was auto-appended
            snapshot_path = Path(tmp) / "pnl-snapshots.jsonl"
            self.assertTrue(snapshot_path.exists())
            store = PnLSnapshotStore(snapshot_path)
            history = store.load_history()
            self.assertEqual(len(history), 1)
            self.assertIn("total_equity", history[0])
            self.assertIn("wallets", history[0])

    def test_pnl_history_output_format(self) -> None:
        """Verify the snapshot data has all fields needed for trending display."""
        with tempfile.TemporaryDirectory() as tmp:
            store = PnLSnapshotStore(Path(tmp) / "snapshots.jsonl")
            store.append(_make_report(equity=3_000_000.0))
            store.append(_make_report(equity=3_005_000.0))

            history = store.load_history()
            required_keys = {"timestamp", "period", "portfolio_return_pct", "total_equity", "total_realized_pnl", "total_trades"}
            for entry in history:
                self.assertTrue(required_keys.issubset(entry.keys()), f"Missing keys: {required_keys - entry.keys()}")


if __name__ == "__main__":
    unittest.main()
