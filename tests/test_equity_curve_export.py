"""Tests for equity curve JSON export logic."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.models import BacktestResult


def _make_backtest_result(equity_curve: list[float]) -> BacktestResult:
    return BacktestResult(
        initial_capital=1_000_000.0,
        final_equity=equity_curve[-1] if equity_curve else 1_000_000.0,
        total_return_pct=(equity_curve[-1] / 1_000_000.0 - 1.0) if equity_curve else 0.0,
        win_rate=0.6,
        profit_factor=1.5,
        max_drawdown=0.05,
        trade_log=[],
        equity_curve=equity_curve,
    )


def _export_equity_curve(
    backtest_result: BacktestResult,
    strategy: str,
    symbol: str,
    artifacts_dir: Path,
) -> Path:
    """Replicate the export logic from the backtest CLI command."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    curve_data = {
        "strategy": strategy,
        "symbol": symbol,
        "initial_capital": backtest_result.initial_capital,
        "final_equity": backtest_result.final_equity,
        "total_return_pct": backtest_result.total_return_pct,
        "equity_curve": backtest_result.equity_curve,
    }
    curve_path = artifacts_dir / f"equity-curve-{strategy}.json"
    curve_path.write_text(json.dumps(curve_data, indent=2), encoding="utf-8")
    return curve_path


class TestEquityCurveExport(unittest.TestCase):
    def test_json_structure_has_required_keys(self) -> None:
        equity_curve = [1_000_000.0, 1_010_000.0, 1_020_000.0]
        result = _make_backtest_result(equity_curve)

        with tempfile.TemporaryDirectory() as tmp:
            curve_path = _export_equity_curve(result, "momentum", "KRW-BTC", Path(tmp))
            data = json.loads(curve_path.read_text(encoding="utf-8"))

        required_keys = {
            "strategy",
            "symbol",
            "initial_capital",
            "final_equity",
            "total_return_pct",
            "equity_curve",
        }
        self.assertEqual(required_keys, set(data.keys()))

    def test_equity_curve_length_matches(self) -> None:
        equity_curve = [1_000_000.0 + i * 5_000.0 for i in range(50)]
        result = _make_backtest_result(equity_curve)

        with tempfile.TemporaryDirectory() as tmp:
            curve_path = _export_equity_curve(result, "composite", "KRW-BTC", Path(tmp))
            data = json.loads(curve_path.read_text(encoding="utf-8"))

        self.assertEqual(len(data["equity_curve"]), 50)

    def test_equity_curve_values_round_trip(self) -> None:
        equity_curve = [1_000_000.0, 1_005_000.0, 998_000.0, 1_012_000.0]
        result = _make_backtest_result(equity_curve)

        with tempfile.TemporaryDirectory() as tmp:
            curve_path = _export_equity_curve(result, "mean_reversion", "KRW-ETH", Path(tmp))
            data = json.loads(curve_path.read_text(encoding="utf-8"))

        self.assertEqual(data["equity_curve"], equity_curve)
        self.assertEqual(data["strategy"], "mean_reversion")
        self.assertEqual(data["symbol"], "KRW-ETH")

    def test_filename_includes_strategy_name(self) -> None:
        result = _make_backtest_result([1_000_000.0])

        with tempfile.TemporaryDirectory() as tmp:
            curve_path = _export_equity_curve(result, "volatility_breakout", "KRW-BTC", Path(tmp))
            self.assertEqual(curve_path.name, "equity-curve-volatility_breakout.json")
            self.assertTrue(curve_path.exists())

    def test_empty_equity_curve_exports_cleanly(self) -> None:
        result = _make_backtest_result([])

        with tempfile.TemporaryDirectory() as tmp:
            curve_path = _export_equity_curve(result, "momentum", "KRW-BTC", Path(tmp))
            data = json.loads(curve_path.read_text(encoding="utf-8"))

        self.assertEqual(data["equity_curve"], [])
        self.assertEqual(len(data["equity_curve"]), 0)


if __name__ == "__main__":
    unittest.main()
