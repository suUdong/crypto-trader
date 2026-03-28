from __future__ import annotations

from crypto_trader.config import HARD_MAX_DAILY_LOSS_PCT, RiskConfig
from crypto_trader.models import StrategyRunRecord, StrategyVerdict, VerdictStatus


class StrategyVerdictEngine:
    def __init__(self, risk_config: RiskConfig) -> None:
        self._risk_config = risk_config

    def evaluate(
        self,
        *,
        consecutive_failures: int,
        realized_pnl: float,
        session_starting_equity: float,
        current_success: bool,
        recent_runs: list[StrategyRunRecord],
    ) -> StrategyVerdict:
        if not current_success or consecutive_failures >= 2:
            reasons = [
                "pipeline failures detected",
                "operator should inspect runtime before continuing",
            ]
            return StrategyVerdict(
                status=VerdictStatus.PAUSE_STRATEGY,
                confidence=0.95,
                reasons=reasons,
            )

        if session_starting_equity > 0:
            effective_daily_loss_pct = min(
                self._risk_config.max_daily_loss_pct,
                HARD_MAX_DAILY_LOSS_PCT,
            )
            daily_loss_limit = session_starting_equity * effective_daily_loss_pct
            used_loss_budget = abs(min(realized_pnl, 0.0))
            if used_loss_budget >= daily_loss_limit:
                return StrategyVerdict(
                    status=VerdictStatus.PAUSE_STRATEGY,
                    confidence=0.9,
                    reasons=["daily loss cap reached", "paper strategy should pause"],
                )
            if daily_loss_limit > 0 and used_loss_budget >= daily_loss_limit * 0.5:
                return StrategyVerdict(
                    status=VerdictStatus.REDUCE_RISK,
                    confidence=0.8,
                    reasons=["loss budget more than half consumed", "risk should be reduced"],
                )

        positive_streak = [
            run
            for run in recent_runs[-5:]
            if run.success and run.realized_pnl >= 0 and run.error is None
        ]
        if len(positive_streak) >= 5 and realized_pnl > 0:
            return StrategyVerdict(
                status=VerdictStatus.CANDIDATE_FOR_PROMOTION,
                confidence=0.75,
                reasons=[
                    "recent paper runs were stable",
                    "realized pnl is positive",
                ],
            )

        return StrategyVerdict(
            status=VerdictStatus.CONTINUE_PAPER,
            confidence=0.6,
            reasons=["no operator intervention required", "continue collecting paper evidence"],
        )
