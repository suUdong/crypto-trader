from __future__ import annotations

import unittest

from crypto_trader.models import (
    BacktestResult,
    DriftReport,
    DriftStatus,
    PromotionStatus,
    TradeRecord,
)
from crypto_trader.operator.promotion import PromotionGate


def build_backtest(total_return_pct: float, max_drawdown: float = 0.1) -> BacktestResult:
    return BacktestResult(
        initial_capital=1_000.0,
        final_equity=1_000.0 * (1.0 + total_return_pct),
        total_return_pct=total_return_pct,
        win_rate=0.6,
        profit_factor=1.4,
        max_drawdown=max_drawdown,
        trade_log=[
            TradeRecord(
                symbol="KRW-BTC",
                entry_time=None,  # type: ignore[arg-type]
                exit_time=None,  # type: ignore[arg-type]
                entry_price=100.0,
                exit_price=105.0,
                quantity=1.0,
                pnl=5.0,
                pnl_pct=0.05,
                exit_reason="take_profit",
            )
        ],
        equity_curve=[1_000.0, 1_050.0],
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


class PromotionGateTests(unittest.TestCase):
    def test_stays_in_paper_when_runs_are_insufficient(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_result=build_backtest(0.1),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=2,
                paper_realized_pnl_pct=0.03,
            ),
        )
        self.assertEqual(decision.status, PromotionStatus.STAY_IN_PAPER)

    def test_blocks_promotion_when_backtest_is_weak(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_result=build_backtest(-0.05),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=10,
                paper_realized_pnl_pct=0.03,
            ),
        )
        self.assertEqual(decision.status, PromotionStatus.DO_NOT_PROMOTE)

    def test_marks_candidate_when_all_conditions_are_met(self) -> None:
        decision = PromotionGate().evaluate(
            symbol="KRW-BTC",
            backtest_result=build_backtest(0.1),
            drift_report=build_drift(
                status=DriftStatus.ON_TRACK,
                paper_run_count=6,
                paper_realized_pnl_pct=0.04,
            ),
        )
        self.assertEqual(decision.status, PromotionStatus.CANDIDATE_FOR_PROMOTION)
