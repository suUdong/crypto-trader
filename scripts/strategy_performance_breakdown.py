#!/usr/bin/env python3
"""Per-wallet strategy performance breakdown with macro gate & trend filter tracking.

Reads paper-trades.jsonl and strategy-runs.jsonl to produce:
  - Per-wallet PnL, win rate, trade count
  - Macro regime gate block counts
  - Trend filter (below_ma_filter) block counts
  - Daily breakdown per wallet

Output: artifacts/strategy-performance-breakdown.json + stdout summary.

Usage:
    python scripts/strategy_performance_breakdown.py
    python scripts/strategy_performance_breakdown.py --hours 168   # 7-day window
    python scripts/strategy_performance_breakdown.py --all         # all time
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

_ARTIFACTS = _PROJECT_ROOT / "artifacts"
_DEFAULT_TRADES = _ARTIFACTS / "paper-trades.jsonl"
_DEFAULT_RUNS = _ARTIFACTS / "strategy-runs.jsonl"
_DEFAULT_OUTPUT = _ARTIFACTS / "strategy-performance-breakdown.json"

# Signal reasons that indicate macro regime gate blocks
_MACRO_GATE_PREFIX = "macro_regime_gate:"
# Signal reasons that indicate trend direction filter blocks
_TREND_FILTER_REASONS = frozenset({
    "below_ma_filter",
    "ema50_trend_gate",
    "trend_direction_filter",
})


def _parse_iso(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


def _load_jsonl(path: Path, time_field: str, cutoff: datetime | None) -> list[dict]:
    if not path.exists():
        print(f"Warning: {path} not found", file=sys.stderr)
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff is not None:
            ts = _parse_iso(rec.get(time_field, ""))
            if ts is None or ts < cutoff:
                continue
        records.append(rec)
    return records


def _date_key(iso_str: str) -> str:
    dt = _parse_iso(iso_str)
    return dt.strftime("%Y-%m-%d") if dt else "unknown"


def build_breakdown(
    trades: list[dict],
    runs: list[dict],
) -> dict:
    """Build the full breakdown structure."""
    now = datetime.now(UTC)

    # --- Per-wallet trade stats ---
    wallet_trades: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        wallet_trades[t.get("wallet", "unknown")].append(t)

    # --- Per-wallet strategy run stats ---
    wallet_runs: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        wn = r.get("wallet_name", "")
        if not wn:
            continue
        wallet_runs[wn].append(r)

    all_wallets = sorted(set(wallet_trades.keys()) | set(wallet_runs.keys()))

    wallet_summaries = []

    for wallet in all_wallets:
        wtrades = wallet_trades.get(wallet, [])
        wruns = wallet_runs.get(wallet, [])

        # Strategy type from runs or infer from wallet name
        strategy_type = "unknown"
        if wruns:
            strategy_type = wruns[0].get("strategy_type", "unknown")

        # Trade PnL
        pnls = [t.get("pnl", 0.0) for t in wtrades]
        pnl_pcts = [t.get("pnl_pct", 0.0) for t in wtrades]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0 and p != 0.0)
        # Exclude zero-pnl non-trades
        total_closed = wins + losses
        win_rate = wins / max(1, total_closed)

        # Exit reason distribution
        exit_reasons: dict[str, int] = defaultdict(int)
        for t in wtrades:
            exit_reasons[t.get("exit_reason", "unknown")] += 1

        # Confidence stats
        confidences = [
            t["entry_confidence"] for t in wtrades
            if isinstance(t.get("entry_confidence"), (int, float))
            and t["entry_confidence"] > 0
        ]

        # Signal counts from strategy runs
        total_signals = len(wruns)
        buy_signals = sum(1 for r in wruns if r.get("signal_action") == "buy")
        sell_signals = sum(1 for r in wruns if r.get("signal_action") == "sell")
        hold_signals = sum(1 for r in wruns if r.get("signal_action") == "hold")

        # Macro gate blocks: reason starts with "macro_regime_gate:"
        macro_gate_blocks = sum(
            1 for r in wruns
            if str(r.get("signal_reason", "")).startswith(_MACRO_GATE_PREFIX)
        )

        # Trend filter blocks: below_ma_filter, ema50_trend_gate, etc.
        trend_filter_blocks = sum(
            1 for r in wruns
            if r.get("signal_reason", "") in _TREND_FILTER_REASONS
        )

        # Daily PnL breakdown for this wallet
        daily_pnl: dict[str, dict] = defaultdict(
            lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
        )
        for t in wtrades:
            day = _date_key(t.get("exit_time", ""))
            daily_pnl[day]["pnl"] += t.get("pnl", 0.0)
            daily_pnl[day]["trades"] += 1
            if t.get("pnl", 0.0) > 0:
                daily_pnl[day]["wins"] += 1
            elif t.get("pnl", 0.0) < 0:
                daily_pnl[day]["losses"] += 1

        summary = {
            "wallet_name": wallet,
            "strategy_type": strategy_type,
            "total_trades": total_closed,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "total_pnl": round(sum(pnls), 2),
            "total_pnl_pct": round(sum(pnl_pcts) * 100, 4),
            "avg_pnl_per_trade": round(sum(pnls) / max(1, total_closed), 2),
            "best_trade_pnl": round(max(pnls), 2) if pnls else 0.0,
            "worst_trade_pnl": round(min(pnls), 2) if pnls else 0.0,
            "avg_entry_confidence": (
                round(sum(confidences) / len(confidences), 4) if confidences else 0.0
            ),
            "total_signals": total_signals,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "hold_signals": hold_signals,
            "macro_gate_blocks": macro_gate_blocks,
            "trend_filter_blocks": trend_filter_blocks,
            "exit_reason_distribution": dict(exit_reasons),
            "daily_breakdown": {
                day: {
                    "pnl": round(v["pnl"], 2),
                    "trades": v["trades"],
                    "wins": v["wins"],
                    "losses": v["losses"],
                }
                for day, v in sorted(daily_pnl.items())
            },
        }
        wallet_summaries.append(summary)

    # Sort by total_pnl descending
    wallet_summaries.sort(key=lambda s: s["total_pnl"], reverse=True)

    # Portfolio-level aggregation
    total_pnl = sum(s["total_pnl"] for s in wallet_summaries)
    total_trades = sum(s["total_trades"] for s in wallet_summaries)
    total_wins = sum(s["wins"] for s in wallet_summaries)
    total_losses = sum(s["losses"] for s in wallet_summaries)
    total_macro_blocks = sum(s["macro_gate_blocks"] for s in wallet_summaries)
    total_trend_blocks = sum(s["trend_filter_blocks"] for s in wallet_summaries)

    return {
        "generated_at": now.isoformat(),
        "portfolio": {
            "total_pnl": round(total_pnl, 2),
            "total_trades": total_trades,
            "total_wins": total_wins,
            "total_losses": total_losses,
            "win_rate": round(total_wins / max(1, total_wins + total_losses), 4),
            "total_macro_gate_blocks": total_macro_blocks,
            "total_trend_filter_blocks": total_trend_blocks,
        },
        "wallets": wallet_summaries,
    }


def _print_summary(data: dict) -> None:
    port = data["portfolio"]
    print("=" * 70)
    print("STRATEGY PERFORMANCE BREAKDOWN")
    print("=" * 70)
    pnl_sign = "+" if port["total_pnl"] >= 0 else ""
    print(
        f"Portfolio: {pnl_sign}{port['total_pnl']:,.0f} KRW | "
        f"{port['total_trades']} trades | "
        f"Win rate: {port['win_rate']:.1%}"
    )
    print(
        f"Macro gate blocks: {port['total_macro_gate_blocks']} | "
        f"Trend filter blocks: {port['total_trend_filter_blocks']}"
    )
    print("-" * 70)

    for w in data["wallets"]:
        pnl_sign = "+" if w["total_pnl"] >= 0 else ""
        print(
            f"\n  {w['wallet_name']} ({w['strategy_type']})"
        )
        print(
            f"    PnL: {pnl_sign}{w['total_pnl']:,.0f} KRW ({w['total_pnl_pct']:+.2f}%) | "
            f"{w['total_trades']}t | Win: {w['win_rate']:.0%}"
        )
        print(
            f"    Signals: {w['total_signals']} total | "
            f"BUY {w['buy_signals']} / SELL {w['sell_signals']} / HOLD {w['hold_signals']}"
        )
        print(
            f"    Blocks: macro_gate={w['macro_gate_blocks']} "
            f"trend_filter={w['trend_filter_blocks']}"
        )
        if w["avg_entry_confidence"] > 0:
            print(f"    Avg entry confidence: {w['avg_entry_confidence']:.3f}")
        if w["exit_reason_distribution"]:
            reasons = ", ".join(
                f"{k}={v}" for k, v in sorted(
                    w["exit_reason_distribution"].items(), key=lambda x: -x[1]
                )
            )
            print(f"    Exit reasons: {reasons}")
        if w["daily_breakdown"]:
            for day, d in w["daily_breakdown"].items():
                day_sign = "+" if d["pnl"] >= 0 else ""
                print(
                    f"      {day}: {day_sign}{d['pnl']:,.0f} KRW "
                    f"({d['trades']}t, {d['wins']}W/{d['losses']}L)"
                )

    print("\n" + "=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy performance breakdown")
    parser.add_argument(
        "--hours", type=int, default=168,
        help="Look-back window in hours (default: 168 = 7 days)",
    )
    parser.add_argument("--all", action="store_true", help="Include all trades (no cutoff)")
    parser.add_argument(
        "--trades", type=Path, default=_DEFAULT_TRADES,
        help="Path to paper-trades.jsonl",
    )
    parser.add_argument(
        "--runs", type=Path, default=_DEFAULT_RUNS,
        help="Path to strategy-runs.jsonl",
    )
    parser.add_argument(
        "--output", type=Path, default=_DEFAULT_OUTPUT,
        help="Output JSON path",
    )
    args = parser.parse_args()

    cutoff = None if args.all else datetime.now(UTC) - timedelta(hours=args.hours)

    trades = _load_jsonl(args.trades, "exit_time", cutoff)
    runs = _load_jsonl(args.runs, "recorded_at", cutoff)

    data = build_breakdown(trades, runs)
    _print_summary(data)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"\nSaved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
