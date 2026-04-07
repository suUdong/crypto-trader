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

import logging
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from crypto_trader.storage.errors import IntegrityError, ValidationError

_LOG = logging.getLogger(__name__)

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


_NUMERIC_FIELDS = ("entry_price", "exit_price", "quantity", "pnl", "pnl_pct")
_NON_NEGATIVE_FIELDS = ("entry_price", "exit_price", "quantity")


@dataclass(frozen=True, slots=True)
class TradeRow:
    """Single closed trade.

    Mirrors the rows in ``artifacts/paper-trades.jsonl`` but normalised to
    the columns we actually query on. Slippage/fee fields can be added when
    Phase 1 starts ingesting them; for now they live in JSONL only.

    Validation runs in ``__post_init__``: NaN/Inf in any numeric field, a
    negative price/quantity, or ``exit_time < entry_time`` will raise
    :class:`ValidationError` before any DB call.
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

    def __post_init__(self) -> None:
        for name in _NUMERIC_FIELDS:
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValidationError(
                    f"TradeRow.{name} must be finite, got {value!r}"
                )
        for name in _NON_NEGATIVE_FIELDS:
            if getattr(self, name) < 0:
                raise ValidationError(
                    f"TradeRow.{name} must be non-negative"
                )
        if self.exit_time < self.entry_time:
            raise ValidationError(
                f"exit_time {self.exit_time!r} precedes entry_time "
                f"{self.entry_time!r}"
            )


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

        Raises :class:`IntegrityError` if a constraint other than the
        natural-key UNIQUE is violated. ``sqlite3.IntegrityError`` never
        leaks past this method.
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
            except sqlite3.IntegrityError as exc:
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
                    _LOG.warning(
                        "insert_trade integrity error without natural-key match: %s",
                        exc,
                    )
                    raise IntegrityError(str(exc)) from exc
                return int(row["id"])

    def query_trades(
        self,
        *,
        wallet: str | None = None,
        exit_reason: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[TradeRow]:
        """Query trades with optional filters.

        ``since``/``until`` are ISO-8601 strings compared lexically against
        ``exit_time`` (the ingest path enforces consistent format).

        ``limit`` caps the result; callers handling large volumes should
        switch to :meth:`iter_trades` once added.
        """

        clauses: list[str] = []
        params: list[object] = []
        if wallet is not None:
            clauses.append("wallet = ?")
            params.append(wallet)
        if exit_reason is not None:
            clauses.append("exit_reason = ?")
            params.append(exit_reason)
        if since is not None:
            clauses.append("exit_time >= ?")
            params.append(since)
        if until is not None:
            clauses.append("exit_time < ?")
            params.append(until)

        sql = "SELECT * FROM trades"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY exit_time ASC, id ASC"
        if limit is not None:
            if limit < 0:
                raise ValidationError("limit must be non-negative")
            sql += " LIMIT ?"
            params.append(limit)

        with self.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
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
