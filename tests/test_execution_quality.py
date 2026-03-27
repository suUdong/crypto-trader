from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.operator.execution_quality import (
    generate_execution_quality_report,
    save_execution_quality_report,
)


class ExecutionQualityReportTests(unittest.TestCase):
    def test_report_matches_trade_events_with_strategy_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            runs_path = base / "strategy-runs.jsonl"
            events_path = base / "events.jsonl"
            runs_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "recorded_at": "2026-03-28T00:00:00+00:00",
                                "symbol": "KRW-BTC",
                                "latest_price": 100.0,
                                "market_regime": "sideways",
                                "signal_action": "buy",
                                "signal_reason": "entry",
                                "signal_confidence": 0.64,
                                "order_status": "filled",
                                "order_side": "buy",
                                "session_starting_equity": 1_000_000.0,
                                "cash": 900_000.0,
                                "open_positions": 1,
                                "realized_pnl": 0.0,
                                "success": True,
                                "error": None,
                                "consecutive_failures": 0,
                                "verdict_status": "continue",
                                "verdict_confidence": 1.0,
                                "wallet_name": "mean_rev_wallet",
                                "strategy_type": "mean_reversion",
                                "signal_indicators": {},
                                "signal_context": {},
                                "session_id": "session-1",
                                "order_type": "limit",
                            }
                        )
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-03-28T00:00:01+00:00",
                                "event_type": "trade",
                                "wallet_name": "mean_rev_wallet",
                                "strategy_type": "mean_reversion",
                                "symbol": "KRW-BTC",
                                "side": "buy",
                                "quantity": 1.0,
                                "fill_price": 100.02,
                                "fee_paid": 0.04,
                                "order_status": "filled",
                                "order_type": "limit",
                                "reason": "entry",
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-03-28T00:05:00+00:00",
                                "event_type": "trade",
                                "wallet_name": "other_wallet",
                                "strategy_type": "momentum",
                                "symbol": "KRW-ETH",
                                "side": "buy",
                                "quantity": 1.0,
                                "fill_price": 200.0,
                                "fee_paid": 0.1,
                                "order_status": "filled",
                                "reason": "entry",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = generate_execution_quality_report(runs_path, events_path)

            self.assertEqual(report.total_fills, 1)
            self.assertEqual(report.fills[0].wallet_name, "mean_rev_wallet")
            self.assertEqual(report.fills[0].order_type, "limit")
            self.assertAlmostEqual(report.fills[0].slippage_pct, 0.0002)
            self.assertAlmostEqual(report.total_fees, 0.04)
            self.assertEqual(report.wallet_breakdown[0].name, "mean_rev_wallet")

    def test_save_execution_quality_report_writes_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            runs_path = base / "strategy-runs.jsonl"
            events_path = base / "events.jsonl"
            runs_path.write_text("", encoding="utf-8")
            events_path.write_text("", encoding="utf-8")
            report = generate_execution_quality_report(runs_path, events_path)
            output_path = base / "execution-quality-report.md"

            save_execution_quality_report(report, output_path)

            self.assertTrue(output_path.exists())
            self.assertTrue(output_path.with_suffix(".json").exists())
            self.assertIn("Execution Quality Report", output_path.read_text(encoding="utf-8"))
