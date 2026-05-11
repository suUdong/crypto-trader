#!/usr/bin/env python3
"""Run preflight_check against the current config and print a human report.

Operator pre-cutover helper — see docs/2026-05-11-ct-live-migration.md §2.
Exit code: 0 when no ERROR issues, 1 otherwise. Warnings never fail.

Usage:
    PYTHONPATH=src python3 scripts/preflight_live_check.py
    PYTHONPATH=src python3 scripts/preflight_live_check.py --config config/daemon.toml
    PYTHONPATH=src python3 scripts/preflight_live_check.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from crypto_trader.config import load_config, preflight_check  # noqa: E402


def run(config_path: str) -> tuple[int, list[dict[str, str]]]:
    config = load_config(config_path, allow_missing_live_credentials=True)
    issues = preflight_check(config)
    payload = [{"level": lvl, "message": msg} for lvl, msg in issues]
    exit_code = 1 if any(lvl == "ERROR" for lvl, _ in issues) else 0
    return exit_code, payload


def format_human(
    config_path: str,
    payload: list[dict[str, str]],
    *,
    exit_code: int,
) -> str:
    lines: list[str] = []
    lines.append(f"Preflight check :: {config_path}")
    lines.append("=" * 60)
    if not payload:
        lines.append("OK — no issues reported.")
    else:
        for item in payload:
            mark = "ERROR" if item["level"] == "ERROR" else "WARN "
            lines.append(f"[{mark}] {item['message']}")
    lines.append("=" * 60)
    lines.append("READY for live cutover." if exit_code == 0 else "BLOCKED — fix ERROR rows above.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-cutover preflight check")
    parser.add_argument("--config", default="config/daemon.toml", help="TOML config path")
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON only (suitable for piping)"
    )
    args = parser.parse_args()

    exit_code, payload = run(args.config)
    if args.json:
        print(json.dumps({"exit_code": exit_code, "issues": payload}, indent=2))
    else:
        print(format_human(args.config, payload, exit_code=exit_code))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
