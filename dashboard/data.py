"""Load artifact JSON/JSONL/MD files for the dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"


def _load_json(filename: str) -> dict[str, Any] | None:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _load_jsonl(filename: str) -> list[dict[str, Any]]:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _load_md(filename: str) -> str | None:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def load_checkpoint() -> dict[str, Any] | None:
    return _load_json("runtime-checkpoint.json")


def load_positions() -> dict[str, Any] | None:
    return _load_json("positions.json")


def load_health() -> dict[str, Any] | None:
    return _load_json("health.json")


def load_regime_report() -> dict[str, Any] | None:
    return _load_json("regime-report.json")


def load_drift_report() -> dict[str, Any] | None:
    return _load_json("drift-report.json")


def load_promotion_gate() -> dict[str, Any] | None:
    return _load_json("promotion-gate.json")


def load_drift_calibration() -> dict[str, Any] | None:
    return _load_json("drift-calibration.json")


def load_backtest_baseline() -> dict[str, Any] | None:
    return _load_json("backtest-baseline.json")


def load_daily_performance() -> dict[str, Any] | None:
    return _load_json("daily-performance.json")


def load_strategy_runs() -> list[dict[str, Any]]:
    return _load_jsonl("strategy-runs.jsonl")


def load_daily_memo() -> str | None:
    return _load_md("daily-memo.md")


def load_operator_report() -> str | None:
    return _load_md("operator-report.md")
