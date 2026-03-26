#!/usr/bin/env python3
"""Generate a docs-ready offline strategy comparison report."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from crypto_trader.operator.offline_strategy_report import (  # noqa: E402
    generate_offline_strategy_report,
    save_offline_strategy_report,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = ROOT / "artifacts" / "backtest-grid-90d" / "baseline.json"
DEFAULT_TUNED = ROOT / "artifacts" / "backtest-grid-90d" / "combined.json"
DEFAULT_WALK_FORWARD = ROOT / "artifacts" / "walk-forward-90d" / "grid-wf-summary.json"
DEFAULT_LIVE_CHECKPOINT = ROOT / "artifacts" / "runtime-checkpoint.json"
DEFAULT_OUTPUT = ROOT / "docs" / "strategy-performance-comparison.md"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the strategy comparison report.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--tuned", type=Path, default=DEFAULT_TUNED)
    parser.add_argument(
        "--walk-forward",
        dest="walk_forward",
        type=Path,
        default=DEFAULT_WALK_FORWARD,
    )
    parser.add_argument(
        "--live-checkpoint",
        dest="live_checkpoint",
        type=Path,
        default=DEFAULT_LIVE_CHECKPOINT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = generate_offline_strategy_report(
        baseline_path=args.baseline,
        tuned_path=args.tuned,
        walk_forward_path=args.walk_forward,
        live_checkpoint_path=args.live_checkpoint,
    )
    save_offline_strategy_report(report, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
