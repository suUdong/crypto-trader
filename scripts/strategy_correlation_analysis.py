#!/usr/bin/env python3
"""Generate strategy-correlation artifacts for diversification analysis."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from crypto_trader.backtest.candle_cache import fetch_upbit_candles  # noqa: E402
from crypto_trader.backtest.correlation import (  # noqa: E402
    diversification_multipliers,
    rank_portfolios,
    signal_correlation,
)
from crypto_trader.config import RegimeConfig, StrategyConfig  # noqa: E402
from crypto_trader.wallet import create_strategy  # noqa: E402

DEFAULT_TUNED = ROOT / "artifacts" / "backtest-grid-90d" / "combined.json"
DEFAULT_OUTPUT_JSON = ROOT / "artifacts" / "strategy-correlation-90d.json"
DEFAULT_OUTPUT_MD = ROOT / "artifacts" / "strategy-correlation-90d.md"
SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]


def _load_tuned_results(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized: dict[str, dict[str, Any]] = {}
    for row in payload.get("optimized_results", []):
        if not isinstance(row, dict):
            continue
        strategy = row.get("strategy")
        if not isinstance(strategy, str):
            continue
        normalized[strategy] = {
            "params": dict(row.get("params", {})),
            "sharpe": float(row.get("avg_sharpe", 0.0)),
            "return_pct": float(row.get("avg_return_pct", 0.0)),
            "profit_factor": float(row.get("avg_profit_factor", 0.0)),
        }
    return normalized


def _build_strategy(strategy_name: str, params: dict[str, Any], candles: list[Any]) -> object:
    config_fields = set(StrategyConfig.__dataclass_fields__)
    strategy_config = StrategyConfig(**{k: v for k, v in params.items() if k in config_fields})
    strategy = create_strategy(strategy_name, strategy_config, RegimeConfig(), params)
    if strategy_name == "kimchi_premium":
        closes = [c.close for c in candles]
        if len(closes) >= 50:
            ma50 = sum(closes[-50:]) / 50.0
            if ma50 > 0:
                strategy._cached_premium = (closes[-1] - ma50) / ma50  # type: ignore[attr-defined]
        strategy._binance = MagicMock()  # type: ignore[attr-defined]
        strategy._fx = MagicMock()  # type: ignore[attr-defined]
        strategy._binance.get_usdt_price.return_value = None  # type: ignore[attr-defined]
        strategy._fx.get_usd_krw_rate.return_value = None  # type: ignore[attr-defined]
    return strategy


def _fetch_candles(symbol: str, days: int) -> list[Any]:
    return fetch_upbit_candles(
        symbol,
        days,
        interval="minute60",
        cache_dir=os.environ.get("CT_CANDLE_CACHE_DIR"),
    )


def _average_matrices(
    matrices: list[dict[tuple[str, str], float]],
    strategy_names: list[str],
) -> dict[tuple[str, str], float]:
    averaged: dict[tuple[str, str], float] = {}
    for i, name_a in enumerate(strategy_names):
        for name_b in strategy_names[i:]:
            values = []
            for matrix in matrices:
                key = (name_a, name_b) if (name_a, name_b) in matrix else (name_b, name_a)
                values.append(matrix.get(key, 0.0))
            averaged[(name_a, name_b)] = sum(values) / len(values) if values else 0.0
    return averaged


def _json_matrix(
    corr_matrix: dict[tuple[str, str], float],
    strategy_names: list[str],
) -> dict[str, dict[str, float]]:
    payload: dict[str, dict[str, float]] = {}
    for name_a in strategy_names:
        payload[name_a] = {}
        for name_b in strategy_names:
            key = (name_a, name_b) if (name_a, name_b) in corr_matrix else (name_b, name_a)
            payload[name_a][name_b] = float(corr_matrix.get(key, 0.0))
    return payload


def _markdown_report(
    strategy_names: list[str],
    corr_matrix: dict[tuple[str, str], float],
    ranked: list[dict[str, float | list[str]]],
    multipliers: dict[str, float],
) -> str:
    lines = [
        "# Strategy Correlation Analysis",
        "",
        "## Pairwise Correlation",
        "",
        "| Strategy | " + " | ".join(strategy_names) + " |",
        "| --- | " + " | ".join("---:" for _ in strategy_names) + " |",
    ]
    for name_a in strategy_names:
        row = [name_a]
        for name_b in strategy_names:
            key = (name_a, name_b) if (name_a, name_b) in corr_matrix else (name_b, name_a)
            row.append(f"{corr_matrix.get(key, 0.0):.3f}")
        lines.append("| " + " | ".join(row) + " |")

    lines.extend(["", "## Diversification Multipliers", ""])
    for strategy_name in strategy_names:
        lines.append(f"- `{strategy_name}`: `{multipliers.get(strategy_name, 1.0):.2f}`")

    lines.extend(["", "## Top Diversified Portfolios", ""])
    for item in ranked[:10]:
        strategies = " + ".join(str(name) for name in item["strategies"])
        lines.append(
            f"- `{strategies}`: score={float(item['portfolio_score']):.3f}, "
            f"div={float(item['diversification_score']):.3f}, "
            f"avg_corr={float(item['avg_correlation']):.3f}, "
            f"avg_sharpe={float(item['avg_sharpe']):.2f}, "
            f"avg_ret={float(item['avg_return_pct']):+.2f}%"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy correlation analysis.")
    parser.add_argument("days", nargs="?", type=int, default=90)
    parser.add_argument("--tuned", type=Path, default=DEFAULT_TUNED)
    parser.add_argument("--json-out", dest="json_out", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--md-out", dest="md_out", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--cache-dir", dest="cache_dir")
    args = parser.parse_args()

    if args.cache_dir:
        os.environ["CT_CANDLE_CACHE_DIR"] = args.cache_dir

    tuned = _load_tuned_results(args.tuned)
    strategy_names = sorted(tuned)
    if not strategy_names:
        raise ValueError("No tuned strategy results found.")

    matrices = []
    for symbol in SYMBOLS:
        candles = _fetch_candles(symbol, args.days)
        strategies = [
            _build_strategy(strategy_name, tuned[strategy_name]["params"], candles)
            for strategy_name in strategy_names
        ]
        matrices.append(signal_correlation(strategies, candles, strategy_names))

    corr_matrix = _average_matrices(matrices, strategy_names)
    performance = {
        strategy_name: {
            "sharpe": float(tuned[strategy_name]["sharpe"]),
            "return_pct": float(tuned[strategy_name]["return_pct"]),
            "profit_factor": float(tuned[strategy_name]["profit_factor"]),
        }
        for strategy_name in strategy_names
    }
    ranked = rank_portfolios(
        corr_matrix,
        performance,
        min_size=2,
        max_size=min(4, len(strategy_names)),
    )
    multipliers = diversification_multipliers(strategy_names, corr_matrix)

    payload = {
        "days": args.days,
        "strategies": strategy_names,
        "pairwise_correlation": _json_matrix(corr_matrix, strategy_names),
        "diversification_multipliers": multipliers,
        "top_portfolios": ranked[:25],
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(
        _markdown_report(strategy_names, corr_matrix, ranked, multipliers) + "\n",
        encoding="utf-8",
    )
    print(args.json_out)
    print(args.md_out)


if __name__ == "__main__":
    main()
