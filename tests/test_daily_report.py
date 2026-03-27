"""Tests for the daily performance report generation."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.monitoring.performance_reporter import PerformanceReporter, PerformanceSummary


def _write_strategy_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8",
    )


def _write_trade_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8",
    )


class TestPerformanceReporter(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.strategy_path = self.tmp / "strategy-runs.jsonl"
        self.trade_path = self.tmp / "paper-trades.jsonl"
        now = datetime.now(UTC)
        self._now = now

        # Create strategy run records
        strategy_records = []
        for i in range(10):
            strategy_records.append(
                {
                    "recorded_at": (now - timedelta(hours=i)).isoformat(),
                    "wallet_name": "momentum_wallet",
                    "strategy_type": "momentum",
                    "symbol": "KRW-BTC",
                    "signal_action": ["buy", "sell", "hold"][i % 3],
                    "signal_confidence": 0.7 + (i % 3) * 0.1,
                    "order_status": "filled" if i % 3 != 2 else None,
                }
            )
        _write_strategy_records(self.strategy_path, strategy_records)

        # Create trade records
        trade_records = []
        for i in range(5):
            trade_records.append(
                {
                    "exit_time": (now - timedelta(hours=i)).isoformat(),
                    "wallet": "momentum_wallet",
                    "pnl": 1000.0 if i % 2 == 0 else -500.0,
                    "pnl_pct": 0.01 if i % 2 == 0 else -0.005,
                }
            )
        _write_trade_records(self.trade_path, trade_records)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generate_returns_summary(self) -> None:
        reporter = PerformanceReporter(self.trade_path, self.strategy_path)
        summary = reporter.generate(period="daily", hours=24)
        self.assertIsInstance(summary, PerformanceSummary)
        self.assertEqual(summary.period, "daily")
        self.assertGreater(len(summary.strategies), 0)

    def test_generate_weekly(self) -> None:
        reporter = PerformanceReporter(self.trade_path, self.strategy_path)
        summary = reporter.generate(period="weekly", hours=168)
        self.assertEqual(summary.period, "weekly")

    def test_strategy_performance_counts(self) -> None:
        reporter = PerformanceReporter(self.trade_path, self.strategy_path)
        summary = reporter.generate(period="daily", hours=48)
        perf = summary.strategies[0]
        self.assertEqual(perf.wallet_name, "momentum_wallet")
        self.assertGreater(perf.total_signals, 0)
        self.assertGreater(perf.trades_executed, 0)

    def test_win_rate_calculation(self) -> None:
        reporter = PerformanceReporter(self.trade_path, self.strategy_path)
        summary = reporter.generate(period="daily", hours=48)
        perf = summary.strategies[0]
        # 3 wins, 2 losses -> 60% win rate
        self.assertAlmostEqual(perf.win_rate, 0.6)

    def test_pnl_calculation(self) -> None:
        reporter = PerformanceReporter(self.trade_path, self.strategy_path)
        summary = reporter.generate(period="daily", hours=48)
        perf = summary.strategies[0]
        # 3 * 1000 + 2 * (-500) = 2000
        self.assertAlmostEqual(perf.total_pnl, 2000.0)

    def test_notification_text_format(self) -> None:
        reporter = PerformanceReporter(self.trade_path, self.strategy_path)
        summary = reporter.generate(period="daily", hours=48)
        text = reporter.to_notification_text(summary)
        self.assertIn("Daily Performance Report", text)
        self.assertIn("Portfolio:", text)
        self.assertIn("momentum_wallet", text)
        self.assertIn("KRW", text)

    def test_save_json(self) -> None:
        reporter = PerformanceReporter(self.trade_path, self.strategy_path)
        summary = reporter.generate(period="daily", hours=24)
        output = self.tmp / "output.json"
        reporter.save_json(summary, output)
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["period"], "daily")
        self.assertIn("strategies", data)
        self.assertIn("portfolio_pnl", data)

    def test_empty_journals_returns_empty_summary(self) -> None:
        empty_strategy = self.tmp / "empty-strat.jsonl"
        empty_trade = self.tmp / "empty-trade.jsonl"
        empty_strategy.write_text("", encoding="utf-8")
        empty_trade.write_text("", encoding="utf-8")
        reporter = PerformanceReporter(empty_trade, empty_strategy)
        summary = reporter.generate(period="daily", hours=24)
        self.assertEqual(len(summary.strategies), 0)
        self.assertAlmostEqual(summary.portfolio_pnl, 0.0)

    def test_missing_journals_returns_empty_summary(self) -> None:
        reporter = PerformanceReporter(
            self.tmp / "nonexistent-trade.jsonl",
            self.tmp / "nonexistent-strat.jsonl",
        )
        summary = reporter.generate(period="daily", hours=24)
        self.assertEqual(len(summary.strategies), 0)

    def test_portfolio_level_aggregation(self) -> None:
        reporter = PerformanceReporter(self.trade_path, self.strategy_path)
        summary = reporter.generate(period="daily", hours=48)
        self.assertEqual(
            summary.portfolio_trades, sum(s.trades_executed for s in summary.strategies)
        )
        self.assertAlmostEqual(summary.portfolio_pnl, sum(s.total_pnl for s in summary.strategies))


if __name__ == "__main__":
    unittest.main()
