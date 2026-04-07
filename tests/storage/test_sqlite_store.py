"""Tests for crypto_trader.storage.sqlite_store.

TDD baseline for Phase 1 DB introduction.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

from crypto_trader.storage import SqliteStore, TradeRow


@pytest.fixture()
def store(tmp_path: Path) -> SqliteStore:
    db_path = tmp_path / "test.sqlite"
    return SqliteStore(db_path)


def _sample_trade(
    *,
    wallet: str = "vpin_doge_wallet",
    symbol: str = "KRW-DOGE",
    entry_time: str = "2026-04-07T00:00:00+00:00",
    exit_time: str = "2026-04-07T01:00:00+00:00",
    pnl_pct: float = -0.0085,
    exit_reason: str = "atr_stop_loss",
) -> TradeRow:
    return TradeRow(
        wallet=wallet,
        symbol=symbol,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=140.0,
        exit_price=139.0,
        quantity=100.0,
        pnl=-100.0,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
        session_id="20260407T000000Z-1",
        position_side="long",
    )


class TestSchemaInitialization:
    def test_creates_database_file_on_init(self, tmp_path: Path) -> None:
        db_path = tmp_path / "new.sqlite"
        assert not db_path.exists()
        SqliteStore(db_path)
        assert db_path.exists()

    def test_creates_trades_table(self, store: SqliteStore) -> None:
        with store.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
            ).fetchone()
        assert row is not None

    def test_uses_wal_mode(self, store: SqliteStore) -> None:
        with store.connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_init_is_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "idem.sqlite"
        SqliteStore(path)
        SqliteStore(path)  # Second init must not raise


class TestInsertTrade:
    def test_insert_returns_row_id(self, store: SqliteStore) -> None:
        row_id = store.insert_trade(_sample_trade())
        assert row_id is not None
        assert row_id > 0

    def test_inserted_trade_is_queryable(self, store: SqliteStore) -> None:
        store.insert_trade(_sample_trade())
        with store.connection() as conn:
            row = conn.execute("SELECT wallet, symbol, exit_reason FROM trades").fetchone()
        assert (row["wallet"], row["symbol"], row["exit_reason"]) == (
            "vpin_doge_wallet",
            "KRW-DOGE",
            "atr_stop_loss",
        )

    def test_dedup_returns_existing_id_for_same_natural_key(
        self, store: SqliteStore
    ) -> None:
        first = store.insert_trade(_sample_trade())
        second = store.insert_trade(_sample_trade())
        assert second == first
        with store.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert count == 1

    def test_dedup_distinguishes_by_session_id(self, store: SqliteStore) -> None:
        first = store.insert_trade(_sample_trade())
        dup_with_other_session = dataclasses.replace(
            _sample_trade(), session_id="other-session"
        )
        second = store.insert_trade(dup_with_other_session)
        assert second != first
        # Same wallet/symbol/entry_time/pnl from a different session is the
        # smoking gun for the dual-daemon bug. Both rows must be retained so
        # we can detect/quantify the duplication, not silently merged.


class TestQueryByWallet:
    def test_filters_to_target_wallet(self, store: SqliteStore) -> None:
        store.insert_trade(_sample_trade(wallet="vpin_doge_wallet"))
        store.insert_trade(_sample_trade(wallet="vpin_xrp_wallet", symbol="KRW-XRP"))
        rows = store.query_trades(wallet="vpin_doge_wallet")
        assert len(rows) == 1
        assert rows[0].wallet == "vpin_doge_wallet"

    def test_returns_empty_list_when_wallet_unknown(self, store: SqliteStore) -> None:
        store.insert_trade(_sample_trade())
        assert store.query_trades(wallet="nonexistent_wallet") == []
