from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCRIPT = REPO_ROOT / "scripts" / "restart_daemon.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _prepare_project(tmp_path: Path) -> tuple[Path, Path]:
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "restart_daemon.sh"
    script_path.write_text(SOURCE_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "daemon.toml").write_text("paper_trading = true\n", encoding="utf-8")
    (tmp_path / "config" / "live.toml").write_text("paper_trading = false\n", encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "runtime-checkpoint.json").write_text(
        json.dumps({"wallet_states": {}}),
        encoding="utf-8",
    )
    (tmp_path / ".venv" / "bin").mkdir(parents=True)

    _write_executable(
        tmp_path / ".venv" / "bin" / "python",
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

project_dir = Path.cwd()
artifacts_dir = project_dir / "artifacts"
artifacts_dir.mkdir(parents=True, exist_ok=True)
(artifacts_dir / "fake-launch.json").write_text(
    json.dumps({"argv": sys.argv[1:], "pid": os.getpid()}),
    encoding="utf-8",
)
(artifacts_dir / "daemon-heartbeat.json").write_text(
    json.dumps(
        {
            "pid": os.getpid(),
            "last_heartbeat": "2026-03-29T00:00:00+00:00",
            "config_path": sys.argv[-1],
        }
    ),
    encoding="utf-8",
)
""",
    )

    bin_dir = tmp_path / "test-bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "ps",
        """#!/usr/bin/env bash
exit 0
""",
    )
    _write_executable(
        bin_dir / "python3",
        f"""#!{sys.executable}
import os
import sys

REAL_PYTHON = {sys.executable!r}
if len(sys.argv) == 3 and sys.argv[1] == "-" and os.environ.get("TEST_MATCHING_PIDS"):
    for pid in os.environ["TEST_MATCHING_PIDS"].split():
        print(pid)
    raise SystemExit(0)

os.execv(REAL_PYTHON, [REAL_PYTHON, *sys.argv[1:]])
""",
    )
    return script_path, bin_dir


def _run_script(
    script_path: Path,
    project_dir: Path,
    bin_dir: Path,
    *extra_env: tuple[str, str],
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    for key, value in extra_env:
        env[key] = value
    return subprocess.run(
        ["bash", str(script_path), "config/daemon.toml"],
        cwd=project_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_restart_daemon_uses_systemd_for_managed_default_config(tmp_path: Path) -> None:
    script_path, bin_dir = _prepare_project(tmp_path)
    (tmp_path / "artifacts" / "daemon-heartbeat.json").write_text(
        json.dumps(
            {
                "pid": 4242,
                "last_heartbeat": "2026-03-29T00:00:00+00:00",
                "config_path": "config/daemon.toml",
            }
        ),
        encoding="utf-8",
    )
    writer_code = (
        "import json, time; "
        "from pathlib import Path; "
        "time.sleep(3); "
        "artifacts = Path.cwd() / 'artifacts'; "
        "(artifacts / 'daemon-heartbeat.json').write_text("
        "json.dumps({"
        "'pid': 5353, "
        "'last_heartbeat': '2026-03-29T00:05:00+00:00', "
        "'config_path': 'config/daemon.toml'"
        "}), "
        "encoding='utf-8')"
    )
    _write_executable(
        bin_dir / "systemctl",
        f"""#!{sys.executable}
import json
import subprocess
import sys
from pathlib import Path

project_dir = Path.cwd()
artifacts_dir = project_dir / "artifacts"
artifacts_dir.mkdir(parents=True, exist_ok=True)
log_path = artifacts_dir / "systemctl-calls.jsonl"
state_path = artifacts_dir / "systemctl-state.json"
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
if not state_path.exists():
    state_path.write_text(json.dumps({{"main_pid": 4242}}), encoding="utf-8")
state = json.loads(state_path.read_text(encoding="utf-8"))
if args[:3] == ["--user", "show", "crypto-trader.service"]:
    sys.stdout.write(f"loaded\\nactive\\n{{state['main_pid']}}\\n")
elif args[:3] == ["--user", "restart", "crypto-trader.service"]:
    state_path.write_text(json.dumps({{"main_pid": 5353}}), encoding="utf-8")
    subprocess.Popen(
        [
            {sys.executable!r},
            "-c",
            {writer_code!r},
        ],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
else:
    raise SystemExit(1)
""",
    )

    result = _run_script(
        script_path,
        tmp_path,
        bin_dir,
        ("TEST_MATCHING_PIDS", "1111 4242"),
    )

    calls = (tmp_path / "artifacts" / "systemctl-calls.jsonl").read_text(encoding="utf-8")
    assert '--user", "restart", "crypto-trader.service"' in calls
    assert not (tmp_path / "artifacts" / "fake-launch.json").exists()
    heartbeat = json.loads(
        (tmp_path / "artifacts" / "daemon-heartbeat.json").read_text(encoding="utf-8")
    )
    assert heartbeat["pid"] == 5353
    assert "Stopping stray daemon PIDs before systemctl restart: 1111" in result.stdout
    assert "Heartbeat confirmed for PID=5353" in result.stdout


def test_restart_daemon_falls_back_to_direct_launch_without_managed_unit(tmp_path: Path) -> None:
    script_path, bin_dir = _prepare_project(tmp_path)
    _write_executable(
        bin_dir / "systemctl",
        """#!/usr/bin/env python3
import sys

args = sys.argv[1:]
if args[:3] == ["--user", "show", "crypto-trader.service"]:
    sys.stdout.write("not-found\\ninactive\\n0\\n")
    raise SystemExit(1)
raise SystemExit(1)
""",
    )

    result = _run_script(script_path, tmp_path, bin_dir)

    launch = json.loads((tmp_path / "artifacts" / "fake-launch.json").read_text(encoding="utf-8"))
    assert launch["argv"][-3:] == ["run-multi", "--config", "config/daemon.toml"]
    assert "Starting daemon" in result.stdout
