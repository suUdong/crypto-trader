from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crypto_trader.models import (
    BacktestBaseline,
    DriftReport,
    DriftStatus,
    PromotionStatus,
    StrategyRunRecord,
)
from crypto_trader.operator.promotion import PromotionGate


def build_baseline(total_return_pct: float, max_drawdown: float = 0.1) -> BacktestBaseline:
    return BacktestBaseline(
        generated_at="2026-03-24T00:00:00Z",
        symbol="KRW-BTC",
        interval="minute60",
        candle_count=200,
        config_fingerprint="fingerprint",
        total_return_pct=total_return_pct,
        win_rate=0.6,
        profit_factor=1.4,
        max_drawdown=max_drawdown,
        trade_count=5,
        average_trade_pnl_pct=0.05,
    )


def build_drift(
    *,
    status: DriftStatus,
    paper_run_count: int,
    paper_realized_pnl_pct: float,
) -> DriftReport:
    return DriftReport(
        generated_at="2026-03-23T00:00:00Z",
        symbol="KRW-BTC",
        status=status,
        reasons=[],
        backtest_total_return_pct=0.1,
        backtest_win_rate=0.6,
        backtest_max_drawdown=0.1,
        backtest_trade_count=5,
        paper_run_count=paper_run_count,
        paper_error_rate=0.0,
        paper_buy_rate=0.2,
        paper_sell_rate=0.2,
        paper_hold_rate=0.6,
        paper_realized_pnl_pct=paper_realized_pnl_pct,
    )


def build_latest_run(verdict_status: str) -> StrategyRunRecord:
    return StrategyRunRecord(
        recorded_at="2026-03-23T00:00:00Z",
        symbol="KRW-BTC",
        latest_price=100.0,
        market_regime="sideways",
        signal_action="hold",
        signal_reason="noop",
        signal_confidence=0.5,
        order_status=None,
        order_side=None,
        session_starting_equity=1_000.0,
        cash=1_020.0,
        open_positions=0,
        realized_pnl=20.0,
        success=True,
        error=None,
        consecutive_failures=0,
        verdict_status=verdict_status,
        verdict_confidence=0.7,
        verdict_reasons=[],
    )


class PromotionGateTests(unittest.TestCase):
    def test_stays_in_paper_when_runs_are_insufficient(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.1),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=2,
                paper_realized_pnl_pct=0.03,
            ),
            latest_run=build_latest_run("continue_paper"),
        )
        self.assertEqual(decision.status, PromotionStatus.STAY_IN_PAPER)

    def test_blocks_promotion_when_backtest_is_weak(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(-0.05),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=10,
                paper_realized_pnl_pct=0.03,
            ),
            latest_run=build_latest_run("continue_paper"),
        )
        self.assertEqual(decision.status, PromotionStatus.DO_NOT_PROMOTE)

    def test_marks_candidate_when_all_conditions_are_met(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.1),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=6,
                paper_realized_pnl_pct=0.04,
            ),
            latest_run=build_latest_run("continue_paper"),
        )
        self.assertEqual(decision.status, PromotionStatus.CANDIDATE_FOR_PROMOTION)

    def test_stays_in_paper_when_latest_verdict_is_reduce_risk(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.1),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=6,
                paper_realized_pnl_pct=0.04,
            ),
            latest_run=build_latest_run("reduce_risk"),
        )
        self.assertEqual(decision.status, PromotionStatus.STAY_IN_PAPER)

    def test_do_not_promote_when_drawdown_exceeds_threshold(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.1, max_drawdown=0.25),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=10,
                paper_realized_pnl_pct=0.05,
            ),
            latest_run=build_latest_run("continue_paper"),
        )
        self.assertEqual(decision.status, PromotionStatus.DO_NOT_PROMOTE)

    def test_stays_in_paper_when_drift_is_out_of_sync(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.1),
            drift_report=build_drift(
                status=DriftStatus.OUT_OF_SYNC,
                paper_run_count=10,
                paper_realized_pnl_pct=0.05,
            ),
            latest_run=build_latest_run("continue_paper"),
        )
        self.assertEqual(decision.status, PromotionStatus.STAY_IN_PAPER)

    def test_stays_in_paper_when_paper_pnl_is_negative(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.1),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=10,
                paper_realized_pnl_pct=-0.02,
            ),
            latest_run=build_latest_run("continue_paper"),
        )
        self.assertEqual(decision.status, PromotionStatus.STAY_IN_PAPER)

    def test_candidate_when_latest_run_is_none(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.1),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=6,
                paper_realized_pnl_pct=0.04,
            ),
            latest_run=None,
        )
        self.assertEqual(decision.status, PromotionStatus.CANDIDATE_FOR_PROMOTION)

    def test_save_writes_promotion_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "promotion.json"
            decision = PromotionGate().evaluate(
                symbol="KRW-BTC",
                backtest_baseline=build_baseline(0.1),
                drift_report=build_drift(
                    status=DriftStatus.ON_TRACK,
                    paper_run_count=6,
                    paper_realized_pnl_pct=0.04,
                ),
                latest_run=None,
            )
            PromotionGate().save(decision, path)
            self.assertTrue(path.exists())
