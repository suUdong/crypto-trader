#!/usr/bin/env python3
"""72-hour performance report: PnL summary + micro-live readiness check."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from crypto_trader.operator.performance_report import generate_performance_report

_ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"
_DEFAULT_CHECKPOINT = _ARTIFACTS / "runtime-checkpoint.json"
_DEFAULT_JOURNAL = _ARTIFACTS / "paper-trades.jsonl"
_DEFAULT_OUTPUT = _ARTIFACTS / "performance-report.md"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 72-hour performance report")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=_DEFAULT_CHECKPOINT,
        help="Path to runtime-checkpoint.json",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=_DEFAULT_JOURNAL,
        help="Path to paper-trades.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Output path for performance-report.md",
    )
    args = parser.parse_args()

    content = generate_performance_report(args.checkpoint, args.journal)

    print(content)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"\n---\nReport saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
