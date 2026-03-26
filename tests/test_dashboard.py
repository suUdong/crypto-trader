"""Tests for the dashboard module."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

try:
    from dashboard import data as data_mod
    from dashboard.auth import check_auth
    _HAS_STREAMLIT = True
except ImportError:
    _HAS_STREAMLIT = False


_skip = unittest.skipIf(not _HAS_STREAMLIT, "streamlit not installed")


def _read_source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


@_skip
class TestDataLoaders(unittest.TestCase):
    """Test artifact data loading functions."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self._orig_dir = data_mod.ARTIFACTS_DIR
        data_mod.ARTIFACTS_DIR = Path(self.tmpdir)
        # Clear st.cache_data between tests
        try:
            import streamlit as st
            st.cache_data.clear()
        except Exception:
            pass

    def tearDown(self) -> None:
        data_mod.ARTIFACTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_json_missing_file(self) -> None:
        result = data_mod._load_json("nonexistent.json")
        self.assertIsNone(result)

    def test_load_json_valid(self) -> None:
        path = Path(self.tmpdir) / "test.json"
        path.write_text(json.dumps({"key": "value"}))
        result = data_mod._load_json("test.json")
        self.assertEqual(result, {"key": "value"})

    def test_load_jsonl_missing(self) -> None:
        result = data_mod._load_jsonl("missing.jsonl")
        self.assertEqual(result, [])

    def test_load_jsonl_valid(self) -> None:
        path = Path(self.tmpdir) / "runs.jsonl"
        lines = [
            json.dumps({"action": "hold", "price": 100}),
            json.dumps({"action": "buy", "price": 200}),
        ]
        path.write_text("\n".join(lines))
        result = data_mod._load_jsonl("runs.jsonl")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["action"], "hold")
        self.assertEqual(result[1]["price"], 200)

    def test_load_jsonl_skips_bad_lines(self) -> None:
        path = Path(self.tmpdir) / "bad.jsonl"
        path.write_text('{"ok": true}\nnot json\n{"also": "ok"}\n')
        result = data_mod._load_jsonl("bad.jsonl")
        self.assertEqual(len(result), 2)

    def test_load_md_missing(self) -> None:
        result = data_mod._load_md("missing.md")
        self.assertIsNone(result)

    def test_load_md_valid(self) -> None:
        path = Path(self.tmpdir) / "memo.md"
        path.write_text("# Hello\nWorld")
        result = data_mod._load_md("memo.md")
        self.assertEqual(result, "# Hello\nWorld")

    def test_load_checkpoint(self) -> None:
        path = Path(self.tmpdir) / "runtime-checkpoint.json"
        checkpoint = {"iteration": 5, "wallet_states": {}}
        path.write_text(json.dumps(checkpoint))
        result = data_mod.load_checkpoint()
        assert result is not None
        self.assertEqual(result["iteration"], 5)

    def test_load_positions(self) -> None:
        path = Path(self.tmpdir) / "positions.json"
        pos = {"positions": [], "open_position_count": 0}
        path.write_text(json.dumps(pos))
        result = data_mod.load_positions()
        assert result is not None
        self.assertEqual(result["open_position_count"], 0)

    def test_load_health(self) -> None:
        path = Path(self.tmpdir) / "health.json"
        health = {"success": True, "last_signal": "hold"}
        path.write_text(json.dumps(health))
        result = data_mod.load_health()
        assert result is not None
        self.assertTrue(result["success"])

    def test_load_regime_report(self) -> None:
        path = Path(self.tmpdir) / "regime-report.json"
        regime = {"market_regime": "bull", "short_return_pct": 0.05}
        path.write_text(json.dumps(regime))
        result = data_mod.load_regime_report()
        assert result is not None
        self.assertEqual(result["market_regime"], "bull")

    def test_load_strategy_runs(self) -> None:
        path = Path(self.tmpdir) / "strategy-runs.jsonl"
        path.write_text(json.dumps({"signal_action": "hold"}) + "\n")
        result = data_mod.load_strategy_runs()
        self.assertEqual(len(result), 1)

    def test_load_daemon_heartbeat(self) -> None:
        path = Path(self.tmpdir) / "daemon-heartbeat.json"
        hb = {
            "last_heartbeat": "2026-03-25T12:00:00+00:00",
            "pid": 1234, "iteration": 5, "uptime_seconds": 300.0,
        }
        path.write_text(json.dumps(hb))
        result = data_mod.load_daemon_heartbeat()
        assert result is not None
        self.assertEqual(result["pid"], 1234)
        self.assertEqual(result["iteration"], 5)

    def test_all_loaders_return_none_when_empty(self) -> None:
        """All JSON loaders return None for missing files."""
        self.assertIsNone(data_mod.load_checkpoint())
        self.assertIsNone(data_mod.load_positions())
        self.assertIsNone(data_mod.load_health())
        self.assertIsNone(data_mod.load_regime_report())
        self.assertIsNone(data_mod.load_drift_report())
        self.assertIsNone(data_mod.load_promotion_gate())
        self.assertIsNone(data_mod.load_backtest_baseline())
        self.assertIsNone(data_mod.load_daily_performance())
        self.assertIsNone(data_mod.load_daily_memo())
        self.assertIsNone(data_mod.load_operator_report())
        self.assertIsNone(data_mod.load_daemon_heartbeat())
        self.assertEqual(data_mod.load_strategy_runs(), [])


@_skip
class TestAuth(unittest.TestCase):
    """Test session-based password authentication."""

    @patch("dashboard.auth.st")
    def test_auth_not_authenticated_by_default(self, mock_st: Any) -> None:
        mock_st.session_state = {}
        self.assertFalse(check_auth())

    @patch("dashboard.auth.st")
    def test_auth_authenticated_when_session_flag_set(self, mock_st: Any) -> None:
        mock_st.session_state = {"dashboard_authenticated": True}
        self.assertTrue(check_auth())

    @patch("dashboard.auth.st")
    def test_auth_false_when_session_flag_false(self, mock_st: Any) -> None:
        mock_st.session_state = {"dashboard_authenticated": False}
        self.assertFalse(check_auth())

    @patch("dashboard.auth.st")
    def test_auth_custom_session_key(self, mock_st: Any) -> None:
        mock_st.session_state = {"y2i_auth": True}
        self.assertTrue(check_auth(session_key="y2i_auth"))

    @patch("dashboard.auth.st")
    def test_auth_custom_session_key_missing(self, mock_st: Any) -> None:
        mock_st.session_state = {}
        self.assertFalse(check_auth(session_key="y2i_auth"))

    def test_render_login_does_not_own_page_config(self) -> None:
        source = _read_source("dashboard/auth.py")
        self.assertNotIn("st.set_page_config", source)


class TestDashboardEntrypoint(unittest.TestCase):
    """Guard startup compatibility for local Streamlit and Cloud."""

    def test_app_uses_cross_version_timezone_utc(self) -> None:
        source = _read_source("dashboard/app.py")
        self.assertIn("from datetime import datetime,", source)
        self.assertIn("timezone", source)
        self.assertIn("_UTC = timezone.utc", source)
        self.assertNotIn("from datetime import UTC, datetime", source)
        self.assertIn("datetime.now(", source)

    def test_app_sets_page_config_before_auth_gate(self) -> None:
        source = _read_source("dashboard/app.py")
        self.assertLess(source.index("st.set_page_config"), source.index("if not check_auth():"))


if __name__ == "__main__":
    unittest.main()
