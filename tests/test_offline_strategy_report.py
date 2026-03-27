from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.operator.offline_strategy_report import (
    generate_offline_strategy_report,
    save_offline_strategy_report,
)


class OfflineStrategyReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.baseline = self.tmp / "baseline.json"
        self.tuned = self.tmp / "combined.json"
        self.walk_forward = self.tmp / "grid-wf-summary.json"
        self.live = self.tmp / "runtime-checkpoint.json"
        self.portfolio = self.tmp / "portfolio-optimization.json"

        self.baseline.write_text(
            json.dumps(
                {
                    "days": 90,
                    "results": [
                        {
                            "strategy": "momentum",
                            "return_pct": 1.0,
                            "max_drawdown": 4.0,
                            "profit_factor": 1.1,
                            "trade_count": 50,
                        },
                        {
                            "strategy": "momentum",
                            "return_pct": 3.0,
                            "max_drawdown": 6.0,
                            "profit_factor": 1.3,
                            "trade_count": 70,
                        },
                        {
                            "strategy": "vpin",
                            "return_pct": -2.0,
                            "max_drawdown": 5.0,
                            "profit_factor": 0.8,
                            "trade_count": 40,
                        },
                        {
                            "strategy": "vpin",
                            "return_pct": -4.0,
                            "max_drawdown": 7.0,
                            "profit_factor": 0.6,
                            "trade_count": 60,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.tuned.write_text(
            json.dumps(
                {
                    "optimized_results": [
                        {
                            "strategy": "momentum",
                            "avg_return_pct": 5.0,
                            "avg_sharpe": 1.4,
                            "avg_mdd_pct": 7.0,
                            "avg_profit_factor": 1.5,
                            "total_trades": 140,
                        },
                        {
                            "strategy": "vpin",
                            "avg_return_pct": -1.0,
                            "avg_sharpe": -0.4,
                            "avg_mdd_pct": 6.5,
                            "avg_profit_factor": 0.9,
                            "total_trades": 100,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.walk_forward.write_text(
            json.dumps(
                {
                    "dataset_days": 90,
                    "strategies": [
                        {
                            "strategy": "momentum",
                            "best": {
                                "avg_return_pct": 0.8,
                                "avg_sharpe": 0.3,
                                "avg_profit_factor": 1.05,
                                "total_trades": 180,
                                "wf_oos_win_rate": 0.5,
                                "wf_avg_efficiency_ratio": -0.4,
                                "validated": False,
                            },
                        },
                        {
                            "strategy": "vpin",
                            "best": {
                                "avg_return_pct": -1.2,
                                "avg_sharpe": -0.8,
                                "avg_profit_factor": 0.85,
                                "total_trades": 120,
                                "wf_oos_win_rate": 0.25,
                                "wf_avg_efficiency_ratio": 0.2,
                                "validated": False,
                            },
                        },
                    ],
                    "validated_count": 0,
                }
            ),
            encoding="utf-8",
        )
        self.live.write_text(
            json.dumps(
                {
                    "wallet_states": {
                        "momentum_wallet": {"strategy_type": "momentum"},
                        "consensus_wallet": {"strategy_type": "consensus"},
                    }
                }
            ),
            encoding="utf-8",
        )
        self.portfolio.write_text(
            json.dumps(
                {
                    "score_basis": "walk_forward_sharpe",
                    "total_capital_krw": 2_000_000,
                    "weights": [
                        {
                            "strategy": "momentum",
                            "weight": 0.7,
                            "allocation_krw": 1_400_000,
                            "walk_forward_sharpe": 0.3,
                            "walk_forward_return_pct": 0.8,
                        },
                        {
                            "strategy": "vpin",
                            "weight": 0.3,
                            "allocation_krw": 600_000,
                            "walk_forward_sharpe": -0.8,
                            "walk_forward_return_pct": -1.2,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generate_report_contains_comparison_sections(self) -> None:
        report = generate_offline_strategy_report(
            baseline_path=self.baseline,
            tuned_path=self.tuned,
            walk_forward_path=self.walk_forward,
            live_checkpoint_path=None,
        )
        self.assertIn("# Strategy Performance Comparison Report", report)
        self.assertIn("**Scope**: 2-strategy offline comparison", report)
        self.assertIn("## Comparison Matrix", report)
        self.assertIn(
            "| momentum | +2.00% | 1.20 | +5.00% | 1.40 | +3.00% | "
            "+0.80% | 0.30 | 50.0% | OOS positive, gate fail |",
            report,
        )
        self.assertIn(
            "| vpin | -3.00% | 0.70 | -1.00% | -0.40 | +2.00% | "
            "-1.20% | -0.80 | 25.0% | Negative edge |",
            report,
        )
        self.assertIn("Promotion remains `NO`", report)

    def test_generate_report_includes_live_scope_note_when_universe_differs(self) -> None:
        report = generate_offline_strategy_report(
            baseline_path=self.baseline,
            tuned_path=self.tuned,
            walk_forward_path=self.walk_forward,
            live_checkpoint_path=self.live,
        )
        self.assertIn("## Live Snapshot Scope Note", report)
        self.assertIn("Extra live-only strategies: `consensus`", report)
        self.assertIn("same 2-strategy matrix", report)

    def test_save_report_writes_output(self) -> None:
        output = self.tmp / "docs" / "report.md"
        save_offline_strategy_report("# test", output)
        self.assertEqual(output.read_text(encoding="utf-8"), "# test")

    def test_generate_report_includes_portfolio_section_when_present(self) -> None:
        report = generate_offline_strategy_report(
            baseline_path=self.baseline,
            tuned_path=self.tuned,
            walk_forward_path=self.walk_forward,
            portfolio_path=self.portfolio,
        )
        self.assertIn("## Recommended Wallet Mix", report)
        self.assertIn("| momentum | 70.0% | 1,400,000 KRW | 0.30 | +0.80% |", report)
