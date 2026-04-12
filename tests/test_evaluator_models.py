"""Tests for evaluator data models."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.models import (
    CheckResult,
    EvalContext,
    EvaluationReport,
    Grade,
)


class TestGrade(unittest.TestCase):
    def test_grade_values(self) -> None:
        self.assertEqual(Grade.PASS, "pass")
        self.assertEqual(Grade.WARN, "warn")
        self.assertEqual(Grade.FAIL, "fail")
        self.assertEqual(Grade.SKIP, "skip")

    def test_grade_ordering(self) -> None:
        grades = [Grade.PASS, Grade.FAIL, Grade.WARN, Grade.SKIP]
        worst = Grade.worst(grades)
        self.assertEqual(worst, Grade.FAIL)

    def test_grade_worst_skip_only(self) -> None:
        self.assertEqual(Grade.worst([Grade.SKIP]), Grade.SKIP)

    def test_grade_worst_empty(self) -> None:
        self.assertEqual(Grade.worst([]), Grade.SKIP)


class TestCheckResult(unittest.TestCase):
    def test_create(self) -> None:
        result = CheckResult(
            check_name="test_check",
            grade=Grade.PASS,
            score=0.85,
            findings=["all good"],
            metrics={"sharpe": 7.5},
            suggestions=[],
        )
        self.assertEqual(result.check_name, "test_check")
        self.assertEqual(result.grade, Grade.PASS)
        self.assertAlmostEqual(result.score, 0.85)

    def test_to_dict(self) -> None:
        result = CheckResult(
            check_name="test_check",
            grade=Grade.WARN,
            score=0.5,
            findings=["needs attention"],
            metrics={"n_trades": 20},
            suggestions=["increase sample size"],
        )
        d = result.to_dict()
        self.assertEqual(d["check_name"], "test_check")
        self.assertEqual(d["grade"], "warn")
        self.assertIsInstance(d["metrics"], dict)


class TestEvalContext(unittest.TestCase):
    def test_create_minimal(self) -> None:
        ctx = EvalContext(
            backtest_history_tail="",
            daemon_strategies=[],
            daemon_config_path=None,
            research_state=None,
            market_scan_state=None,
            checkpoint=None,
            journal_trades=[],
            prev_report=None,
        )
        self.assertEqual(ctx.daemon_strategies, [])
        self.assertIsNone(ctx.checkpoint)


class TestEvaluationReport(unittest.TestCase):
    def test_create(self) -> None:
        cr = CheckResult(
            check_name="test",
            grade=Grade.PASS,
            score=0.9,
            findings=[],
            metrics={},
            suggestions=[],
        )
        report = EvaluationReport(
            eval_id="eval-test",
            timestamp="2026-04-13T00:00:00+00:00",
            overall_grade=Grade.PASS,
            overall_score=0.9,
            check_results=[cr],
            data_sources_used=["backtest_history.md"],
            trigger_reason="manual",
        )
        self.assertEqual(report.eval_id, "eval-test")
        self.assertEqual(len(report.check_results), 1)

    def test_to_dict(self) -> None:
        cr = CheckResult(
            check_name="test",
            grade=Grade.WARN,
            score=0.5,
            findings=["f1"],
            metrics={"k": 1},
            suggestions=[],
        )
        report = EvaluationReport(
            eval_id="eval-abc",
            timestamp="2026-04-13T00:00:00+00:00",
            overall_grade=Grade.WARN,
            overall_score=0.5,
            check_results=[cr],
            data_sources_used=["test"],
            trigger_reason="scheduled",
        )
        d = report.to_dict()
        self.assertEqual(d["schema_version"], 2)
        self.assertEqual(d["overall_grade"], "warn")
        self.assertIsInstance(d["check_results"], list)


if __name__ == "__main__":
    unittest.main()
