"""Tests for paper-trades.jsonl → SqliteStore migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crypto_trader.storage import SqliteStore
from crypto_trader.storage.jsonl_migration import (
    MigrationReport,
    migrate_paper_trades_jsonl,
)


def _trade_record(
    *,
    wallet: str = "vpin_doge_wallet",
    symbol: str = "KRW-DOGE",
    entry_time: str = "2026-04-07T00:00:00+00:00",
    exit_time: str = "2026-04-07T01:00:00+00:00",
    pnl_pct: float = -0.0085,
    exit_reason: str = "atr_stop_loss",
    session_id: str = "20260407T000000Z-1",
    extra: dict | None = None,
) -> dict:
    rec = {
        "wallet": wallet,
        "symbol": symbol,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry_price": 140.0,
        "exit_price": 139.0,
        "quantity": 100.0,
        "pnl": -100.0,
        "pnl_pct": pnl_pct,
        "exit_reason": exit_reason,
        "session_id": session_id,
        "position_side": "long",
    }
    if extra:
        rec.update(extra)
    return rec


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


@pytest.fixture()
def store(tmp_path: Path) -> SqliteStore:
    return SqliteStore(tmp_path / "store.sqlite")


class TestMigration:
    def test_imports_all_records_from_clean_jsonl(
        self, tmp_path: Path, store: SqliteStore
    ) -> None:
        jsonl = tmp_path / "trades.jsonl"
        _write_jsonl(
            jsonl,
            [
                _trade_record(),
                _trade_record(symbol="KRW-XRP", wallet="vpin_xrp_wallet"),
            ],
        )

        report = migrate_paper_trades_jsonl(jsonl, store)

        assert isinstance(report, MigrationReport)
        assert report.total_lines == 2
        assert report.inserted == 2
        assert report.skipped_duplicate == 0
        assert report.skipped_malformed == 0
        assert len(store.query_trades()) == 2

    def test_idempotent_rerun_does_not_duplicate(
        self, tmp_path: Path, store: SqliteStore
    ) -> None:
        jsonl = tmp_path / "trades.jsonl"
        _write_jsonl(jsonl, [_trade_record()])
        migrate_paper_trades_jsonl(jsonl, store)
        second = migrate_paper_trades_jsonl(jsonl, store)
        assert second.skipped_duplicate == 1
        assert second.inserted == 0
        assert len(store.query_trades()) == 1

    def test_preserves_dual_daemon_duplicates_with_different_session_ids(
        self, tmp_path: Path, store: SqliteStore
    ) -> None:
        # Reproduces the 2026-04-07 dual-daemon incident: same trade
        # recorded twice with different session ids. Both rows must land.
        jsonl = tmp_path / "trades.jsonl"
        _write_jsonl(
            jsonl,
            [
                _trade_record(session_id="session-A"),
                _trade_record(session_id="session-B"),
            ],
        )
        report = migrate_paper_trades_jsonl(jsonl, store)
        assert report.inserted == 2
        assert len(store.query_trades()) == 2

    def test_skips_malformed_lines_without_aborting(
        self, tmp_path: Path, store: SqliteStore
    ) -> None:
        jsonl = tmp_path / "trades.jsonl"
        jsonl.write_text(
            "not-json\n"
            + json.dumps(_trade_record()) + "\n"
            + json.dumps({"wallet": "missing_required_fields"}) + "\n"
        )
        report = migrate_paper_trades_jsonl(jsonl, store)
        assert report.inserted == 1
        assert report.skipped_malformed == 2
        assert report.total_lines == 3

    def test_ignores_extra_jsonl_columns(
        self, tmp_path: Path, store: SqliteStore
    ) -> None:
        # paper-trades.jsonl carries fee/slippage columns we do not store yet
        jsonl = tmp_path / "trades.jsonl"
        _write_jsonl(
            jsonl,
            [
                _trade_record(
                    extra={
                        "entry_fee_paid": 12.34,
                        "exit_fee_paid": 13.21,
                        "entry_slippage_pct": 0.0005,
                    }
                )
            ],
        )
        report = migrate_paper_trades_jsonl(jsonl, store)
        assert report.inserted == 1
