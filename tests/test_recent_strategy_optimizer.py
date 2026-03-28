from __future__ import annotations

import unittest

from scripts.auto_tune import TuneResult
from scripts.optimize_recent_strategies import render_report


class RenderReportTests(unittest.TestCase):
    def test_render_report_includes_baseline_and_optimized_metrics(self) -> None:
        baseline_results = [
            {
                "strategy": "momentum",
                "symbol": "KRW-BTC",
                "return_pct": 1.0,
                "sharpe": 0.5,
                "mdd_pct": 2.0,
                "win_rate": 40.0,
                "profit_factor": 1.1,
                "trade_count": 10,
            },
            {
                "strategy": "momentum",
                "symbol": "KRW-ETH",
                "return_pct": 3.0,
                "sharpe": 1.5,
                "mdd_pct": 4.0,
                "win_rate": 60.0,
                "profit_factor": 1.3,
                "trade_count": 20,
            },
        ]
        tune_results = [
            TuneResult(
                strategy="momentum",
                params={"momentum_lookback": 12},
                risk_params={"stop_loss_pct": 0.02},
                avg_return_pct=4.2,
                avg_sharpe=1.8,
                avg_mdd_pct=3.1,
                avg_win_rate=55.0,
                avg_profit_factor=1.4,
                total_trades=42,
                best_score=1.7,
                candidate_rank=1,
                top_candidates=[],
                per_symbol={
                    "KRW-BTC": {
                        "return_pct": 5.0,
                        "sharpe": 2.0,
                        "mdd_pct": 2.0,
                        "win_rate": 60.0,
                        "profit_factor": 1.5,
                        "trade_count": 21,
                    }
                },
            )
        ]

        report = render_report(
            days=30,
            json_path="artifacts/test.json",
            toml_path="artifacts/test.toml",
            tune_results=tune_results,
            baseline_results=baseline_results,
        )

        self.assertIn("Baseline avg return: `+2.00%`", report)
        self.assertIn("Optimized avg Sharpe: `1.80`", report)
        self.assertIn("Best risk-adjusted candidate in this 30-day pass: `momentum`", report)
        self.assertIn("artifacts/test.json", report)


if __name__ == "__main__":
    unittest.main()
