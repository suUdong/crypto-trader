"""crypto-trader storage layer.

Phase 1: SQLite (operational) + DuckDB (analytics).
Phase 2: PostgreSQL self-host.

Goal: replace JSONL/JSON file scattering with a single source of truth that
provides transactions, indexes, and safe concurrent reads.
"""

from crypto_trader.storage.jsonl_migration import (
    MigrationReport,
    migrate_paper_trades_jsonl,
)
from crypto_trader.storage.sqlite_store import SqliteStore, TradeRow

__all__ = [
    "MigrationReport",
    "SqliteStore",
    "TradeRow",
    "migrate_paper_trades_jsonl",
]
