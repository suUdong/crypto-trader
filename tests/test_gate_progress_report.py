from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.operator.gate_progress import generate_gate_progress_report


class GateProgressReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.runtime_checkpoint = self.tmp / "runtime-checkpoint.json"
        self.backtest_baseline = self.tmp / "backtest-baseline.json"
        self.drift_report = self.tmp / "drift-report.json"
        self.promotion_gate = self.tmp / "promotion-gate.json"
        self.strategy_runs = self.tmp / "strategy-runs.jsonl"
        self.walk_forward = self.tmp / "grid-wf-summary.json"

        self.runtime_checkpoint.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-26T19:14:42.300893+00:00",
                    "wallet_states": {
                        "momentum_btc_wallet": {
                            "strategy_type": "momentum",
                            "equity": 1_000_000.0,
                            "realized_pnl": 0.0,
                            "trade_count": 0,
                            "open_positions": 0,
                        },
                        "momentum_eth_wallet": {
                            "strategy_type": "momentum",
                            "equity": 1_000_000.0,
                            "realized_pnl": 0.0,
                            "trade_count": 0,
                            "open_positions": 0,
                        },
                        "kimchi_premium_wallet": {
                            "strategy_type": "kimchi_premium",
                            "equity": 999_609.38,
                            "realized_pnl": 0.0,
                            "trade_count": 0,
                            "open_positions": 1,
                        },
                        "consensus_btc_wallet": {
                            "strategy_type": "consensus",
                            "equity": 1_000_000.0,
                            "realized_pnl": 0.0,
                            "trade_count": 0,
                            "open_positions": 0,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        self.backtest_baseline.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-26T19:10:47.745449+00:00",
                    "total_return_pct": 0.0206,
                    "max_drawdown": 0.0,
                }
            ),
            encoding="utf-8",
        )
        self.drift_report.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-26T19:06:53.751188+00:00",
                    "status": "on_track",
                    "paper_run_count": 20,
                    "paper_realized_pnl_pct": 0.0,
                }
            ),
            encoding="utf-8",
        )
        self.promotion_gate.write_text(
            json.dumps(
                {
                    "status": "stay_in_paper",
                    "reasons": ["paper pnl is not yet positive"],
                    "minimum_paper_runs_required": 5,
                    "backtest_total_return_pct": 0.0093,
                }
            ),
            encoding="utf-8",
        )
        self.strategy_runs.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "recorded_at": "2026-03-26T19:14:42.300323+00:00",
                            "verdict_status": "continue",
                        }
                    )
                ]
            ),
            encoding="utf-8",
        )
        self.walk_forward.write_text(
            json.dumps(
                {
                    "strategies": [
                        {
                            "strategy": "momentum",
                            "best": {"avg_return_pct": 0.71, "avg_sharpe": 0.29},
                        },
                        {
                            "strategy": "kimchi_premium",
                            "best": {"avg_return_pct": 0.47, "avg_sharpe": 0.22},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_report_contains_key_sections_and_progress(self) -> None:
        report = generate_gate_progress_report(
            runtime_checkpoint_path=self.runtime_checkpoint,
            backtest_baseline_path=self.backtest_baseline,
            drift_report_path=self.drift_report,
            promotion_gate_path=self.promotion_gate,
            strategy_run_journal_path=self.strategy_runs,
            walk_forward_summary_path=self.walk_forward,
        )

        self.assertIn("# Gate Progress - ", report)
        self.assertIn("## Strategy Snapshot", report)
        self.assertIn("## Promotion Gate Progress", report)
        self.assertIn("400% | PASS", report)
        self.assertIn("0% | FAIL", report)
        self.assertIn("`stay_in_paper`", report)
        self.assertIn("`paper pnl is not yet positive`", report)
        self.assertIn("`kimchi_premium`", report)

    def test_report_mentions_artifact_skew_when_baseline_differs(self) -> None:
        report = generate_gate_progress_report(
            runtime_checkpoint_path=self.runtime_checkpoint,
            backtest_baseline_path=self.backtest_baseline,
            drift_report_path=self.drift_report,
            promotion_gate_path=self.promotion_gate,
            strategy_run_journal_path=self.strategy_runs,
            walk_forward_summary_path=self.walk_forward,
        )

        self.assertIn("Artifact skew note", report)
        self.assertIn("`+0.93%`", report)
        self.assertIn("`+2.06%`", report)

    def test_report_writes_output_file_when_requested(self) -> None:
        output_path = self.tmp / "docs" / "gate-progress.md"
        generate_gate_progress_report(
            runtime_checkpoint_path=self.runtime_checkpoint,
            backtest_baseline_path=self.backtest_baseline,
            drift_report_path=self.drift_report,
            promotion_gate_path=self.promotion_gate,
            strategy_run_journal_path=self.strategy_runs,
            walk_forward_summary_path=self.walk_forward,
            output_path=output_path,
        )

        self.assertTrue(output_path.exists())
        self.assertIn("Gate Progress", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
