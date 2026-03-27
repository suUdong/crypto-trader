#!/usr/bin/env python3
"""Grid search for optimal strategy parameters using real Upbit data."""
from __future__ import annotations

import itertools
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, "src")

from unittest.mock import MagicMock  # noqa: E402

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
from crypto_trader.strategy.kimchi_premium import KimchiPremiumStrategy  # noqa: E402
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy  # noqa: E402
from crypto_trader.wallet import create_strategy  # noqa: E402

SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
INTERVAL = "minute60"


@dataclass
class GridResult:
    strategy: str
    params: dict[str, float | int]
    symbol: str
    return_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    trade_count: int
    sharpe_approx: float


@dataclass
class ParamSetSummary:
    strategy: str
    params: dict[str, float | int]
    avg_return_pct: float
    avg_win_rate: float
    avg_profit_factor: float
    avg_max_drawdown: float
    avg_sharpe: float
    total_trades: int
    score: float
    symbol_count: int
    per_symbol: dict[str, dict[str, float | int]]


def fetch_candles(symbol: str, days: int) -> list[Candle]:
    """Fetch hourly candles, using local cache when configured."""
    return fetch_upbit_candles(
        symbol,
        days,
        interval=INTERVAL,
        cache_dir=os.environ.get("CT_CANDLE_CACHE_DIR"),
    )


# Parameter grids per strategy
MEAN_REVERSION_GRID = {
    "bollinger_window": [15, 20, 25],
    "bollinger_stddev": [1.5, 1.8, 2.0, 2.2],
    "rsi_period": [10, 14, 18],
    "rsi_recovery_ceiling": [55.0, 60.0, 65.0],
    "max_holding_bars": [36, 48, 60],
}

MOMENTUM_GRID = {
    "momentum_lookback": [15, 20, 25],
    "momentum_entry_threshold": [0.003, 0.005, 0.008],
    "rsi_period": [10, 14, 18],
    "rsi_overbought": [65.0, 70.0, 75.0],
    "max_holding_bars": [36, 48, 60],
}

MOMENTUM_PULLBACK_GRID = {
    "momentum_lookback": [10, 15, 20],
    "momentum_entry_threshold": [0.003, 0.006],
    "bollinger_window": [15, 20],
    "bollinger_stddev": [1.5, 1.8],
    "rsi_period": [10, 14],
    "rsi_recovery_ceiling": [50.0, 60.0],
    "adx_threshold": [15.0, 20.0],
    "max_holding_bars": [24, 36],
}

VPIN_GRID = {
    "rsi_period": [10, 14],
    "momentum_lookback": [15, 20],
    "max_holding_bars": [36, 48],
}

OBI_GRID = {
    "rsi_period": [10, 14],
    "momentum_lookback": [15, 20],
    "max_holding_bars": [36, 48],
}

VOLATILITY_BREAKOUT_GRID = {
    "k_base": [0.3, 0.5, 0.7],
    "noise_lookback": [10, 15, 20],
    "ma_filter_period": [10, 15, 20],
    "max_holding_bars": [24, 36, 48],
}

KIMCHI_PREMIUM_GRID = {
    "rsi_period": [10, 14, 18],
    "rsi_recovery_ceiling": [50.0, 60.0, 70.0],
    "rsi_overbought": [65.0, 70.0, 75.0],
    "max_holding_bars": [24, 36, 48],
    "min_trade_interval_bars": [6, 12, 18],
    "min_confidence": [0.4, 0.6, 0.8],
}

COMPOSITE_GRID = {
    "bollinger_window": [15, 20, 25],
    "bollinger_stddev": [1.5, 1.8, 2.0],
    "momentum_lookback": [15, 20, 25],
    "momentum_entry_threshold": [0.003, 0.005, 0.008],
    "rsi_period": [10, 14],
    "rsi_recovery_ceiling": [55.0, 60.0, 65.0],
    "max_holding_bars": [36, 48],
}

STRATEGY_GRIDS: dict[str, dict[str, list[float | int]]] = {
    "mean_reversion": MEAN_REVERSION_GRID,
    "momentum": MOMENTUM_GRID,
    "momentum_pullback": MOMENTUM_PULLBACK_GRID,
    "composite": COMPOSITE_GRID,
    "vpin": VPIN_GRID,
    "obi": OBI_GRID,
    "volatility_breakout": VOLATILITY_BREAKOUT_GRID,
    "kimchi_premium": KIMCHI_PREMIUM_GRID,
}


def _param_key(params: dict[str, float | int]) -> str:
    return json.dumps(sorted(params.items()), separators=(",", ":"))


def _approx_sharpe(equity_curve: list[float]) -> float:
    """Approximate annualized Sharpe from hourly equity curve."""
    if len(equity_curve) < 3:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / max(1.0, equity_curve[i - 1])
        for i in range(1, len(equity_curve))
    ]
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = variance**0.5
    if std_r == 0:
        return 0.0
    # Annualize: 24h * 365d = 8760 hourly bars
    return (mean_r / std_r) * (8760**0.5)


def _create_strategy_for_grid(
    strategy_type: str,
    params: dict[str, float | int],
    strategy_config: StrategyConfig,
    regime_config: RegimeConfig,
):
    """Create strategy instance handling strategy-specific constructor params."""
    if strategy_type == "volatility_breakout":
        return VolatilityBreakoutStrategy(
            strategy_config,
            k_base=float(params.get("k_base", 0.5)),
            noise_lookback=int(params.get("noise_lookback", 20)),
            ma_filter_period=int(params.get("ma_filter_period", 20)),
            max_holding_bars=int(params.get("max_holding_bars", strategy_config.max_holding_bars)),
        )
    if strategy_type == "kimchi_premium":
        # Simulate premium using MA deviation as proxy for backtest
        mock_binance = MagicMock()
        mock_fx = MagicMock()
        # Set up premium simulation: we'll update per-symbol before each run
        mock_binance.get_btc_usdt_price.return_value = None
        mock_fx.get_usd_krw_rate.return_value = None
        return KimchiPremiumStrategy(
            strategy_config,
            binance_client=mock_binance,
            fx_client=mock_fx,
            min_trade_interval_bars=int(params.get("min_trade_interval_bars", 12)),
            min_confidence=float(params.get("min_confidence", 0.6)),
            cooldown_hours=float(params.get("cooldown_hours", 24.0)),
        )
    return create_strategy(strategy_type, strategy_config, regime_config)


def _setup_kimchi_premium_mock(strategy: KimchiPremiumStrategy, candles: list[Candle]) -> None:
    """Configure mock premium using MA-deviation as proxy.

    Simulates premium as deviation of current price from 50-period MA,
    scaled to typical kimchi premium range (-3% to +10%).
    """
    if len(candles) < 50:
        return
    closes = [c.close for c in candles]
    ma50 = sum(closes[-50:]) / 50.0
    if ma50 <= 0:
        return
    # Scale: price 5% above MA → ~5% premium, price 3% below MA → ~-3% premium
    deviation = (closes[-1] - ma50) / ma50
    simulated_premium = deviation * 1.0  # 1:1 mapping
    # Inject simulated premium via cached value
    strategy._cached_premium = simulated_premium
    # Make external calls return None so _calculate_premium uses cached
    strategy._binance.get_btc_usdt_price.return_value = None
    strategy._fx.get_usd_krw_rate.return_value = None


def run_grid_for_strategy(
    strategy_type: str,
    candles_by_symbol: dict[str, list[Candle]],
) -> list[GridResult]:
    grid = STRATEGY_GRIDS.get(strategy_type)
    if grid is None:
        return []

    param_names = list(grid.keys())
    param_values = list(grid.values())
    combos = list(itertools.product(*param_values))
    results: list[GridResult] = []

    print(f"\n  {strategy_type}: {len(combos)} param combos x {len(candles_by_symbol)} symbols")

    # Separate strategy-specific constructor params from StrategyConfig params
    strategy_config_fields = {f for f in StrategyConfig.__dataclass_fields__}

    for combo in combos:
        params = dict(zip(param_names, combo, strict=True))
        config_kwargs = {k: v for k, v in params.items() if k in strategy_config_fields}

        strategy_config = StrategyConfig(**config_kwargs)
        regime_config = RegimeConfig()
        risk_config = RiskConfig()
        backtest_config = BacktestConfig(
            initial_capital=1_000_000.0,
            fee_rate=0.0005,
            slippage_pct=0.0005,
        )

        for symbol, candles in candles_by_symbol.items():
            strategy = _create_strategy_for_grid(
                strategy_type, params, strategy_config, regime_config,
            )
            # For kimchi_premium, simulate premium from price data
            if strategy_type == "kimchi_premium":
                _setup_kimchi_premium_mock(strategy, candles)

            risk_manager = RiskManager(risk_config)
            engine = BacktestEngine(
                strategy=strategy,
                risk_manager=risk_manager,
                config=backtest_config,
                symbol=symbol,
            )
            result = engine.run(candles)
            sharpe = _approx_sharpe(result.equity_curve)

            results.append(
                GridResult(
                    strategy=strategy_type,
                    params=params,
                    symbol=symbol,
                    return_pct=result.total_return_pct * 100,
                    win_rate=result.win_rate * 100,
                    profit_factor=result.profit_factor,
                    max_drawdown=result.max_drawdown * 100,
                    trade_count=len(result.trade_log),
                    sharpe_approx=sharpe,
                )
            )

    return results


def summarize_param_sets(results: list[GridResult]) -> list[ParamSetSummary]:
    """Aggregate grid results into averaged param-set summaries across symbols."""
    grouped: dict[str, list[GridResult]] = {}
    for result in results:
        grouped.setdefault(_param_key(result.params), []).append(result)

    summaries: list[ParamSetSummary] = []
    for group in grouped.values():
        first = group[0]
        count = len(group)
        score = sum(
            r.sharpe_approx * (1.0 - r.max_drawdown / 100.0)
            for r in group
        ) / max(1, count)
        summaries.append(
            ParamSetSummary(
                strategy=first.strategy,
                params=first.params,
                avg_return_pct=sum(r.return_pct for r in group) / max(1, count),
                avg_win_rate=sum(r.win_rate for r in group) / max(1, count),
                avg_profit_factor=sum(r.profit_factor for r in group) / max(1, count),
                avg_max_drawdown=sum(r.max_drawdown for r in group) / max(1, count),
                avg_sharpe=sum(r.sharpe_approx for r in group) / max(1, count),
                total_trades=sum(r.trade_count for r in group),
                score=score,
                symbol_count=count,
                per_symbol={
                    r.symbol: {
                        "return_pct": r.return_pct,
                        "win_rate": r.win_rate,
                        "profit_factor": r.profit_factor,
                        "max_drawdown": r.max_drawdown,
                        "trade_count": r.trade_count,
                        "sharpe_approx": r.sharpe_approx,
                    }
                    for r in group
                },
            )
        )

    return sorted(
        summaries,
        key=lambda summary: (
            summary.score,
            summary.avg_sharpe,
            summary.avg_return_pct,
        ),
        reverse=True,
    )


def top_param_sets(results: list[GridResult], top_n: int = 3) -> list[ParamSetSummary]:
    """Return the highest-scoring aggregated parameter sets."""
    if top_n <= 0:
        return []
    return summarize_param_sets(results)[:top_n]


def find_best_params(results: list[GridResult]) -> dict[str, float | int]:
    """Find params that maximize average Sharpe across all symbols."""
    top_sets = top_param_sets(results, top_n=1)
    return top_sets[0].params if top_sets else {}


def main() -> None:
    days = 30
    if len(sys.argv) > 1:
        days = int(sys.argv[1])

    strategy_filter = None
    if len(sys.argv) > 2:
        strategy_filter = sys.argv[2]

    print(f"\n{'='*80}")
    print(f"  GRID SEARCH - {days}-day hourly candles from Upbit")
    print(f"{'='*80}")

    # Fetch candles for all symbols
    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    strategies = [strategy_filter] if strategy_filter else list(STRATEGY_GRIDS.keys())

    for strategy_type in strategies:
        results = run_grid_for_strategy(strategy_type, candles_by_symbol)
        if not results:
            continue

        top_candidates = top_param_sets(results, top_n=3)
        best_params = top_candidates[0].params if top_candidates else {}

        print(f"\n  Best params for {strategy_type}:")
        for k, v in sorted(best_params.items()):
            print(f"    {k}: {v}")

        print("\n  Top candidate sets:")
        for idx, candidate in enumerate(top_candidates, start=1):
            print(
                f"    #{idx} score={candidate.score:.4f} sharpe={candidate.avg_sharpe:.2f} "
                f"return={candidate.avg_return_pct:+.2f}% mdd={candidate.avg_max_drawdown:.2f}% "
                f"trades={candidate.total_trades}"
            )
            print(f"      params={candidate.params}")

        # Show best results per symbol
        best_per_symbol = {}
        for r in results:
            if _param_key(r.params) == _param_key(best_params):
                best_per_symbol[r.symbol] = r

        print(
            f"\n  {'Symbol':<12} {'Return%':>9} {'WinRate%':>9} "
            f"{'PF':>7} {'MDD%':>7} {'Sharpe':>8} {'Trades':>7}"
        )
        print(f"  {'-'*63}")
        for symbol in SYMBOLS:
            if symbol in best_per_symbol:
                r = best_per_symbol[symbol]
                pf = f"{r.profit_factor:.2f}" if r.profit_factor < 1000 else "inf"
                print(
                    f"  {r.symbol:<12} {r.return_pct:>+8.2f}% {r.win_rate:>8.1f}% "
                    f"{pf:>7} {r.max_drawdown:>6.2f}% {r.sharpe_approx:>7.2f} {r.trade_count:>7}"
                )

        avg_return = sum(r.return_pct for r in best_per_symbol.values()) / max(
            1, len(best_per_symbol)
        )
        avg_sharpe = sum(r.sharpe_approx for r in best_per_symbol.values()) / max(
            1, len(best_per_symbol)
        )
        print(f"\n  Avg Return: {avg_return:+.2f}%  Avg Sharpe: {avg_sharpe:.2f}")

    print(f"\n{'='*80}")
    print("  Grid search complete.")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
