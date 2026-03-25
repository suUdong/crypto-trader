from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.models import (
    BacktestBaseline,
    DriftReport,
    DriftStatus,
    PromotionGateDecision,
    PromotionStatus,
    StrategyRunRecord,
)


class PromotionGate:
    def __init__(self, minimum_paper_runs_required: int = 5) -> None:
        self._minimum_paper_runs_required = minimum_paper_runs_required

    def evaluate(
        self,
        *,
        symbol: str,
        backtest_baseline: BacktestBaseline,
        drift_report: DriftReport,
        latest_run: StrategyRunRecord | None,
    ) -> PromotionGateDecision:
        reasons: list[str] = []

        if backtest_baseline.total_return_pct <= 0:
            reasons.append("backtest return is not positive")
        if backtest_baseline.max_drawdown > 0.2:
            reasons.append("backtest drawdown is above 20%")
        if drift_report.paper_run_count < self._minimum_paper_runs_required:
            reasons.append("not enough paper runs have been recorded yet")
        if drift_report.status is DriftStatus.OUT_OF_SYNC:
            reasons.append("paper behavior is out of sync with the backtest")
        if drift_report.status is DriftStatus.CAUTION:
            reasons.append("paper behavior still needs more observation")
        if drift_report.paper_realized_pnl_pct <= 0:
            reasons.append("paper pnl is not yet positive")
        if (
            latest_run is not None
            and latest_run.verdict_status in {"pause_strategy", "reduce_risk"}
        ):
            reasons.append("latest strategy verdict does not support promotion")

        if (
            "backtest return is not positive" in reasons
            or "backtest drawdown is above 20%" in reasons
        ):
            status = PromotionStatus.DO_NOT_PROMOTE
        elif reasons:
            status = PromotionStatus.STAY_IN_PAPER
        else:
            status = PromotionStatus.CANDIDATE_FOR_PROMOTION
            reasons.append("paper evidence and drift checks support a promotion review")

        return PromotionGateDecision(
            generated_at=datetime.now(UTC).isoformat(),
            symbol=symbol,
            status=status,
            reasons=reasons,
            minimum_paper_runs_required=self._minimum_paper_runs_required,
            observed_paper_runs=drift_report.paper_run_count,
            backtest_total_return_pct=backtest_baseline.total_return_pct,
            paper_realized_pnl_pct=drift_report.paper_realized_pnl_pct,
            drift_status=drift_report.status,
        )

    def save(self, decision: PromotionGateDecision, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(decision)
        payload["status"] = decision.status.value
        payload["drift_status"] = decision.drift_status.value
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
