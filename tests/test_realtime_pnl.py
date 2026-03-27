from __future__ import annotations

import json
from pathlib import Path

import pytest

from crypto_trader.monitoring.realtime_pnl import (
    format_position_snapshot,
    load_position_snapshot,
    sorted_position_rows,
)


def test_load_position_snapshot_reads_json(tmp_path: Path) -> None:
    path = tmp_path / "positions.json"
    path.write_text(
        json.dumps({"generated_at": "2025-01-01T00:00:00Z", "positions": []}),
        encoding="utf-8",
    )

    snapshot = load_position_snapshot(path)

    assert snapshot["generated_at"] == "2025-01-01T00:00:00Z"
    assert snapshot["positions"] == []


def test_sorted_position_rows_orders_by_abs_unrealized_pnl() -> None:
    rows = sorted_position_rows(
        {
            "positions": [
                {"symbol": "KRW-BTC", "unrealized_pnl": 500.0},
                {"symbol": "KRW-ETH", "unrealized_pnl": -2_000.0},
                {"symbol": "KRW-XRP", "unrealized_pnl": 100.0},
            ]
        }
    )

    assert [row["symbol"] for row in rows] == ["KRW-ETH", "KRW-BTC", "KRW-XRP"]


def test_format_position_snapshot_renders_table() -> None:
    output = format_position_snapshot(
        {
            "generated_at": "2025-01-01T00:00:00Z",
            "mark_to_market_equity": 1_050_000.0,
            "total_unrealized_pnl": 50_000.0,
            "positions": [
                {
                    "wallet": "momentum_wallet",
                    "symbol": "KRW-BTC",
                    "qty": 1.25,
                    "entry_price": 100_000.0,
                    "market_price": 110_000.0,
                    "unrealized_pnl": 12_500.0,
                    "unrealized_pnl_pct": 0.1,
                }
            ],
        }
    )

    assert "momentum_wallet" in output
    assert "KRW-BTC" in output
    assert "+10.00%" in output


def test_load_position_snapshot_rejects_bad_shape(tmp_path: Path) -> None:
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"positions": {}}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_position_snapshot(path)
