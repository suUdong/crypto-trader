from __future__ import annotations

import unittest

from scripts.auto_tune import TuneResult
from scripts.backtest_strategy_sweep import render_report


class RenderSweepReportTests(unittest.TestCase):
    def test_render_report_compares_required_metrics_and_breakout_alias(self) -> None:
        baseline_results = [
            {
                "strategy": "volatility_breakout",
                "symbol": "KRW-BTC",
                "return_pct": 1.0,
                "sharpe": 0.4,
                "mdd_pct": 3.0,
                "win_rate": 45.0,
                "profit_factor": 1.1,
                "trade_count": 8,
            },
            {
                "strategy": "volatility_breakout",
                "symbol": "KRW-ETH",
                "return_pct": 2.0,
                "sharpe": 0.8,
                "mdd_pct": 4.0,
                "win_rate": 55.0,
                "profit_factor": 1.3,
                "trade_count": 12,
            },
        ]
        tune_results = [
            TuneResult(
                strategy="volatility_breakout",
                params={"k_base": 0.3},
                risk_params={"stop_loss_pct": 0.02},
                avg_return_pct=4.5,
                avg_sharpe=1.7,
                avg_mdd_pct=2.8,
                avg_win_rate=57.0,
                avg_profit_factor=1.5,
                total_trades=28,
                best_score=1.6,
                candidate_rank=1,
                top_candidates=[],
                per_symbol={
                    "KRW-BTC": {
                        "return_pct": 5.0,
                        "sharpe": 1.8,
                        "mdd_pct": 2.5,
                        "win_rate": 58.0,
                        "profit_factor": 1.6,
                        "trade_count": 14,
                    }
                },
            )
        ]

        report = render_report(
            days=90,
            json_path="backtest_results/strategy-sweep-90d.json",
            toml_path="backtest_results/strategy-sweep-90d.toml",
            tune_results=tune_results,
            baseline_results=baseline_results,
        )

        self.assertIn("Optimized Win Rate", report)
        self.assertIn("Optimized MDD", report)
        self.assertIn("Optimized Sharpe", report)
        self.assertIn("breakout (volatility_breakout)", report)
        self.assertIn("Best risk-adjusted strategy in this 3-month pass", report)
        self.assertIn("backtest_results/strategy-sweep-90d.json", report)


if __name__ == "__main__":
    unittest.main()
