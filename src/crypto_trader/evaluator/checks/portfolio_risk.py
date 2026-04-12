"""Portfolio risk check: concentration, regime coverage."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import CheckResult, EvalContext, Grade

MAX_SINGLE_STRATEGY_PCT = 0.40
MIN_ACTIVE_STRATEGIES = 2


class PortfolioRiskCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "portfolio_risk"

    def run(self, ctx: EvalContext) -> CheckResult:
        if not ctx.checkpoint:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["runtime-checkpoint 없음"],
                metrics={},
                suggestions=[],
            )

        wallet_states: dict[str, Any] = ctx.checkpoint.get("wallet_states", {})
        if not wallet_states:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["wallet_states 없음"],
                metrics={},
                suggestions=[],
            )

        findings: list[str] = []
        suggestions: list[str] = []
        worst_grade = Grade.PASS
        scores: list[float] = []

        strategy_equity: dict[str, float] = defaultdict(float)
        total_equity = 0.0
        for ws in wallet_states.values():
            equity = float(ws.get("equity", 0.0))
            strategy = ws.get("strategy_type", "unknown")
            strategy_equity[strategy] += equity
            total_equity += equity

        if total_equity > 0:
            for strategy, equity in strategy_equity.items():
                pct = equity / total_equity
                if pct > MAX_SINGLE_STRATEGY_PCT:
                    worst_grade = Grade.worst([worst_grade, Grade.WARN])
                    findings.append(
                        f"{strategy}: 자본 비중 {pct:.0%} > {MAX_SINGLE_STRATEGY_PCT:.0%}"
                    )
                    suggestions.append(f"{strategy} 비중 축소 또는 타 전략 자본 확대")
                    scores.append(0.4)
                else:
                    scores.append(1.0)

        unique_strategies = len(strategy_equity)
        if unique_strategies < MIN_ACTIVE_STRATEGIES:
            worst_grade = Grade.worst([worst_grade, Grade.WARN])
            findings.append(
                f"활성 전략 {unique_strategies}개 < {MIN_ACTIVE_STRATEGIES}개"
                " — 레짐 커버리지 부족"
            )
            suggestions.append("다양한 레짐에서 작동하는 전략 추가 필요")
            scores.append(0.3)
        else:
            scores.append(1.0)

        if not findings:
            findings.append(f"포트폴리오 {unique_strategies}개 전략 — 집중도 양호")

        avg_score = sum(scores) / len(scores) if scores else 0.0

        metrics: dict[str, Any] = {
            "unique_strategies": unique_strategies,
            "total_equity": total_equity,
            "concentration": {
                s: round(e / total_equity, 3) if total_equity > 0 else 0.0
                for s, e in strategy_equity.items()
            },
        }

        return CheckResult(
            check_name=self.name,
            grade=worst_grade,
            score=round(min(avg_score, 1.0), 4),
            findings=findings,
            metrics=metrics,
            suggestions=suggestions,
        )
