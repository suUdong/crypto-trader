"""Tests for crypto_trader.storage.sqlite_store.

TDD baseline for Phase 1 DB introduction.
"""

from __future__ import annotations

import dataclasses
import math
import multiprocessing as mp
import sqlite3
from pathlib import Path

import pytest

from crypto_trader.storage import SqliteStore, TradeRow
from crypto_trader.storage.errors import StorageError, ValidationError


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

    def test_filters_by_exit_reason(self, store: SqliteStore) -> None:
        store.insert_trade(_sample_trade(exit_reason="atr_stop_loss"))
        store.insert_trade(
            _sample_trade(
                entry_time="2026-04-07T02:00:00+00:00",
                exit_time="2026-04-07T03:00:00+00:00",
                exit_reason="rsi_overbought",
            )
        )
        rows = store.query_trades(exit_reason="atr_stop_loss")
        assert len(rows) == 1
        assert rows[0].exit_reason == "atr_stop_loss"

    def test_filters_by_since(self, store: SqliteStore) -> None:
        store.insert_trade(_sample_trade())  # exit 01:00
        store.insert_trade(
            _sample_trade(
                entry_time="2026-04-07T05:00:00+00:00",
                exit_time="2026-04-07T06:00:00+00:00",
            )
        )
        rows = store.query_trades(since="2026-04-07T05:00:00+00:00")
        assert len(rows) == 1
        assert rows[0].exit_time == "2026-04-07T06:00:00+00:00"

    def test_limit_caps_result(self, store: SqliteStore) -> None:
        for i in range(5):
            store.insert_trade(
                _sample_trade(
                    entry_time=f"2026-04-07T0{i}:00:00+00:00",
                    exit_time=f"2026-04-07T0{i+1}:00:00+00:00",
                )
            )
        rows = store.query_trades(limit=3)
        assert len(rows) == 3


class TestInputValidation:
    def test_rejects_nan_pnl_pct(self) -> None:
        with pytest.raises(ValidationError):
            TradeRow(
                wallet="w",
                symbol="KRW-X",
                entry_time="2026-04-07T00:00:00+00:00",
                exit_time="2026-04-07T01:00:00+00:00",
                entry_price=1.0,
                exit_price=1.0,
                quantity=1.0,
                pnl=0.0,
                pnl_pct=math.nan,
                exit_reason="x",
                session_id="s",
            )

    def test_rejects_infinite_price(self) -> None:
        with pytest.raises(ValidationError):
            TradeRow(
                wallet="w",
                symbol="KRW-X",
                entry_time="2026-04-07T00:00:00+00:00",
                exit_time="2026-04-07T01:00:00+00:00",
                entry_price=math.inf,
                exit_price=1.0,
                quantity=1.0,
                pnl=0.0,
                pnl_pct=0.0,
                exit_reason="x",
                session_id="s",
            )

    def test_rejects_negative_quantity(self) -> None:
        with pytest.raises(ValidationError):
            TradeRow(
                wallet="w",
                symbol="KRW-X",
                entry_time="2026-04-07T00:00:00+00:00",
                exit_time="2026-04-07T01:00:00+00:00",
                entry_price=1.0,
                exit_price=1.0,
                quantity=-1.0,
                pnl=0.0,
                pnl_pct=0.0,
                exit_reason="x",
                session_id="s",
            )

    def test_rejects_exit_before_entry(self) -> None:
        with pytest.raises(ValidationError):
            TradeRow(
                wallet="w",
                symbol="KRW-X",
                entry_time="2026-04-07T05:00:00+00:00",
                exit_time="2026-04-07T01:00:00+00:00",  # before entry
                entry_price=1.0,
                exit_price=1.0,
                quantity=1.0,
                pnl=0.0,
                pnl_pct=0.0,
                exit_reason="x",
                session_id="s",
            )

    def test_validation_error_is_storage_error(self) -> None:
        assert issubclass(ValidationError, StorageError)


def _worker_insert(args: tuple[str, int]) -> int:
    db_path, idx = args
    from crypto_trader.storage import SqliteStore as _S, TradeRow as _T  # re-import in subproc
    s = _S(db_path)
    return s.insert_trade(
        _T(
            wallet="w",
            symbol="KRW-X",
            entry_time=f"2026-04-07T{idx:02d}:00:00+00:00",
            exit_time=f"2026-04-07T{idx:02d}:30:00+00:00",
            entry_price=1.0,
            exit_price=1.0,
            quantity=1.0,
            pnl=0.0,
            pnl_pct=0.0,
            exit_reason="x",
            session_id=f"s{idx}",
        )
    )


class TestConcurrency:
    def test_multiple_processes_can_insert_concurrently(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "concurrent.sqlite"
        SqliteStore(db_path)  # initialise schema
        with mp.get_context("spawn").Pool(processes=4) as pool:
            results = pool.map(
                _worker_insert, [(str(db_path), i) for i in range(20)]
            )
        assert len(results) == 20
        assert len(set(results)) == 20  # all unique row ids
        store = SqliteStore(db_path)
        assert len(store.query_trades()) == 20
