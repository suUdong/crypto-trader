"""Tests for scripts/preflight_live_check.py operator helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _import_script():
    import importlib.util
    import sys

    src_dir = _SCRIPT_DIR.parent / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    path = _SCRIPT_DIR / "preflight_live_check.py"
    spec = importlib.util.spec_from_file_location("preflight_live_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _import_script()


def _write_paper_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[trading]
paper_trading = true
symbol = "KRW-BTC"

[telegram]
bot_token = "tok"
chat_id = "123"

[[wallets]]
name = "w1"
strategy = "momentum"
""",
        encoding="utf-8",
    )
    return cfg


def _write_live_config_missing_gates(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[trading]
paper_trading = false
symbol = "KRW-BTC"

[telegram]
bot_token = "tok"
chat_id = "123"

[risk]
max_position_pct = 0.10

[[wallets]]
name = "w1"
strategy = "momentum"
""",
        encoding="utf-8",
    )
    return cfg


def test_paper_config_returns_zero(tmp_path, script, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _write_paper_config(tmp_path)
    exit_code, payload = script.run(str(cfg))
    assert exit_code == 0
    assert all(p["level"] != "ERROR" for p in payload)


def test_live_config_without_gates_blocks(tmp_path, script, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _write_live_config_missing_gates(tmp_path)
    exit_code, payload = script.run(str(cfg))
    assert exit_code == 1
    # Should report missing env opt-in and missing confirmation marker
    messages = " ".join(p["message"] for p in payload if p["level"] == "ERROR")
    assert "LIVE_TRADING_ENABLED" in messages
    assert "confirmation marker missing" in messages


def test_format_human_ready(script):
    out = script.format_human("config/x.toml", [], exit_code=0)
    assert "READY for live cutover" in out
    assert "OK" in out


def test_format_human_blocked(script):
    payload = [
        {"level": "ERROR", "message": "missing thing"},
        {"level": "WARNING", "message": "soft thing"},
    ]
    out = script.format_human("config/x.toml", payload, exit_code=1)
    assert "BLOCKED" in out
    assert "[ERROR] missing thing" in out
    assert "[WARN ] soft thing" in out


def test_main_json_output(tmp_path, script, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cfg = _write_paper_config(tmp_path)
    monkeypatch.setattr("sys.argv", ["preflight_live_check.py", "--config", str(cfg), "--json"])
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["exit_code"] == 0
    assert isinstance(payload["issues"], list)
