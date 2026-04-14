from __future__ import annotations

from crypto_trader.operator.research_tasks import parse_new_task_markers


def test_parse_new_task_markers_extracts_valid_lines() -> None:
    tasks = parse_new_task_markers(
        """
noise
NEW_TASK id=task_a script=backtest_a.py desc=first task
NEW_TASK id=task_b script=backtest_b.py desc=second task
"""
    )

    assert tasks == [
        {
            "id": "task_a",
            "type": "backtest",
            "desc": "first task",
            "script": "backtest_a.py",
            "notify_on_significant": True,
        },
        {
            "id": "task_b",
            "type": "backtest",
            "desc": "second task",
            "script": "backtest_b.py",
            "notify_on_significant": True,
        },
    ]


def test_parse_new_task_markers_ignores_invalid_lines() -> None:
    tasks = parse_new_task_markers(
        """
NEW_TASK id=missing_script desc=bad
NEW_TASK script=missing_id.py desc=bad
"""
    )

    assert tasks == []
