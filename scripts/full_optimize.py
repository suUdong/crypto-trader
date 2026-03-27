#!/usr/bin/env python3
"""Full 5-strategy parameter optimization: momentum, vpin, vbreak, kimchi, volume_spike.

Grid search across all key parameters, compare return/win-rate/MDD/Sharpe,
output best params per strategy+symbol for daemon.toml update.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, "src")
sys.path.insert(0, os.path.dirname(__file__))

from grid_search import (  # noqa: E402
    STRATEGY_GRIDS,
    SYMBOLS,
    GridResult,
    ParamSetSummary,
    _approx_sharpe,
    _param_key,
    fetch_candles,
    run_grid_for_strategy,
    summarize_param_sets,
    top_param_sets,
)

from crypto_trader.backtest.engine import BacktestEngine  # noqa: E402
from crypto_trader.config import (  # noqa: E402
    BacktestConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
)
from crypto_trader.models import Candle  # noqa: E402
from crypto_trader.risk.manager import RiskManager  # noqa: E402
from crypto_trader.strategy.volume_spike import VolumeSpikeStrategy  # noqa: E402
from crypto_trader.strategy.vpin import VPINStrategy  # noqa: E402

# ── Fine-grained grids for all 5 strategies ──

# Compact grids — ~2000 total combos for practical runtime
STRATEGY_GRIDS["momentum"] = {
    "momentum_lookback": [10, 12, 15],
    "momentum_entry_threshold": [0.0005, 0.001, 0.002, 0.003],
    "rsi_period": [12, 14],
    "rsi_overbought": [70.0, 72.0, 75.0],
    "max_holding_bars": [36, 48],
    "adx_threshold": [15.0, 18.0, 20.0, 25.0],
}

STRATEGY_GRIDS["vpin"] = {
    "rsi_period": [10, 14],
    "momentum_lookback": [10, 12, 15],
    "max_holding_bars": [36, 48],
    "vpin_low_threshold": [0.45, 0.50, 0.55],
    "vpin_high_threshold": [0.70, 0.80, 0.85],
    "vpin_momentum_threshold": [0.0005, 0.001, 0.002],
    "bucket_count": [15, 20],
}

STRATEGY_GRIDS["volatility_breakout"] = {
    "k_base": [0.15, 0.20, 0.25, 0.30, 0.40, 0.50],
    "noise_lookback": [10, 12, 15],
    "ma_filter_period": [5, 8, 10],
    "max_holding_bars": [24, 36, 48],
}

STRATEGY_GRIDS["kimchi_premium"] = {
    "rsi_period": [10, 14],
    "rsi_recovery_ceiling": [45.0, 50.0, 60.0],
    "rsi_overbought": [70.0, 75.0],
    "max_holding_bars": [18, 24, 36],
    "min_trade_interval_bars": [6, 12, 18],
    "min_confidence": [0.3, 0.4, 0.5],
    "cooldown_hours": [4.0, 8.0, 16.0],
}

# Volume spike — custom grid runner since grid_search.py doesn't handle it
VOLUME_SPIKE_GRID = {
    "spike_mult": [1.5, 2.0, 2.5, 3.0],
    "volume_window": [15, 20, 25],
    "min_body_ratio": [0.25, 0.35, 0.4],
    "momentum_lookback": [10, 12, 15],
    "rsi_period": [12, 14],
    "rsi_overbought": [70.0, 75.0],
    "max_holding_bars": [36, 48],
    "adx_threshold": [15.0, 20.0, 25.0],
}


def run_volume_spike_grid(
    candles_by_symbol: dict[str, list[Candle]],
) -> list[GridResult]:
    """Custom grid runner for volume_spike (needs constructor params)."""
    import itertools

    grid = VOLUME_SPIKE_GRID
    param_names = list(grid.keys())
    param_values = list(grid.values())
    combos = list(itertools.product(*param_values))

    # Sample if too large (>5000 combos)
    import random
    if len(combos) > 5000:
        random.seed(42)
        combos = random.sample(combos, 5000)

    strategy_config_fields = {f for f in StrategyConfig.__dataclass_fields__}
    results: list[GridResult] = []

    print(f"\n  volume_spike: {len(combos)} param combos x {len(candles_by_symbol)} symbols")

    for i, combo in enumerate(combos):
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
            strategy = VolumeSpikeStrategy(
                strategy_config,
                regime_config,
                spike_mult=float(params.get("spike_mult", 2.5)),
                volume_window=int(params.get("volume_window", 20)),
                min_body_ratio=float(params.get("min_body_ratio", 0.4)),
            )

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
                    strategy="volume_spike",
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

        if (i + 1) % 500 == 0:
            print(f"    ... {i+1}/{len(combos)} combos done")

    return results


def run_vpin_grid(
    candles_by_symbol: dict[str, list[Candle]],
) -> list[GridResult]:
    """Custom grid runner for VPIN (needs constructor params not in StrategyConfig)."""
    import itertools

    grid = STRATEGY_GRIDS["vpin"]
    param_names = list(grid.keys())
    param_values = list(grid.values())
    combos = list(itertools.product(*param_values))

    # Sample if too large
    import random
    if len(combos) > 5000:
        random.seed(42)
        combos = random.sample(combos, 5000)

    strategy_config_fields = {f for f in StrategyConfig.__dataclass_fields__}
    results: list[GridResult] = []

    print(f"\n  vpin: {len(combos)} param combos x {len(candles_by_symbol)} symbols")

    for i, combo in enumerate(combos):
        params = dict(zip(param_names, combo, strict=True))
        config_kwargs = {k: v for k, v in params.items() if k in strategy_config_fields}

        strategy_config = StrategyConfig(**config_kwargs)
        risk_config = RiskConfig()
        backtest_config = BacktestConfig(
            initial_capital=1_000_000.0,
            fee_rate=0.0005,
            slippage_pct=0.0005,
        )

        for symbol, candles in candles_by_symbol.items():
            strategy = VPINStrategy(
                strategy_config,
                vpin_high_threshold=float(params.get("vpin_high_threshold", 0.80)),
                vpin_low_threshold=float(params.get("vpin_low_threshold", 0.55)),
                bucket_count=int(params.get("bucket_count", 20)),
                vpin_momentum_threshold=float(params.get("vpin_momentum_threshold", 0.001)),
                vpin_rsi_ceiling=float(params.get("vpin_rsi_ceiling", 78.0)),
                vpin_rsi_floor=float(params.get("vpin_rsi_floor", 22.0)),
            )

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
                    strategy="vpin",
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

        if (i + 1) % 500 == 0:
            print(f"    ... {i+1}/{len(combos)} combos done")

    return results


def print_strategy_results(
    strategy_type: str,
    results: list[GridResult],
    top_n: int = 5,
) -> ParamSetSummary | None:
    """Print top candidates and per-symbol breakdown. Returns best."""
    if not results:
        print(f"\n  === {strategy_type.upper()} === NO RESULTS")
        return None

    top_candidates = top_param_sets(results, top_n=top_n)
    best = top_candidates[0] if top_candidates else None

    print(f"\n{'=' * 80}")
    print(f"  === {strategy_type.upper()} ===")
    if best:
        print("  BEST params:")
        for k, v in sorted(best.params.items()):
            print(f"    {k}: {v}")
        print(
            f"  Score: {best.score:.4f} | Sharpe: {best.avg_sharpe:.2f} | "
            f"Return: {best.avg_return_pct:+.2f}% | MDD: {best.avg_max_drawdown:.2f}% | "
            f"WR: {best.avg_win_rate:.1f}% | Trades: {best.total_trades}"
        )

    print(f"\n  Top {top_n} candidates:")
    for idx, c in enumerate(top_candidates, 1):
        print(
            f"    #{idx} score={c.score:.4f} sharpe={c.avg_sharpe:.2f} "
            f"ret={c.avg_return_pct:+.2f}% mdd={c.avg_max_drawdown:.2f}% "
            f"wr={c.avg_win_rate:.1f}% trades={c.total_trades}"
        )

    # Per-symbol for best
    if best:
        best_key = _param_key(best.params)
        print("\n  Per-symbol (best params):")
        print(
            f"  {'Symbol':<12} {'Return%':>9} {'WR%':>6} {'PF':>7} "
            f"{'MDD%':>7} {'Sharpe':>8} {'Trades':>7}"
        )
        print(f"  {'-' * 60}")
        for r in results:
            if _param_key(r.params) == best_key:
                pf = f"{r.profit_factor:.2f}" if r.profit_factor < 1000 else "inf"
                print(
                    f"  {r.symbol:<12} {r.return_pct:>+8.2f}% {r.win_rate:>5.1f}% "
                    f"{pf:>7} {r.max_drawdown:>6.2f}% "
                    f"{r.sharpe_approx:>7.2f} {r.trade_count:>7}"
                )

    # Also find best per-symbol (for per-wallet optimization)
    print("\n  Best per-symbol:")
    for symbol in SYMBOLS:
        symbol_results = [r for r in results if r.symbol == symbol]
        if not symbol_results:
            continue
        # Group by param set
        grouped: dict[str, list[GridResult]] = {}
        for r in symbol_results:
            grouped.setdefault(_param_key(r.params), []).append(r)
        # Find best for this symbol
        best_for_sym = max(
            symbol_results,
            key=lambda r: r.sharpe_approx * (1.0 - r.max_drawdown / 100.0),
        )
        pf = f"{best_for_sym.profit_factor:.2f}" if best_for_sym.profit_factor < 1000 else "inf"
        print(
            f"  {symbol:<12} sharpe={best_for_sym.sharpe_approx:.2f} "
            f"ret={best_for_sym.return_pct:+.2f}% wr={best_for_sym.win_rate:.1f}% "
            f"pf={pf} mdd={best_for_sym.max_drawdown:.2f}% trades={best_for_sym.trade_count}"
        )
        print(f"    params: {best_for_sym.params}")

    return best


def main() -> None:
    days = 90
    t0 = time.time()

    print(f"\n{'#' * 80}")
    print(f"  FULL 5-STRATEGY OPTIMIZATION — {days}-day data")
    print("  Strategies: momentum, vpin, volatility_breakout, kimchi_premium, volume_spike")
    print(f"{'#' * 80}")

    # Fetch candles
    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    all_best: dict[str, ParamSetSummary | None] = {}
    all_results: dict[str, list[GridResult]] = {}

    # 1) Momentum (uses standard grid runner)
    print(f"\n{'=' * 80}\n  Running MOMENTUM grid search...")
    results_mom = run_grid_for_strategy("momentum", candles_by_symbol)
    all_results["momentum"] = results_mom
    all_best["momentum"] = print_strategy_results("momentum", results_mom)

    # 2) VPIN (custom runner for constructor params)
    print(f"\n{'=' * 80}\n  Running VPIN grid search...")
    results_vpin = run_vpin_grid(candles_by_symbol)
    all_results["vpin"] = results_vpin
    all_best["vpin"] = print_strategy_results("vpin", results_vpin)

    # 3) Volatility Breakout (uses standard grid runner)
    print(f"\n{'=' * 80}\n  Running VOLATILITY BREAKOUT grid search...")
    results_vbreak = run_grid_for_strategy("volatility_breakout", candles_by_symbol)
    all_results["volatility_breakout"] = results_vbreak
    all_best["volatility_breakout"] = print_strategy_results("volatility_breakout", results_vbreak)

    # 4) Kimchi Premium (uses standard grid runner with mock)
    print(f"\n{'=' * 80}\n  Running KIMCHI PREMIUM grid search...")
    results_kimchi = run_grid_for_strategy("kimchi_premium", candles_by_symbol)
    all_results["kimchi_premium"] = results_kimchi
    all_best["kimchi_premium"] = print_strategy_results("kimchi_premium", results_kimchi)

    # 5) Volume Spike (custom runner)
    print(f"\n{'=' * 80}\n  Running VOLUME SPIKE grid search...")
    results_volspike = run_volume_spike_grid(candles_by_symbol)
    all_results["volume_spike"] = results_volspike
    all_best["volume_spike"] = print_strategy_results("volume_spike", results_volspike)

    # ── Summary ──
    elapsed = time.time() - t0
    print(f"\n\n{'#' * 80}")
    print(f"  OPTIMIZATION SUMMARY ({elapsed:.0f}s)")
    print(f"{'#' * 80}")

    for strat, best in all_best.items():
        if best:
            print(
                f"\n  {strat.upper()}: sharpe={best.avg_sharpe:.2f} "
                f"ret={best.avg_return_pct:+.2f}% wr={best.avg_win_rate:.1f}% "
                f"mdd={best.avg_max_drawdown:.2f}% trades={best.total_trades}"
            )
            print(f"    params: {best.params}")
        else:
            print(f"\n  {strat.upper()}: NO RESULTS")

    # Save full results to JSON for later analysis
    output = {}
    for strat, results in all_results.items():
        summaries = summarize_param_sets(results)
        output[strat] = {
            "best_params": summaries[0].params if summaries else {},
            "best_score": summaries[0].score if summaries else 0,
            "best_sharpe": summaries[0].avg_sharpe if summaries else 0,
            "best_return_pct": summaries[0].avg_return_pct if summaries else 0,
            "best_mdd": summaries[0].avg_max_drawdown if summaries else 0,
            "best_win_rate": summaries[0].avg_win_rate if summaries else 0,
            "total_trades": summaries[0].total_trades if summaries else 0,
            "per_symbol": summaries[0].per_symbol if summaries else {},
            "top5": [
                {
                    "params": s.params,
                    "score": s.score,
                    "sharpe": s.avg_sharpe,
                    "return_pct": s.avg_return_pct,
                    "mdd": s.avg_max_drawdown,
                    "win_rate": s.avg_win_rate,
                    "trades": s.total_trades,
                }
                for s in summaries[:5]
            ],
        }

        # Also find best per-symbol
        per_sym_best = {}
        for symbol in SYMBOLS:
            sym_results = [r for r in results if r.symbol == symbol]
            if sym_results:
                best_r = max(
                    sym_results,
                    key=lambda r: r.sharpe_approx * (1.0 - r.max_drawdown / 100.0),
                )
                per_sym_best[symbol] = {
                    "params": best_r.params,
                    "sharpe": best_r.sharpe_approx,
                    "return_pct": best_r.return_pct,
                    "win_rate": best_r.win_rate,
                    "mdd": best_r.max_drawdown,
                    "profit_factor": best_r.profit_factor,
                    "trades": best_r.trade_count,
                }
        output[strat]["best_per_symbol"] = per_sym_best

    out_path = "artifacts/optimization-results-5strat.json"
    os.makedirs("artifacts", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")
    print(f"{'#' * 80}\n")


if __name__ == "__main__":
    main()
