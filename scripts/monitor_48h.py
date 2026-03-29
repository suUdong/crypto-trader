#!/usr/bin/env python3
"""48-hour monitoring for vpin_eth P0 concentration.

Reads paper-trades.jsonl and daemon.log to produce a rolling status report.
Saves cumulative state to artifacts/monitoring-48h.json.
Alerts (stdout + exit code 1) on: 3 consecutive losses or MDD > 3%.

Usage:
    python scripts/monitor_48h.py                  # print report
    python scripts/monitor_48h.py --send            # also send via Telegram
    python scripts/monitor_48h.py --json            # JSON output only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS = _PROJECT_ROOT / "artifacts"
_TRADES_FILE = _ARTIFACTS / "paper-trades.jsonl"
_DAEMON_LOG = _ARTIFACTS / "daemon.log"
_STATE_FILE = _ARTIFACTS / "monitoring-48h.json"

# Alert thresholds
MAX_CONSECUTIVE_LOSSES = 3
MAX_MDD_PCT = 0.03  # 3%

# Monitoring window
WINDOW_HOURS = 48

# Target wallet
TARGET_WALLET = "vpin_eth_wallet"


def load_trades(since: datetime) -> list[dict]:
    """Load vpin_eth trades from paper-trades.jsonl within the window."""
    if not _TRADES_FILE.exists():
        return []
    trades = []
    for line in _TRADES_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            t = json.loads(line)
        except json.JSONDecodeError:
            continue
        if t.get("wallet") != TARGET_WALLET:
            continue
        exit_time = t.get("exit_time")
        if exit_time:
            ts = datetime.fromisoformat(exit_time)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts >= since:
                trades.append(t)
    trades.sort(key=lambda t: t.get("exit_time", ""))
    return trades


def parse_daemon_log_gates(since: datetime) -> dict:
    """Count macro gate and trend filter blocks from daemon.log."""
    counts = {
        "macro_gate_blocks": 0,
        "trend_filter_blocks": 0,
        "total_signals": 0,
        "hold_reasons": {},
    }
    if not _DAEMON_LOG.exists():
        return counts

    # Pattern: [vpin_eth_wallet] KRW-ETH price=... signal=... reason=...
    pat = re.compile(
        r"\[vpin_eth_wallet\].*signal=(\w+)\s+reason=(\S+)"
    )
    for line in _DAEMON_LOG.read_text().splitlines():
        # Parse timestamp from log line
        ts_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if not ts_match:
            continue
        try:
            ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC
            )
        except ValueError:
            continue
        if ts < since:
            continue

        m = pat.search(line)
        if not m:
            continue

        counts["total_signals"] += 1
        signal_action = m.group(1)
        reason = m.group(2)

        if signal_action == "hold":
            counts["hold_reasons"][reason] = counts["hold_reasons"].get(reason, 0) + 1
            if "macro" in reason.lower() or "regime" in reason.lower():
                counts["macro_gate_blocks"] += 1
            if "ema_trend" in reason.lower() or "trend" in reason.lower():
                counts["trend_filter_blocks"] += 1

    return counts


def compute_metrics(trades: list[dict]) -> dict:
    """Compute win rate, PnL, MDD, consecutive losses."""
    if not trades:
        return {
            "trade_count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "avg_pnl_pct": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0,
            "max_drawdown_pct": 0.0,
            "current_consecutive_losses": 0,
            "max_consecutive_losses": 0,
        }

    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    losses = sum(1 for t in trades if t.get("pnl", 0) <= 0)
    pnls = [t.get("pnl", 0) for t in trades]
    pnl_pcts = [t.get("pnl_pct", 0) for t in trades]

    # MDD from cumulative PnL curve
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnl_pcts:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Consecutive losses (current streak and max)
    current_streak = 0
    max_streak = 0
    for t in trades:
        if t.get("pnl", 0) <= 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    return {
        "trade_count": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(trades) if trades else 0.0,
        "total_pnl": sum(pnls),
        "total_pnl_pct": sum(pnl_pcts),
        "avg_pnl_pct": sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0.0,
        "best_trade_pnl": max(pnls) if pnls else 0.0,
        "worst_trade_pnl": min(pnls) if pnls else 0.0,
        "max_drawdown_pct": max_dd,
        "current_consecutive_losses": current_streak,
        "max_consecutive_losses": max_streak,
    }


def check_alerts(metrics: dict) -> list[str]:
    """Return alert messages if thresholds breached."""
    alerts = []
    if metrics["current_consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
        alerts.append(
            f"ALERT: {metrics['current_consecutive_losses']} consecutive losses "
            f"(threshold: {MAX_CONSECUTIVE_LOSSES})"
        )
    if metrics["max_drawdown_pct"] > MAX_MDD_PCT:
        alerts.append(
            f"ALERT: MDD {metrics['max_drawdown_pct']:.2%} exceeds "
            f"threshold {MAX_MDD_PCT:.0%}"
        )
    return alerts


def format_report(
    metrics: dict, gate_stats: dict, alerts: list[str], window_start: str
) -> str:
    """Format human-readable monitoring report."""
    lines = [
        "=" * 50,
        "  vpin_eth 48h Monitoring Report",
        f"  Window: {window_start} ~ now",
        f"  Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 50,
        "",
        "--- Trade Performance ---",
        f"  Trades:       {metrics['trade_count']}",
        f"  Wins/Losses:  {metrics['wins']}/{metrics['losses']}",
        f"  Win Rate:     {metrics['win_rate']:.1%}",
        f"  Total PnL:    ₩{metrics['total_pnl']:,.0f} ({metrics['total_pnl_pct']:.2%})",
        f"  Avg PnL%:     {metrics['avg_pnl_pct']:.2%}",
        f"  Best Trade:   ₩{metrics['best_trade_pnl']:,.0f}",
        f"  Worst Trade:  ₩{metrics['worst_trade_pnl']:,.0f}",
        "",
        "--- Risk ---",
        f"  Max Drawdown:         {metrics['max_drawdown_pct']:.2%}",
        f"  Consecutive Losses:   {metrics['current_consecutive_losses']} "
        f"(max: {metrics['max_consecutive_losses']})",
        "",
        "--- Signal Gates (from daemon.log) ---",
        f"  Total signals parsed: {gate_stats['total_signals']}",
        f"  Macro gate blocks:    {gate_stats['macro_gate_blocks']}",
        f"  Trend filter blocks:  {gate_stats['trend_filter_blocks']}",
    ]
    if gate_stats["hold_reasons"]:
        lines.append("  Hold reason breakdown:")
        for reason, count in sorted(
            gate_stats["hold_reasons"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"    {reason}: {count}")

    if alerts:
        lines.append("")
        lines.append("*** ALERTS ***")
        for a in alerts:
            lines.append(f"  {a}")
    else:
        lines.append("")
        lines.append("  No alerts — all thresholds OK")

    lines.append("")
    return "\n".join(lines)


def save_state(metrics: dict, gate_stats: dict, alerts: list[str]) -> None:
    """Append snapshot to monitoring-48h.json."""
    state: dict = {"snapshots": []}
    if _STATE_FILE.exists():
        try:
            state = json.loads(_STATE_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            state = {"snapshots": []}

    snapshot = {
        "timestamp": datetime.now(UTC).isoformat(),
        "metrics": metrics,
        "gate_stats": {
            k: v for k, v in gate_stats.items() if k != "hold_reasons"
        },
        "hold_reasons": gate_stats.get("hold_reasons", {}),
        "alerts": alerts,
    }
    state["snapshots"].append(snapshot)

    # Keep last 96 snapshots (48h at 30min intervals)
    state["snapshots"] = state["snapshots"][-96:]
    _STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="48h vpin_eth monitoring")
    parser.add_argument("--send", action="store_true", help="Send alert via Telegram")
    parser.add_argument("--json", action="store_true", help="JSON output only")
    args = parser.parse_args()

    now = datetime.now(UTC)
    window_start = now - timedelta(hours=WINDOW_HOURS)

    trades = load_trades(since=window_start)
    metrics = compute_metrics(trades)
    gate_stats = parse_daemon_log_gates(since=window_start)
    alerts = check_alerts(metrics)

    save_state(metrics, gate_stats, alerts)

    if args.json:
        out = {
            "timestamp": now.isoformat(),
            "window_start": window_start.isoformat(),
            "metrics": metrics,
            "gate_stats": gate_stats,
            "alerts": alerts,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        report = format_report(
            metrics, gate_stats, alerts,
            window_start.strftime("%Y-%m-%d %H:%M UTC"),
        )
        print(report)

    if args.send and alerts:
        try:
            sys.path.insert(0, str(_PROJECT_ROOT / "src"))
            from crypto_trader.config import load_config
            from crypto_trader.notifications.telegram import TelegramNotifier

            cfg = load_config()
            notifier = TelegramNotifier(cfg.telegram)
            alert_msg = (
                "🚨 vpin_eth 48h Monitor\n"
                + "\n".join(alerts)
                + f"\nWin rate: {metrics['win_rate']:.1%}"
                + f"\nPnL: ₩{metrics['total_pnl']:,.0f}"
            )
            notifier.send_message(alert_msg)
        except Exception as exc:
            print(f"Telegram send failed: {exc}", file=sys.stderr)

    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
