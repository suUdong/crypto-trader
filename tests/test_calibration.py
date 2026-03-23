from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crypto_trader.models import BacktestBaseline, DriftCalibrationReport, StrategyRunRecord
from crypto_trader.operator.calibration import DriftCalibrationToolkit


def build_run(realized_pnl: float, regime: str, *, success: bool = True) -> StrategyRunRecord:
    return StrategyRunRecord(
        recorded_at="2026-03-24T00:00:00Z",
        symbol="KRW-BTC",
        latest_price=100.0,
        market_regime=regime,
        signal_action="hold",
        signal_reason="noop",
        signal_confidence=0.5,
        order_status=None,
        order_side=None,
        session_starting_equity=1_000.0,
        cash=1_000.0 + realized_pnl,
        open_positions=0,
        realized_pnl=realized_pnl,
        success=success,
        error=None if success else "error",
        consecutive_failures=0,
        verdict_status="continue_paper",
        verdict_confidence=0.6,
        verdict_reasons=[],
    )


def build_baseline() -> BacktestBaseline:
    return BacktestBaseline(
        generated_at="2026-03-24T00:00:00Z",
        symbol="KRW-BTC",
        interval="minute60",
        candle_count=200,
        config_fingerprint="fingerprint",
        total_return_pct=0.1,
        win_rate=0.6,
        profit_factor=1.4,
        max_drawdown=0.1,
        trade_count=5,
        average_trade_pnl_pct=0.03,
    )


class DriftCalibrationToolkitTests(unittest.TestCase):
    def test_generate_groups_runs_by_regime(self) -> None:
        report = DriftCalibrationToolkit().generate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(),
            recent_runs=[
                build_run(20.0, "bull"),
                build_run(10.0, "bull"),
                build_run(-10.0, "bear", success=False),
            ],
        )
        regimes = {entry.regime for entry in report.entries}
        self.assertEqual(regimes, {"bear", "bull"})

    def test_generate_suggests_nonzero_thresholds(self) -> None:
        report = DriftCalibrationToolkit().generate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(),
            recent_runs=[build_run(20.0, "bull")],
        )
        self.assertGreater(report.entries[0].suggested_return_tolerance_pct, 0.0)
        self.assertGreater(report.entries[0].suggested_error_rate_threshold, 0.0)

    def test_save_writes_calibration_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "calibration.json"
            report = DriftCalibrationReport(
                generated_at="2026-03-24T00:00:00Z",
                symbol="KRW-BTC",
                entries=[],
            )
            DriftCalibrationToolkit().save(report, path)
            self.assertTrue(path.exists())
