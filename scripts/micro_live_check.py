#!/usr/bin/env python3
"""Micro-live transition auto-check: evaluates readiness from artifacts.

Outputs structured JSON + human-readable summary. Exit code 0 = READY, 1 = NOT READY.
Designed for cron / CI usage.

Usage:
    PYTHONPATH=src python3 scripts/micro_live_check.py
    PYTHONPATH=src python3 scripts/micro_live_check.py
        --checkpoint artifacts/runtime-checkpoint.json
    PYTHONPATH=src python3 scripts/micro_live_check.py --json-only
    PYTHONPATH=src python3 scripts/micro_live_check.py --notify  # sends via Telegram if configured
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from crypto_trader.operator.promotion import MicroLiveCriteria

_ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"
_DEFAULT_CHECKPOINT = _ARTIFACTS / "runtime-checkpoint.json"
_DEFAULT_JOURNAL = _ARTIFACTS / "paper-trades.jsonl"
_DEFAULT_STRATEGY_RUNS = _ARTIFACTS / "strategy-runs.jsonl"
_DEFAULT_OUTPUT = _ARTIFACTS / "micro-live-check.json"


def run_check(
    checkpoint_path: Path,
    journal_path: Path,
    strategy_runs_path: Path | None = None,
) -> dict:
    """Evaluate micro-live readiness and return structured result."""
    ready, reasons, metrics = MicroLiveCriteria.evaluate_from_artifacts(
        checkpoint_path=checkpoint_path,
        journal_path=journal_path,
        strategy_runs_path=strategy_runs_path,
    )

    thresholds = {
        "paper_days": MicroLiveCriteria.MINIMUM_PAPER_DAYS,
        "total_trades": MicroLiveCriteria.MINIMUM_TRADES,
        "win_rate": MicroLiveCriteria.MINIMUM_WIN_RATE,
        "max_drawdown": MicroLiveCriteria.MAXIMUM_DRAWDOWN,
        "profit_factor": MicroLiveCriteria.MINIMUM_PROFIT_FACTOR,
        "positive_strategies": MicroLiveCriteria.MINIMUM_POSITIVE_STRATEGIES,
    }

    criteria_results = []
    if metrics:
        criteria_results = [
            {
                "criterion": "paper_days",
                "value": metrics.get("paper_days", 0),
                "threshold": f">= {thresholds['paper_days']}d",
                "pass": metrics.get("paper_days", 0) >= thresholds["paper_days"],
            },
            {
                "criterion": "total_trades",
                "value": metrics.get("total_trades", 0),
                "threshold": f">= {thresholds['total_trades']}",
                "pass": metrics.get("total_trades", 0) >= thresholds["total_trades"],
            },
            {
                "criterion": "win_rate",
                "value": round(metrics.get("win_rate", 0.0), 4),
                "threshold": f">= {thresholds['win_rate']:.0%}",
                "pass": metrics.get("win_rate", 0.0) >= thresholds["win_rate"],
            },
            {
                "criterion": "max_drawdown",
                "value": round(metrics.get("max_drawdown", 0.0), 4),
                "threshold": f"<= {thresholds['max_drawdown']:.0%}",
                "pass": metrics.get("max_drawdown", 0.0) <= thresholds["max_drawdown"],
            },
            {
                "criterion": "profit_factor",
                "value": round(metrics.get("profit_factor", 0.0), 4),
                "threshold": f">= {thresholds['profit_factor']:.1f}",
                "pass": metrics.get("profit_factor", 0.0) >= thresholds["profit_factor"],
            },
            {
                "criterion": "positive_strategies",
                "value": metrics.get("positive_strategies", 0),
                "threshold": f">= {thresholds['positive_strategies']}",
                "pass": metrics.get("positive_strategies", 0) >= thresholds["positive_strategies"],
            },
        ]

    passed = sum(1 for c in criteria_results if c["pass"])
    total = len(criteria_results)

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "ready": ready,
        "score": f"{passed}/{total}",
        "criteria": criteria_results,
        "reasons": reasons,
        "metrics": metrics,
    }


def format_human(result: dict) -> str:
    """Format result as human-readable text."""
    lines = [
        f"Micro-Live Readiness Check ({result['checked_at'][:19]}Z)",
        f"Status: {'READY' if result['ready'] else 'NOT READY'} ({result['score']})",
        "",
    ]
    for c in result.get("criteria", []):
        mark = "PASS" if c["pass"] else "FAIL"
        lines.append(f"  [{mark}] {c['criterion']}: {c['value']} (need {c['threshold']})")

    if result.get("reasons"):
        lines.append("")
        for r in result["reasons"]:
            lines.append(f"  - {r}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Micro-live transition auto-check")
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
        "--strategy-runs",
        type=Path,
        default=_DEFAULT_STRATEGY_RUNS,
        help="Path to strategy-runs.jsonl (for paper_days start date)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Output path for JSON result",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Output only JSON (no human summary)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send result via Telegram (requires config/daemon.toml)",
    )
    args = parser.parse_args()

    result = run_check(args.checkpoint, args.journal, args.strategy_runs)

    # Save JSON
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(result, indent=2))
    else:
        print(format_human(result))

    if args.notify:
        _send_notify(result)

    sys.exit(0 if result["ready"] else 1)


def _send_notify(result: dict) -> None:
    """Attempt to send Telegram notification."""
    try:
        from crypto_trader.config import load_config
        from crypto_trader.notifications.telegram import TelegramNotifier

        config = load_config("config/daemon.toml")
        if not config.telegram.enabled:
            return
        notifier = TelegramNotifier(config.telegram)
        msg = format_human(result)
        notifier.send_message(f"[Micro-Live Check]\n{msg}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
