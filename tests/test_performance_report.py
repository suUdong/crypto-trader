"""Tests for performance report helpers."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.operator.performance_report import (
    build_artifact_health_section,
    build_readiness_section,
    compute_paper_days,
    compute_profit_factor,
    generate_performance_report,
)
from crypto_trader.operator.pnl_report import PortfolioPnLReport, StrategyPnLMetrics


def _write_checkpoint(path: Path, *, generated_at: str | None = None) -> None:
    ts = generated_at or datetime.now(UTC).isoformat()
    data = {
        "generated_at": ts,
        "iteration": 50,
        "session_id": "session-123",
        "config_path": "config/test.toml",
        "symbols": ["KRW-BTC", "KRW-ETH"],
        "wallet_names": ["momentum_wallet", "mean_reversion_wallet", "obi_wallet"],
        "wallet_states": {
            "momentum_wallet": {
                "strategy_type": "momentum",
                "cash": 800_000,
                "realized_pnl": 25_000,
                "open_positions": 1,
                "equity": 1_050_000,
                "trade_count": 15,
            },
            "mean_reversion_wallet": {
                "strategy_type": "mean_reversion",
                "cash": 700_000,
                "realized_pnl": 12_000,
                "open_positions": 2,
                "equity": 1_030_000,
                "trade_count": 10,
            },
            "obi_wallet": {
                "strategy_type": "obi",
                "cash": 980_000,
                "realized_pnl": -5_000,
                "open_positions": 0,
                "equity": 990_000,
                "trade_count": 5,
            },
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_journal(path: Path, *, first_ts: str | None = None) -> None:
    ts = first_ts or (datetime.now(UTC) - timedelta(days=10)).isoformat()
    trades = [
        {"wallet": "momentum_wallet", "pnl": 5000, "timestamp": ts},
        {"wallet": "momentum_wallet", "pnl": 3000, "timestamp": ts},
        {"wallet": "momentum_wallet", "pnl": -1000, "timestamp": ts},
        {"wallet": "mean_reversion_wallet", "pnl": 4000, "timestamp": ts},
        {"wallet": "mean_reversion_wallet", "pnl": -500, "timestamp": ts},
        {"wallet": "obi_wallet", "pnl": -2000, "timestamp": ts},
    ]
    path.write_text("\n".join(json.dumps(t) for t in trades), encoding="utf-8")


def _write_heartbeat(
    path: Path,
    *,
    session_id: str = "session-123",
    symbols: list[str] | None = None,
    wallet_names: list[str] | None = None,
) -> None:
    payload = {
        "last_heartbeat": datetime.now(UTC).isoformat(),
        "pid": 1234,
        "iteration": 50,
        "uptime_seconds": 120.0,
        "poll_interval_seconds": 60,
        "session_id": session_id,
        "config_path": "config/test.toml",
        "symbols": symbols or ["KRW-BTC", "KRW-ETH"],
        "wallet_names": wallet_names or ["momentum_wallet", "mean_reversion_wallet", "obi_wallet"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestGenerateReport(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.checkpoint = self.tmp / "runtime-checkpoint.json"
        self.heartbeat = self.tmp / "daemon-heartbeat.json"
        self.journal = self.tmp / "paper-trades.jsonl"
        _write_checkpoint(self.checkpoint)
        _write_heartbeat(self.heartbeat)
        _write_journal(self.journal)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_report_has_72h_header(self) -> None:
        md = generate_performance_report(self.checkpoint, self.journal)
        self.assertIn("## 72-Hour Performance Report", md)

    def test_report_has_portfolio_summary(self) -> None:
        md = generate_performance_report(self.checkpoint, self.journal)
        self.assertIn("Portfolio Summary", md)

    def test_report_has_micro_live_readiness_section(self) -> None:
        md = generate_performance_report(self.checkpoint, self.journal)
        self.assertIn("## Micro-Live Readiness", md)

    def test_report_contains_strategy_names(self) -> None:
        md = generate_performance_report(self.checkpoint, self.journal)
        self.assertIn("momentum", md)
        self.assertIn("mean_reversion", md)

    def test_report_missing_checkpoint_still_returns_markdown(self) -> None:
        md = generate_performance_report(self.tmp / "nonexistent.json", self.journal)
        self.assertIn("## 72-Hour Performance Report", md)
        self.assertIn("## Micro-Live Readiness", md)

    def test_report_has_artifact_health_section(self) -> None:
        md = generate_performance_report(self.checkpoint, self.journal)
        self.assertIn("## Artifact Health", md)
        self.assertIn("HEALTHY", md)

    def test_report_warns_when_heartbeat_missing(self) -> None:
        self.heartbeat.unlink()
        md = generate_performance_report(self.checkpoint, self.journal)
        self.assertIn("WARNING (missing_heartbeat)", md)
        self.assertIn("point-in-time diagnostic summary", md)

    def test_report_warns_when_artifacts_are_stale(self) -> None:
        stale_ts = "2026-03-20T00:00:00+00:00"
        _write_checkpoint(self.checkpoint, generated_at=stale_ts)
        self.heartbeat.write_text(
            json.dumps(
                {
                    "last_heartbeat": stale_ts,
                    "pid": 1234,
                    "iteration": 50,
                    "uptime_seconds": 120.0,
                    "poll_interval_seconds": 60,
                    "session_id": "session-123",
                    "config_path": "config/test.toml",
                    "symbols": ["KRW-BTC", "KRW-ETH"],
                    "wallet_names": ["momentum_wallet", "mean_reversion_wallet", "obi_wallet"],
                }
            ),
            encoding="utf-8",
        )
        md = generate_performance_report(self.checkpoint, self.journal)
        self.assertIn("WARNING (stale_artifacts)", md)
        self.assertIn("Freshness status | stale_artifacts |", md)


class TestComputePaperDays(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_paper_days_from_journal_timestamp(self) -> None:
        journal = self.tmp / "trades.jsonl"
        ten_days_ago = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        _write_journal(journal, first_ts=ten_days_ago)
        checkpoint = self.tmp / "cp.json"
        _write_checkpoint(checkpoint)
        days = compute_paper_days(checkpoint, journal)
        self.assertGreaterEqual(days, 9)

    def test_paper_days_from_checkpoint_when_no_journal(self) -> None:
        checkpoint = self.tmp / "cp.json"
        five_days_ago = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        _write_checkpoint(checkpoint, generated_at=five_days_ago)
        missing_journal = self.tmp / "no-journal.jsonl"
        days = compute_paper_days(checkpoint, missing_journal)
        self.assertGreaterEqual(days, 4)

    def test_paper_days_zero_when_both_missing(self) -> None:
        days = compute_paper_days(
            self.tmp / "no-cp.json",
            self.tmp / "no-journal.jsonl",
        )
        self.assertEqual(days, 0)


class TestComputeProfitFactor(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_profit_factor_computed_correctly(self) -> None:
        journal = self.tmp / "trades.jsonl"
        trades = [
            {"pnl": 100},
            {"pnl": 200},
            {"pnl": -50},
            {"pnl": -100},
        ]
        journal.write_text("\n".join(json.dumps(t) for t in trades), encoding="utf-8")
        pf = compute_profit_factor(journal)
        # gross_profit=300, gross_loss=150 -> PF=2.0
        self.assertAlmostEqual(pf, 2.0)

    def test_profit_factor_zero_when_no_losses(self) -> None:
        journal = self.tmp / "trades.jsonl"
        journal.write_text(json.dumps({"pnl": 0}), encoding="utf-8")
        pf = compute_profit_factor(journal)
        self.assertEqual(pf, 0.0)

    def test_profit_factor_inf_when_no_losses_with_profit(self) -> None:
        journal = self.tmp / "trades.jsonl"
        journal.write_text(json.dumps({"pnl": 500}), encoding="utf-8")
        pf = compute_profit_factor(journal)
        self.assertEqual(pf, float("inf"))

    def test_profit_factor_missing_journal(self) -> None:
        pf = compute_profit_factor(self.tmp / "missing.jsonl")
        self.assertEqual(pf, 0.0)


class TestMicroLiveReadinessSection(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.checkpoint = self.tmp / "runtime-checkpoint.json"
        self.journal = self.tmp / "paper-trades.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_report(self) -> object:
        from crypto_trader.operator.pnl_report import PnLReportGenerator

        _write_checkpoint(self.checkpoint)
        _write_journal(self.journal)
        gen = PnLReportGenerator()
        return gen.generate_from_checkpoint(self.checkpoint, self.journal, period="72h")

    def test_readiness_section_contains_criteria_table(self) -> None:
        report = self._make_report()
        section = build_readiness_section(report, self.checkpoint, self.journal)
        self.assertIn("| Criterion |", section)
        self.assertIn("Paper days", section)
        self.assertIn("Win rate", section)
        self.assertIn("Profit factor", section)

    def test_not_ready_when_no_paper_days(self) -> None:
        # Checkpoint is just-now, journal also just-now -> 0 days
        _write_checkpoint(self.checkpoint)
        ts_now = datetime.now(UTC).isoformat()
        trades = [{"wallet": "momentum_wallet", "pnl": 100, "timestamp": ts_now}]
        self.journal.write_text(json.dumps(trades[0]), encoding="utf-8")
        from crypto_trader.operator.pnl_report import PnLReportGenerator

        gen = PnLReportGenerator()
        report = gen.generate_from_checkpoint(self.checkpoint, self.journal, period="72h")
        section = build_readiness_section(report, self.checkpoint, self.journal)
        self.assertIn("NOT READY", section)

    def test_ready_label_shown_when_all_criteria_met(self) -> None:
        # Setup: 10 days ago journal, many profitable trades
        ten_days_ago = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        _write_journal(self.journal, first_ts=ten_days_ago)
        # Build a report that has >=45% win rate, low MDD, >=2 positive strategies
        _write_checkpoint(self.checkpoint)
        # Override report to guarantee all metrics pass
        report = PortfolioPnLReport(
            generated_at=datetime.now(UTC).isoformat(),
            period="72h",
            strategies=[
                StrategyPnLMetrics(
                    strategy="momentum",
                    wallet="momentum_wallet",
                    total_return_pct=5.0,
                    realized_pnl=50000,
                    unrealized_pnl=0,
                    trade_count=15,
                    win_count=9,
                    loss_count=6,
                    win_rate=0.6,
                    profit_factor=1.5,
                    max_drawdown_pct=0.0,
                    sharpe_ratio=1.2,
                    equity=1_050_000,
                    initial_capital=1_000_000,
                ),
                StrategyPnLMetrics(
                    strategy="mean_reversion",
                    wallet="mean_reversion_wallet",
                    total_return_pct=3.0,
                    realized_pnl=30000,
                    unrealized_pnl=0,
                    trade_count=10,
                    win_count=6,
                    loss_count=4,
                    win_rate=0.6,
                    profit_factor=1.5,
                    max_drawdown_pct=0.0,
                    sharpe_ratio=1.0,
                    equity=1_030_000,
                    initial_capital=1_000_000,
                ),
            ],
            portfolio_return_pct=4.0,
            portfolio_sharpe=1.1,
            portfolio_mdd=3.0,  # 3% -> 0.03 as fraction
            portfolio_win_rate=0.6,
            total_trades=25,
            total_realized_pnl=80000,
            total_equity=2_080_000,
            total_initial_capital=2_000_000,
        )
        section = build_readiness_section(report, self.checkpoint, self.journal)
        self.assertIn("READY", section)

    def test_details_list_reasons(self) -> None:
        report = self._make_report()
        section = build_readiness_section(report, self.checkpoint, self.journal)
        self.assertIn("### Details", section)


class TestArtifactHealthSection(unittest.TestCase):
    def test_health_section_warns_on_session_mismatch(self) -> None:
        report = PortfolioPnLReport(
            generated_at=datetime.now(UTC).isoformat(),
            period="72h",
            strategies=[],
            portfolio_return_pct=0.0,
            portfolio_sharpe=0.0,
            portfolio_mdd=0.0,
            portfolio_win_rate=0.0,
            total_trades=0,
            total_realized_pnl=0.0,
            total_equity=0.0,
            total_initial_capital=0.0,
            source_generated_at="2026-03-26T00:00:00+00:00",
            source_session_id="session-a",
            heartbeat_generated_at="2026-03-26T00:00:05+00:00",
            heartbeat_session_id="session-b",
            heartbeat_poll_interval_seconds=60,
            artifact_consistency_status="session_mismatch",
            artifact_consistency_reason="checkpoint and heartbeat session ids differ",
        )
        section = build_artifact_health_section(report)
        self.assertIn("WARNING (session_mismatch)", section)
        self.assertIn("checkpoint and heartbeat session ids differ", section)

    def test_health_section_warns_on_stale_heartbeat(self) -> None:
        report = PortfolioPnLReport(
            generated_at="2026-03-26T01:00:00+00:00",
            period="72h",
            strategies=[],
            portfolio_return_pct=0.0,
            portfolio_sharpe=0.0,
            portfolio_mdd=0.0,
            portfolio_win_rate=0.0,
            total_trades=0,
            total_realized_pnl=0.0,
            total_equity=0.0,
            total_initial_capital=0.0,
            source_generated_at="2026-03-26T00:59:00+00:00",
            source_session_id="session-a",
            heartbeat_generated_at="2026-03-26T00:40:00+00:00",
            heartbeat_session_id="session-a",
            heartbeat_poll_interval_seconds=60,
            artifact_consistency_status="consistent",
            artifact_consistency_reason="checkpoint and heartbeat align",
        )
        section = build_artifact_health_section(report)
        self.assertIn("WARNING (stale_heartbeat)", section)
        self.assertIn("Heartbeat age | 20m 0s (stale)", section)


if __name__ == "__main__":
    unittest.main()
