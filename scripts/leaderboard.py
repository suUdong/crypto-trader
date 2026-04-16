#!/usr/bin/env python3
"""crypto-trader wallet leaderboard — ranked table with live status and PnL."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tomllib
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"

_COLOR_ENABLED = True


def _c(code: str, text: str) -> str:
    if not _COLOR_ENABLED:
        return text
    return f"{code}{text}{RESET}"


def green(t: str) -> str:
    return _c(GREEN, t)


def red(t: str) -> str:
    return _c(RED, t)


def yellow(t: str) -> str:
    return _c(YELLOW, t)


def bold(t: str) -> str:
    return _c(BOLD, t)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_active_wallets(config_path: str) -> dict[str, str]:
    """Return {wallet_name: strategy} for active (non-commented) wallets in TOML."""
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    result: dict[str, str] = {}
    for w in data.get("wallets", []):
        name = w.get("name", "")
        strategy = w.get("strategy", "")
        if name:
            result[name] = strategy
    return result


def load_trades(db_path: str) -> list[dict[str, Any]]:
    """Return deduplicated closed trades from SQLite (or empty list if missing)."""
    if not os.path.exists(db_path):
        return []
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        # Deduplicate across sessions — same (wallet, symbol, entry_time, exit_time) = 1 trade
        cur.execute(
            """
            SELECT
                wallet,
                symbol,
                entry_time,
                exit_time,
                AVG(entry_price)  AS entry_price,
                AVG(exit_price)   AS exit_price,
                AVG(pnl)          AS pnl,
                AVG(pnl_pct)      AS pnl_pct,
                MAX(exit_reason)  AS exit_reason
            FROM trades
            GROUP BY wallet, symbol, entry_time, exit_time
            ORDER BY wallet, entry_time
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] failed to read DB: {exc}", file=sys.stderr)
        return []


def load_positions(positions_path: str) -> tuple[list[dict[str, Any]], str]:
    """Return (positions_list, generated_at_str)."""
    if not os.path.exists(positions_path):
        return [], ""
    try:
        with open(positions_path) as f:
            data = json.load(f)
        return data.get("positions", []), data.get("generated_at", "")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] failed to read positions.json: {exc}", file=sys.stderr)
        return [], ""


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def build_wallet_rows(
    active_wallets: dict[str, str],
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate per-wallet stats and return list of row dicts."""

    # --- realized PnL & trade counts per wallet ---
    realized: dict[str, float] = {}
    wins: dict[str, int] = {}
    counts: dict[str, int] = {}
    all_wallets_in_db: set[str] = set()

    for t in trades:
        w = t["wallet"]
        all_wallets_in_db.add(w)
        realized[w] = realized.get(w, 0.0) + t["pnl"]
        counts[w] = counts.get(w, 0) + 1
        if t["pnl"] > 0:
            wins[w] = wins.get(w, 0) + 1

    # --- unrealized PnL & open position count per wallet ---
    unrealized: dict[str, float] = {}
    open_count: dict[str, int] = {}
    for p in positions:
        w = p["wallet"]
        unrealized[w] = unrealized.get(w, 0.0) + p.get("unrealized_pnl", 0.0)
        open_count[w] = open_count.get(w, 0) + 1

    # Union of all known wallets
    all_names: set[str] = set(active_wallets.keys()) | all_wallets_in_db

    rows: list[dict[str, Any]] = []
    for name in all_names:
        is_active = name in active_wallets
        strategy = active_wallets.get(name, "—")
        n_trades = counts.get(name, 0)
        n_wins = wins.get(name, 0)
        win_rate = n_wins / n_trades if n_trades > 0 else 0.0
        r_pnl = realized.get(name, 0.0)
        u_pnl = unrealized.get(name, 0.0)
        n_open = open_count.get(name, 0)

        if not is_active:
            status = "제외"
        elif n_open > 0:
            status = "매매중"
        else:
            status = "대기"

        rows.append(
            {
                "name": name,
                "strategy": strategy,
                "status": status,
                "is_active": is_active,
                "trade_count": n_trades,
                "win_rate": win_rate,
                "realized_pnl": r_pnl,
                "unrealized_pnl": u_pnl,
                "open_positions": n_open,
                "total_pnl": r_pnl + u_pnl,
            }
        )

    # Sort by total PnL descending
    rows.sort(key=lambda r: r["total_pnl"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_pnl(val: float, width: int = 12) -> str:
    """Format PnL with sign, Korean Won symbol, color."""
    sign = "+" if val >= 0 else ""
    s = f"₩{sign}{val:,.0f}"
    colored = green(s) if val >= 0 else red(s)
    # Pad to visual width (color codes are invisible)
    pad = max(0, width - len(s))
    return " " * pad + colored


def fmt_wr(win_rate: float, trade_count: int) -> str:
    pct = f"{win_rate * 100:.0f}%"
    if win_rate >= 0.5:
        return green(pct)
    if win_rate < 0.20 and trade_count >= 5:
        return red(pct)
    return pct


def fmt_status(status: str) -> str:
    if status == "매매중":
        return green(status)
    if status == "제외":
        return red(status)
    return yellow(status)


def truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------

COL_RANK = 4
COL_NAME = 30
COL_STRAT = 18
COL_STATUS = 8
COL_COUNT = 6
COL_WR = 6
COL_RPNL = 13
COL_UPNL = 13
COL_OPEN = 5

SEP = "─" * 100


def print_table(rows: list[dict[str, Any]], generated_at: str) -> None:
    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M UTC")
    # Use positions.json timestamp if available
    if generated_at:
        try:
            ts = datetime.fromisoformat(generated_at)
            now_str = ts.strftime("%Y-%m-%dT%H:%M UTC")
        except ValueError:
            pass

    title = f"  CRYPTO-TRADER LEADERBOARD  {now_str}"
    print()
    print(bold(title))
    print()

    # Header
    hdr = (
        f"  {'순위':<{COL_RANK}}"
        f"{'지갑':<{COL_NAME}}"
        f"{'전략':<{COL_STRAT}}"
        f"{'상태':<{COL_STATUS}}"
        f"{'건수':>{COL_COUNT}}"
        f"{'WR':>{COL_WR}}"
        f"{'실현PnL':>{COL_RPNL}}"
        f"{'미실현':>{COL_UPNL}}"
        f"{'포지션':>{COL_OPEN}}"
    )
    print(bold(hdr))
    print("  " + SEP)

    total_trades = 0
    total_wins = 0
    total_rpnl = 0.0
    total_upnl = 0.0
    total_open = 0

    for i, row in enumerate(rows, start=1):
        name = truncate(row["name"], COL_NAME)
        strategy = truncate(row["strategy"], COL_STRAT)
        status_str = fmt_status(row["status"])
        # Visual width of status (strip ANSI for padding calc)
        status_plain = row["status"]
        status_pad = COL_STATUS - len(status_plain)

        wr_str = fmt_wr(row["win_rate"], row["trade_count"])
        wr_plain = f"{row['win_rate'] * 100:.0f}%"
        wr_pad = COL_WR - len(wr_plain)

        rpnl_str = fmt_pnl(row["realized_pnl"], COL_RPNL)
        upnl_str = fmt_pnl(row["unrealized_pnl"], COL_UPNL)

        open_str = f"{row['open_positions']}건"

        print(
            f"  {i:<{COL_RANK}}"
            f"{name:<{COL_NAME}}"
            f"{strategy:<{COL_STRAT}}"
            f"{status_str}{' ' * status_pad}"
            f"{row['trade_count']:>{COL_COUNT}}"
            f"{' ' * wr_pad}{wr_str}"
            f"{rpnl_str}"
            f"{upnl_str}"
            f"{open_str:>{COL_OPEN}}"
        )

        total_trades += row["trade_count"]
        total_wins += int(row["win_rate"] * row["trade_count"])
        total_rpnl += row["realized_pnl"]
        total_upnl += row["unrealized_pnl"]
        total_open += row["open_positions"]

    print("  " + SEP)

    total_wr = total_wins / total_trades if total_trades > 0 else 0.0
    total_wr_str = fmt_wr(total_wr, total_trades)
    total_wr_plain = f"{total_wr * 100:.0f}%"
    total_wr_pad = COL_WR - len(total_wr_plain)

    total_rpnl_str = fmt_pnl(total_rpnl, COL_RPNL)
    total_upnl_str = fmt_pnl(total_upnl, COL_UPNL)
    total_open_str = f"{total_open}건"

    label = "TOTAL"
    print(
        f"  {'':<{COL_RANK}}"
        f"{bold(label):<{COL_NAME + 18}}"
        f"{' ' * COL_STATUS}"
        f"{total_trades:>{COL_COUNT}}"
        f"{' ' * total_wr_pad}{total_wr_str}"
        f"{total_rpnl_str}"
        f"{total_upnl_str}"
        f"{total_open_str:>{COL_OPEN}}"
    )

    grand_total = total_rpnl + total_upnl
    grand_str = fmt_pnl(grand_total)
    print(f"      합산: {grand_str}")
    print()


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def print_json(rows: list[dict[str, Any]], generated_at: str) -> None:
    out = {
        "generated_at": generated_at,
        "wallets": rows,
        "summary": {
            "total_trades": sum(r["trade_count"] for r in rows),
            "total_realized_pnl": sum(r["realized_pnl"] for r in rows),
            "total_unrealized_pnl": sum(r["unrealized_pnl"] for r in rows),
            "total_pnl": sum(r["total_pnl"] for r in rows),
            "total_open_positions": sum(r["open_positions"] for r in rows),
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="crypto-trader wallet leaderboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    parser.add_argument(
        "--config",
        default="config/daemon.toml",
        metavar="PATH",
        help="Path to daemon.toml (default: config/daemon.toml)",
    )
    parser.add_argument(
        "--db",
        default="artifacts/paper-trades.db",
        metavar="PATH",
        help="Path to paper-trades.db (default: artifacts/paper-trades.db)",
    )
    parser.add_argument(
        "--positions",
        default="artifacts/positions.json",
        metavar="PATH",
        help="Path to positions.json (default: artifacts/positions.json)",
    )
    return parser.parse_args()


def main() -> None:
    global _COLOR_ENABLED  # noqa: PLW0603

    args = parse_args()

    if args.no_color or args.json:
        _COLOR_ENABLED = False

    # Resolve paths relative to the script's project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    def resolve(p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(project_root, p)

    config_path = resolve(args.config)
    db_path = resolve(args.db)
    positions_path = resolve(args.positions)

    active_wallets = load_active_wallets(config_path)
    trades = load_trades(db_path)
    positions, generated_at = load_positions(positions_path)

    rows = build_wallet_rows(active_wallets, trades, positions)

    if args.json:
        print_json(rows, generated_at)
    else:
        print_table(rows, generated_at)


if __name__ == "__main__":
    main()
