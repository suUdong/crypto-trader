from __future__ import annotations

import unittest

from crypto_trader.config import RiskConfig
from crypto_trader.models import StrategyRunRecord, VerdictStatus
from crypto_trader.operator.verdicts import StrategyVerdictEngine


def build_run(
    realized_pnl: float,
    *,
    success: bool = True,
    error: str | None = None,
) -> StrategyRunRecord:
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
        cash=1_000.0,
        open_positions=0,
        realized_pnl=realized_pnl,
        success=success,
        error=error,
        consecutive_failures=0,
        verdict_status="continue_paper",
        verdict_confidence=0.5,
        verdict_reasons=[],
    )


class StrategyVerdictEngineTests(unittest.TestCase):
    def test_pause_strategy_on_runtime_failure(self) -> None:
        engine = StrategyVerdictEngine(RiskConfig())
        verdict = engine.evaluate(
            consecutive_failures=2,
            realized_pnl=0.0,
            session_starting_equity=1_000.0,
            current_success=False,
            recent_runs=[],
        )
        self.assertEqual(verdict.status, VerdictStatus.PAUSE_STRATEGY)

    def test_reduce_risk_when_loss_budget_half_consumed(self) -> None:
        engine = StrategyVerdictEngine(RiskConfig(max_daily_loss_pct=0.1))
        verdict = engine.evaluate(
            consecutive_failures=0,
            realized_pnl=-30.0,
            session_starting_equity=1_000.0,
            current_success=True,
            recent_runs=[],
        )
        self.assertEqual(verdict.status, VerdictStatus.REDUCE_RISK)

    def test_candidate_for_promotion_after_stable_positive_runs(self) -> None:
        engine = StrategyVerdictEngine(RiskConfig())
        recent_runs = [build_run(5.0) for _ in range(5)]
        verdict = engine.evaluate(
            consecutive_failures=0,
            realized_pnl=10.0,
            session_starting_equity=1_000.0,
            current_success=True,
            recent_runs=recent_runs,
        )
        self.assertEqual(verdict.status, VerdictStatus.CANDIDATE_FOR_PROMOTION)

    def test_continue_paper_by_default(self) -> None:
        engine = StrategyVerdictEngine(RiskConfig())
        verdict = engine.evaluate(
            consecutive_failures=0,
            realized_pnl=0.0,
            session_starting_equity=1_000.0,
            current_success=True,
            recent_runs=[],
        )
        self.assertEqual(verdict.status, VerdictStatus.CONTINUE_PAPER)

    def test_pause_strategy_when_daily_loss_cap_fully_consumed(self) -> None:
        engine = StrategyVerdictEngine(RiskConfig(max_daily_loss_pct=0.1))
        verdict = engine.evaluate(
            consecutive_failures=0,
            realized_pnl=-60.0,
            session_starting_equity=1_000.0,
            current_success=True,
            recent_runs=[],
        )
        self.assertEqual(verdict.status, VerdictStatus.PAUSE_STRATEGY)

    def test_verdict_engine_uses_hard_daily_loss_cap_when_config_is_looser(self) -> None:
        engine = StrategyVerdictEngine(RiskConfig(max_daily_loss_pct=0.2))
        verdict = engine.evaluate(
            consecutive_failures=0,
            realized_pnl=-60.0,
            session_starting_equity=1_000.0,
            current_success=True,
            recent_runs=[],
        )
        self.assertEqual(verdict.status, VerdictStatus.PAUSE_STRATEGY)

    def test_pause_on_current_failure_even_without_consecutive(self) -> None:
        engine = StrategyVerdictEngine(RiskConfig())
        verdict = engine.evaluate(
            consecutive_failures=0,
            realized_pnl=0.0,
            session_starting_equity=1_000.0,
            current_success=False,
            recent_runs=[],
        )
        self.assertEqual(verdict.status, VerdictStatus.PAUSE_STRATEGY)

    def test_continue_paper_when_zero_starting_equity(self) -> None:
        engine = StrategyVerdictEngine(RiskConfig())
        verdict = engine.evaluate(
            consecutive_failures=0,
            realized_pnl=-50.0,
            session_starting_equity=0.0,
            current_success=True,
            recent_runs=[],
        )
        self.assertEqual(verdict.status, VerdictStatus.CONTINUE_PAPER)
