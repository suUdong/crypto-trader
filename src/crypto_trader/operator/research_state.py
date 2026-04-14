from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict, cast

from crypto_trader.operator.research_tasks import ResearchTask


class ResearchLoopState(TypedDict):
    cycle: int
    done: list[str]
    last_run: str | None
    quality_log: list[dict[str, Any]]
    interval_last_run: dict[str, str]
    dynamic_tasks: list[ResearchTask]


def default_research_state() -> ResearchLoopState:
    return {
        "cycle": 0,
        "done": [],
        "last_run": None,
        "quality_log": [],
        "interval_last_run": {},
        "dynamic_tasks": [],
    }


def normalize_research_state(raw: dict[str, Any] | None) -> ResearchLoopState:
    state = default_research_state()
    if raw is None:
        return state
    cycle = raw.get("cycle")
    state["cycle"] = int(cycle) if isinstance(cycle, int | float) else 0
    done = raw.get("done")
    if isinstance(done, list):
        state["done"] = [str(item) for item in done]
    last_run = raw.get("last_run")
    state["last_run"] = str(last_run) if isinstance(last_run, str) else None
    quality_log = raw.get("quality_log")
    if isinstance(quality_log, list):
        state["quality_log"] = [item for item in quality_log if isinstance(item, dict)]
    interval_last_run = raw.get("interval_last_run")
    if isinstance(interval_last_run, dict):
        state["interval_last_run"] = {
            str(key): str(value)
            for key, value in interval_last_run.items()
            if isinstance(key, str) and isinstance(value, str)
        }
    dynamic_tasks = raw.get("dynamic_tasks")
    if isinstance(dynamic_tasks, list):
        state["dynamic_tasks"] = [
            cast(ResearchTask, item)
            for item in dynamic_tasks
            if isinstance(item, dict)
        ]
    return state


def load_research_state(path: Path) -> ResearchLoopState:
    if not path.exists():
        return default_research_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_research_state()
    if not isinstance(raw, dict):
        return default_research_state()
    return normalize_research_state(raw)


def state_snapshot_for_save(state: ResearchLoopState) -> ResearchLoopState:
    return {
        "cycle": state["cycle"],
        "done": state["done"],
        "last_run": state["last_run"],
        "quality_log": state.get("quality_log", [])[-50:],
        "interval_last_run": state.get("interval_last_run", {}),
        "dynamic_tasks": state.get("dynamic_tasks", [])[-20:],
    }


def save_research_state(path: Path, state: ResearchLoopState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = state_snapshot_for_save(state)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
