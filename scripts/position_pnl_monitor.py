#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch runtime position-level P&L snapshots.")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("artifacts/positions.json"),
        help="Path to positions.json snapshot",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds when following",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Continuously print the latest snapshot when the file changes",
    )
    return parser


def _print_snapshot(path: Path) -> None:
    from crypto_trader.monitoring.realtime_pnl import (
        format_position_snapshot,
        load_position_snapshot,
    )

    snapshot = load_position_snapshot(path)
    print(format_position_snapshot(snapshot))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.follow:
        _print_snapshot(args.path)
        return 0

    last_mtime_ns: int | None = None
    while True:
        if not args.path.exists():
            print(f"waiting for snapshot: {args.path}", file=sys.stderr)
            time.sleep(args.interval)
            continue
        stat = args.path.stat()
        if last_mtime_ns != stat.st_mtime_ns:
            last_mtime_ns = stat.st_mtime_ns
            print("\033[2J\033[H", end="")
            _print_snapshot(args.path)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
