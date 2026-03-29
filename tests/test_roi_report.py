from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.operator.roi_report import RoiReportGenerator


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _write_config(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_generate_uses_runtime_baseline_and_aggregates_strategy_contributions(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "daemon.toml"
    checkpoint_path = tmp_path / "runtime-checkpoint.json"
    runs_path = tmp_path / "strategy-runs.jsonl"

    _write_config(
        config_path,
        """
[[wallets]]
name = "m1"
strategy = "momentum"
initial_capital = 600000.0

[[wallets]]
name = "v1"
strategy = "vpin"
initial_capital = 500000.0
""".strip(),
    )
    _write_json(
        checkpoint_path,
        {
            "generated_at": "2026-03-27T22:00:00+00:00",
            "wallet_states": {
                "m1": {
                    "strategy_type": "momentum",
                    "initial_capital": 500_000.0,
                    "cash": 499_000.0,
                    "realized_pnl": -700.0,
                    "open_positions": 1,
                    "equity": 499_000.0,
                    "positions": {
                        "KRW-BTC": {
                            "quantity": 1.0,
                            "entry_price": 1_000.0,
                            "market_price": 700.0,
                        }
                    },
                },
                "v1": {
                    "strategy_type": "vpin",
                    "initial_capital": 500_000.0,
                    "cash": 499_500.0,
                    "realized_pnl": -500.0,
                    "open_positions": 0,
                    "equity": 499_500.0,
                    "positions": {},
                },
            },
        },
    )
    _write_jsonl(runs_path, [])

    report = RoiReportGenerator().generate(
        config_path=config_path,
        checkpoint_path=checkpoint_path,
        strategy_runs_path=runs_path,
        current_equity=998_500.0,
        report_month="2026-03",
        generated_at=datetime(2026, 3, 27, 22, 30, tzinfo=UTC),
    )

    assert report.baseline.runtime_start_capital == 1_000_000.0
    assert report.baseline.config_start_capital == 1_100_000.0
    assert report.baseline.headline_pnl == -1_500.0
    assert round(report.baseline.headline_return_pct, 4) == -0.15
    assert report.baseline.config_pnl == -101_500.0

    assert [row.strategy for row in report.strategy_contributions] == ["momentum", "vpin"]
    assert report.strategy_contributions[0].pnl == -1_000.0
    assert report.strategy_contributions[0].contribution_pct == 66.66666666666666
    assert report.strategy_contributions[1].pnl == -500.0
    assert report.strategy_contributions[1].contribution_pct == 33.33333333333333


def test_generate_reconstructs_session_curve_and_daily_weekly_curves(tmp_path: Path) -> None:
    config_path = tmp_path / "daemon.toml"
    checkpoint_path = tmp_path / "runtime-checkpoint.json"
    runs_path = tmp_path / "strategy-runs.jsonl"

    _write_config(
        config_path,
        """
[[wallets]]
name = "trend_wallet"
strategy = "momentum"
initial_capital = 1000000.0

[[wallets]]
name = "cash_wallet"
strategy = "vpin"
initial_capital = 500000.0
""".strip(),
    )
    _write_json(
        checkpoint_path,
        {
            "generated_at": "2026-03-27T16:20:00+00:00",
            "wallet_states": {
                "trend_wallet": {
                    "strategy_type": "momentum",
                    "initial_capital": 1_000_000.0,
                    "cash": 900_000.0,
                    "realized_pnl": 0.0,
                    "open_positions": 1,
                    "equity": 1_020_000.0,
                    "positions": {
                        "KRW-BTC": {
                            "quantity": 1_000.0,
                            "entry_price": 100.0,
                            "market_price": 120.0,
                        }
                    },
                },
                "cash_wallet": {
                    "strategy_type": "vpin",
                    "initial_capital": 500_000.0,
                    "cash": 500_000.0,
                    "realized_pnl": 0.0,
                    "open_positions": 0,
                    "equity": 500_000.0,
                    "positions": {},
                },
            },
        },
    )
    _write_jsonl(
        runs_path,
        [
            {
                "wallet_name": "trend_wallet",
                "recorded_at": "2026-03-27T14:00:00+00:00",
                "symbol": "KRW-BTC",
                "latest_price": 100.0,
                "cash": 900_000.0,
                "open_positions": 1,
            },
            {
                "wallet_name": "cash_wallet",
                "recorded_at": "2026-03-27T14:00:30+00:00",
                "symbol": "KRW-ETH",
                "latest_price": 10.0,
                "cash": 500_000.0,
                "open_positions": 0,
            },
            {
                "wallet_name": "trend_wallet",
                "recorded_at": "2026-03-27T16:00:00+00:00",
                "symbol": "KRW-BTC",
                "latest_price": 110.0,
                "cash": 900_000.0,
                "open_positions": 1,
            },
        ],
    )

    report = RoiReportGenerator().generate(
        config_path=config_path,
        checkpoint_path=checkpoint_path,
        strategy_runs_path=runs_path,
        current_equity=1_530_000.0,
        report_month="2026-03",
        generated_at=datetime(2026, 3, 27, 16, 30, tzinfo=UTC),
    )

    assert report.session_curve[0].equity == 1_500_000.0
    assert report.session_curve[-1].equity == 1_530_000.0
    assert any(point.label == "2026-03-27" for point in report.daily_curve)
    assert any(point.label == "2026-03-28" for point in report.daily_curve)
    assert len(report.weekly_curve) == 1
    assert report.weekly_curve[0].label == "2026-W13"


def test_markdown_contains_required_sections(tmp_path: Path) -> None:
    config_path = tmp_path / "daemon.toml"
    checkpoint_path = tmp_path / "runtime-checkpoint.json"
    runs_path = tmp_path / "strategy-runs.jsonl"

    _write_config(
        config_path,
        """
[[wallets]]
name = "wallet"
strategy = "momentum"
initial_capital = 1000000.0
""".strip(),
    )
    _write_json(
        checkpoint_path,
        {
            "generated_at": "2026-03-27T22:00:00+00:00",
            "wallet_states": {
                "wallet": {
                    "strategy_type": "momentum",
                    "initial_capital": 1_000_000.0,
                    "cash": 999_500.0,
                    "realized_pnl": -500.0,
                    "open_positions": 0,
                    "equity": 999_500.0,
                    "positions": {},
                }
            },
        },
    )
    _write_jsonl(runs_path, [])

    generator = RoiReportGenerator()
    report = generator.generate(
        config_path=config_path,
        checkpoint_path=checkpoint_path,
        strategy_runs_path=runs_path,
        current_equity=999_500.0,
        report_month="2026-03",
        generated_at=datetime(2026, 3, 27, 22, 30, tzinfo=UTC),
    )
    markdown = generator.to_markdown(report)

    assert "# ROI Report 2026-03" in markdown
    assert "## Starting Capital Check" in markdown
    assert "## Strategy Contribution" in markdown
    assert "## Daily Profit Curve" in markdown
    assert "## Weekly Profit Curve" in markdown
    assert "## Assumptions" in markdown
