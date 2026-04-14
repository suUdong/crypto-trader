from __future__ import annotations

import json
from pathlib import Path

from crypto_trader.operator.research_state import (
    default_research_state,
    load_research_state,
    normalize_research_state,
    save_research_state,
    state_snapshot_for_save,
)


def test_default_research_state_shape() -> None:
    state = default_research_state()

    assert state == {
        "cycle": 0,
        "done": [],
        "last_run": None,
        "quality_log": [],
        "interval_last_run": {},
        "dynamic_tasks": [],
    }


def test_load_research_state_returns_defaults_for_missing_or_invalid(tmp_path: Path) -> None:
    missing = load_research_state(tmp_path / "missing.json")
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")
    invalid = load_research_state(invalid_path)

    assert missing == default_research_state()
    assert invalid == default_research_state()


def test_normalize_research_state_filters_and_coerces_values() -> None:
    normalized = normalize_research_state(
        {
            "cycle": 3,
            "done": ["a", 1],
            "last_run": "2026-04-11T00:00:00+00:00",
            "quality_log": [{"id": "x"}, "bad"],
            "interval_last_run": {"daily": "2026-04-11T00:00:00+00:00", 1: 2},
            "dynamic_tasks": [{"id": "dyn"}, "bad"],
        }
    )

    assert normalized["cycle"] == 3
    assert normalized["done"] == ["a", "1"]
    assert normalized["quality_log"] == [{"id": "x"}]
    assert normalized["interval_last_run"] == {"daily": "2026-04-11T00:00:00+00:00"}
    assert normalized["dynamic_tasks"] == [{"id": "dyn"}]


def test_state_snapshot_for_save_trims_logs_and_dynamic_tasks() -> None:
    state = default_research_state()
    state["quality_log"] = [{"id": str(i)} for i in range(55)]
    state["dynamic_tasks"] = [{"id": str(i)} for i in range(25)]

    snapshot = state_snapshot_for_save(state)

    assert len(snapshot["quality_log"]) == 50
    assert snapshot["quality_log"][0]["id"] == "5"
    assert len(snapshot["dynamic_tasks"]) == 20
    assert snapshot["dynamic_tasks"][0]["id"] == "5"


def test_save_research_state_writes_trimmed_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = default_research_state()
    state["cycle"] = 9
    state["quality_log"] = [{"id": str(i)} for i in range(55)]
    save_research_state(path, state)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["cycle"] == 9
    assert len(payload["quality_log"]) == 50
