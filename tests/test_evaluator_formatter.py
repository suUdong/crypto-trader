"""Tests for evaluator formatter (Opus + fallback)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from crypto_trader.evaluator.formatter import fallback_format, format_report
from crypto_trader.evaluator.models import CheckResult, EvaluationReport, Grade


def _make_report() -> EvaluationReport:
    return EvaluationReport(
        eval_id="eval-test123",
        timestamp="2026-04-13T12:00:00+00:00",
        overall_grade=Grade.WARN,
        overall_score=0.65,
        check_results=[
            CheckResult(
                check_name="backtest_quality",
                grade=Grade.PASS,
                score=0.82,
                findings=["n=86, Sharpe 유의"],
                metrics={"avg_n_trades": 86},
                suggestions=[],
            ),
            CheckResult(
                check_name="strategy_health",
                grade=Grade.WARN,
                score=0.5,
                findings=["w1(momentum): MDD 12%"],
                metrics={},
                suggestions=["파라미터 재검토"],
            ),
        ],
        data_sources_used=["backtest_history.md", "checkpoint"],
        trigger_reason="file_change:strategy_research.state.json",
    )


class TestFallbackFormat(unittest.TestCase):
    def test_contains_eval_id(self) -> None:
        report = _make_report()
        text = fallback_format(report)
        self.assertIn("eval-test123", text)

    def test_contains_grade(self) -> None:
        report = _make_report()
        text = fallback_format(report)
        self.assertIn("warn", text)

    def test_contains_check_names(self) -> None:
        report = _make_report()
        text = fallback_format(report)
        self.assertIn("backtest_quality", text)
        self.assertIn("strategy_health", text)


class TestFormatReport(unittest.TestCase):
    @patch("crypto_trader.evaluator.formatter._call_opus")
    def test_uses_opus_when_available(self, mock_opus: unittest.mock.MagicMock) -> None:
        mock_opus.return_value = (
            '```json\n{"telegram_summary": "test summary", '
            '"detailed_summary": "detailed"}\n```'
        )
        report = _make_report()
        result = format_report(report)
        self.assertEqual(result.telegram_summary, "test summary")
        mock_opus.assert_called_once()

    @patch("crypto_trader.evaluator.formatter._call_opus")
    def test_falls_back_on_opus_failure(
        self, mock_opus: unittest.mock.MagicMock
    ) -> None:
        mock_opus.return_value = None
        report = _make_report()
        result = format_report(report)
        self.assertIn("eval-test123", result.telegram_summary)

    def test_format_report_dry_run(self) -> None:
        report = _make_report()
        result = format_report(report, dry_run=True)
        self.assertIn("eval-test123", result.telegram_summary)


if __name__ == "__main__":
    unittest.main()
