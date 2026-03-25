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


class MicroLiveCriteria:
    """Criteria for paper-to-micro-live transition."""

    MINIMUM_PAPER_DAYS: int = 7
    MINIMUM_TRADES: int = 10
    MINIMUM_WIN_RATE: float = 0.45
    MAXIMUM_DRAWDOWN: float = 0.10
    MINIMUM_PROFIT_FACTOR: float = 1.2
    MINIMUM_POSITIVE_STRATEGIES: int = 2

    @classmethod
    def evaluate(
        cls,
        paper_days: int,
        total_trades: int,
        win_rate: float,
        max_drawdown: float,
        profit_factor: float,
        positive_strategies: int,
    ) -> tuple[bool, list[str]]:
        """Return (ready, reasons) for micro-live transition."""
        reasons: list[str] = []
        ready = True

        if paper_days < cls.MINIMUM_PAPER_DAYS:
            reasons.append(f"Need {cls.MINIMUM_PAPER_DAYS}d paper trading (have {paper_days}d)")
            ready = False
        if total_trades < cls.MINIMUM_TRADES:
            reasons.append(f"Need {cls.MINIMUM_TRADES}+ trades (have {total_trades})")
            ready = False
        if win_rate < cls.MINIMUM_WIN_RATE:
            reasons.append(f"Win rate {win_rate:.0%} below {cls.MINIMUM_WIN_RATE:.0%} minimum")
            ready = False
        if max_drawdown > cls.MAXIMUM_DRAWDOWN:
            reasons.append(f"MDD {max_drawdown:.1%} exceeds {cls.MAXIMUM_DRAWDOWN:.0%} limit")
            ready = False
        if profit_factor < cls.MINIMUM_PROFIT_FACTOR:
            reasons.append(f"Profit factor {profit_factor:.2f} below {cls.MINIMUM_PROFIT_FACTOR:.1f}")
            ready = False
        if positive_strategies < cls.MINIMUM_POSITIVE_STRATEGIES:
            reasons.append(
                f"Need {cls.MINIMUM_POSITIVE_STRATEGIES}+ profitable strategies "
                f"(have {positive_strategies})"
            )
            ready = False

        if ready:
            reasons.append("All micro-live criteria met. Ready for transition.")

        return ready, reasons


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
