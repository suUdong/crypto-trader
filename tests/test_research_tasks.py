from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_trader.operator.research_tasks import (
    DEFAULT_RESEARCH_PIPELINE,
    interval_task_due,
    pick_next_research_task,
)


def test_default_pipeline_starts_with_gpu_scan_task() -> None:
    assert DEFAULT_RESEARCH_PIPELINE[0]["id"] == "stealth_sol_sweep"
    assert DEFAULT_RESEARCH_PIPELINE[0]["requires_torch"] is True


def test_pick_next_research_task_prefers_non_interval_tasks() -> None:
    task = pick_next_research_task(
        DEFAULT_RESEARCH_PIPELINE,
        done_ids={
            "stealth_sol_sweep",
            "truth_seeker_sweep",
            "vpin_eth_grid",
            "momentum_sol_grid",
            "regime_stealth",
            "alpha_backtest",
            "strategy_tournament",
            "btc_dip_recovery",
            "btc_dip_alt_entry",
        },
        torch_available=True,
        interval_last_run={},
        now=datetime(2026, 4, 11, tzinfo=UTC),
    )

    assert task is not None
    assert task["id"] == "new_strategy_hypothesis"


def test_pick_next_research_task_skips_torch_tasks_when_unavailable() -> None:
    task = pick_next_research_task(
        DEFAULT_RESEARCH_PIPELINE,
        done_ids=set(),
        torch_available=False,
        interval_last_run={},
        now=datetime(2026, 4, 11, tzinfo=UTC),
    )

    assert task is not None
    assert task["id"] == "truth_seeker_sweep"


def test_pick_next_research_task_returns_due_interval_after_normal_tasks() -> None:
    now = datetime(2026, 4, 11, 12, tzinfo=UTC)
    done_ids = {
        task["id"]
        for task in DEFAULT_RESEARCH_PIPELINE
        if task["id"] != "daily_quality_review"
    }

    task = pick_next_research_task(
        DEFAULT_RESEARCH_PIPELINE,
        done_ids=done_ids,
        torch_available=True,
        interval_last_run={
            "daily_quality_review": (now - timedelta(hours=25)).isoformat()
        },
        now=now,
    )

    assert task is not None
    assert task["id"] == "daily_quality_review"


def test_pick_next_research_task_honors_dynamic_tasks() -> None:
    tasks = list(DEFAULT_RESEARCH_PIPELINE) + [
        {
            "id": "dynamic_followup",
            "type": "backtest",
            "desc": "followup",
            "script": "backtest_followup.py",
        }
    ]

    task = pick_next_research_task(
        tasks,
        done_ids={item["id"] for item in DEFAULT_RESEARCH_PIPELINE},
        torch_available=True,
        interval_last_run={},
        now=datetime(2026, 4, 11, tzinfo=UTC),
    )

    assert task is not None
    assert task["id"] == "dynamic_followup"


def test_interval_task_due_checks_elapsed_hours() -> None:
    task = {
        "id": "daily_quality_review",
        "interval_hours": 24,
    }
    now = datetime(2026, 4, 11, 12, tzinfo=UTC)

    assert interval_task_due(task, {}, now=now) is True
    assert interval_task_due(
        task,
        {"daily_quality_review": (now - timedelta(hours=23)).isoformat()},
        now=now,
    ) is False
    assert interval_task_due(
        task,
        {"daily_quality_review": (now - timedelta(hours=24)).isoformat()},
        now=now,
    ) is True
