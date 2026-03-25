from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.models import Candle
from scripts.walk_forward import FoldResult, aggregate_fold_results, build_walk_forward_windows


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


if __name__ == "__main__":
    unittest.main()
