from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crypto_trader.models import BacktestResult, DriftStatus, StrategyRunRecord, TradeRecord
from crypto_trader.operator.drift import DriftReportGenerator


def build_backtest(total_return_pct: float) -> BacktestResult:
    return BacktestResult(
        initial_capital=1_000.0,
        final_equity=1_000.0 * (1.0 + total_return_pct),
        total_return_pct=total_return_pct,
        win_rate=0.6,
        profit_factor=1.4,
        max_drawdown=0.1,
        trade_log=[
            TradeRecord(
                symbol="KRW-BTC",
                entry_time=None,  # type: ignore[arg-type]
                exit_time=None,  # type: ignore[arg-type]
                entry_price=100.0,
                exit_price=105.0,
                quantity=1.0,
                pnl=5.0,
                pnl_pct=0.05,
                exit_reason="take_profit",
            )
        ],
        equity_curve=[1_000.0, 1_050.0],
    )


def build_run(realized_pnl: float, *, success: bool = True) -> StrategyRunRecord:
    return StrategyRunRecord(
        recorded_at="2026-03-23T00:00:00Z",
        symbol="KRW-BTC",
        latest_price=100.0,
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


class DriftReportGeneratorTests(unittest.TestCase):
    def test_insufficient_data_when_no_runs_exist(self) -> None:
        report = DriftReportGenerator().generate(
            symbol="KRW-BTC",
            backtest_result=build_backtest(0.1),
            recent_runs=[],
        )
        self.assertEqual(report.status, DriftStatus.INSUFFICIENT_DATA)

    def test_out_of_sync_when_paper_direction_diverges_from_backtest(self) -> None:
        report = DriftReportGenerator().generate(
            symbol="KRW-BTC",
            backtest_result=build_backtest(0.12),
            recent_runs=[build_run(-120.0)],
        )
        self.assertEqual(report.status, DriftStatus.OUT_OF_SYNC)

    def test_on_track_when_direction_and_health_match(self) -> None:
        report = DriftReportGenerator().generate(
            symbol="KRW-BTC",
            backtest_result=build_backtest(0.05),
            recent_runs=[build_run(30.0), build_run(40.0)],
        )
        self.assertEqual(report.status, DriftStatus.ON_TRACK)

    def test_save_writes_report_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "drift.json"
            generator = DriftReportGenerator()
            report = generator.generate(
                symbol="KRW-BTC",
                backtest_result=build_backtest(0.05),
                recent_runs=[build_run(10.0)],
            )
            generator.save(report, path)
            self.assertTrue(path.exists())
