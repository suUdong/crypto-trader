from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.research_summary_report import generate_report


class ResearchSummaryReportTests(unittest.TestCase):
    def test_generate_report_contains_wallet_and_walk_forward_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            baseline = tmp / "baseline.json"
            walk_forward = tmp / "grid-wf-summary.json"
            portfolio = tmp / "portfolio.json"

            baseline.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "strategy": "momentum",
                                "return_pct": 1.0,
                                "profit_factor": 1.2,
                                "max_drawdown": 2.0,
                                "trade_count": 10,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            walk_forward.write_text(
                json.dumps(
                    {
                        "validated_count": 1,
                        "best_research_candidate": {
                            "strategy": "momentum",
                            "best": {"avg_sharpe": 0.8},
                        },
                        "strategies": [
                            {
                                "strategy": "momentum",
                                "best": {
                                    "avg_sharpe": 0.8,
                                    "avg_return_pct": 1.4,
                                    "wf_oos_win_rate": 0.6,
                                    "validated": True,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            portfolio.write_text(
                json.dumps(
                    {
                        "weights": [
                            {
                                "strategy": "momentum",
                                "weight": 1.0,
                                "allocation_krw": 1_000_000,
                                "walk_forward_sharpe": 0.8,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = generate_report(baseline, walk_forward, portfolio)

            self.assertIn("# Backtest Research Report", report)
            self.assertIn(
                "| momentum | +1.00% | 1.20 | 0.80 | +1.40% | 60.0% | YES | 100.0% |",
                report,
            )
            self.assertIn("| momentum | 100.0% | 1,000,000 KRW | 0.80 |", report)


if __name__ == "__main__":
    unittest.main()
