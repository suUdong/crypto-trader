"""Loss-attribution analysis for paper-trades.jsonl.

Deduplicates session-replicated rows and groups by wallet, symbol, exit_reason
to identify the largest realized-PnL drains. Writes a Markdown report.

Usage:
    python scripts/analyze_paper_losses.py \
        --input artifacts/paper-trades.jsonl \
        --output artifacts/loss-attribution-2026-05-11.md
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_trades(path: Path) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            trades.append(json.loads(line))
    return trades


def dedupe(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop session-replicated rows.

    The daemon writes the same trade once per session_id when multiple daemon
    sessions reload an open position. Dedup key intentionally excludes
    session_id and quantity (quantity differs across reloads but represents
    the same logical trade).
    """
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for t in trades:
        key = (
            t.get("symbol"),
            t.get("entry_time"),
            t.get("exit_time"),
            t.get("wallet"),
            t.get("exit_reason"),
            round(float(t.get("entry_price", 0.0)), 6),
            round(float(t.get("exit_price", 0.0)), 6),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def group_stats(
    trades: list[dict[str, Any]], key: str
) -> list[tuple[str, int, int, float, float]]:
    """Return (group_value, count, wins, total_pnl, win_rate)."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        buckets[str(t.get(key, "<unknown>"))].append(t)
    rows = []
    for group, items in buckets.items():
        total_pnl = sum(float(t.get("pnl", 0.0)) for t in items)
        wins = sum(1 for t in items if float(t.get("pnl", 0.0)) > 0)
        wr = wins / len(items) if items else 0.0
        rows.append((group, len(items), wins, total_pnl, wr))
    rows.sort(key=lambda r: r[3])  # ascending PnL — worst first
    return rows


def format_table(
    rows: list[tuple[str, int, int, float, float]],
    header: str,
    limit: int | None = None,
) -> str:
    out = [
        f"### {header}",
        "",
        "| Group | Trades | Wins | WR | Total PnL (₩) |",
        "|---|---:|---:|---:|---:|",
    ]
    show = rows[:limit] if limit else rows
    for grp, n, wins, pnl, wr in show:
        out.append(f"| `{grp}` | {n} | {wins} | {wr*100:.1f}% | {pnl:+,.0f} |")
    out.append("")
    return "\n".join(out)


def cross_breakdown(
    trades: list[dict[str, Any]], key_a: str, key_b: str, limit: int = 15
) -> str:
    """Top-N worst (key_a × key_b) pairs by total PnL."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        k = (str(t.get(key_a, "?")), str(t.get(key_b, "?")))
        buckets[k].append(t)
    rows = []
    for (a, b), items in buckets.items():
        total_pnl = sum(float(t.get("pnl", 0.0)) for t in items)
        wins = sum(1 for t in items if float(t.get("pnl", 0.0)) > 0)
        wr = wins / len(items) if items else 0.0
        rows.append((a, b, len(items), wins, total_pnl, wr))
    rows.sort(key=lambda r: r[4])
    out = [
        f"### Worst {key_a} × {key_b} pairs (top {limit})",
        "",
        f"| {key_a} | {key_b} | Trades | WR | Total PnL (₩) |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows[:limit]:
        a, b, n, _, pnl, wr = row
        out.append(f"| `{a}` | `{b}` | {n} | {wr*100:.1f}% | {pnl:+,.0f} |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="artifacts/paper-trades.jsonl")
    p.add_argument("--output", default="artifacts/loss-attribution-2026-05-11.md")
    args = p.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    raw = load_trades(in_path)
    deduped = dedupe(raw)

    total_pnl = sum(float(t.get("pnl", 0.0)) for t in deduped)
    wins = sum(1 for t in deduped if float(t.get("pnl", 0.0)) > 0)
    losses = sum(1 for t in deduped if float(t.get("pnl", 0.0)) < 0)
    flats = len(deduped) - wins - losses
    wr = wins / len(deduped) if deduped else 0.0

    wallet_rows = group_stats(deduped, "wallet")
    symbol_rows = group_stats(deduped, "symbol")
    reason_rows = group_stats(deduped, "exit_reason")

    lines = [
        "# Loss Attribution Report — 2026-05-11",
        "",
        f"- Raw rows: **{len(raw)}**",
        f"- After dedup: **{len(deduped)}** unique trades",
        f"- Wins / Losses / Flat: **{wins} / {losses} / {flats}**",
        f"- Aggregate win rate: **{wr*100:.1f}%**",
        f"- Aggregate realized PnL (deduped): **₩{total_pnl:+,.0f}**",
        "",
        "Dedup key: (symbol, entry_time, exit_time, wallet, exit_reason, entry_price, exit_price). "
        "Session-replicated duplicates collapsed.",
        "",
        format_table(wallet_rows, "All wallets sorted by total PnL (worst first)"),
        format_table(symbol_rows, "All symbols sorted by total PnL (worst first)"),
        format_table(reason_rows, "All exit_reasons sorted by total PnL (worst first)"),
        cross_breakdown(deduped, "wallet", "exit_reason", limit=20),
        cross_breakdown(deduped, "wallet", "symbol", limit=20),
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path} ({len(deduped)} unique trades, PnL ₩{total_pnl:+,.0f})")


if __name__ == "__main__":
    main()
