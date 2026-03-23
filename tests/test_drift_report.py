from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crypto_trader.config import DriftConfig
from crypto_trader.models import (
    BacktestBaseline,
    DriftStatus,
    StrategyRunRecord,
)
from crypto_trader.operator.drift import DriftReportGenerator


def build_baseline(total_return_pct: float) -> BacktestBaseline:
    return BacktestBaseline(
        generated_at="2026-03-24T00:00:00Z",
        symbol="KRW-BTC",
        interval="minute60",
        candle_count=200,
        config_fingerprint="fingerprint",
        total_return_pct=total_return_pct,
        win_rate=0.6,
        profit_factor=1.4,
        max_drawdown=0.1,
        trade_count=1,
        average_trade_pnl_pct=0.05,
    )


def build_run(
    realized_pnl: float,
    *,
    success: bool = True,
    market_regime: str = "sideways",
) -> StrategyRunRecord:
    return StrategyRunRecord(
        recorded_at="2026-03-23T00:00:00Z",
        symbol="KRW-BTC",
        latest_price=100.0,
        market_regime=market_regime,
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
            backtest_baseline=build_baseline(0.1),
            recent_runs=[],
        )
        self.assertEqual(report.status, DriftStatus.INSUFFICIENT_DATA)

    def test_out_of_sync_when_paper_direction_diverges_from_backtest(self) -> None:
        report = DriftReportGenerator().generate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.12),
            recent_runs=[build_run(-120.0)],
        )
        self.assertEqual(report.status, DriftStatus.OUT_OF_SYNC)

    def test_bull_regime_allows_wider_return_tolerance(self) -> None:
        generator = DriftReportGenerator(DriftConfig(bull_return_tolerance_pct=0.15))
        report = generator.generate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.12),
            recent_runs=[build_run(20.0, market_regime="bull")],
        )
        self.assertEqual(report.status, DriftStatus.CAUTION)

    def test_bear_regime_uses_tighter_return_tolerance(self) -> None:
        generator = DriftReportGenerator(DriftConfig(bear_return_tolerance_pct=0.05))
        report = generator.generate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.12),
            recent_runs=[build_run(20.0, market_regime="bear")],
        )
        self.assertEqual(report.status, DriftStatus.OUT_OF_SYNC)

    def test_on_track_when_direction_and_health_match(self) -> None:
        report = DriftReportGenerator().generate(
            symbol="KRW-BTC",
            backtest_baseline=build_baseline(0.05),
            recent_runs=[build_run(30.0), build_run(40.0)],
        )
        self.assertEqual(report.status, DriftStatus.ON_TRACK)

    def test_save_writes_report_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "drift.json"
            generator = DriftReportGenerator()
            report = generator.generate(
                symbol="KRW-BTC",
                backtest_baseline=build_baseline(0.05),
                recent_runs=[build_run(10.0)],
            )
            generator.save(report, path)
            self.assertTrue(path.exists())
