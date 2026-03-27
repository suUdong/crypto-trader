#!/usr/bin/env python3
"""Generate and optionally send a daily performance report.

Usage:
    python scripts/daily_report.py                          # print to stdout
    python scripts/daily_report.py --send                   # also send via Telegram
    python scripts/daily_report.py --period weekly --hours 168
    python scripts/daily_report.py --save artifacts/daily-perf.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is importable
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root / "src"))

def main() -> None:
    from crypto_trader.config import load_config
    from crypto_trader.monitoring.performance_reporter import PerformanceReporter
    from crypto_trader.notifications.telegram import TelegramNotifier
    from crypto_trader.operator.automated_reporting import (
        AutomatedReportGenerator,
        build_legacy_daily_performance_summary,
    )

    parser = argparse.ArgumentParser(description="Generate daily performance report")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config TOML (default: CT_CONFIG or config/example.toml)",
    )
    parser.add_argument(
        "--period", default="daily", choices=["daily", "weekly"], help="Report period label"
    )
    parser.add_argument(
        "--hours", type=int, default=24, help="Look-back window in hours (default: 24)"
    )
    parser.add_argument("--send", action="store_true", help="Send report via Telegram")
    parser.add_argument("--save", default=None, help="Save JSON report to this path")
    parser.add_argument(
        "--output",
        default=None,
        help="Save the markdown report to this path (JSON sidecar shares the same stem)",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    strategy_journal = Path(config.runtime.strategy_run_journal_path)
    trade_journal = Path(config.runtime.paper_trade_journal_path)

    reporter = PerformanceReporter(
        trade_journal_path=trade_journal,
        strategy_journal_path=strategy_journal,
    )
    generator = AutomatedReportGenerator()

    summary = reporter.generate(period=args.period, hours=args.hours)
    report = generator.generate(
        checkpoint_path=config.runtime.runtime_checkpoint_path,
        strategy_run_journal_path=strategy_journal,
        trade_journal_path=trade_journal,
        period=args.period,
        hours=args.hours,
    )
    text = reporter.to_notification_text(summary)
    artifacts_dir = Path(config.runtime.daily_performance_path).parent
    output_path = (
        Path(args.output)
        if args.output
        else generator.default_output_path(period=args.period, artifacts_dir=artifacts_dir)
    )
    generator.save(report, output_path)

    # Always print to stdout
    print(generator.to_markdown(report))
    print(
        f"\n--- Strategies: {len(summary.strategies)} | "
        f"Trades: {summary.portfolio_trades} | "
        f"Win rate: {summary.portfolio_win_rate:.1%} ---"
    )
    print(f"\nReport saved to {output_path}")

    if args.save:
        reporter.save_json(summary, args.save)
        print(f"\nJSON saved to {args.save}")
    elif args.period == "daily":
        Path(config.runtime.daily_performance_path).write_text(
            json.dumps(
                build_legacy_daily_performance_summary(report, report_path=output_path),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    if args.send:
        if config.telegram.enabled:
            notifier = TelegramNotifier(config.telegram)
            notifier.send_message(text)
            print("\nReport sent via Telegram.")
        else:
            print(
                "\nTelegram not configured. Set CT_TELEGRAM_BOT_TOKEN and CT_TELEGRAM_CHAT_ID.",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
