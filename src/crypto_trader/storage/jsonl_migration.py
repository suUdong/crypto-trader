"""One-shot migration: artifacts/paper-trades.jsonl → SqliteStore.

Run idempotently. The 2026-04-07 dual-daemon incident produced 29 duplicate
trade rows that share the natural key but differ on ``session_id``; this
migration deliberately preserves them so analytics can flag the bug rather
than silently merge them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from crypto_trader.storage.sqlite_store import SqliteStore, TradeRow

_LOG = logging.getLogger(__name__)

_REQUIRED_FIELDS: tuple[str, ...] = (
    "wallet",
    "symbol",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "quantity",
    "pnl",
    "pnl_pct",
    "exit_reason",
    "session_id",
)


@dataclass(frozen=True, slots=True)
class MigrationReport:
    total_lines: int
    inserted: int
    skipped_duplicate: int
    skipped_malformed: int


def _parse_record(raw: str) -> dict | None:
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    if any(field not in record for field in _REQUIRED_FIELDS):
        return None
    return record


def _to_trade_row(record: dict) -> TradeRow:
    return TradeRow(
        wallet=str(record["wallet"]),
        symbol=str(record["symbol"]),
        entry_time=str(record["entry_time"]),
        exit_time=str(record["exit_time"]),
        entry_price=float(record["entry_price"]),
        exit_price=float(record["exit_price"]),
        quantity=float(record["quantity"]),
        pnl=float(record["pnl"]),
        pnl_pct=float(record["pnl_pct"]),
        exit_reason=str(record["exit_reason"]),
        session_id=str(record["session_id"]),
        position_side=str(record.get("position_side", "long")),
    )


def migrate_paper_trades_jsonl(
    jsonl_path: Path | str,
    store: SqliteStore,
) -> MigrationReport:
    """Read each line of paper-trades.jsonl and insert into ``store``.

    Returns counts. Inserts that hit the natural-key UNIQUE constraint are
    counted as ``skipped_duplicate``, not failures, so re-running the
    migration after dual-write rollout is safe.
    """

    jsonl_path = Path(jsonl_path)
    total = 0
    inserted = 0
    duplicate = 0
    malformed = 0

    with jsonl_path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            total += 1
            record = _parse_record(line)
            if record is None:
                malformed += 1
                _LOG.warning("skipping malformed line %d in %s", total, jsonl_path)
                continue
            try:
                trade = _to_trade_row(record)
            except (TypeError, ValueError) as exc:
                malformed += 1
                _LOG.warning("coercion failure on line %d: %s", total, exc)
                continue

            # Detect "already present" via a count probe so we can distinguish
            # a fresh insert from an idempotent re-run for the report.
            with store.connection() as conn:
                existing = conn.execute(
                    """
                    SELECT 1 FROM trades
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
            if existing is not None:
                duplicate += 1
                continue

            store.insert_trade(trade)
            inserted += 1

    return MigrationReport(
        total_lines=total,
        inserted=inserted,
        skipped_duplicate=duplicate,
        skipped_malformed=malformed,
    )
