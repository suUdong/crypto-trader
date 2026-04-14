from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.operator.research_quality import (
    format_history_entry,
    grade_emoji,
    parse_research_result,
    quality_check_backtest,
    quality_check_hypothesis,
)


def test_parse_research_result_uses_best_sharpe_and_metrics() -> None:
    result = parse_research_result(
        """
Sharpe: +1.20
WR: 44.0%
trades: 12
avg: 0.4%
Sharpe: +3.40
WR: 61.5%
trades: 33
avg: 1.2%
"""
    )

    assert result["best_sharpe"] == 3.4
    assert result["best_wr"] == 61.5
    assert result["total_trades"] == 33
    assert result["avg_pct"] == 1.2


def test_parse_research_result_falls_back_to_edge_when_sharpe_missing() -> None:
    result = parse_research_result("Edge: +2.15%\nWR: 55%\ntrades: 30")

    assert result["best_sharpe"] == 2.15
    assert result["best_wr"] == 55.0
    assert result["total_trades"] == 30


def test_quality_check_backtest_classifies_promising_and_low_trade_count() -> None:
    promising = quality_check_backtest(
        {
            "best_sharpe": 4.2,
            "best_wr": 61.0,
            "total_trades": 35,
            "avg_pct": 1.1,
            "raw_tail": "Sharpe: +4.2",
        }
    )
    poor = quality_check_backtest(
        {
            "best_sharpe": 9.0,
            "best_wr": 70.0,
            "total_trades": 12,
            "avg_pct": 3.0,
            "raw_tail": "Sharpe: +9.0",
        }
    )

    assert promising["grade"] == "promising"
    assert poor["grade"] == "poor"
    assert "거래 수 부족" in poor["reason"]


def test_quality_check_backtest_detects_error_patterns() -> None:
    verdict = quality_check_backtest(
        {
            "best_sharpe": None,
            "best_wr": None,
            "total_trades": None,
            "avg_pct": None,
            "raw_tail": "Traceback (most recent call last)",
        }
    )

    assert verdict["grade"] == "error"


def test_quality_check_hypothesis_rejects_short_or_error_text() -> None:
    assert quality_check_hypothesis("ImportError happened")["grade"] == "error"
    assert quality_check_hypothesis("too short")["grade"] == "error"
    assert quality_check_hypothesis("정상 응답입니다. " * 10)["grade"] == "ok"


def test_format_history_entry_renders_expected_markdown() -> None:
    entry = format_history_entry(
        {"id": "task_a", "desc": "테스트 전략"},
        {
            "best_sharpe": 3.2,
            "best_wr": 55.0,
            "total_trades": 40,
            "avg_pct": 0.8,
            "raw_tail": "Sharpe: +3.2",
        },
        note="메모",
        grade="promising",
        now=datetime(2026, 4, 11, 0, 0, tzinfo=UTC),
    )

    assert "테스트 전략" in entry
    assert "[ralph:task_a]" in entry
    assert "🌟[promising]" in entry
    assert "**메모**: 메모" in entry
    assert "Sharpe: +3.2" in entry
    assert grade_emoji("ok") == "✅"
