#!/usr/bin/env python3
"""Run backtests for all strategy x symbol combinations on real Upbit data."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

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
from crypto_trader.wallet import create_strategy  # noqa: E402

SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
STRATEGIES = ["momentum", "mean_reversion", "composite", "kimchi_premium", "obi", "vpin", "volatility_breakout"]
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

    strategy = create_strategy(strategy_type, strategy_config, regime_config)
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
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run backtests for all strategies and symbols.",
    )
    parser.add_argument("days", nargs="?", type=int, default=90)
    parser.add_argument("--json-out", dest="json_out")
    parser.add_argument("--cache-dir", dest="cache_dir")
    args = parser.parse_args()

    days = args.days
    if args.cache_dir:
        os.environ["CT_CANDLE_CACHE_DIR"] = args.cache_dir

    print(f"\n{'='*80}")
    print(f"  BACKTEST ALL STRATEGIES - {days}-day hourly candles from Upbit")
    print(f"{'='*80}\n")

    header = (
        f"{'Strategy':<16} {'Symbol':<10} {'Candles':>7} "
        f"{'Return%':>9} {'MDD%':>7} {'WinRate%':>9} "
        f"{'Trades':>7} {'PF':>7}"
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
            print(
                f"{result['strategy']:<16} {result['symbol']:<10} "
                f"{result['candles']:>7} "
                f"{result['return_pct']:>+8.2f}% "
                f"{result['max_drawdown']:>6.2f}% "
                f"{result['win_rate']:>8.1f}% "
                f"{result['trade_count']:>7} "
                f"{pf_str:>7}"
            )

    # Summary
    print(f"\n{'='*80}")
    print("  SUMMARY")
    print(f"{'='*80}")
    total_trades = sum(int(r["trade_count"]) for r in all_results)
    strategies_with_trades = {
        r["strategy"] for r in all_results if int(r["trade_count"]) > 0
    }
    symbols_with_trades = {
        r["symbol"] for r in all_results if int(r["trade_count"]) > 0
    }
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


if __name__ == "__main__":
    main()
