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
