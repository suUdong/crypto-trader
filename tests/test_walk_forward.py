from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from crypto_trader.models import Candle
from scripts.walk_forward import (
    FoldResult,
    aggregate_fold_results,
    build_walk_forward_windows,
    select_validated_strategy,
    validation_gate_status,
    write_validated_config,
    write_walk_forward_markdown,
)


def _make_candles(count: int, start: datetime | None = None) -> list[Candle]:
    base = start or datetime(2025, 1, 1)
    candles: list[Candle] = []
    for index in range(count):
        price = 100.0 + index
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=index),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=1_000.0 + index,
            )
        )
    return candles


class WalkForwardTests(unittest.TestCase):
    def test_build_walk_forward_windows_uses_shortest_history(self) -> None:
        candles_by_symbol = {
            "KRW-BTC": _make_candles(10),
            "KRW-ETH": _make_candles(12),
        }

        windows = build_walk_forward_windows(candles_by_symbol, train_bars=4, test_bars=2)

        self.assertEqual(len(windows), 3)
        first_train, first_test = windows[0]
        self.assertEqual(len(first_train["KRW-BTC"]), 4)
        self.assertEqual(len(first_test["KRW-BTC"]), 2)
        self.assertEqual(first_train["KRW-BTC"][0].timestamp, datetime(2025, 1, 1))
        self.assertEqual(first_test["KRW-BTC"][0].timestamp, datetime(2025, 1, 1, 4))

        last_train, last_test = windows[-1]
        self.assertEqual(last_train["KRW-BTC"][0].timestamp, datetime(2025, 1, 1, 4))
        self.assertEqual(last_test["KRW-BTC"][0].timestamp, datetime(2025, 1, 1, 8))

    def test_aggregate_fold_results_averages_metrics(self) -> None:
        folds = [
            FoldResult(
                fold_index=1,
                strategy="momentum",
                train_start="a",
                train_end="b",
                test_start="c",
                test_end="d",
                tuned_params={"x": 1},
                tuned_risk_params={"y": 1.0},
                train_sharpe=1.0,
                train_return_pct=2.0,
                train_mdd_pct=3.0,
                test_sharpe=0.5,
                test_return_pct=1.0,
                test_mdd_pct=4.0,
                test_win_rate=50.0,
                test_profit_factor=1.2,
                test_total_trades=10,
                candidate_rank=1,
            ),
            FoldResult(
                fold_index=2,
                strategy="momentum",
                train_start="e",
                train_end="f",
                test_start="g",
                test_end="h",
                tuned_params={"x": 2},
                tuned_risk_params={"y": 2.0},
                train_sharpe=3.0,
                train_return_pct=4.0,
                train_mdd_pct=5.0,
                test_sharpe=1.5,
                test_return_pct=2.0,
                test_mdd_pct=6.0,
                test_win_rate=55.0,
                test_profit_factor=1.4,
                test_total_trades=12,
                candidate_rank=2,
            ),
        ]

        aggregate = aggregate_fold_results(folds)

        self.assertEqual(aggregate["fold_count"], 2)
        self.assertEqual(aggregate["total_test_trades"], 22)
        self.assertAlmostEqual(float(aggregate["avg_train_sharpe"]), 2.0)
        self.assertAlmostEqual(float(aggregate["avg_test_sharpe"]), 1.0)
        self.assertAlmostEqual(float(aggregate["avg_test_return_pct"]), 1.5)

    def test_select_validated_strategy_prefers_best_out_of_sample_sharpe(self) -> None:
        momentum_fold = FoldResult(
            fold_index=2,
            strategy="momentum",
            train_start="a",
            train_end="b",
            test_start="c",
            test_end="d",
            tuned_params={"x": 1},
            tuned_risk_params={"y": 1.0},
            train_sharpe=1.5,
            train_return_pct=2.0,
            train_mdd_pct=3.0,
            test_sharpe=1.2,
            test_return_pct=1.5,
            test_mdd_pct=2.0,
            test_win_rate=50.0,
            test_profit_factor=1.3,
            test_total_trades=20,
            candidate_rank=1,
        )
        composite_fold = FoldResult(
            fold_index=2,
            strategy="composite",
            train_start="a",
            train_end="b",
            test_start="c",
            test_end="d",
            tuned_params={"x": 2},
            tuned_risk_params={"y": 2.0},
            train_sharpe=1.0,
            train_return_pct=1.0,
            train_mdd_pct=2.0,
            test_sharpe=0.4,
            test_return_pct=0.5,
            test_mdd_pct=1.0,
            test_win_rate=48.0,
            test_profit_factor=1.1,
            test_total_trades=10,
            candidate_rank=2,
        )

        selection = select_validated_strategy(
            {
                "momentum": [momentum_fold],
                "composite": [composite_fold],
            }
        )

        assert selection is not None
        self.assertEqual(selection[0], "momentum")
        self.assertEqual(selection[1].tuned_params, {"x": 1})

    def test_validation_gate_status_returns_fail_reasons(self) -> None:
        passed, reasons = validation_gate_status(
            {
                "avg_test_sharpe": -0.1,
                "avg_test_return_pct": -0.5,
                "total_test_trades": 5,
            },
            min_test_sharpe=0.0,
            min_test_return_pct=0.0,
            min_total_trades=20,
        )

        self.assertFalse(passed)
        self.assertEqual(len(reasons), 3)

    def test_write_validated_config_skips_output_on_gate_fail(self) -> None:
        fold = FoldResult(
            fold_index=1,
            strategy="momentum",
            train_start="a",
            train_end="b",
            test_start="c",
            test_end="d",
            tuned_params={"x": 1},
            tuned_risk_params={"y": 1.0},
            train_sharpe=1.0,
            train_return_pct=1.0,
            train_mdd_pct=1.0,
            test_sharpe=0.1,
            test_return_pct=0.1,
            test_mdd_pct=1.0,
            test_win_rate=50.0,
            test_profit_factor=1.2,
            test_total_trades=10,
            candidate_rank=1,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "validated.toml"
            base_path = Path(tmpdir) / "base.toml"
            base_path.write_text("[trading]\nexchange = \"upbit\"\n", encoding="utf-8")
            write_validated_config(
                str(output_path),
                (
                    "momentum",
                    fold,
                    {
                        "avg_test_sharpe": 0.1,
                        "avg_test_return_pct": 0.1,
                        "total_test_trades": 10,
                    },
                ),
                str(base_path),
                gate_passed=False,
            )
            self.assertFalse(output_path.exists())

    def test_write_walk_forward_markdown_reports_fail_state(self) -> None:
        fold = FoldResult(
            fold_index=1,
            strategy="momentum",
            train_start="a",
            train_end="b",
            test_start="c",
            test_end="d",
            tuned_params={"x": 1},
            tuned_risk_params={"y": 1.0},
            train_sharpe=1.0,
            train_return_pct=1.0,
            train_mdd_pct=1.0,
            test_sharpe=-0.1,
            test_return_pct=-0.2,
            test_mdd_pct=1.0,
            test_win_rate=50.0,
            test_profit_factor=1.2,
            test_total_trades=10,
            candidate_rank=1,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.md"
            write_walk_forward_markdown(
                str(report_path),
                {"momentum": [fold]},
                90,
                60,
                15,
                (
                    "momentum",
                    fold,
                    {
                        "avg_test_sharpe": -0.1,
                        "avg_test_return_pct": -0.2,
                        "total_test_trades": 10,
                    },
                ),
                (False, ["avg_test_sharpe -0.10 <= 0.00"]),
                (0.0, 0.0, 20),
            )
            text = report_path.read_text(encoding="utf-8")

        self.assertIn("## Validation Decision", text)
        self.assertIn("Gate status: `FAIL`", text)
        self.assertIn("Validated config output: `skipped`", text)
        self.assertIn("Gate thresholds:", text)


if __name__ == "__main__":
    unittest.main()
