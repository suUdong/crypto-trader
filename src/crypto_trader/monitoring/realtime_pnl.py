from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_position_snapshot(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("position snapshot must be a JSON object")
    positions = payload.get("positions", [])
    if not isinstance(positions, list):
        raise ValueError("position snapshot positions must be a list")
    payload["positions"] = positions
    return payload


def sorted_position_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    positions = snapshot.get("positions", [])
    return sorted(
        (row for row in positions if isinstance(row, dict)),
        key=lambda row: abs(float(row.get("unrealized_pnl", 0.0) or 0.0)),
        reverse=True,
    )


def format_position_snapshot(snapshot: dict[str, Any]) -> str:
    generated_at = str(snapshot.get("generated_at", "n/a"))
    positions = sorted_position_rows(snapshot)
    total_unrealized = float(snapshot.get("total_unrealized_pnl", 0.0) or 0.0)
    equity = float(snapshot.get("mark_to_market_equity", 0.0) or 0.0)
    lines = [
        f"Snapshot: {generated_at}",
        (
            f"Open positions: {len(positions)} | "
            f"Unrealized P&L: {total_unrealized:+,.0f} KRW | "
            f"Equity: {equity:,.0f} KRW"
        ),
    ]
    if not positions:
        lines.append("No open positions.")
        return "\n".join(lines)

    header = (
        f"{'Wallet':<20} {'Symbol':<12} {'Qty':>10} {'Entry':>12} "
        f"{'Market':>12} {'P&L':>12} {'P&L %':>8}"
    )
    lines.extend([header, "-" * len(header)])
    for row in positions:
        lines.append(
            f"{str(row.get('wallet', '-')):<20} "
            f"{str(row.get('symbol', '-')):<12} "
            f"{float(row.get('qty', 0.0) or 0.0):>10.6f} "
            f"{float(row.get('entry_price', 0.0) or 0.0):>12,.0f} "
            f"{float(row.get('market_price', 0.0) or 0.0):>12,.0f} "
            f"{float(row.get('unrealized_pnl', 0.0) or 0.0):>+12,.0f} "
            f"{float(row.get('unrealized_pnl_pct', 0.0) or 0.0) * 100:>+7.2f}%"
        )
    return "\n".join(lines)
