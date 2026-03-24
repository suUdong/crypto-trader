from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crypto_trader.models import (
    DriftReport,
    DriftStatus,
    PromotionGateDecision,
    PromotionStatus,
    StrategyRunRecord,
)
from crypto_trader.operator.memo import OperatorDailyMemo


def build_run() -> StrategyRunRecord:
    return StrategyRunRecord(
        recorded_at="2026-03-23T00:00:00Z",
        symbol="KRW-BTC",
        latest_price=100.0,
        market_regime="bull",
        signal_action="buy",
        signal_reason="entry",
        signal_confidence=0.8,
        order_status="filled",
        order_side="buy",
        session_starting_equity=1_000.0,
        cash=900.0,
        open_positions=1,
        realized_pnl=20.0,
        success=True,
        error=None,
        consecutive_failures=0,
        verdict_status="continue_paper",
        verdict_confidence=0.6,
        verdict_reasons=["ok"],
    )


def build_drift() -> DriftReport:
    return DriftReport(
        generated_at="2026-03-23T00:00:00Z",
        symbol="KRW-BTC",
        status=DriftStatus.ON_TRACK,
        reasons=["aligned"],
        backtest_total_return_pct=0.1,
        backtest_win_rate=0.6,
        backtest_max_drawdown=0.1,
        backtest_trade_count=5,
        paper_run_count=6,
        paper_error_rate=0.0,
        paper_buy_rate=0.2,
        paper_sell_rate=0.2,
        paper_hold_rate=0.6,
        paper_realized_pnl_pct=0.04,
    )


def build_decision() -> PromotionGateDecision:
    return PromotionGateDecision(
        generated_at="2026-03-23T00:00:00Z",
        symbol="KRW-BTC",
        status=PromotionStatus.CANDIDATE_FOR_PROMOTION,
        reasons=["strong evidence"],
        minimum_paper_runs_required=5,
        observed_paper_runs=6,
        backtest_total_return_pct=0.1,
        paper_realized_pnl_pct=0.04,
        drift_status=DriftStatus.ON_TRACK,
    )


class OperatorDailyMemoTests(unittest.TestCase):
    def test_render_contains_run_drift_and_promotion_sections(self) -> None:
        memo = OperatorDailyMemo().render(
            latest_run=build_run(),
            drift_report=build_drift(),
            promotion_decision=build_decision(),
        )
        self.assertIn("# Strategy Lab Daily Memo", memo)
        self.assertIn("## Run Snapshot", memo)
        self.assertIn("## Drift Status", memo)
        self.assertIn("## Promotion Gate", memo)
        self.assertIn("candidate_for_promotion", memo)
        self.assertIn("bull", memo)

    def test_render_with_no_latest_run(self) -> None:
        memo = OperatorDailyMemo().render(
            latest_run=None,
            drift_report=build_drift(),
            promotion_decision=build_decision(),
        )
        self.assertIn("No strategy runs have been recorded yet", memo)

    def test_render_includes_drift_reasons(self) -> None:
        memo = OperatorDailyMemo().render(
            latest_run=build_run(),
            drift_report=build_drift(),
            promotion_decision=build_decision(),
        )
        self.assertIn("aligned", memo)

    def test_save_writes_memo_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memo.md"
            OperatorDailyMemo().save("hello", path)
            self.assertEqual(path.read_text(encoding="utf-8"), "hello")
