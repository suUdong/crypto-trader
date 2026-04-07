"""DuckDB analytics view over the SqliteStore.

The operational write path stays on SQLite (`SqliteStore`). For analytics
we attach DuckDB read-only over the same file so we get vectorised SQL
without copying data.

This module is the foundation for replacing the ad-hoc python+grep
analyses (e.g. ``stage1a_live_performance``) with reusable SQL.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from crypto_trader.storage.sqlite_store import SqliteStore, TradeRow


@dataclass(frozen=True, slots=True)
class WalletStats:
    wallet: str
    trade_count: int
    win_rate: float
    avg_pnl_pct: float
    sum_pnl: float


class AnalyticsView:
    """DuckDB analytics over a SqliteStore.

    Each call opens a fresh DuckDB connection that ATTACHes the SQLite
    file read-only. This keeps the analytics path completely independent
    of the daemon's write path; the daemon never sees DuckDB.
    """

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def _attach(self) -> duckdb.DuckDBPyConnection:
        conn = duckdb.connect(database=":memory:")
        # READ_ONLY so we can never accidentally mutate the operational DB.
        conn.execute(
            f"ATTACH '{self._store.path}' AS opdb (TYPE sqlite, READ_ONLY);"
        )
        return conn

    # ── wallet level metrics ──────────────────────────────────────────────

    def wallet_stats(self) -> list[WalletStats]:
        with self._attach() as conn:
            rows = conn.execute(
                """
                SELECT
                    wallet,
                    COUNT(*)                                          AS trade_count,
                    AVG(CASE WHEN pnl_pct > 0 THEN 1.0 ELSE 0.0 END)  AS win_rate,
                    AVG(pnl_pct)                                      AS avg_pnl_pct,
                    SUM(pnl)                                          AS sum_pnl
                FROM opdb.trades
                GROUP BY wallet
                ORDER BY wallet
                """
            ).fetchall()
        return [
            WalletStats(
                wallet=r[0],
                trade_count=int(r[1]),
                win_rate=float(r[2]),
                avg_pnl_pct=float(r[3]),
                sum_pnl=float(r[4]),
            )
            for r in rows
        ]

    def exit_reason_distribution(self, *, wallet: str) -> dict[str, int]:
        with self._attach() as conn:
            rows = conn.execute(
                """
                SELECT exit_reason, COUNT(*) AS n
                FROM opdb.trades
                WHERE wallet = ?
                GROUP BY exit_reason
                ORDER BY n DESC
                """,
                [wallet],
            ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def recent_trades(self, *, since: str) -> list[TradeRow]:
        """Return trades whose ``exit_time`` >= ``since`` (ISO string compare).

        SQLite stores ISO-8601 strings so a lexical comparison is also a
        chronological one as long as the format is consistent. The migration
        + insert paths enforce that.
        """
        with self._attach() as conn:
            rows = conn.execute(
                """
                SELECT wallet, symbol, entry_time, exit_time, entry_price,
                       exit_price, quantity, pnl, pnl_pct, exit_reason,
                       session_id, position_side
                FROM opdb.trades
                WHERE exit_time >= ?
                ORDER BY exit_time ASC
                """,
                [since],
            ).fetchall()
        return [
            TradeRow(
                wallet=r[0],
                symbol=r[1],
                entry_time=r[2],
                exit_time=r[3],
                entry_price=float(r[4]),
                exit_price=float(r[5]),
                quantity=float(r[6]),
                pnl=float(r[7]),
                pnl_pct=float(r[8]),
                exit_reason=r[9],
                session_id=r[10],
                position_side=r[11],
            )
            for r in rows
        ]
