"""Tests for the dashboard module."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import data as data_mod
from dashboard.auth import DEFAULT_TOKEN, check_auth


class TestDataLoaders(unittest.TestCase):
    """Test artifact data loading functions."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self._orig_dir = data_mod.ARTIFACTS_DIR
        data_mod.ARTIFACTS_DIR = Path(self.tmpdir)

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
        self.assertEqual(result["iteration"], 5)

    def test_load_positions(self) -> None:
        path = Path(self.tmpdir) / "positions.json"
        pos = {"positions": [], "open_position_count": 0}
        path.write_text(json.dumps(pos))
        result = data_mod.load_positions()
        self.assertEqual(result["open_position_count"], 0)

    def test_load_health(self) -> None:
        path = Path(self.tmpdir) / "health.json"
        health = {"success": True, "last_signal": "hold"}
        path.write_text(json.dumps(health))
        result = data_mod.load_health()
        self.assertTrue(result["success"])

    def test_load_regime_report(self) -> None:
        path = Path(self.tmpdir) / "regime-report.json"
        regime = {"market_regime": "bull", "short_return_pct": 0.05}
        path.write_text(json.dumps(regime))
        result = data_mod.load_regime_report()
        self.assertEqual(result["market_regime"], "bull")

    def test_load_strategy_runs(self) -> None:
        path = Path(self.tmpdir) / "strategy-runs.jsonl"
        path.write_text(json.dumps({"signal_action": "hold"}) + "\n")
        result = data_mod.load_strategy_runs()
        self.assertEqual(len(result), 1)

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
        self.assertEqual(data_mod.load_strategy_runs(), [])


class TestAuth(unittest.TestCase):
    """Test URL token authentication."""

    @patch("dashboard.auth.st")
    def test_auth_default_token(self, mock_st: object) -> None:
        mock_st.query_params = {"token": DEFAULT_TOKEN}
        os.environ.pop("DASHBOARD_TOKEN", None)
        self.assertTrue(check_auth())

    @patch("dashboard.auth.st")
    def test_auth_missing_token(self, mock_st: object) -> None:
        mock_st.query_params = {}
        os.environ.pop("DASHBOARD_TOKEN", None)
        self.assertFalse(check_auth())

    @patch("dashboard.auth.st")
    def test_auth_wrong_token(self, mock_st: object) -> None:
        mock_st.query_params = {"token": "wrong"}
        os.environ.pop("DASHBOARD_TOKEN", None)
        self.assertFalse(check_auth())

    @patch("dashboard.auth.st")
    def test_auth_custom_env_token(self, mock_st: object) -> None:
        mock_st.query_params = {"token": "my_secret"}
        os.environ["DASHBOARD_TOKEN"] = "my_secret"
        try:
            self.assertTrue(check_auth())
        finally:
            del os.environ["DASHBOARD_TOKEN"]

    @patch("dashboard.auth.st")
    def test_auth_custom_env_wrong(self, mock_st: object) -> None:
        mock_st.query_params = {"token": "demo"}
        os.environ["DASHBOARD_TOKEN"] = "my_secret"
        try:
            self.assertFalse(check_auth())
        finally:
            del os.environ["DASHBOARD_TOKEN"]


if __name__ == "__main__":
    unittest.main()
