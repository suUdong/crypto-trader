"""SessionStart hook: inject SESSION_HANDOFF.md into Claude session context.

Reads SESSION_HANDOFF.md, appends recent git commits, outputs JSON in
Claude Code hook format. Always exits 0 — soft fail if handoff missing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _read_handoff(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _get_recent_commits() -> str:
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "(git log failed)"
    except Exception:
        return "(git log unavailable)"


def main() -> None:
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    handoff_path = project_dir / "SESSION_HANDOFF.md"

    handoff_content = _read_handoff(handoff_path)

    if handoff_content:
        commits = _get_recent_commits()
        context = (
            "# Session Handoff\n\n"
            "**INSTRUCTION**: 사용자의 첫 메시지가 `ㄱ`이면 "
            "반드시 아래 루틴을 먼저 실행할 것:\n"
            "1. handoff 내용을 3-5줄로 요약 "
            "(실행 상태, 핵심 결과, 다음 할 일 포함)\n"
            "2. '무엇을 하시겠습니까?' 라고 물어볼 것\n\n"
            f"{handoff_content}\n\n--- Recent commits ---\n{commits}"
        )
    else:
        context = f"No handoff file found at {handoff_path}."

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
