"""Tests for the apply-params CLI command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _make_grid_wf_json(tmpdir: Path, strategy: str, date_str: str = "2026-03-26") -> Path:
    """Write a mock grid-wf JSON export and return its path."""
    artifacts_dir = tmpdir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "strategy_type": strategy,
        "candidates_tested": 3,
        "candidates_validated": 1,
        "results": [
            {
                "params": {"momentum_lookback": 20, "momentum_entry_threshold": 0.008},
                "avg_sharpe": 1.5,
                "avg_return_pct": 4.2,
                "total_trades": 25,
                "validated": True,
                "wf_avg_efficiency_ratio": 0.65,
                "wf_oos_win_rate": 0.6,
            }
        ],
        "best_validated": {
            "params": {"momentum_lookback": 20, "momentum_entry_threshold": 0.008},
            "avg_sharpe": 1.5,
            "avg_return_pct": 4.2,
            "total_trades": 25,
            "validated": True,
            "wf_avg_efficiency_ratio": 0.65,
            "wf_oos_win_rate": 0.6,
        },
    }
    path = artifacts_dir / f"grid-wf-{strategy}-{date_str}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _run_apply_params(
    tmpdir: Path,
    config_path: Path,
    strategy: str = "momentum",
    wallet: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-m",
        "crypto_trader.cli",
        "apply-params",
        "--config",
        str(config_path),
        "--strategy",
        strategy,
    ]
    if wallet:
        cmd += ["--wallet", wallet]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        cmd,
        cwd=tmpdir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_config(
    tmpdir: Path, strategy: str = "momentum", wallet_name: str = "btc_momentum"
) -> Path:
    config_path = tmpdir / "config.toml"
    config_path.write_text(
        f"""
[trading]
symbol = "KRW-BTC"

[[wallets]]
name = "{wallet_name}"
symbol = "KRW-BTC"
strategy = "{strategy}"
initial_capital = 100000

[wallets.strategy_overrides]
momentum_lookback = 14
""".strip(),
        encoding="utf-8",
    )
    return config_path


class TestApplyParamsReadsLatestFile(unittest.TestCase):
    """apply-params reads the most recent grid-wf JSON for the given strategy."""

    def test_reads_latest_json_when_multiple_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            config_path = _write_config(tmpdir)
            # Create two dated files; the later one should be used
            _make_grid_wf_json(tmpdir, "momentum", "2026-03-25")
            _make_grid_wf_json(tmpdir, "momentum", "2026-03-26")

            result = _run_apply_params(
                tmpdir, config_path, strategy="momentum", wallet="btc_momentum"
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            # Output should reference the latest file name
            self.assertIn("2026-03-26", result.stdout)

    def test_reports_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            config_path = _write_config(tmpdir)
            (tmpdir / "artifacts").mkdir()

            result = _run_apply_params(
                tmpdir, config_path, strategy="momentum", wallet="btc_momentum"
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("No grid-wf results found", result.stdout)


class TestApplyParamsWalletDetection(unittest.TestCase):
    """apply-params auto-detects the wallet matching the strategy."""

    def test_auto_detects_matching_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            config_path = _write_config(tmpdir, strategy="momentum", wallet_name="btc_momentum")
            _make_grid_wf_json(tmpdir, "momentum")

            result = _run_apply_params(tmpdir, config_path, strategy="momentum")

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("btc_momentum", result.stdout)

    def test_explicit_wallet_overrides_auto_detect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            config_path = _write_config(tmpdir, strategy="momentum", wallet_name="btc_momentum")
            _make_grid_wf_json(tmpdir, "momentum")

            result = _run_apply_params(
                tmpdir, config_path, strategy="momentum", wallet="btc_momentum"
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("btc_momentum", result.stdout)

    def test_reports_no_matching_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            # Config has a mean_reversion wallet but we ask for momentum auto-detect
            config_path = _write_config(tmpdir, strategy="mean_reversion", wallet_name="btc_mr")
            _make_grid_wf_json(tmpdir, "momentum")

            result = _run_apply_params(tmpdir, config_path, strategy="momentum")

            self.assertEqual(result.returncode, 0)
            self.assertIn("No wallet with strategy=momentum", result.stdout)


class TestApplyParamsSidecarOutput(unittest.TestCase):
    """apply-params writes a JSON sidecar with the resolved params."""

    def test_sidecar_written_with_correct_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            config_path = _write_config(tmpdir)
            _make_grid_wf_json(tmpdir, "momentum")

            result = _run_apply_params(
                tmpdir, config_path, strategy="momentum", wallet="btc_momentum"
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            sidecar = tmpdir / "artifacts" / "apply-params-btc_momentum.json"
            self.assertTrue(sidecar.exists(), msg="Sidecar file was not created")
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(data["wallet"], "btc_momentum")
            self.assertEqual(data["strategy"], "momentum")
            self.assertIn("params", data)
            self.assertIn("best_sharpe", data)
            self.assertIn("source", data)

    def test_sidecar_params_filtered_to_strategy_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            config_path = _write_config(tmpdir)
            # Add a non-strategy key to best_validated params
            artifacts_dir = tmpdir / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "strategy_type": "momentum",
                "candidates_tested": 1,
                "candidates_validated": 1,
                "results": [],
                "best_validated": {
                    "params": {
                        "momentum_lookback": 20,
                        "not_a_real_param": 999,
                    },
                    "avg_sharpe": 1.2,
                    "avg_return_pct": 3.0,
                    "total_trades": 10,
                    "validated": True,
                    "wf_avg_efficiency_ratio": 0.6,
                    "wf_oos_win_rate": 0.55,
                },
            }
            (artifacts_dir / "grid-wf-momentum-2026-03-26.json").write_text(
                json.dumps(data), encoding="utf-8"
            )

            result = _run_apply_params(
                tmpdir, config_path, strategy="momentum", wallet="btc_momentum"
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            sidecar = tmpdir / "artifacts" / "apply-params-btc_momentum.json"
            sidecar_data = json.loads(sidecar.read_text(encoding="utf-8"))
            # not_a_real_param should be filtered out since it's not in _STRATEGY_FIELD_NAMES
            self.assertNotIn("not_a_real_param", sidecar_data["params"])

    def test_no_best_validated_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            config_path = _write_config(tmpdir)
            artifacts_dir = tmpdir / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "strategy_type": "momentum",
                "candidates_tested": 1,
                "candidates_validated": 0,
                "results": [],
                "best_validated": None,
            }
            (artifacts_dir / "grid-wf-momentum-2026-03-26.json").write_text(
                json.dumps(data), encoding="utf-8"
            )

            result = _run_apply_params(
                tmpdir, config_path, strategy="momentum", wallet="btc_momentum"
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("No validated candidate", result.stdout)


if __name__ == "__main__":
    unittest.main()
