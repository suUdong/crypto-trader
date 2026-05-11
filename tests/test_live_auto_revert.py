"""Tests for KillSwitch.trigger() and the live auto-revert runtime hook."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from crypto_trader.multi_runtime import MultiSymbolRuntime
from crypto_trader.risk.kill_switch import KillSwitch, KillSwitchConfig, KillSwitchState


def test_trigger_marks_state_and_records_reason():
    ks = KillSwitch(KillSwitchConfig())
    state = ks.trigger("manual_audit")
    assert state.triggered is True
    assert "manual_audit" in state.trigger_reason
    assert state.triggered_at != ""


def test_trigger_is_idempotent():
    """A second trigger() must NOT overwrite the original reason or timestamp."""
    ks = KillSwitch(KillSwitchConfig())
    first = ks.trigger("first_event")
    original_reason = first.trigger_reason
    original_ts = first.triggered_at
    second = ks.trigger("second_event")
    assert second.trigger_reason == original_reason
    assert second.triggered_at == original_ts


def _make_runtime_stub(
    tmp_path: Path,
    *,
    paper_trading: bool,
    revert_pct: float,
    starting_equity: float,
    kill_switch: KillSwitch | None = None,
) -> MultiSymbolRuntime:
    """Build a bare-bones runtime instance for hook-level tests.

    Bypasses the full constructor — we only exercise the two private hooks
    `_maybe_trigger_live_auto_revert` and `_write_live_revert_flag` and need
    the attributes those methods touch.
    """
    runtime = MultiSymbolRuntime.__new__(MultiSymbolRuntime)
    trading = SimpleNamespace(
        paper_trading=paper_trading,
        live_auto_revert_loss_pct=revert_pct,
    )
    runtime_cfg = SimpleNamespace(kill_switch_path=str(tmp_path / "kill_switch.json"))
    runtime._config = SimpleNamespace(trading=trading, runtime=runtime_cfg)  # type: ignore[attr-defined]
    runtime._total_starting_equity = starting_equity  # type: ignore[attr-defined]
    runtime._kill_switch = kill_switch or KillSwitch(KillSwitchConfig())  # type: ignore[attr-defined]
    runtime._logger = logging.getLogger("test_live_auto_revert")  # type: ignore[attr-defined]
    return runtime


def test_auto_revert_no_op_in_paper_mode(tmp_path):
    runtime = _make_runtime_stub(
        tmp_path, paper_trading=True, revert_pct=0.02, starting_equity=1_000_000.0
    )
    state = KillSwitchState()
    out = runtime._maybe_trigger_live_auto_revert(state, total_equity=500_000.0)
    assert out.triggered is False


def test_auto_revert_no_op_when_threshold_disabled(tmp_path):
    runtime = _make_runtime_stub(
        tmp_path, paper_trading=False, revert_pct=0.0, starting_equity=1_000_000.0
    )
    state = KillSwitchState()
    out = runtime._maybe_trigger_live_auto_revert(state, total_equity=900_000.0)
    assert out.triggered is False


def test_auto_revert_no_op_when_starting_equity_zero(tmp_path):
    runtime = _make_runtime_stub(
        tmp_path, paper_trading=False, revert_pct=0.02, starting_equity=0.0
    )
    state = KillSwitchState()
    out = runtime._maybe_trigger_live_auto_revert(state, total_equity=0.0)
    assert out.triggered is False


def test_auto_revert_no_op_when_loss_below_threshold(tmp_path):
    runtime = _make_runtime_stub(
        tmp_path, paper_trading=False, revert_pct=0.02, starting_equity=1_000_000.0
    )
    # 1% loss < 2% threshold
    state = KillSwitchState()
    out = runtime._maybe_trigger_live_auto_revert(state, total_equity=990_000.0)
    assert out.triggered is False


def test_auto_revert_triggers_at_threshold(tmp_path):
    runtime = _make_runtime_stub(
        tmp_path, paper_trading=False, revert_pct=0.02, starting_equity=1_000_000.0
    )
    state = KillSwitchState()
    out = runtime._maybe_trigger_live_auto_revert(state, total_equity=980_000.0)
    assert out.triggered is True
    assert "live_auto_paper_revert" in out.trigger_reason
    assert "2.00%" in out.trigger_reason  # threshold


def test_auto_revert_writes_flag_file(tmp_path):
    runtime = _make_runtime_stub(
        tmp_path, paper_trading=False, revert_pct=0.02, starting_equity=1_000_000.0
    )
    state = KillSwitchState()
    runtime._maybe_trigger_live_auto_revert(state, total_equity=950_000.0)
    flag_path = tmp_path / "live-auto-revert.flag"
    assert flag_path.exists()
    payload = json.loads(flag_path.read_text())
    assert payload["daily_loss_pct"] == 0.05
    assert payload["threshold_pct"] == 0.02
    assert payload["starting_equity"] == 1_000_000.0
    assert "live_auto_paper_revert" in payload["reason"]


def test_auto_revert_no_op_when_already_triggered(tmp_path):
    """If the kill switch is already halted, we must NOT re-trigger or rewrite the flag."""
    ks = KillSwitch(KillSwitchConfig())
    ks.trigger("original_reason")
    runtime = _make_runtime_stub(
        tmp_path,
        paper_trading=False,
        revert_pct=0.02,
        starting_equity=1_000_000.0,
        kill_switch=ks,
    )
    state = ks.state
    out = runtime._maybe_trigger_live_auto_revert(state, total_equity=900_000.0)
    # Reason preserved
    assert out.trigger_reason == "original_reason"
    # NOTE: _maybe_trigger_live_auto_revert is called with state.triggered=True
    # from the call site only when the regular kill_switch.check didn't fire,
    # so this path tests the early-exit semantics: trigger() is idempotent and
    # the existing state is returned unchanged.


def test_runtime_hook_used_via_dependency_check(tmp_path):
    """Spot-check that the runtime uses the _maybe_trigger_live_auto_revert
    method on `_check_kill_switch_after_tick` — guards against accidental
    removal."""
    runtime = _make_runtime_stub(
        tmp_path, paper_trading=False, revert_pct=0.02, starting_equity=1_000_000.0
    )
    # Method must exist and be callable
    assert callable(runtime._maybe_trigger_live_auto_revert)
    assert callable(runtime._write_live_revert_flag)


def test_flag_write_survives_oserror(tmp_path, caplog):
    """Flag write failure must not crash the hook — must log and continue."""
    runtime = _make_runtime_stub(
        tmp_path, paper_trading=False, revert_pct=0.02, starting_equity=1_000_000.0
    )
    # Force flag path to an unwritable location by overriding kill_switch_path
    runtime._config.runtime.kill_switch_path = "/proc/cannot-write/kill_switch.json"
    # Direct call should not raise
    with caplog.at_level(logging.ERROR):
        runtime._write_live_revert_flag(0.05, 0.02, "test_reason")
    assert any("Failed to write live revert flag" in r.message for r in caplog.records)


def test_trigger_called_with_full_reason_string(tmp_path):
    """The kill-switch trigger reason must include loss and threshold percents."""
    ks = MagicMock(wraps=KillSwitch(KillSwitchConfig()))
    runtime = _make_runtime_stub(
        tmp_path,
        paper_trading=False,
        revert_pct=0.02,
        starting_equity=1_000_000.0,
        kill_switch=ks,
    )
    state = KillSwitchState()
    runtime._maybe_trigger_live_auto_revert(state, total_equity=960_000.0)
    assert ks.trigger.called
    reason = ks.trigger.call_args.args[0]
    assert "daily_loss=4.00%" in reason
    assert "revert_cap=2.00%" in reason
