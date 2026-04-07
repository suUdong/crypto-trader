"""SQLite-backed storage for trades, positions, and PnL snapshots.

Design notes
------------
* WAL mode so reader processes (dashboard, analytics, ad-hoc psql/duckdb) do
  not block the daemon's writes.
* Natural deduplication is intentionally narrow: we key on
  ``(wallet, symbol, entry_time, exit_time, session_id)``.

  The 2026-04-07 dual-daemon incident produced 29 duplicated trades that
  shared everything *except* ``session_id``. Merging them would hide the bug
  rather than make it visible, so we deliberately keep both rows and let
  analytics (DuckDB) flag the duplicates.
* This module is intentionally framework-free: no pydantic, no SQLAlchemy.
  Phase 2 (PostgreSQL) will reuse the same row dataclasses, only the
  ``connection()`` and DDL strings change.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

_TRADES_DDL = """
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet        TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    entry_time    TEXT NOT NULL,
    exit_time     TEXT NOT NULL,
    entry_price   REAL NOT NULL,
    exit_price    REAL NOT NULL,
    quantity      REAL NOT NULL,
    pnl           REAL NOT NULL,
    pnl_pct       REAL NOT NULL,
    exit_reason   TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    position_side TEXT NOT NULL DEFAULT 'long',
    inserted_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (wallet, symbol, entry_time, exit_time, session_id)
);
"""

_TRADES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_trades_wallet      ON trades(wallet);",
    "CREATE INDEX IF NOT EXISTS idx_trades_exit_time   ON trades(exit_time);",
    "CREATE INDEX IF NOT EXISTS idx_trades_exit_reason ON trades(exit_reason);",
)


@dataclass(frozen=True, slots=True)
class TradeRow:
    """Single closed trade.

    Mirrors the rows in ``artifacts/paper-trades.jsonl`` but normalised to
    the columns we actually query on. Slippage/fee fields can be added when
    Phase 1 starts ingesting them; for now they live in JSONL only.
    """

    wallet: str
    symbol: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    session_id: str
    position_side: str = "long"


class SqliteStore:
    """Thin wrapper around an on-disk SQLite database.

    A single instance is safe to share across one process; multiple writers
    on the same file rely on WAL mode plus SQLite's own locking. Phase 2
    will replace this with a PostgreSQL connection pool.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── schema ────────────────────────────────────────────────────────────

    def _initialise(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(_TRADES_DDL)
            for stmt in _TRADES_INDEXES:
                conn.execute(stmt)

    # ── trades ────────────────────────────────────────────────────────────

    def insert_trade(self, trade: TradeRow) -> int:
        """Insert one trade, returning the row id.

        Idempotent on the natural key. If a trade with the same
        (wallet, symbol, entry_time, exit_time, session_id) already exists,
        the existing id is returned and no new row is created.
        """

        with self.connection() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO trades (
                        wallet, symbol, entry_time, exit_time,
                        entry_price, exit_price, quantity,
                        pnl, pnl_pct, exit_reason,
                        session_id, position_side
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.wallet,
                        trade.symbol,
                        trade.entry_time,
                        trade.exit_time,
                        trade.entry_price,
                        trade.exit_price,
                        trade.quantity,
                        trade.pnl,
                        trade.pnl_pct,
                        trade.exit_reason,
                        trade.session_id,
                        trade.position_side,
                    ),
                )
                return int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                row = conn.execute(
                    """
                    SELECT id FROM trades
                    WHERE wallet = ? AND symbol = ? AND entry_time = ?
                      AND exit_time = ? AND session_id = ?
                    """,
                    (
                        trade.wallet,
                        trade.symbol,
                        trade.entry_time,
                        trade.exit_time,
                        trade.session_id,
                    ),
                ).fetchone()
                if row is None:
                    raise
                return int(row["id"])

    def query_trades(self, *, wallet: str | None = None) -> list[TradeRow]:
        sql = "SELECT * FROM trades"
        params: tuple = ()
        if wallet is not None:
            sql += " WHERE wallet = ?"
            params = (wallet,)
        sql += " ORDER BY exit_time ASC, id ASC"
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            TradeRow(
                wallet=r["wallet"],
                symbol=r["symbol"],
                entry_time=r["entry_time"],
                exit_time=r["exit_time"],
                entry_price=r["entry_price"],
                exit_price=r["exit_price"],
                quantity=r["quantity"],
                pnl=r["pnl"],
                pnl_pct=r["pnl_pct"],
                exit_reason=r["exit_reason"],
                session_id=r["session_id"],
                position_side=r["position_side"],
            )
            for r in rows
        ]
