from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast


@dataclass(frozen=True)
class ServiceStatus:
    loaded: bool
    active_state: str
    main_pid: int | None


@dataclass(frozen=True)
class WatchdogAssessment:
    healthy: bool
    reason: str
    matching_pids: tuple[int, ...]
    stray_pids: tuple[int, ...]
    heartbeat_pid: int | None
    heartbeat_age_seconds: float | None


def _assessment(
    healthy: bool,
    reason: str,
    matching_pids: tuple[int, ...],
    stray_pids: tuple[int, ...],
    heartbeat_pid: int | None,
    heartbeat_age_seconds: float | None,
) -> WatchdogAssessment:
    return WatchdogAssessment(
        healthy=healthy,
        reason=reason,
        matching_pids=matching_pids,
        stray_pids=stray_pids,
        heartbeat_pid=heartbeat_pid,
        heartbeat_age_seconds=heartbeat_age_seconds,
    )


def _parse_process_rows(stdout: str, config_path: str) -> tuple[int, ...]:
    matches: list[int] = []
    needle = f"--config {config_path}"
    for raw in stdout.splitlines():
        entry = raw.strip()
        if not entry:
            continue
        pid_text, _, args = entry.partition(" ")
        if not pid_text.isdigit():
            continue
        if "run-multi" not in args or needle not in args:
            continue
        matches.append(int(pid_text))
    return tuple(matches)


def find_matching_daemon_pids(config_path: str) -> tuple[int, ...]:
    ps = subprocess.run(
        ["ps", "-eo", "pid=,args="],
        check=True,
        capture_output=True,
        text=True,
    )
    return _parse_process_rows(ps.stdout, config_path)


def _parse_heartbeat_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def evaluate_watchdog(
    *,
    matching_pids: tuple[int, ...],
    heartbeat: dict[str, object] | None,
    config_path: str,
    heartbeat_max_age_seconds: int,
    now: datetime,
    service_main_pid: int | None,
    service_active: bool,
) -> WatchdogAssessment:
    heartbeat_pid_raw = None if heartbeat is None else heartbeat.get("pid")
    heartbeat_pid = heartbeat_pid_raw if isinstance(heartbeat_pid_raw, int) else None
    heartbeat_dt = (
        None if heartbeat is None else _parse_heartbeat_timestamp(heartbeat.get("last_heartbeat"))
    )
    heartbeat_age_seconds = (
        None
        if heartbeat_dt is None
        else max(0.0, (now.astimezone(UTC) - heartbeat_dt).total_seconds())
    )
    expected_pid = service_main_pid if service_main_pid and service_main_pid > 0 else None
    if expected_pid is not None:
        stray_pids = tuple(pid for pid in matching_pids if pid != expected_pid)
    elif service_active:
        stray_pids = ()
    elif heartbeat_pid is not None:
        stray_pids = tuple(pid for pid in matching_pids if pid != heartbeat_pid)
    else:
        stray_pids = matching_pids[1:] if len(matching_pids) > 1 else ()

    if not matching_pids:
        return _assessment(
            False,
            "process_missing",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if heartbeat is None:
        return _assessment(
            False,
            "heartbeat_missing",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if heartbeat.get("config_path") != config_path:
        return _assessment(
            False,
            "heartbeat_config_mismatch",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if heartbeat_age_seconds is None:
        return _assessment(
            False,
            "heartbeat_timestamp_invalid",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if heartbeat_age_seconds > heartbeat_max_age_seconds:
        return _assessment(
            False,
            "heartbeat_stale",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if service_active and expected_pid is None:
        return _assessment(
            False,
            "systemd_main_pid_unknown",
            matching_pids,
            (),
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if expected_pid is not None and expected_pid not in matching_pids:
        return _assessment(
            False,
            "systemd_main_pid_missing",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if heartbeat_pid is None or heartbeat_pid not in matching_pids:
        return _assessment(
            False,
            "heartbeat_pid_not_running",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if expected_pid is not None and heartbeat_pid != expected_pid:
        return _assessment(
            False,
            "heartbeat_pid_mismatch",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    if stray_pids:
        return _assessment(
            False,
            "duplicate_daemons",
            matching_pids,
            stray_pids,
            heartbeat_pid,
            heartbeat_age_seconds,
        )
    return _assessment(
        True,
        "healthy",
        matching_pids,
        (),
        heartbeat_pid,
        heartbeat_age_seconds,
    )


def _read_heartbeat(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return cast(dict[str, object], payload) if isinstance(payload, dict) else None


def _read_service_status(unit: str) -> ServiceStatus:
    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            unit,
            "-p",
            "LoadState",
            "-p",
            "ActiveState",
            "-p",
            "MainPID",
            "--value",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ServiceStatus(False, "unknown", None)
    lines = [line.strip() for line in result.stdout.splitlines()]
    while len(lines) < 3:
        lines.append("")
    load_state, active_state, main_pid_text = lines[:3]
    main_pid = int(main_pid_text) if main_pid_text.isdigit() and int(main_pid_text) > 0 else None
    return ServiceStatus(
        load_state not in {"", "not-found"},
        active_state or "unknown",
        main_pid,
    )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_stray_pids(pids: tuple[int, ...], config_path: str) -> None:
    if not pids:
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            continue
    deadline = time.monotonic() + 10
    remaining = set(pids)
    while remaining and time.monotonic() < deadline:
        time.sleep(1)
        remaining = {pid for pid in remaining if _pid_exists(pid)}
    current_matches = set(find_matching_daemon_pids(config_path))
    for pid in sorted(remaining):
        if pid not in current_matches:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            continue


def _systemd_action(service_status: ServiceStatus) -> str:
    if service_status.active_state in {"active", "activating", "reloading"}:
        return "restart"
    return "start"


def _run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Heartbeat-aware daemon watchdog.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--config", default="config/daemon.toml")
    parser.add_argument("--systemd-unit", default="crypto-trader.service")
    parser.add_argument("--heartbeat-max-age-seconds", type=int, default=240)
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).resolve()
    heartbeat_path = project_dir / "artifacts" / "daemon-heartbeat.json"
    restart_script = project_dir / "scripts" / "restart_daemon.sh"

    def load_assessment() -> tuple[ServiceStatus, WatchdogAssessment, str]:
        service_status = _read_service_status(args.systemd_unit)
        matching_pids = find_matching_daemon_pids(args.config)
        heartbeat = _read_heartbeat(heartbeat_path)
        assessment = evaluate_watchdog(
            matching_pids=matching_pids,
            heartbeat=heartbeat,
            config_path=args.config,
            heartbeat_max_age_seconds=args.heartbeat_max_age_seconds,
            now=datetime.now(UTC),
            service_main_pid=service_status.main_pid,
            service_active=service_status.active_state in {"active", "activating", "reloading"},
        )
        heartbeat_age = (
            "n/a"
            if assessment.heartbeat_age_seconds is None
            else f"{assessment.heartbeat_age_seconds:.0f}s"
        )
        return service_status, assessment, heartbeat_age

    service_status, assessment, heartbeat_age = load_assessment()
    prefix = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if assessment.healthy:
        print(
            f"{prefix} INFO: watchdog healthy "
            f"pid={assessment.heartbeat_pid} age={heartbeat_age}"
        )
        return 0

    if assessment.stray_pids:
        joined = ",".join(str(pid) for pid in assessment.stray_pids)
        print(f"{prefix} WARN: killing stray daemon pids={joined}")
        _kill_stray_pids(assessment.stray_pids, args.config)
        service_status, assessment, heartbeat_age = load_assessment()
        if assessment.healthy:
            print(
                f"{prefix} INFO: watchdog healthy after stray cleanup "
                f"pid={assessment.heartbeat_pid} age={heartbeat_age}"
            )
            return 0

    if assessment.reason == "systemd_main_pid_unknown":
        print(
            f"{prefix} INFO: deferring watchdog action while systemd main pid is unknown "
            f"age={heartbeat_age}"
        )
        return 0

    if service_status.loaded:
        action = _systemd_action(service_status)
        print(
            f"{prefix} WARN: unhealthy reason={assessment.reason} "
            f"main_pid={service_status.main_pid or 0} age={heartbeat_age} "
            f"-> systemctl --user {action} {args.systemd_unit}"
        )
        subprocess.run(
            ["systemctl", "--user", action, args.systemd_unit],
            cwd=project_dir,
            check=True,
        )
        return 0

    print(
        f"{prefix} WARN: unhealthy reason={assessment.reason} "
        f"age={heartbeat_age} -> restart_daemon.sh"
    )
    subprocess.run(["bash", str(restart_script), args.config], cwd=project_dir, check=True)
    return 0


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except subprocess.CalledProcessError as exc:
        print(f"watchdog command failed: {exc}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
