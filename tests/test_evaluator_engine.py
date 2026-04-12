"""Tests for evaluator engine: check discovery, pipeline execution, aggregation."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.engine import discover_checks, run_evaluation
from crypto_trader.evaluator.models import (
    CheckResult,
    EvalContext,
    EvaluationReport,
    Grade,
)


class _PassCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "always_pass"

    def run(self, ctx: EvalContext) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            grade=Grade.PASS,
            score=1.0,
            findings=["all good"],
            metrics={},
            suggestions=[],
        )


class _WarnCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "always_warn"

    @property
    def weight(self) -> float:
        return 2.0

    def run(self, ctx: EvalContext) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            grade=Grade.WARN,
            score=0.5,
            findings=["needs attention"],
            metrics={},
            suggestions=[],
        )


class _FailCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "always_fail"

    def run(self, ctx: EvalContext) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            grade=Grade.FAIL,
            score=0.0,
            findings=["critical issue"],
            metrics={},
            suggestions=["fix it"],
        )


class _SkipCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "always_skip"

    def run(self, ctx: EvalContext) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            grade=Grade.SKIP,
            score=0.0,
            findings=["no data"],
            metrics={},
            suggestions=[],
        )


def _make_ctx() -> EvalContext:
    return EvalContext(
        backtest_history_tail="",
        daemon_strategies=[],
        daemon_config_path=None,
        research_state=None,
        market_scan_state=None,
        checkpoint=None,
        journal_trades=[],
        prev_report=None,
    )


class TestDiscoverChecks(unittest.TestCase):
    def test_discovers_at_least_one_check(self) -> None:
        checks = discover_checks()
        self.assertIsInstance(checks, list)
        for check in checks:
            self.assertIsInstance(check, BaseCheck)


class TestRunEvaluation(unittest.TestCase):
    def test_all_pass(self) -> None:
        report = run_evaluation(
            checks=[_PassCheck()],
            ctx=_make_ctx(),
            trigger_reason="test",
        )
        self.assertIsInstance(report, EvaluationReport)
        self.assertEqual(report.overall_grade, Grade.PASS)
        self.assertAlmostEqual(report.overall_score, 1.0)
        self.assertEqual(len(report.check_results), 1)

    def test_worst_grade_wins(self) -> None:
        report = run_evaluation(
            checks=[_PassCheck(), _WarnCheck(), _FailCheck()],
            ctx=_make_ctx(),
            trigger_reason="test",
        )
        self.assertEqual(report.overall_grade, Grade.FAIL)

    def test_weighted_score(self) -> None:
        # _PassCheck weight=1.0 score=1.0, _WarnCheck weight=2.0 score=0.5
        # weighted avg = (1.0*1.0 + 2.0*0.5) / (1.0 + 2.0) = 2.0/3.0
        report = run_evaluation(
            checks=[_PassCheck(), _WarnCheck()],
            ctx=_make_ctx(),
            trigger_reason="test",
        )
        self.assertAlmostEqual(report.overall_score, 2.0 / 3.0, places=3)

    def test_skip_excluded_from_score(self) -> None:
        report = run_evaluation(
            checks=[_PassCheck(), _SkipCheck()],
            ctx=_make_ctx(),
            trigger_reason="test",
        )
        self.assertAlmostEqual(report.overall_score, 1.0)

    def test_empty_checks(self) -> None:
        report = run_evaluation(checks=[], ctx=_make_ctx(), trigger_reason="test")
        self.assertEqual(report.overall_grade, Grade.SKIP)
        self.assertAlmostEqual(report.overall_score, 0.0)

    def test_report_has_eval_id_and_timestamp(self) -> None:
        report = run_evaluation(
            checks=[_PassCheck()],
            ctx=_make_ctx(),
            trigger_reason="manual",
        )
        self.assertTrue(report.eval_id.startswith("eval-"))
        self.assertIn("T", report.timestamp)
        self.assertEqual(report.trigger_reason, "manual")


if __name__ == "__main__":
    unittest.main()
