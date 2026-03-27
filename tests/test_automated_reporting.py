from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.operator.automated_reporting import (
    AutomatedReportGenerator,
    build_legacy_daily_performance_summary,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_generate_daily_report_includes_wallet_metrics_positions_and_strategy_summary(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
    checkpoint = tmp_path / "runtime-checkpoint.json"
    runs = tmp_path / "strategy-runs.jsonl"
    trades = tmp_path / "paper-trades.jsonl"

    _write_json(
        checkpoint,
        {
            "generated_at": _iso(now),
            "wallet_states": {
                "momentum_btc_wallet": {
                    "strategy_type": "momentum",
                    "initial_capital": 1_000_000.0,
                    "cash": 990_000.0,
                    "realized_pnl": 5_000.0,
                    "open_positions": 1,
                    "equity": 1_015_000.0,
                    "trade_count": 1,
                    "positions": {
                        "KRW-BTC": {
                            "quantity": 0.002,
                            "entry_price": 100_000_000.0,
                            "entry_time": _iso(now - timedelta(hours=2)),
                        }
                    },
                }
            },
        },
    )
    _write_jsonl(
        runs,
        [
            {
                "recorded_at": _iso(now - timedelta(hours=1)),
                "wallet_name": "momentum_btc_wallet",
                "strategy_type": "momentum",
                "symbol": "KRW-BTC",
                "latest_price": 105_000_000.0,
                "signal_action": "buy",
                "signal_confidence": 0.81,
                "order_status": "filled",
            }
        ],
    )
    _write_jsonl(
        trades,
        [
            {
                "wallet": "momentum_btc_wallet",
                "symbol": "KRW-BTC",
                "entry_time": _iso(now - timedelta(hours=4)),
                "exit_time": _iso(now - timedelta(hours=3)),
                "pnl": 5_000.0,
                "pnl_pct": 0.005,
            }
        ],
    )

    report = AutomatedReportGenerator().generate(
        checkpoint_path=checkpoint,
        strategy_run_journal_path=runs,
        trade_journal_path=trades,
        period="daily",
        hours=24,
    )

    assert report.period == "daily"
    assert report.total_open_positions == 1
    assert report.portfolio_trades == 1
    assert len(report.wallets) == 1
    assert len(report.wallets[0].positions) == 1
    assert report.wallets[0].positions[0].symbol == "KRW-BTC"
    assert report.wallets[0].positions[0].latest_price == 105_000_000.0
    assert report.strategies[0].wallet_name == "momentum_btc_wallet"


def test_save_writes_markdown_json_and_legacy_daily_summary(tmp_path: Path) -> None:
    now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
    checkpoint = tmp_path / "runtime-checkpoint.json"
    runs = tmp_path / "strategy-runs.jsonl"
    trades = tmp_path / "paper-trades.jsonl"
    _write_json(
        checkpoint,
        {
            "generated_at": _iso(now),
            "wallet_states": {
                "volspike_btc_wallet": {
                    "strategy_type": "volume_spike",
                    "initial_capital": 500_000.0,
                    "cash": 500_000.0,
                    "realized_pnl": 0.0,
                    "open_positions": 0,
                    "equity": 500_000.0,
                    "trade_count": 0,
                    "positions": {},
                }
            },
        },
    )
    _write_jsonl(runs, [])
    _write_jsonl(trades, [])

    generator = AutomatedReportGenerator()
    report = generator.generate(
        checkpoint_path=checkpoint,
        strategy_run_journal_path=runs,
        trade_journal_path=trades,
        period="weekly",
        hours=168,
    )
    output_path = tmp_path / "artifacts" / "weekly-report.md"
    generator.save(report, output_path)
    legacy_summary = build_legacy_daily_performance_summary(
        report,
        report_path=output_path,
    )

    assert output_path.exists()
    assert output_path.with_suffix(".json").exists()
    assert "Weekly Summary Report" in output_path.read_text(encoding="utf-8")
    assert legacy_summary["report_path"].endswith("weekly-report.md")
