from __future__ import annotations

from crypto_trader.operator.research_summary import (
    build_poor_ids,
    build_promising_summary,
    build_quality_review_lines,
    build_quality_summary,
)


def test_build_quality_summary_formats_buckets() -> None:
    summary = build_quality_summary(
        [
            {"id": "a", "grade": "promising", "sharpe": 4.2},
            {"id": "b", "grade": "marginal", "sharpe": 1.1},
            {"id": "c", "grade": "poor", "sharpe": -0.2},
        ]
    )

    assert "✅ 유망 결과: a(Sharpe+4.20)" in summary
    assert "🔶 추가검증 필요: b(Sharpe+1.10)" in summary
    assert "🔻 엣지 부족 (재탐색 불필요): c" in summary


def test_build_promising_summary_uses_latest_promising_items() -> None:
    summary = build_promising_summary(
        [
            {"id": "a", "grade": "promising", "sharpe": 4.2, "reason": "ok"},
            {"id": "b", "grade": "poor", "sharpe": -0.1, "reason": "bad"},
        ]
    )

    assert "a: Sharpe +4.20 — ok" in summary


def test_build_poor_ids_and_review_lines() -> None:
    quality_log = [
        {"id": "a", "grade": "poor", "reason": "bad"},
        {"id": "b", "grade": "promising", "sharpe": 3.5, "reason": "good"},
    ]

    assert build_poor_ids(quality_log) == ["a"]
    assert build_quality_review_lines(quality_log) == "- b: Sharpe+3.50 (good)"
