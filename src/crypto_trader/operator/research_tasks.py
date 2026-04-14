from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TypedDict


class ResearchTask(TypedDict, total=False):
    id: str
    type: str
    desc: str
    script: str
    requires_torch: bool
    notify_on_significant: bool
    notify: bool
    interval_hours: int


DEFAULT_RESEARCH_PIPELINE: list[ResearchTask] = [
    {
        "id": "stealth_sol_sweep",
        "type": "backtest",
        "desc": "stealth_3gate 전체 마켓 스캔 (GPU)",
        "script": "backtest_stealth_deep.py",
        "requires_torch": True,
        "notify_on_significant": True,
    },
    {
        "id": "truth_seeker_sweep",
        "type": "backtest",
        "desc": "TruthSeeker 전략 파라미터 스윕",
        "script": "backtest_truth_seeker.py",
        "notify_on_significant": True,
    },
    {
        "id": "vpin_eth_grid",
        "type": "backtest",
        "desc": "vpin_eth 파라미터 그리드",
        "script": "backtest_vpin_eth_grid.py",
        "notify_on_significant": True,
    },
    {
        "id": "momentum_sol_grid",
        "type": "backtest",
        "desc": "momentum_sol 파라미터 그리드",
        "script": "backtest_momentum_sol_grid.py",
        "notify_on_significant": True,
    },
    {
        "id": "regime_stealth",
        "type": "backtest",
        "desc": "BTC 레짐 + 스텔스 2-Factor 백테스트",
        "script": "backtest_regime_stealth.py",
        "notify_on_significant": True,
    },
    {
        "id": "alpha_backtest",
        "type": "backtest",
        "desc": "GPU Alpha filter 백테스트",
        "script": "backtest_alpha_filter.py",
        "requires_torch": True,
        "notify_on_significant": True,
    },
    {
        "id": "strategy_tournament",
        "type": "backtest",
        "desc": "GPU Strategy Tournament",
        "script": "gpu_tournament.py",
        "notify_on_significant": True,
    },
    {
        "id": "btc_dip_recovery",
        "type": "backtest",
        "desc": "BTC 급락+acc≈1.0 → 48h 회복 패턴",
        "script": "backtest_btc_dip_recovery.py",
        "notify_on_significant": True,
    },
    {
        "id": "btc_dip_alt_entry",
        "type": "backtest",
        "desc": "BTC 급락 후 알트 진입 전략 (LINK/ADA/XRP)",
        "script": "backtest_btc_dip_alt_entry.py",
        "notify_on_significant": True,
    },
    {
        "id": "new_strategy_hypothesis",
        "type": "hypothesis",
        "desc": "Claude 신규 전략 가설 생성",
        "notify": True,
    },
    {
        "id": "daily_quality_review",
        "type": "quality_review",
        "desc": "Claude 품질/방향성 일일 리뷰",
        "notify": True,
        "interval_hours": 24,
    },
]

_NEW_TASK_RE = re.compile(r"NEW_TASK\s+id=(\S+)\s+script=(\S+\.py)\s+desc=(.+)")


def interval_task_due(
    task: ResearchTask,
    interval_last_run: dict[str, str],
    *,
    now: datetime | None = None,
) -> bool:
    interval_h = task.get("interval_hours")
    if interval_h is None:
        return False
    last = interval_last_run.get(task["id"])
    if last is None:
        return True
    current_time = now or datetime.now(UTC)
    elapsed = (current_time - datetime.fromisoformat(last)).total_seconds() / 3600
    return elapsed >= interval_h


def pick_next_research_task(
    tasks: list[ResearchTask],
    *,
    done_ids: set[str],
    torch_available: bool,
    interval_last_run: dict[str, str],
    now: datetime | None = None,
) -> ResearchTask | None:
    for task in tasks:
        if task.get("interval_hours"):
            continue
        if task["id"] in done_ids:
            continue
        if task.get("requires_torch") and not torch_available:
            continue
        return task

    for task in tasks:
        if task.get("interval_hours") and interval_task_due(
            task,
            interval_last_run,
            now=now,
        ):
            return task
    return None


def parse_new_task_markers(output: str) -> list[ResearchTask]:
    tasks: list[ResearchTask] = []
    for line in output.splitlines():
        match = _NEW_TASK_RE.match(line.strip())
        if not match:
            continue
        task_id, script, desc = match.group(1), match.group(2), match.group(3).strip()
        tasks.append(
            {
                "id": task_id,
                "type": "backtest",
                "desc": desc,
                "script": script,
                "notify_on_significant": True,
            }
        )
    return tasks
