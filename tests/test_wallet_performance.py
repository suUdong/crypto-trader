"""Tests for recent wallet performance reporting."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.operator.wallet_performance import WalletPerformanceReportGenerator


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_generate_marks_open_positions_to_market_for_wallet_curve(tmp_path: Path) -> None:
    now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
    entry_time = now - timedelta(hours=3)
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
                    "realized_pnl": 0.0,
                    "open_positions": 1,
                    "equity": 1_000_200.0,
                    "trade_count": 0,
                    "positions": {
                        "KRW-BTC": {
                            "quantity": 100.0,
                            "entry_price": 100.0,
                            "entry_time": _iso(entry_time),
                            "entry_fee_paid": 0.0,
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
                "wallet_name": "momentum_btc_wallet",
                "recorded_at": _iso(entry_time),
                "symbol": "KRW-BTC",
                "latest_price": 101.0,
            },
            {
                "wallet_name": "momentum_btc_wallet",
                "recorded_at": _iso(entry_time + timedelta(hours=1)),
                "symbol": "KRW-BTC",
                "latest_price": 98.0,
            },
            {
                "wallet_name": "momentum_btc_wallet",
                "recorded_at": _iso(now),
                "symbol": "KRW-BTC",
                "latest_price": 102.0,
            },
        ],
    )
    _write_jsonl(trades, [])

    report = WalletPerformanceReportGenerator().generate(checkpoint, runs, trades)

    wallet = report.wallets[0]
    assert wallet.wallet == "momentum_btc_wallet"
    assert wallet.return_pct > 0.0
    assert wallet.sharpe_ratio != 0.0
    assert wallet.max_drawdown_pct > 0.0
    assert report.portfolio_return_pct == wallet.return_pct


def test_generate_applies_closed_trade_pnl_at_exit_time(tmp_path: Path) -> None:
    now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
    exit_time = now - timedelta(hours=2)
    checkpoint = tmp_path / "runtime-checkpoint.json"
    runs = tmp_path / "strategy-runs.jsonl"
    trades = tmp_path / "paper-trades.jsonl"

    _write_json(
        checkpoint,
        {
            "generated_at": _iso(now),
            "wallet_states": {
                "vbreak_xrp_wallet": {
                    "strategy_type": "volatility_breakout",
                    "initial_capital": 1_500_000.0,
                    "cash": 1_499_250.0,
                    "realized_pnl": -750.0,
                    "open_positions": 0,
                    "equity": 1_499_250.0,
                    "trade_count": 1,
                    "positions": {},
                }
            },
        },
    )
    _write_jsonl(runs, [])
    _write_jsonl(
        trades,
        [
            {
                "wallet": "vbreak_xrp_wallet",
                "entry_time": _iso(exit_time - timedelta(hours=1)),
                "exit_time": _iso(exit_time),
                "pnl": -750.0,
            }
        ],
    )

    report = WalletPerformanceReportGenerator().generate(checkpoint, runs, trades)

    wallet = report.wallets[0]
    assert wallet.trade_count == 1
    assert wallet.loss_count == 1
    assert wallet.return_pct < 0.0
    assert wallet.realized_pnl == -750.0


def test_generate_ignores_rows_for_wallets_not_in_checkpoint(tmp_path: Path) -> None:
    now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
    checkpoint = tmp_path / "runtime-checkpoint.json"
    runs = tmp_path / "strategy-runs.jsonl"
    trades = tmp_path / "paper-trades.jsonl"

    _write_json(
        checkpoint,
        {
            "generated_at": _iso(now),
            "wallet_states": {
                "momentum_eth_wallet": {
                    "strategy_type": "momentum",
                    "initial_capital": 1_500_000.0,
                    "cash": 1_500_000.0,
                    "realized_pnl": 0.0,
                    "open_positions": 0,
                    "equity": 1_500_000.0,
                    "trade_count": 0,
                    "positions": {},
                }
            },
        },
    )
    _write_jsonl(
        runs,
        [
            {
                "wallet_name": "legacy_wallet",
                "recorded_at": _iso(now - timedelta(hours=1)),
                "symbol": "KRW-ETH",
                "latest_price": 3000.0,
            }
        ],
    )
    _write_jsonl(
        trades,
        [
            {
                "wallet": "legacy_wallet",
                "exit_time": _iso(now - timedelta(hours=1)),
                "pnl": 1000.0,
            }
        ],
    )

    report = WalletPerformanceReportGenerator().generate(checkpoint, runs, trades)

    assert len(report.wallets) == 1
    assert report.wallets[0].wallet == "momentum_eth_wallet"
    assert report.wallets[0].trade_count == 0


def test_save_writes_markdown_and_json(tmp_path: Path) -> None:
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

    generator = WalletPerformanceReportGenerator()
    report = generator.generate(checkpoint, runs, trades)
    output_path = tmp_path / "reports" / "wallet-performance.md"
    generator.save(report, output_path)

    assert output_path.exists()
    assert output_path.with_suffix(".json").exists()
