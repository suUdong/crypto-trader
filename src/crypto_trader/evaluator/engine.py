"""Evaluator v2 pipeline engine: discover checks, run, aggregate."""

from __future__ import annotations

import importlib
import pkgutil
import uuid
from datetime import UTC, datetime

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import (
    EvalContext,
    EvaluationReport,
    Grade,
)


def discover_checks() -> list[BaseCheck]:
    """Auto-discover BaseCheck subclasses in the checks package."""
    from crypto_trader.evaluator import checks as checks_pkg

    found: list[BaseCheck] = []
    for info in pkgutil.iter_modules(checks_pkg.__path__):
        if info.name == "base":
            continue
        mod = importlib.import_module(f"crypto_trader.evaluator.checks.{info.name}")
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseCheck)
                and attr is not BaseCheck
            ):
                found.append(attr())
    return found


def run_evaluation(
    *,
    checks: list[BaseCheck],
    ctx: EvalContext,
    trigger_reason: str,
) -> EvaluationReport:
    """Run all checks and aggregate into an EvaluationReport."""
    results = [check.run(ctx) for check in checks]

    if not results:
        return EvaluationReport(
            eval_id=f"eval-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(UTC).isoformat(),
            overall_grade=Grade.SKIP,
            overall_score=0.0,
            check_results=[],
            data_sources_used=[],
            trigger_reason=trigger_reason,
        )

    overall_grade = Grade.worst([r.grade for r in results])

    # Weighted average score, excluding SKIP
    scored = [(r, c.weight) for r, c in zip(results, checks, strict=True) if r.grade != Grade.SKIP]
    if scored:
        total_weight = sum(w for _, w in scored)
        overall_score = sum(r.score * w for r, w in scored) / total_weight
    else:
        overall_score = 0.0

    data_sources: list[str] = []
    for r in results:
        for key in r.metrics:
            if key not in data_sources:
                data_sources.append(key)

    return EvaluationReport(
        eval_id=f"eval-{uuid.uuid4().hex[:8]}",
        timestamp=datetime.now(UTC).isoformat(),
        overall_grade=overall_grade,
        overall_score=round(overall_score, 4),
        check_results=results,
        data_sources_used=data_sources,
        trigger_reason=trigger_reason,
    )
