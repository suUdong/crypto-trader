from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crypto_trader.models import (
    BacktestBaseline,
    DriftCalibrationEntry,
    DriftCalibrationReport,
    DriftReport,
    DriftStatus,
    PromotionGateDecision,
    PromotionStatus,
    RegimeReport,
)
from crypto_trader.operator.report import OperatorReportBuilder


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


def build_regime_report() -> RegimeReport:
    return RegimeReport(
        generated_at="2026-03-24T00:00:00Z",
        symbol="KRW-BTC",
        market_regime="bull",
        short_return_pct=0.05,
        long_return_pct=0.12,
        base_parameters={"max_holding_bars": 24},
        adjusted_parameters={"max_holding_bars": 32},
        reasons=["trend is positive"],
    )


def build_drift() -> DriftReport:
    return DriftReport(
        generated_at="2026-03-24T00:00:00Z",
        symbol="KRW-BTC",
        status=DriftStatus.ON_TRACK,
        reasons=["aligned"],
        backtest_total_return_pct=0.1,
        backtest_win_rate=0.6,
        backtest_max_drawdown=0.1,
        backtest_trade_count=5,
        paper_run_count=6,
        paper_error_rate=0.0,
        paper_buy_rate=0.1,
        paper_sell_rate=0.1,
        paper_hold_rate=0.8,
        paper_realized_pnl_pct=0.04,
    )


def build_promotion() -> PromotionGateDecision:
    return PromotionGateDecision(
        generated_at="2026-03-24T00:00:00Z",
        symbol="KRW-BTC",
        status=PromotionStatus.STAY_IN_PAPER,
        reasons=["need more runs"],
        minimum_paper_runs_required=5,
        observed_paper_runs=2,
        backtest_total_return_pct=0.1,
        paper_realized_pnl_pct=0.04,
        drift_status=DriftStatus.ON_TRACK,
    )


def build_calibration() -> DriftCalibrationReport:
    return DriftCalibrationReport(
        generated_at="2026-03-24T00:00:00Z",
        symbol="KRW-BTC",
        entries=[
            DriftCalibrationEntry(
                regime="bull",
                sample_count=5,
                average_abs_return_gap_pct=0.02,
                suggested_return_tolerance_pct=0.03,
                observed_error_rate=0.0,
                suggested_error_rate_threshold=0.05,
            )
        ],
    )


class OperatorReportBuilderTests(unittest.TestCase):
    def test_build_contains_all_sections(self) -> None:
        report = OperatorReportBuilder().build(
            baseline=build_baseline(),
            regime_report=build_regime_report(),
            drift_report=build_drift(),
            promotion_decision=build_promotion(),
            memo="# memo",
            calibration_report=build_calibration(),
        )
        self.assertIn("# Operator Report", report.report_markdown)
        self.assertIn("## Baseline", report.report_markdown)
        self.assertIn("## Regime", report.report_markdown)
        self.assertIn("## Drift", report.report_markdown)
        self.assertIn("## Promotion", report.report_markdown)
        self.assertIn("## Calibration", report.report_markdown)

    def test_save_writes_operator_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "operator-report.md"
            report = OperatorReportBuilder().build(
                baseline=build_baseline(),
                regime_report=build_regime_report(),
                drift_report=build_drift(),
                promotion_decision=build_promotion(),
                memo="# memo",
                calibration_report=None,
            )
            OperatorReportBuilder().save(report, path)
            self.assertTrue(path.exists())
