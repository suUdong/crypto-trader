"""PreToolUse hook for Bash: run pytest before git commit.

Detects git commit/revert/cherry-pick/merge/am/rebase commands.
Blocks --no-verify flag unconditionally.
In normal mode: runs pytest and blocks commit on failure.
In dry-run mode (HARNESS_DRY_RUN=1): blocks with message.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

GIT_WRITE_SUBCOMMANDS = frozenset(
    ["commit", "revert", "cherry-pick", "merge", "am", "rebase"]
)


def _split_chained(command: str) -> list[str]:
    parts: list[str] = []
    normalised = command.replace("&&", ";").replace("|", ";")
    for part in normalised.split(";"):
        stripped = part.strip()
        if stripped:
            parts.append(stripped)
    return parts


def _unwrap_bash_c(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if len(tokens) >= 3 and tokens[0] in ("bash", "sh") and tokens[1] == "-c":
        return tokens[2]
    return None


def _detect_git_write(command: str) -> tuple[bool, str | None]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False, None

    if not tokens:
        return False, None

    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens = tokens[1:]

    if not tokens or tokens[0] != "git":
        return False, None

    idx = 1
    while idx < len(tokens) and tokens[idx] == "-c":
        idx += 2

    if idx >= len(tokens):
        return False, None

    subcommand = tokens[idx]
    if subcommand not in GIT_WRITE_SUBCOMMANDS:
        return False, None

    remaining = tokens[idx + 1:]
    for flag in remaining:
        if flag == "--no-verify":
            return True, "--no-verify flag is forbidden"
        if flag.startswith("-") and not flag.startswith("--") and "n" in flag[1:]:
            return True, "--no-verify flag is forbidden (short -n)"

    return True, None


def _check_command(command: str) -> tuple[bool, str | None]:
    inner = _unwrap_bash_c(command)
    if inner is not None:
        return _check_command(inner)

    for part in _split_chained(command):
        is_write, reason = _detect_git_write(part)
        if is_write:
            return True, reason

    return False, None


def _output(decision: str, reason_msg: str = "") -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            **({"permissionDecisionReason": reason_msg} if reason_msg else {}),
        }
    }
    print(json.dumps(out))
    sys.exit(0 if decision == "allow" else 2)


def main() -> None:
    raw_input = os.environ.get("TOOL_INPUT", "{}")
    dry_run = os.environ.get("HARNESS_DRY_RUN", "0") == "1"

    try:
        tool_input: dict = json.loads(raw_input)  # type: ignore[type-arg]
    except json.JSONDecodeError as exc:
        print(f"ERROR: Could not parse TOOL_INPUT: {exc}", file=sys.stderr)
        sys.exit(2)

    command: str = tool_input.get("command", "")
    is_blocked, reason = _check_command(command)

    if not is_blocked:
        _output("allow")

    if reason and "--no-verify" in reason:
        _output("deny", reason)

    if dry_run:
        _output("deny", "Commit detected — skipping pytest (dry-run mode)")

    result = subprocess.run(["pytest", "-x", "-q"], capture_output=False)
    if result.returncode != 0:
        _output("deny", "pytest failed — commit aborted")

    _output("allow")


if __name__ == "__main__":
    main()
