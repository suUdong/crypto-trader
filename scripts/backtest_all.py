#!/usr/bin/env python3
"""Run backtests for all strategy x symbol combinations on real Upbit data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from crypto_trader.backtest.candle_cache import fetch_upbit_candles  # noqa: E402
from crypto_trader.backtest.engine import BacktestEngine  # noqa: E402
from crypto_trader.config import (  # noqa: E402
    BacktestConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
)
from crypto_trader.models import Candle  # noqa: E402
from crypto_trader.risk.manager import RiskManager  # noqa: E402
from scripts.grid_search import (  # noqa: E402
    _create_strategy_for_grid,
    _setup_kimchi_premium_mock,
)

SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
STRATEGIES = [
    "momentum",
    "momentum_pullback",
    "bollinger_rsi",
    "mean_reversion",
    "composite",
    "kimchi_premium",
    "funding_rate",
    "volume_spike",
    "obi",
    "vpin",
    "volatility_breakout",
    "ema_crossover",
    "consensus",
]
INTERVAL = "minute60"


def fetch_candles(symbol: str, days: int) -> list[Candle]:
    """Fetch hourly candles, using local cache when configured."""
    return fetch_upbit_candles(
        symbol,
        days,
        interval=INTERVAL,
        cache_dir=os.environ.get("CT_CANDLE_CACHE_DIR"),
    )


def run_backtest(
    strategy_type: str,
    candles: list[Candle],
    symbol: str,
) -> dict[str, float | int | str]:
    strategy_config = StrategyConfig()
    regime_config = RegimeConfig()
    risk_config = RiskConfig()
    backtest_config = BacktestConfig(
        initial_capital=1_000_000.0,
        fee_rate=0.0005,
        slippage_pct=0.0005,
    )

    strategy = _create_strategy_for_grid(
        strategy_type,
        {},
        strategy_config,
        regime_config,
    )
    if strategy_type == "kimchi_premium":
        _setup_kimchi_premium_mock(strategy, candles)
    if strategy_type == "funding_rate" and hasattr(strategy, "prime_backtest_funding"):
        strategy.prime_backtest_funding(symbol, candles)
    risk_manager = RiskManager(risk_config)
    engine = BacktestEngine(
        strategy=strategy,
        risk_manager=risk_manager,
        config=backtest_config,
        symbol=symbol,
    )
    result = engine.run(candles)

    return {
        "strategy": strategy_type,
        "symbol": symbol,
        "candles": len(candles),
        "return_pct": result.total_return_pct * 100,
        "max_drawdown": result.max_drawdown * 100,
        "win_rate": result.win_rate * 100,
        "trade_count": len(result.trade_log),
        "profit_factor": result.profit_factor,
        "final_equity": result.final_equity,
        "sharpe_ratio": result.sharpe_ratio,
        "sortino_ratio": result.sortino_ratio,
        "calmar_ratio": result.calmar_ratio,
        "mdd_duration_bars": result.max_drawdown_duration_bars,
    }


def _generate_comparison_report(
    all_results: list[dict[str, float | int | str]],
    days: int,
) -> str:
    """Generate a markdown strategy comparison report ranked by Sharpe and MDD."""
    report_date = datetime.now(UTC).date().isoformat()

    # Aggregate per strategy
    strat_agg: dict[str, dict[str, list[float | int]]] = {}
    for r in all_results:
        name = str(r["strategy"])
        if name not in strat_agg:
            strat_agg[name] = {
                "return_pct": [],
                "max_drawdown": [],
                "sharpe_ratio": [],
                "sortino_ratio": [],
                "calmar_ratio": [],
                "win_rate": [],
                "profit_factor": [],
                "trade_count": [],
                "mdd_duration_bars": [],
            }
        agg = strat_agg[name]
        for key in agg:
            agg[key].append(float(r[key]))  # type: ignore[arg-type]

    def _avg(vals: list[float | int]) -> float:
        return sum(float(v) for v in vals) / len(vals) if vals else 0.0

    def _cap(v: float, limit: float = 999.99) -> str:
        if abs(v) > limit or v != v:  # noqa: PLR0124
            return "inf" if v > 0 else "-inf"
        return f"{v:.2f}"

    # Rank by avg Sharpe desc, then avg MDD asc
    ranked = sorted(
        strat_agg.items(),
        key=lambda kv: (-_avg(kv[1]["sharpe_ratio"]), _avg(kv[1]["max_drawdown"])),
    )

    lines = [
        f"# {days}-Day Strategy Comparison Report",
        "",
        f"Date: {report_date}",
        "",
        "## Scope",
        "",
        f"- Window: latest **{days} days** of hourly Upbit candles",
        f"- Symbols: {', '.join(f'`{s}`' for s in SYMBOLS)}",
        f"- Strategies: {len(strat_agg)} tested",
        f"- Total results: {len(all_results)}",
        "",
        "## Strategy Ranking (by avg Sharpe ratio)",
        "",
        (
            "| Rank | Strategy | Avg Sharpe | Avg Sortino | Avg Calmar "
            "| Avg MDD% | Avg Return% | Avg WinRate% | Total Trades |"
        ),
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for rank, (name, agg) in enumerate(ranked, start=1):
        lines.append(
            f"| {rank} "
            f"| {name} "
            f"| {_cap(_avg(agg['sharpe_ratio']))} "
            f"| {_cap(_avg(agg['sortino_ratio']))} "
            f"| {_cap(_avg(agg['calmar_ratio']))} "
            f"| {_avg(agg['max_drawdown']):.2f} "
            f"| {_avg(agg['return_pct']):+.2f} "
            f"| {_avg(agg['win_rate']):.1f} "
            f"| {int(sum(agg['trade_count']))} |"
        )

    # Per-strategy × per-symbol breakdown
    lines.extend(["", "## Per-Strategy Detail", ""])
    for name, agg in ranked:
        lines.extend([
            f"### `{name}`",
            "",
            f"- Avg Sharpe: **{_cap(_avg(agg['sharpe_ratio']))}**",
            f"- Avg Sortino: {_cap(_avg(agg['sortino_ratio']))}",
            f"- Avg Calmar: {_cap(_avg(agg['calmar_ratio']))}",
            f"- Avg MDD: {_avg(agg['max_drawdown']):.2f}%",
            f"- Avg MDD Duration: {_avg(agg['mdd_duration_bars']):.0f} bars",
            f"- Avg Return: {_avg(agg['return_pct']):+.2f}%",
            f"- Avg Profit Factor: {_cap(_avg(agg['profit_factor']))}",
            f"- Total Trades: {int(sum(agg['trade_count']))}",
            "",
            "| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for r in all_results:
            if str(r["strategy"]) == name:
                pf = float(r["profit_factor"])
                lines.append(
                    f"| {r['symbol']} "
                    f"| {float(r['return_pct']):+.2f} "
                    f"| {float(r['max_drawdown']):.2f} "
                    f"| {_cap(float(r['sharpe_ratio']))} "
                    f"| {_cap(float(r['sortino_ratio']))} "
                    f"| {float(r['win_rate']):.1f} "
                    f"| {int(r['trade_count'])} "
                    f"| {_cap(pf)} |"
                )
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run backtests for all strategies and symbols.",
    )
    parser.add_argument("days", nargs="?", type=int, default=90)
    parser.add_argument("--json-out", dest="json_out")
    parser.add_argument("--cache-dir", dest="cache_dir")
    parser.add_argument("--report-dir", dest="report_dir", default="backtest_results")
    args = parser.parse_args()

    days = args.days
    if args.cache_dir:
        os.environ["CT_CANDLE_CACHE_DIR"] = args.cache_dir

    print(f"\n{'=' * 80}")
    print(f"  BACKTEST ALL STRATEGIES - {days}-day hourly candles from Upbit")
    print(f"{'=' * 80}\n")

    header = (
        f"{'Strategy':<16} {'Symbol':<10} {'Candles':>7} "
        f"{'Return%':>9} {'MDD%':>7} {'Sharpe':>8} "
        f"{'WinRate%':>9} {'Trades':>7} {'PF':>7}"
    )
    print(header)
    print("-" * len(header))

    all_results: list[dict[str, float | int | str]] = []

    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")

        if len(candles) < 50:
            print(f"  SKIP: insufficient data ({len(candles)} candles)")
            continue

        for strategy_type in STRATEGIES:
            result = run_backtest(strategy_type, candles, symbol)
            all_results.append(result)
            pf = result["profit_factor"]
            pf_str = f"{pf:.2f}" if isinstance(pf, float) and pf < 1000 else "inf"
            sharpe = result["sharpe_ratio"]
            sharpe_str = (
                f"{sharpe:.2f}" if isinstance(sharpe, float) and abs(sharpe) < 1e6 else "inf"
            )
            print(
                f"{result['strategy']:<16} {result['symbol']:<10} "
                f"{result['candles']:>7} "
                f"{result['return_pct']:>+8.2f}% "
                f"{result['max_drawdown']:>6.2f}% "
                f"{sharpe_str:>8} "
                f"{result['win_rate']:>8.1f}% "
                f"{result['trade_count']:>7} "
                f"{pf_str:>7}"
            )

    # Summary
    print(f"\n{'=' * 80}")
    print("  SUMMARY")
    print(f"{'=' * 80}")
    total_trades = sum(int(r["trade_count"]) for r in all_results)
    strategies_with_trades = {r["strategy"] for r in all_results if int(r["trade_count"]) > 0}
    symbols_with_trades = {r["symbol"] for r in all_results if int(r["trade_count"]) > 0}
    print(f"  Total trades across all combos: {total_trades}")
    print(f"  Strategies generating trades: {strategies_with_trades or 'NONE'}")
    print(f"  Symbols with trades: {symbols_with_trades or 'NONE'}")

    if total_trades == 0:
        print("\n  WARNING: No trades generated. Parameters may still be too conservative.")
        sys.exit(1)
    else:
        count = len(strategies_with_trades)
        print(f"\n  SUCCESS: {total_trades} trades across {count} strategies")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {
                    "days": days,
                    "interval": INTERVAL,
                    "symbols": SYMBOLS,
                    "strategies": STRATEGIES,
                    "results": all_results,
                    "summary": {
                        "total_trades": total_trades,
                        "strategies_with_trades": sorted(strategies_with_trades),
                        "symbols_with_trades": sorted(symbols_with_trades),
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\n  JSON results written to: {args.json_out}")

    # Generate comparison report
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"strategy-comparison-{days}d.md"
    report_path.write_text(
        _generate_comparison_report(all_results, days),
        encoding="utf-8",
    )
    print(f"  Comparison report written to: {report_path}")


if __name__ == "__main__":
    main()
