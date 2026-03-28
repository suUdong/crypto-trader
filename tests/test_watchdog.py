from __future__ import annotations

import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.operator import watchdog as watchdog_mod
from crypto_trader.operator.watchdog import ServiceStatus, WatchdogAssessment, evaluate_watchdog


def _heartbeat(
    *,
    pid: int,
    last_heartbeat: datetime,
    config_path: str = "config/daemon.toml",
) -> dict[str, object]:
    return {
        "pid": pid,
        "last_heartbeat": last_heartbeat.isoformat(),
        "config_path": config_path,
    }


def test_evaluate_watchdog_accepts_fresh_single_process() -> None:
    now = datetime(2026, 3, 29, 5, 20, tzinfo=UTC)
    assessment = evaluate_watchdog(
        matching_pids=(1234,),
        heartbeat=_heartbeat(pid=1234, last_heartbeat=now - timedelta(seconds=30)),
        config_path="config/daemon.toml",
        heartbeat_max_age_seconds=240,
        now=now,
        service_main_pid=1234,
        service_active=True,
    )

    assert assessment.healthy is True
    assert assessment.reason == "healthy"
    assert assessment.stray_pids == ()


def test_evaluate_watchdog_flags_stale_heartbeat() -> None:
    now = datetime(2026, 3, 29, 5, 20, tzinfo=UTC)
    assessment = evaluate_watchdog(
        matching_pids=(1234,),
        heartbeat=_heartbeat(pid=1234, last_heartbeat=now - timedelta(minutes=10)),
        config_path="config/daemon.toml",
        heartbeat_max_age_seconds=240,
        now=now,
        service_main_pid=1234,
        service_active=True,
    )

    assert assessment.healthy is False
    assert assessment.reason == "heartbeat_stale"


def test_evaluate_watchdog_flags_duplicate_processes_when_systemd_has_main_pid() -> None:
    now = datetime(2026, 3, 29, 5, 20, tzinfo=UTC)
    assessment = evaluate_watchdog(
        matching_pids=(4446, 43424),
        heartbeat=_heartbeat(pid=4446, last_heartbeat=now - timedelta(seconds=15)),
        config_path="config/daemon.toml",
        heartbeat_max_age_seconds=240,
        now=now,
        service_main_pid=43424,
        service_active=True,
    )

    assert assessment.healthy is False
    assert assessment.reason == "heartbeat_pid_mismatch"
    assert assessment.stray_pids == (4446,)


def test_evaluate_watchdog_defers_stray_kill_when_systemd_is_active_but_main_pid_unknown() -> None:
    now = datetime(2026, 3, 29, 5, 20, tzinfo=UTC)
    assessment = evaluate_watchdog(
        matching_pids=(101893, 103100),
        heartbeat=_heartbeat(pid=103100, last_heartbeat=now - timedelta(seconds=15)),
        config_path="config/daemon.toml",
        heartbeat_max_age_seconds=240,
        now=now,
        service_main_pid=None,
        service_active=True,
    )

    assert assessment.healthy is False
    assert assessment.reason == "systemd_main_pid_unknown"
    assert assessment.stray_pids == ()


def test_run_skips_systemd_restart_when_stray_cleanup_restores_health(
    monkeypatch, tmp_path: Path
) -> None:
    assessments = iter(
        [
            WatchdogAssessment(
                healthy=False,
                reason="duplicate_daemons",
                matching_pids=(4446, 43424),
                stray_pids=(4446,),
                heartbeat_pid=4446,
                heartbeat_age_seconds=15.0,
            ),
            WatchdogAssessment(
                healthy=True,
                reason="healthy",
                matching_pids=(43424,),
                stray_pids=(),
                heartbeat_pid=43424,
                heartbeat_age_seconds=5.0,
            ),
        ]
    )
    killed: list[tuple[int, ...]] = []

    monkeypatch.setattr(
        watchdog_mod,
        "_read_service_status",
        lambda unit: ServiceStatus(loaded=True, active_state="active", main_pid=43424),
    )
    monkeypatch.setattr(
        watchdog_mod,
        "find_matching_daemon_pids",
        lambda config_path: (4446, 43424),
    )
    monkeypatch.setattr(watchdog_mod, "_read_heartbeat", lambda path: {})
    monkeypatch.setattr(
        watchdog_mod,
        "evaluate_watchdog",
        lambda **kwargs: next(assessments),
    )
    monkeypatch.setattr(
        watchdog_mod,
        "_kill_stray_pids",
        lambda pids, config_path: killed.append(pids),
    )

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("systemctl restart should not run after healthy re-check")

    monkeypatch.setattr(watchdog_mod.subprocess, "run", fail_subprocess)

    exit_code = watchdog_mod._run(
        [
            "--project-dir",
            str(tmp_path),
            "--config",
            "config/daemon.toml",
        ]
    )

    assert exit_code == 0
    assert killed == [(4446,)]


def test_run_defers_when_systemd_main_pid_is_temporarily_unknown(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        watchdog_mod,
        "_read_service_status",
        lambda unit: ServiceStatus(loaded=True, active_state="active", main_pid=None),
    )
    monkeypatch.setattr(
        watchdog_mod,
        "find_matching_daemon_pids",
        lambda config_path: (43424,),
    )
    monkeypatch.setattr(watchdog_mod, "_read_heartbeat", lambda path: {})
    monkeypatch.setattr(
        watchdog_mod,
        "evaluate_watchdog",
        lambda **kwargs: WatchdogAssessment(
            healthy=False,
            reason="systemd_main_pid_unknown",
            matching_pids=(43424,),
            stray_pids=(),
            heartbeat_pid=43424,
            heartbeat_age_seconds=5.0,
        ),
    )

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("systemctl restart should not run while MainPID is unknown")

    monkeypatch.setattr(watchdog_mod.subprocess, "run", fail_subprocess)

    exit_code = watchdog_mod._run(
        [
            "--project-dir",
            str(tmp_path),
            "--config",
            "config/daemon.toml",
        ]
    )

    assert exit_code == 0


def test_kill_stray_pids_ignores_process_exit_races(monkeypatch) -> None:
    seen: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        seen.append((pid, sig))
        if sig == signal.SIGTERM:
            raise ProcessLookupError(pid)

    monkeypatch.setattr(watchdog_mod.os, "kill", fake_kill)
    monkeypatch.setattr(watchdog_mod.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(watchdog_mod.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(watchdog_mod, "_pid_exists", lambda pid: False)
    monkeypatch.setattr(watchdog_mod, "find_matching_daemon_pids", lambda config_path: ())

    watchdog_mod._kill_stray_pids((4446,), "config/daemon.toml")

    assert seen == [(4446, signal.SIGTERM)]
