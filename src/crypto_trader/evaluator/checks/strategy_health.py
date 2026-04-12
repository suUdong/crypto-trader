"""Strategy health check: per-wallet drawdown, idle detection."""

from __future__ import annotations

from typing import Any

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import CheckResult, EvalContext, Grade

MDD_WARN = 0.10
MDD_FAIL = 0.20
MIN_TRADES_FOR_ACTIVE = 1


class StrategyHealthCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "strategy_health"

    def run(self, ctx: EvalContext) -> CheckResult:
        if not ctx.checkpoint:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["runtime-checkpoint 없음"],
                metrics={},
                suggestions=["daemon 실행 후 체크포인트 생성 필요"],
            )

        wallet_states: dict[str, Any] = ctx.checkpoint.get("wallet_states", {})
        if not wallet_states:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["체크포인트에 wallet_states 없음"],
                metrics={},
                suggestions=[],
            )

        findings: list[str] = []
        suggestions: list[str] = []
        worst_grade = Grade.PASS
        scores: list[float] = []

        for wallet_name, ws in wallet_states.items():
            initial = float(ws.get("initial_capital") or ws.get("equity", 1_000_000))
            equity = float(ws.get("equity", initial))
            trades = int(ws.get("trade_count", 0))
            strategy = ws.get("strategy_type", "unknown")

            if initial > 0:
                drawdown = max(0.0, (initial - equity) / initial)
            else:
                drawdown = 0.0

            if drawdown >= MDD_FAIL:
                worst_grade = Grade.worst([worst_grade, Grade.FAIL])
                findings.append(
                    f"{wallet_name}({strategy}): MDD {drawdown:.1%} >= {MDD_FAIL:.0%}"
                )
                suggestions.append(f"{wallet_name}: 전략 중단 또는 파라미터 재검토")
                scores.append(0.0)
            elif drawdown >= MDD_WARN:
                worst_grade = Grade.worst([worst_grade, Grade.WARN])
                findings.append(
                    f"{wallet_name}({strategy}): MDD {drawdown:.1%} >= {MDD_WARN:.0%}"
                )
                scores.append(0.3)
            else:
                scores.append(1.0 - drawdown)

            if trades < MIN_TRADES_FOR_ACTIVE:
                worst_grade = Grade.worst([worst_grade, Grade.WARN])
                findings.append(
                    f"{wallet_name}({strategy}): 거래 {trades}건 — 유휴 상태"
                )
                suggestions.append(f"{wallet_name}: 시그널 생성 조건 점검 또는 자본 재배분")
                scores.append(0.2)

        if not findings:
            findings.append(f"활성 지갑 {len(wallet_states)}개 — 건강 상태 양호")

        avg_score = sum(scores) / len(scores) if scores else 0.0

        metrics: dict[str, Any] = {
            "wallet_count": len(wallet_states),
            "active_strategies": list({
                ws.get("strategy_type", "unknown") for ws in wallet_states.values()
            }),
        }

        return CheckResult(
            check_name=self.name,
            grade=worst_grade,
            score=round(min(avg_score, 1.0), 4),
            findings=findings,
            metrics=metrics,
            suggestions=suggestions,
        )
