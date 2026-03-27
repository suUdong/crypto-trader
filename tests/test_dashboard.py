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

    def test_load_paper_trades_missing(self) -> None:
        result = data_mod.load_paper_trades()
        self.assertEqual(result, [])

    def test_load_paper_trades_valid(self) -> None:
        path = Path(self.tmpdir) / "paper-trades.jsonl"
        trades = [
            json.dumps({
                "symbol": "KRW-BTC", "entry_price": 50000000,
                "exit_price": 51000000, "pnl": 100000, "pnl_pct": 2.0,
                "wallet": "momentum_wallet",
                "entry_time": "2026-03-27T01:00:00+00:00",
                "exit_time": "2026-03-27T05:00:00+00:00",
            }),
            json.dumps({
                "symbol": "KRW-ETH", "entry_price": 3000000,
                "exit_price": 2900000, "pnl": -50000, "pnl_pct": -1.5,
                "wallet": "mean_reversion_wallet",
                "entry_time": "2026-03-27T02:00:00+00:00",
                "exit_time": "2026-03-27T06:00:00+00:00",
            }),
        ]
        path.write_text("\n".join(trades))
        result = data_mod.load_paper_trades()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["symbol"], "KRW-BTC")
        self.assertEqual(result[1]["pnl"], -50000)

    def test_load_signal_summary_empty(self) -> None:
        result = data_mod.load_signal_summary()
        self.assertEqual(result["hold_reasons"], {})
        self.assertEqual(result["by_wallet"], {})

    def test_load_signal_summary_aggregation(self) -> None:
        path = Path(self.tmpdir) / "strategy-runs.jsonl"
        runs = [
            json.dumps({
                "signal_action": "hold", "signal_reason": "below_ma_filter",
                "wallet_name": "momentum_wallet", "signal_confidence": 0.3,
            }),
            json.dumps({
                "signal_action": "hold", "signal_reason": "below_ma_filter",
                "wallet_name": "momentum_wallet", "signal_confidence": 0.4,
            }),
            json.dumps({
                "signal_action": "buy", "signal_reason": "momentum_strong",
                "wallet_name": "momentum_wallet", "signal_confidence": 0.8,
            }),
            json.dumps({
                "signal_action": "hold", "signal_reason": "cooldown_active",
                "wallet_name": "vbreak_wallet", "signal_confidence": 0.2,
            }),
            json.dumps({
                "signal_action": "sell", "signal_reason": "exit_trailing",
                "wallet_name": "vbreak_wallet", "signal_confidence": 0.9,
            }),
        ]
        path.write_text("\n".join(runs))
        result = data_mod.load_signal_summary()

        # Hold reasons
        self.assertEqual(result["hold_reasons"]["below_ma_filter"], 2)
        self.assertEqual(result["hold_reasons"]["cooldown_active"], 1)
        self.assertNotIn("momentum_strong", result["hold_reasons"])

        # By wallet
        mom = result["by_wallet"]["momentum_wallet"]
        self.assertEqual(mom["buy"], 1)
        self.assertEqual(mom["sell"], 0)
        self.assertEqual(mom["hold"], 2)
        self.assertEqual(mom["total"], 3)
        self.assertAlmostEqual(mom["avg_conf"], 0.5, places=2)

        vb = result["by_wallet"]["vbreak_wallet"]
        self.assertEqual(vb["buy"], 0)
        self.assertEqual(vb["sell"], 1)
        self.assertEqual(vb["hold"], 1)
        self.assertEqual(vb["total"], 2)
        self.assertAlmostEqual(vb["avg_conf"], 0.55, places=2)

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
        self.assertEqual(data_mod.load_paper_trades(), [])


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


@_skip
class TestStrategyKrMapping(unittest.TestCase):
    """Test Korean name mappings include new strategies."""

    def test_volume_spike_in_strategy_kr(self) -> None:
        self.assertIn("volume_spike", data_mod.STRATEGY_KR)
        self.assertEqual(data_mod.STRATEGY_KR["volume_spike"], "거래량급등")

    def test_strategy_kr_volume_spike_wallet(self) -> None:
        result = data_mod.strategy_kr("volume_spike_wallet")
        self.assertEqual(result, "거래량급등")

    def test_strategy_kr_volume_spike_per_symbol(self) -> None:
        result = data_mod.strategy_kr("volume_spike_btc_wallet")
        self.assertEqual(result, "거래량급등 (BTC)")


@_skip
class TestNewTabData(unittest.TestCase):
    """Test data patterns used by the new dashboard tabs."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self._orig_dir = data_mod.ARTIFACTS_DIR
        data_mod.ARTIFACTS_DIR = Path(self.tmpdir)
        try:
            import streamlit as st
            st.cache_data.clear()
        except Exception:
            pass

    def tearDown(self) -> None:
        data_mod.ARTIFACTS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_kill_switch_with_config(self) -> None:
        path = Path(self.tmpdir) / "kill-switch.json"
        ks = {
            "triggered": False,
            "trigger_reason": "",
            "consecutive_losses": 2,
            "daily_loss_pct": 0.01,
            "portfolio_drawdown_pct": 0.02,
            "warning_active": False,
            "position_size_penalty": 1.0,
            "config": {
                "max_portfolio_drawdown_pct": 0.05,
                "max_daily_loss_pct": 0.03,
                "max_consecutive_losses": 5,
                "warn_threshold_pct": 0.5,
                "reduce_threshold_pct": 0.75,
                "reduce_position_factor": 0.5,
            },
        }
        path.write_text(json.dumps(ks))
        result = data_mod.load_kill_switch()
        assert result is not None
        self.assertFalse(result["triggered"])
        self.assertEqual(result["consecutive_losses"], 2)
        self.assertIn("config", result)
        self.assertEqual(result["config"]["max_consecutive_losses"], 5)

    def test_checkpoint_with_positions(self) -> None:
        path = Path(self.tmpdir) / "runtime-checkpoint.json"
        cp = {
            "iteration": 10,
            "wallet_states": {
                "volume_spike_btc_wallet": {
                    "equity": 1050000,
                    "initial_capital": 1000000,
                    "realized_pnl": 30000,
                    "trade_count": 5,
                    "open_positions": 1,
                    "positions": {
                        "KRW-BTC": {
                            "entry_price": 90000000,
                            "quantity": 0.001,
                        },
                    },
                },
                "momentum_btc_wallet": {
                    "equity": 980000,
                    "initial_capital": 1000000,
                    "realized_pnl": -20000,
                    "trade_count": 3,
                    "open_positions": 0,
                    "positions": {},
                },
            },
        }
        path.write_text(json.dumps(cp))
        result = data_mod.load_checkpoint()
        assert result is not None
        ws = result["wallet_states"]
        self.assertIn("volume_spike_btc_wallet", ws)
        self.assertEqual(ws["volume_spike_btc_wallet"]["positions"]["KRW-BTC"]["entry_price"], 90000000)

    def test_volume_spike_signal_filtering(self) -> None:
        """Verify volume_spike signals can be filtered from strategy-runs."""
        path = Path(self.tmpdir) / "strategy-runs.jsonl"
        runs = [
            json.dumps({
                "signal_action": "buy", "wallet_name": "volume_spike_btc_wallet",
                "signal_confidence": 0.85, "symbol": "KRW-BTC",
            }),
            json.dumps({
                "signal_action": "hold", "wallet_name": "momentum_btc_wallet",
                "signal_confidence": 0.3, "symbol": "KRW-BTC",
            }),
            json.dumps({
                "signal_action": "hold", "wallet_name": "volume_spike_eth_wallet",
                "signal_confidence": 0.4, "symbol": "KRW-ETH",
            }),
        ]
        path.write_text("\n".join(runs))
        all_runs = data_mod.load_strategy_runs()
        vs_runs = [r for r in all_runs if "volume_spike" in r.get("wallet_name", "")]
        self.assertEqual(len(vs_runs), 2)
        self.assertEqual(vs_runs[0]["signal_action"], "buy")

    def test_paper_trades_volume_spike_filtering(self) -> None:
        path = Path(self.tmpdir) / "paper-trades.jsonl"
        trades = [
            json.dumps({
                "symbol": "KRW-BTC", "pnl": 50000, "pnl_pct": 1.5,
                "wallet": "volume_spike_btc_wallet",
                "entry_time": "2026-03-27T01:00:00+00:00",
                "exit_time": "2026-03-27T05:00:00+00:00",
                "entry_price": 90000000, "exit_price": 91350000,
            }),
            json.dumps({
                "symbol": "KRW-ETH", "pnl": -10000, "pnl_pct": -0.5,
                "wallet": "momentum_eth_wallet",
                "entry_time": "2026-03-27T02:00:00+00:00",
                "exit_time": "2026-03-27T06:00:00+00:00",
                "entry_price": 3000000, "exit_price": 2985000,
            }),
        ]
        path.write_text("\n".join(trades))
        all_trades = data_mod.load_paper_trades()
        vs_trades = [t for t in all_trades if "volume_spike" in t.get("wallet", "")]
        self.assertEqual(len(vs_trades), 1)
        self.assertEqual(vs_trades[0]["pnl"], 50000)


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

    def test_app_has_new_tabs(self) -> None:
        source = _read_source("dashboard/app.py")
        self.assertIn("tab_vspike", source)
        self.assertIn("tab_pnl_chart", source)
        self.assertIn("tab_corr", source)
        self.assertIn("tab_killswitch", source)
        self.assertIn("거래량급등", source)
        self.assertIn("포지션PnL", source)
        self.assertIn("상관관계", source)
        self.assertIn("킬스위치", source)


if __name__ == "__main__":
    unittest.main()
