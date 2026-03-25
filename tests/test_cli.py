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
