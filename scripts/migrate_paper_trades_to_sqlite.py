#!/usr/bin/env python3
"""One-shot CLI: migrate artifacts/paper-trades.jsonl into a SqliteStore.

Idempotent — running it again after dual-write is rolled out is safe.

Usage
-----
    python scripts/migrate_paper_trades_to_sqlite.py
    python scripts/migrate_paper_trades_to_sqlite.py \
        --jsonl artifacts/paper-trades.jsonl \
        --db data/storage/crypto_trader.sqlite
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running directly without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from crypto_trader.storage import SqliteStore, migrate_paper_trades_jsonl  # noqa: E402

_DEFAULT_JSONL = _REPO_ROOT / "artifacts" / "paper-trades.jsonl"
_DEFAULT_DB = _REPO_ROOT / "data" / "storage" / "crypto_trader.sqlite"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=_DEFAULT_JSONL,
        help=f"paper-trades.jsonl path (default: {_DEFAULT_JSONL.relative_to(_REPO_ROOT)})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help=f"target SQLite path (default: {_DEFAULT_DB.relative_to(_REPO_ROOT)})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="emit per-line warnings for malformed records",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="[%(levelname)s] %(message)s",
    )

    if not args.jsonl.exists():
        print(f"error: {args.jsonl} does not exist", file=sys.stderr)
        return 2

    print(f"source : {args.jsonl}")
    print(f"target : {args.db}")
    store = SqliteStore(args.db)
    report = migrate_paper_trades_jsonl(args.jsonl, store)

    print()
    print("=== migration report ===")
    print(f"  total_lines       : {report.total_lines}")
    print(f"  inserted          : {report.inserted}")
    print(f"  skipped_duplicate : {report.skipped_duplicate}")
    print(f"  skipped_malformed : {report.skipped_malformed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
