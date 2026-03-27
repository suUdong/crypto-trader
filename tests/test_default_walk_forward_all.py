from __future__ import annotations

import unittest

from crypto_trader.backtest.walk_forward import WalkForwardFold, WalkForwardReport
from crypto_trader.models import BacktestResult
from scripts.default_walk_forward_all import _aggregate_strategy_reports


def _result(return_pct: float, sharpe: float, profit_factor: float, trades: int) -> BacktestResult:
    return BacktestResult(
        initial_capital=1_000_000.0,
        total_return_pct=return_pct / 100.0,
        win_rate=0.5,
        profit_factor=profit_factor,
        max_drawdown=0.01,
        trade_log=[{"pnl": 1.0}] * trades,
        equity_curve=[1_000_000.0, 1_001_000.0],
        final_equity=1_001_000.0,
        sharpe_ratio=sharpe,
    )


class DefaultWalkForwardAllTests(unittest.TestCase):
    def test_aggregate_strategy_reports_builds_legacy_summary_shape(self) -> None:
        report = WalkForwardReport(
            strategy_name="momentum",
            symbol="KRW-BTC",
            total_folds=1,
            folds=[
                WalkForwardFold(
                    fold_index=0,
                    train_bars=100,
                    test_bars=40,
                    train_result=_result(2.0, 1.0, 1.2, 3),
                    test_result=_result(1.0, 0.6, 1.1, 2),
                )
            ],
        )

        summary = _aggregate_strategy_reports("momentum", [report])

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["strategy"], "momentum")
        self.assertEqual(summary["candidates_tested"], 1)
        self.assertAlmostEqual(summary["best"]["avg_sharpe"], 0.6)
        self.assertAlmostEqual(summary["best"]["wf_oos_win_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
