#!/usr/bin/env python3
"""Strategy correlation analysis and portfolio weight optimization."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "src")

import pyupbit  # noqa: E402

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
STRATEGIES = [
    "momentum",
    "mean_reversion",
    "composite",
    "kimchi_premium",
    "obi",
    "vpin",
    "volatility_breakout",
]
INTERVAL = "minute60"


@dataclass
class StrategyMetrics:
    strategy: str
    avg_return: float
    avg_sharpe: float
    avg_mdd: float
    returns_by_symbol: dict[str, float]
    equity_curves: dict[str, list[float]]


def fetch_candles(symbol: str, days: int) -> list[Candle]:
    """Fetch hourly candles by paginating pyupbit."""
    total_needed = days * 24
    all_candles: list[Candle] = []
    to_dt: datetime | None = None

    while len(all_candles) < total_needed:
        remaining = total_needed - len(all_candles)
        batch_size = min(200, remaining)
        df = pyupbit.get_ohlcv(symbol, interval=INTERVAL, count=batch_size, to=to_dt)
        if df is None or df.empty:
            break
        batch: list[Candle] = []
        for idx, row in df.iterrows():
            ts = idx if isinstance(idx, datetime) else datetime.fromisoformat(str(idx))
            batch.append(
                Candle(
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        if not batch:
            break
        to_dt = batch[0].timestamp - timedelta(seconds=1)
        all_candles = batch + all_candles
        if len(batch) < batch_size:
            break
        time.sleep(0.15)

    return all_candles


def compute_correlation(curve_a: list[float], curve_b: list[float]) -> float:
    """Compute Pearson correlation between two return series."""
    min_len = min(len(curve_a), len(curve_b))
    if min_len < 3:
        return 0.0

    returns_a = [
        (curve_a[i] - curve_a[i - 1]) / max(1.0, curve_a[i - 1]) for i in range(1, min_len)
    ]
    returns_b = [
        (curve_b[i] - curve_b[i - 1]) / max(1.0, curve_b[i - 1]) for i in range(1, min_len)
    ]

    n = len(returns_a)
    mean_a = sum(returns_a) / n
    mean_b = sum(returns_b) / n

    cov = sum((returns_a[i] - mean_a) * (returns_b[i] - mean_b) for i in range(n)) / n
    std_a = (sum((r - mean_a) ** 2 for r in returns_a) / n) ** 0.5
    std_b = (sum((r - mean_b) ** 2 for r in returns_b) / n) ** 0.5

    if std_a == 0 or std_b == 0:
        return 0.0

    return cov / (std_a * std_b)


def approx_sharpe(equity_curve: list[float]) -> float:
    """Approximate annualized Sharpe from hourly equity curve."""
    if len(equity_curve) < 3:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / max(1.0, equity_curve[i - 1])
        for i in range(1, len(equity_curve))
    ]
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = variance**0.5
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * (8760**0.5)


def optimize_weights(metrics: list[StrategyMetrics]) -> dict[str, float]:
    """Simple mean-variance optimization using Sharpe-weighted allocation.

    For a more sophisticated approach, this would use quadratic programming,
    but we use a Sharpe-proportional heuristic that accounts for correlation.
    """
    if not metrics:
        return {}

    # Base weight proportional to Sharpe ratio (floor at 0)
    sharpes = {m.strategy: max(0.0, m.avg_sharpe) for m in metrics}
    total_sharpe = sum(sharpes.values())

    if total_sharpe == 0:
        # Equal weight if no positive Sharpe
        n = len(metrics)
        return {m.strategy: 1.0 / n for m in metrics}

    weights = {s: v / total_sharpe for s, v in sharpes.items()}

    # Penalize high-MDD strategies
    for m in metrics:
        if m.avg_mdd > 5.0:
            weights[m.strategy] *= 0.8
        if m.avg_mdd > 10.0:
            weights[m.strategy] *= 0.7

    # Renormalize
    total = sum(weights.values())
    if total > 0:
        weights = {s: w / total for s, w in weights.items()}

    return weights


def main() -> None:
    days = 30
    if len(sys.argv) > 1:
        days = int(sys.argv[1])

    print(f"\n{'=' * 80}")
    print(f"  PORTFOLIO OPTIMIZER - {days}-day analysis")
    print(f"{'=' * 80}")

    # Fetch candles
    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    # Run backtests for all strategies
    all_metrics: list[StrategyMetrics] = []
    all_curves: dict[str, dict[str, list[float]]] = {}

    for strategy_type in STRATEGIES:
        returns_by_sym: dict[str, float] = {}
        curves_by_sym: dict[str, list[float]] = {}
        mdds: list[float] = []
        sharpes: list[float] = []

        for symbol, candles in candles_by_symbol.items():
            config = StrategyConfig()
            regime = RegimeConfig()
            risk = RiskConfig()
            bt_config = BacktestConfig(
                initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005
            )

            strategy = create_strategy(strategy_type, config, regime)
            rm = RiskManager(risk)
            engine = BacktestEngine(
                strategy=strategy, risk_manager=rm, config=bt_config, symbol=symbol
            )
            result = engine.run(candles)

            returns_by_sym[symbol] = result.total_return_pct * 100
            curves_by_sym[symbol] = result.equity_curve
            mdds.append(result.max_drawdown * 100)
            sharpes.append(approx_sharpe(result.equity_curve))

        avg_ret = sum(returns_by_sym.values()) / max(1, len(returns_by_sym))
        avg_sh = sum(sharpes) / max(1, len(sharpes))
        avg_mdd = sum(mdds) / max(1, len(mdds))

        m = StrategyMetrics(
            strategy=strategy_type,
            avg_return=avg_ret,
            avg_sharpe=avg_sh,
            avg_mdd=avg_mdd,
            returns_by_symbol=returns_by_sym,
            equity_curves=curves_by_sym,
        )
        all_metrics.append(m)
        all_curves[strategy_type] = curves_by_sym

    # Print strategy performance
    print(f"\n{'=' * 80}")
    print("  STRATEGY PERFORMANCE")
    print(f"{'=' * 80}")
    print(f"\n  {'Strategy':<16} {'Avg Return%':>12} {'Avg Sharpe':>12} {'Avg MDD%':>10}")
    print(f"  {'-' * 52}")
    for m in sorted(all_metrics, key=lambda x: x.avg_sharpe, reverse=True):
        print(
            f"  {m.strategy:<16} {m.avg_return:>+11.2f}% {m.avg_sharpe:>11.2f} {m.avg_mdd:>9.2f}%"
        )

    # Correlation matrix
    print(f"\n{'=' * 80}")
    print("  RETURN CORRELATION MATRIX")
    print(f"{'=' * 80}\n")

    # Compute average correlation across symbols
    header = f"  {'':>16}"
    for s in STRATEGIES:
        header += f" {s:>14}"
    print(header)
    print(f"  {'-' * (16 + 15 * len(STRATEGIES))}")

    for s1 in STRATEGIES:
        row = f"  {s1:>16}"
        for s2 in STRATEGIES:
            if s1 == s2:
                row += f" {'1.000':>14}"
            else:
                corrs = []
                for symbol in candles_by_symbol:
                    c1 = all_curves.get(s1, {}).get(symbol, [])
                    c2 = all_curves.get(s2, {}).get(symbol, [])
                    if c1 and c2:
                        corrs.append(compute_correlation(c1, c2))
                avg_corr = sum(corrs) / max(1, len(corrs))
                row += f" {avg_corr:>13.3f}"
        print(row)

    # Optimal weights
    weights = optimize_weights(all_metrics)
    print(f"\n{'=' * 80}")
    print("  RECOMMENDED PORTFOLIO WEIGHTS")
    print(f"{'=' * 80}\n")

    total_capital = len(STRATEGIES) * 1_000_000
    for strategy, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        alloc = total_capital * weight
        print(f"  {strategy:<16} {weight:>6.1%}  ({alloc:>12,.0f} KRW)")

    # Save report
    total_capital = len(STRATEGIES) * 1_000_000
    report_lines = [
        "# Portfolio Optimization Report",
        "",
        f"**Analysis Period**: {days} days",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Total Capital**: {total_capital:,.0f} KRW",
        "",
        "## Recommended Weights",
        "",
        "| Strategy | Weight | Allocation |",
        "|----------|--------|------------|",
    ]
    for strategy, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        alloc = total_capital * weight
        report_lines.append(f"| {strategy} | {weight:.1%} | {alloc:,.0f} KRW |")

    report_path = Path("artifacts/portfolio-optimization.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n  Report saved to {report_path}")


if __name__ == "__main__":
    main()
