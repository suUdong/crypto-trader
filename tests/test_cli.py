from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from crypto_trader.cli import _build_risk_manager
from crypto_trader.config import load_config

ROOT = Path(__file__).resolve().parents[1]


class CliModuleExecutionTests(unittest.TestCase):
    def test_module_execution_invokes_argparse_help(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = "src"
        result = subprocess.run(
            [sys.executable, "-m", "crypto_trader.cli", "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Crypto trader control plane", result.stdout)

    def test_build_risk_manager_preserves_extended_risk_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(
                """
[risk]
risk_per_trade_pct = 0.01
stop_loss_pct = 0.03
take_profit_pct = 0.06
trailing_stop_pct = 0.04
atr_stop_multiplier = 2.0
""".strip(),
                encoding="utf-8",
            )
            config = load_config(path, {})

        risk_manager = _build_risk_manager(config)

        self.assertEqual(risk_manager._trailing_stop_pct, 0.04)
        self.assertEqual(risk_manager._atr_stop_multiplier, 2.0)

    def test_performance_report_command_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "runtime-checkpoint.json"
            journal_path = Path(tmpdir) / "paper-trades.jsonl"
            output_path = Path(tmpdir) / "performance-report.md"
            checkpoint_path.write_text(
                '{"generated_at":"2026-03-26T00:00:00+00:00","wallet_states":{}}',
                encoding="utf-8",
            )
            journal_path.write_text("", encoding="utf-8")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                f"""
[runtime]
runtime_checkpoint_path = "{checkpoint_path}"
paper_trade_journal_path = "{journal_path}"
performance_report_path = "{output_path}"
""".strip(),
                encoding="utf-8",
            )

            env = dict(os.environ)
            env["PYTHONPATH"] = "src"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "crypto_trader.cli",
                    "performance-report",
                    "--config",
                    str(config_path),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertTrue(output_path.exists())
            self.assertIn("72-Hour Performance Report", output_path.read_text(encoding="utf-8"))

    def test_wallet_performance_command_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "runtime-checkpoint.json"
            runs_path = Path(tmpdir) / "strategy-runs.jsonl"
            journal_path = Path(tmpdir) / "paper-trades.jsonl"
            checkpoint_path.write_text(
                """
{
  "generated_at": "2026-03-27T11:45:00+00:00",
  "wallet_names": ["momentum_wallet"],
  "wallet_states": {
    "momentum_wallet": {
      "strategy_type": "momentum",
      "initial_capital": 1000000,
      "equity": 1010000
    }
  }
}
                """.strip(),
                encoding="utf-8",
            )
            runs_path.write_text(
                """
{"recorded_at":"2026-03-27T10:05:00+00:00","wallet_name":"momentum_wallet","session_starting_equity":1000000}
{"recorded_at":"2026-03-27T11:05:00+00:00","wallet_name":"momentum_wallet","session_starting_equity":1005000}
                """.strip(),
                encoding="utf-8",
            )
            journal_path.write_text("", encoding="utf-8")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                f"""
[runtime]
runtime_checkpoint_path = "{checkpoint_path}"
strategy_run_journal_path = "{runs_path}"
paper_trade_journal_path = "{journal_path}"
                """.strip(),
                encoding="utf-8",
            )

            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "crypto_trader.cli",
                    "wallet-performance",
                    "--config",
                    str(config_path),
                ],
                cwd=tmpdir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            output_path = Path(tmpdir) / "artifacts" / "wallet-performance-7d.md"
            self.assertTrue(output_path.exists())
            self.assertIn("Wallet Performance Report", output_path.read_text(encoding="utf-8"))

    def test_execution_quality_report_allows_live_config_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "runtime-checkpoint.json"
            runs_path = Path(tmpdir) / "strategy-runs.jsonl"
            logs_dir = Path(tmpdir) / "logs"
            events_path = logs_dir / "events.jsonl"
            checkpoint_path.write_text(
                '{"generated_at":"2026-03-28T00:00:00+00:00","wallet_states":{}}',
                encoding="utf-8",
            )
            runs_path.write_text(
                (
                    '{"recorded_at":"2026-03-28T00:00:00+00:00","symbol":"KRW-BTC",'
                    '"latest_price":100.0,"market_regime":"sideways","signal_action":"buy",'
                    '"signal_reason":"entry","signal_confidence":0.64,"order_status":"filled",'
                    '"order_side":"buy","session_starting_equity":1000000.0,"cash":900000.0,'
                    '"open_positions":1,"realized_pnl":0.0,"success":true,"error":null,'
                    '"consecutive_failures":0,"verdict_status":"continue","verdict_confidence":1.0,'
                    '"wallet_name":"mean_rev_wallet","strategy_type":"mean_reversion",'
                    '"signal_indicators":{},"signal_context":{},"session_id":"session-1",'
                    '"order_type":"limit"}\n'
                ),
                encoding="utf-8",
            )
            logs_dir.mkdir(parents=True, exist_ok=True)
            events_path.write_text(
                (
                    '{"timestamp":"2026-03-28T00:00:01+00:00","event_type":"trade",'
                    '"wallet_name":"mean_rev_wallet","strategy_type":"mean_reversion",'
                    '"symbol":"KRW-BTC","side":"buy","quantity":1.0,"fill_price":100.02,'
                    '"fee_paid":0.04,"order_status":"filled","order_type":"limit",'
                    '"reason":"entry"}\n'
                ),
                encoding="utf-8",
            )
            config_path = Path(tmpdir) / "live-config.toml"
            config_path.write_text(
                f"""
[trading]
paper_trading = false

[runtime]
runtime_checkpoint_path = "{checkpoint_path}"
strategy_run_journal_path = "{runs_path}"
paper_trade_journal_path = "{Path(tmpdir) / "paper-trades.jsonl"}"
                """.strip(),
                encoding="utf-8",
            )

            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "crypto_trader.cli",
                    "execution-quality-report",
                    "--config",
                    str(config_path),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("Execution Quality Report", result.stdout)
