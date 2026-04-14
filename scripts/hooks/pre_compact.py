"""PreCompact hook: update SESSION_HANDOFF.md with HEAD sha and timestamp.

Replaces **last_commit** and **updated_at** lines if present, preserves
all other content. Always exits 0 — soft fail if file missing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _get_head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_timestamp() -> str:
    kst = timezone(timedelta(hours=9))
    now = datetime.now(tz=kst)
    return now.strftime("%Y-%m-%dT%H:%M:%S+09:00")


def main() -> None:
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    handoff_path = project_dir / "SESSION_HANDOFF.md"

    if not handoff_path.exists():
        sys.exit(0)

    content = handoff_path.read_text(encoding="utf-8")

    sha = _get_head_sha()
    timestamp = _get_timestamp()

    content = re.sub(
        r"^\*\*last_commit\*\*:.*$",
        f"**last_commit**: {sha}",
        content,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r"^\*\*updated_at\*\*:.*$",
        f"**updated_at**: {timestamp}",
        content,
        flags=re.MULTILINE,
    )

    handoff_path.write_text(content, encoding="utf-8")

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": f"SESSION_HANDOFF.md updated: {sha} @ {timestamp}",
        }
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
