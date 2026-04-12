"""Data models for the strategy evaluator v2 pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class Grade(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

    @staticmethod
    def worst(grades: list[Grade]) -> Grade:
        """Return the worst grade from a list. FAIL > WARN > SKIP > PASS."""
        if not grades:
            return Grade.SKIP
        priority = {Grade.FAIL: 3, Grade.WARN: 2, Grade.SKIP: 1, Grade.PASS: 0}
        return max(grades, key=lambda g: priority[g])


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    grade: Grade
    score: float  # 0.0 ~ 1.0
    findings: list[str]
    metrics: dict[str, Any]
    suggestions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "grade": self.grade.value,
            "score": self.score,
            "findings": list(self.findings),
            "metrics": dict(self.metrics),
            "suggestions": list(self.suggestions),
        }


@dataclass
class EvalContext:
    backtest_history_tail: str
    daemon_strategies: list[str]
    daemon_config_path: Path | None
    research_state: dict[str, Any] | None
    market_scan_state: dict[str, Any] | None
    checkpoint: dict[str, Any] | None
    journal_trades: list[dict[str, Any]]
    prev_report: EvaluationReport | None


@dataclass
class EvaluationReport:
    eval_id: str
    timestamp: str
    overall_grade: Grade
    overall_score: float
    check_results: list[CheckResult]
    data_sources_used: list[str]
    trigger_reason: str
    summary_for_human: str = ""
    telegram_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "generated_at": self.timestamp,
            "eval_id": self.eval_id,
            "trigger_reason": self.trigger_reason,
            "overall_grade": self.overall_grade.value,
            "overall_score": self.overall_score,
            "check_results": [cr.to_dict() for cr in self.check_results],
            "data_sources_used": self.data_sources_used,
            "summary_for_human": self.summary_for_human,
            "telegram_summary": self.telegram_summary,
        }
