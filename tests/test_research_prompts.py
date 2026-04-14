from __future__ import annotations

from crypto_trader.operator.research_prompts import (
    build_followup_prompt,
    build_hypothesis_prompt,
    build_quality_review_prompt,
    build_replenish_prompt,
)


def test_build_hypothesis_prompt_includes_summary_and_history() -> None:
    prompt = build_hypothesis_prompt("quality-summary", "history-tail")

    assert "quality-summary" in prompt
    assert "history-tail" in prompt
    assert "예상 스크립트" in prompt


def test_build_followup_prompt_includes_task_result_context() -> None:
    prompt = build_followup_prompt(
        task_desc="task",
        sharpe=4.2,
        raw_tail="raw-output",
        history_tail="history-tail",
        python_path=".venv/bin/python",
    )

    assert "task" in prompt
    assert "+4.200" in prompt
    assert "raw-output" in prompt
    assert ".venv/bin/python" in prompt


def test_build_replenish_prompt_includes_done_and_poor_ids() -> None:
    prompt = build_replenish_prompt(
        promising_summary="promising",
        done_ids=["a", "b"],
        poor_ids=["x"],
        history_tail="history-tail",
        python_path=".venv/bin/python",
    )

    assert "promising" in prompt
    assert "a, b" in prompt
    assert "x" in prompt
    assert "history-tail" in prompt


def test_build_quality_review_prompt_includes_stats_and_promising_lines() -> None:
    prompt = build_quality_review_prompt(
        stats={"promising": 2, "marginal": 1, "poor": 3, "error": 0},
        promising_lines="- task_a",
        history_tail="history-tail",
    )

    assert "promising: 2개" in prompt
    assert "- task_a" in prompt
    assert "history-tail" in prompt
