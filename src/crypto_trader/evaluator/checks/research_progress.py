"""Research progress check: research loop and market scan activity."""

from __future__ import annotations

from typing import Any

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import CheckResult, EvalContext, Grade


class ResearchProgressCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "research_progress"

    @property
    def weight(self) -> float:
        return 0.5  # informational, lower weight

    def run(self, ctx: EvalContext) -> CheckResult:
        if not ctx.research_state and not ctx.market_scan_state:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["research_state 및 market_scan_state 없음"],
                metrics={},
                suggestions=[],
            )

        findings: list[str] = []
        metrics: dict[str, Any] = {}
        grade = Grade.PASS
        scores: list[float] = []

        if ctx.research_state:
            cycle = ctx.research_state.get("cycle", 0)
            done = ctx.research_state.get("done", [])
            metrics["research_cycle"] = cycle
            metrics["entries_completed"] = len(done)
            if done:
                findings.append(f"research 사이클 {cycle}, 완료 항목 {len(done)}개")
                scores.append(0.8)
            else:
                findings.append(f"research 사이클 {cycle} — 완료 항목 없음")
                scores.append(0.3)

        if ctx.market_scan_state:
            scan_cycle = ctx.market_scan_state.get("current_cycle", 0)
            metrics["market_scan_cycle"] = scan_cycle
            findings.append(f"market scan 사이클 {scan_cycle}")
            scores.append(0.8)

        avg_score = sum(scores) / len(scores) if scores else 0.0

        return CheckResult(
            check_name=self.name,
            grade=grade,
            score=round(min(avg_score, 1.0), 4),
            findings=findings,
            metrics=metrics,
            suggestions=[],
        )
