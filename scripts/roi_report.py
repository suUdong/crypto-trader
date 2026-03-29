"""Generate a ROI report from current runtime artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crypto_trader.operator.roi_report import RoiReportGenerator  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a ROI report")
    parser.add_argument("--config", default="config/daemon.toml")
    parser.add_argument("--checkpoint", default="artifacts/runtime-checkpoint.json")
    parser.add_argument("--strategy-runs", default="artifacts/strategy-runs.jsonl")
    parser.add_argument("--current-equity", type=float, required=True)
    parser.add_argument("--report-month", default="2026-03")
    parser.add_argument("--timezone", default="Asia/Seoul")
    parser.add_argument("--output", default="reports/roi-report-2026-03.md")
    args = parser.parse_args()

    report = RoiReportGenerator().generate(
        config_path=args.config,
        checkpoint_path=args.checkpoint,
        strategy_runs_path=args.strategy_runs,
        current_equity=args.current_equity,
        report_month=args.report_month,
        timezone_name=args.timezone,
    )
    output = Path(args.output)
    RoiReportGenerator().save(report, output)
    print(output)


if __name__ == "__main__":
    main()
