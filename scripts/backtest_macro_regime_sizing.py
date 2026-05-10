#!/usr/bin/env python3
"""Replay paper trades with macro-intelligence regime sizing multipliers.

The replay keeps each historical trade's entry and exit logic fixed, then scales
trade PnL by the macro multiplier that would have been active on entry date.
That isolates the wallet-sizing effect from strategy selection.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TRADES = _PROJECT_ROOT / "artifacts" / "paper-trades.jsonl"
_DEFAULT_OUTPUT = _PROJECT_ROOT / "artifacts" / "macro-regime-sizing-backtest.json"
_DEFAULT_MACRO_REPO = _PROJECT_ROOT.parent / "macro-intelligence"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _dedupe_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for trade in trades:
        key = (
            trade.get("symbol"),
            trade.get("entry_time"),
            trade.get("exit_time"),
            trade.get("wallet"),
            trade.get("exit_reason"),
            round(float(trade.get("entry_price", 0.0) or 0.0), 6),
            round(float(trade.get("exit_price", 0.0) or 0.0), 6),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(trade)
    return deduped


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _sharpe(returns: list[float], annualization: float = 365.0) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return mean / std * math.sqrt(annualization)


def _level(score: float) -> str:
    if score >= 0.30:
        return "risk_on"
    if score <= -0.30:
        return "risk_off"
    return "neutral"


def _multiplier(score: float) -> float:
    return max(0.50, min(1.50, 1.0 + score * 0.5))


def _risk_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    macro_risk = payload.get("macro_risk")
    if isinstance(macro_risk, dict) and isinstance(macro_risk.get("score"), (int, float)):
        score = max(-1.0, min(1.0, float(macro_risk["score"])))
        return {
            "score": score,
            "level": str(macro_risk.get("level") or _level(score)),
            "multiplier": float(macro_risk.get("position_size_multiplier") or _multiplier(score)),
        }

    layers = payload.get("layers", {})
    scores: dict[str, float] = {}
    for name in ("us", "kr", "crypto"):
        layer = layers.get(name, {}) if isinstance(layers, dict) else {}
        raw = layer.get("ensemble_score") if isinstance(layer, dict) else None
        if isinstance(raw, (int, float)):
            scores[name] = max(-1.0, min(1.0, float(raw)))
        else:
            regime = (
                str(layer.get("regime", "neutral")).lower()
                if isinstance(layer, dict)
                else "neutral"
            )
            scores[name] = {
                "expansionary": 1.0,
                "neutral": 0.0,
                "contractionary": -1.0,
            }.get(regime, 0.0)

    weighted = scores["us"] * 0.50 + scores["kr"] * 0.25 + scores["crypto"] * 0.25
    score = max(-1.0, min(1.0, weighted * 0.60 + scores["crypto"] * 0.40))
    return {"score": score, "level": _level(score), "multiplier": _multiplier(score)}


def _macro_lookup(macro_repo: Path, db_path: str | None):
    macro_src = macro_repo / "src"
    if macro_src.exists() and str(macro_src) not in sys.path:
        sys.path.insert(0, str(macro_src))
    try:
        from macro_intelligence.api import get_downstream_regime, get_regime_summary_for_date
        from macro_intelligence.config import Config
    except Exception as exc:
        raise RuntimeError(f"macro-intelligence import failed: {exc}") from exc

    config = Config()
    if db_path:
        config.db_path = Path(db_path)

    cache: dict[date, dict[str, Any]] = {}

    def _lookup(day: date) -> dict[str, Any]:
        if day not in cache:
            payload = get_regime_summary_for_date(day, config=config)
            if payload.get("status") != "ok":
                payload = get_downstream_regime("crypto-trader", config=config)
            cache[day] = _risk_from_payload(payload) if payload.get("status") == "ok" else {
                "score": 0.0,
                "level": "unavailable",
                "multiplier": 1.0,
            }
        return cache[day]

    return _lookup


def run_backtest(
    trades_path: Path,
    macro_repo: Path,
    db_path: str | None,
    initial_capital: float,
    dedupe: bool,
) -> dict[str, Any]:
    raw_trades = _load_jsonl(trades_path)
    trades = _dedupe_trades(raw_trades) if dedupe else raw_trades
    lookup = _macro_lookup(macro_repo, db_path)
    daily: dict[str, dict[str, float]] = defaultdict(
        lambda: {"baseline_pnl": 0.0, "macro_pnl": 0.0}
    )
    multiplier_counts: dict[str, int] = defaultdict(int)
    used_trades = 0

    for trade in trades:
        entry_dt = _parse_dt(trade.get("entry_time"))
        exit_dt = _parse_dt(trade.get("exit_time")) or entry_dt
        pnl = trade.get("pnl")
        if entry_dt is None or exit_dt is None or not isinstance(pnl, (int, float)):
            continue
        risk = lookup(entry_dt.date())
        multiplier = float(risk["multiplier"])
        day_key = exit_dt.date().isoformat()
        daily[day_key]["baseline_pnl"] += float(pnl)
        daily[day_key]["macro_pnl"] += float(pnl) * multiplier
        multiplier_counts[str(risk["level"])] += 1
        used_trades += 1

    daily_rows = [
        {
            "date": day,
            "baseline_pnl": values["baseline_pnl"],
            "macro_pnl": values["macro_pnl"],
            "baseline_return": values["baseline_pnl"] / initial_capital,
            "macro_return": values["macro_pnl"] / initial_capital,
        }
        for day, values in sorted(daily.items())
    ]
    baseline_returns = [row["baseline_return"] for row in daily_rows]
    macro_returns = [row["macro_return"] for row in daily_rows]
    baseline_sharpe = _sharpe(baseline_returns)
    macro_sharpe = _sharpe(macro_returns)
    return {
        "trades_path": str(trades_path),
        "raw_trade_rows": len(raw_trades),
        "deduped": dedupe,
        "trade_count": used_trades,
        "daily_points": len(daily_rows),
        "initial_capital": initial_capital,
        "baseline_total_pnl": round(sum(row["baseline_pnl"] for row in daily_rows), 2),
        "macro_total_pnl": round(sum(row["macro_pnl"] for row in daily_rows), 2),
        "baseline_sharpe": round(baseline_sharpe, 4) if baseline_sharpe is not None else None,
        "macro_sharpe": round(macro_sharpe, 4) if macro_sharpe is not None else None,
        "sharpe_delta": (
            round(macro_sharpe - baseline_sharpe, 4)
            if baseline_sharpe is not None and macro_sharpe is not None
            else None
        ),
        "macro_level_trade_counts": dict(sorted(multiplier_counts.items())),
        "daily": daily_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path, default=_DEFAULT_TRADES)
    parser.add_argument("--macro-repo", type=Path, default=_DEFAULT_MACRO_REPO)
    parser.add_argument("--macro-db", default="")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--no-dedupe", action="store_true")
    args = parser.parse_args()

    result = run_backtest(
        trades_path=args.trades,
        macro_repo=args.macro_repo,
        db_path=args.macro_db or None,
        initial_capital=args.initial_capital,
        dedupe=not args.no_dedupe,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Macro regime sizing replay")
    print(f"Trades: {result['trade_count']} | daily points: {result['daily_points']}")
    print(f"Baseline Sharpe: {result['baseline_sharpe']}")
    print(f"Macro-adjusted Sharpe: {result['macro_sharpe']}")
    print(f"Sharpe delta: {result['sharpe_delta']}")
    print(f"Baseline PnL: {result['baseline_total_pnl']}")
    print(f"Macro-adjusted PnL: {result['macro_total_pnl']}")
    print(f"Macro levels: {result['macro_level_trade_counts']}")
    print(f"Wrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
