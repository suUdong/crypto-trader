from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.walk_forward import FoldResult, write_grid_summary_json


class WalkForwardSummaryTests(unittest.TestCase):
    def test_grid_summary_is_report_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "grid-wf-summary.json"
            folds = {
                "momentum": [
                    FoldResult(
                        fold_index=1,
                        strategy="momentum",
                        train_start="2025-01-01T00:00:00",
                        train_end="2025-02-01T00:00:00",
                        test_start="2025-02-01T01:00:00",
                        test_end="2025-02-15T00:00:00",
                        tuned_params={"momentum_lookback": 20},
                        tuned_risk_params={"stop_loss_pct": 0.03},
                        train_sharpe=1.0,
                        train_return_pct=3.0,
                        train_mdd_pct=4.0,
                        test_sharpe=0.5,
                        test_return_pct=1.2,
                        test_mdd_pct=3.5,
                        test_win_rate=55.0,
                        test_profit_factor=1.2,
                        test_total_trades=12,
                        candidate_rank=1,
                    )
                ],
                "momentum_pullback": [
                    FoldResult(
                        fold_index=1,
                        strategy="momentum_pullback",
                        train_start="2025-01-01T00:00:00",
                        train_end="2025-02-01T00:00:00",
                        test_start="2025-02-01T01:00:00",
                        test_end="2025-02-15T00:00:00",
                        tuned_params={"momentum_lookback": 15},
                        tuned_risk_params={"stop_loss_pct": 0.04},
                        train_sharpe=0.8,
                        train_return_pct=2.0,
                        train_mdd_pct=3.0,
                        test_sharpe=-0.2,
                        test_return_pct=-0.3,
                        test_mdd_pct=4.5,
                        test_win_rate=40.0,
                        test_profit_factor=0.9,
                        test_total_trades=8,
                        candidate_rank=2,
                    )
                ],
            }

            write_grid_summary_json(
                output_path=str(output),
                folds_by_strategy=folds,
                total_days=90,
                symbols=["KRW-BTC", "KRW-ETH"],
                top_n=3,
                gate_thresholds=(0.0, 0.0, 10),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["dataset_days"], 90)
            self.assertEqual(payload["validated_count"], 1)
            self.assertEqual(payload["best_research_candidate"]["strategy"], "momentum")
            strategy_rows = {row["strategy"]: row for row in payload["strategies"]}
            self.assertAlmostEqual(strategy_rows["momentum"]["best"]["wf_oos_win_rate"], 0.55)
            self.assertTrue(strategy_rows["momentum"]["best"]["validated"])
            self.assertFalse(strategy_rows["momentum_pullback"]["best"]["validated"])


if __name__ == "__main__":
    unittest.main()
