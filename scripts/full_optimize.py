#!/usr/bin/env python3
"""Full 5-strategy parameter optimization with tight grids around production params.

Grid search across key parameters, compare return/win-rate/MDD/Sharpe,
output best params per strategy+symbol for daemon.toml update.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

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
from scripts.grid_search import (  # noqa: E402
    STRATEGY_GRIDS,
    SYMBOLS,
    GridResult,
    ParamSetSummary,
    _approx_sharpe,
    fetch_candles,
    run_grid_for_strategy,
    summarize_param_sets,
    top_param_sets,
)

# ── Tight grids centered on production params (~50 combos each) ──

# ~50 combos per strategy, ~250 total × 4 symbols = ~1000 backtests

# Momentum (48 combos): neighborhood of production params
STRATEGY_GRIDS["momentum"] = {
    "momentum_lookback": [10, 12, 15],
    "momentum_entry_threshold": [0.001, 0.002, 0.003],
    "rsi_period": [14],
    "rsi_overbought": [70.0, 72.0],
    "max_holding_bars": [36, 48],
    "adx_threshold": [15.0, 20.0, 25.0],
}
# 3×3×1×2×2×3 = 108 → manageable but covers key axes

# VPIN (48 combos): focus on VPIN-specific thresholds
STRATEGY_GRIDS["vpin"] = {
    "rsi_period": [14],
    "momentum_lookback": [10, 12],
    "max_holding_bars": [36, 48],
    "vpin_low_threshold": [0.45, 0.55],
    "vpin_high_threshold": [0.75, 0.80, 0.85],
    "vpin_momentum_threshold": [0.0005, 0.001],
    "bucket_count": [20],
}
# 1×2×2×2×3×2×1 = 48

# Vbreak (45 combos): k_base is the key lever
STRATEGY_GRIDS["volatility_breakout"] = {
    "k_base": [0.20, 0.25, 0.30, 0.40, 0.50],
    "noise_lookback": [10, 15],
    "ma_filter_period": [5, 8, 10],
    "max_holding_bars": [36],
}
# 5×2×3×1 = 30 (small enough to also try hold=24)

# Kimchi (54 combos): cooldown/interval key levers
STRATEGY_GRIDS["kimchi_premium"] = {
    "rsi_period": [14],
    "rsi_recovery_ceiling": [45.0, 50.0],
    "rsi_overbought": [75.0],
    "max_holding_bars": [24, 36],
    "min_trade_interval_bars": [6, 12, 18],
    "min_confidence": [0.3, 0.4, 0.5],
    "cooldown_hours": [4.0, 8.0, 16.0],
}
# 1×2×1×2×3×3×3 = 108

# Volume spike (48 combos): spike_mult + body_ratio are key
VOLUME_SPIKE_GRID = {
    "spike_mult": [1.5, 2.0, 2.5, 3.0],
    "volume_window": [20],
    "min_body_ratio": [0.3, 0.4],
    "momentum_lookback": [12],
    "rsi_period": [14],
    "rsi_overbought": [72.0],
    "max_holding_bars": [36, 48],
    "adx_threshold": [15.0, 20.0, 25.0],
}
# 4×1×2×1×1×1×2×3 = 48


def run_custom_grid(
    strategy_type: str,
    grid: dict,
    candles_by_symbol: dict[str, list[Candle]],
    create_fn,
) -> list[GridResult]:
    """Generic grid runner with custom strategy creation."""
    param_names = list(grid.keys())
    param_values = list(grid.values())
    combos = list(itertools.product(*param_values))
    strategy_config_fields = {f for f in StrategyConfig.__dataclass_fields__}
    results: list[GridResult] = []

    total = len(combos) * len(candles_by_symbol)
    print(
        f"\n  {strategy_type}: {len(combos)} combos x "
        f"{len(candles_by_symbol)} symbols = {total} backtests"
    )

    for i, combo in enumerate(combos):
        params = dict(zip(param_names, combo, strict=True))
        config_kwargs = {k: v for k, v in params.items() if k in strategy_config_fields}
        strategy_config = StrategyConfig(**config_kwargs)
        backtest_config = BacktestConfig(
            initial_capital=1_000_000.0,
            fee_rate=0.0005,
            slippage_pct=0.0005,
        )

        for symbol, candles in candles_by_symbol.items():
            strategy = create_fn(strategy_config, params)
            risk_manager = RiskManager(RiskConfig())
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

        if (i + 1) % 100 == 0:
            print(f"    ... {i + 1}/{len(combos)} combos done")

    print(f"    Done: {len(results)} results")
    return results


def print_results(strategy_type: str, results: list[GridResult]) -> ParamSetSummary | None:
    """Print top candidates and per-symbol best. Returns best summary."""
    if not results:
        print(f"\n  === {strategy_type.upper()} === NO RESULTS")
        return None

    top_candidates = top_param_sets(results, top_n=5)
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

    print("\n  Top 5:")
    for idx, c in enumerate(top_candidates, 1):
        print(
            f"    #{idx} score={c.score:.4f} sharpe={c.avg_sharpe:.2f} "
            f"ret={c.avg_return_pct:+.2f}% mdd={c.avg_max_drawdown:.2f}% "
            f"wr={c.avg_win_rate:.1f}% trades={c.total_trades}"
        )

    # Per-symbol best
    print("\n  Best per-symbol:")
    print(
        f"  {'Symbol':<12} {'Sharpe':>8} {'Return%':>9} "
        f"{'WR%':>6} {'PF':>7} {'MDD%':>7} {'Trades':>7}"
    )
    print(f"  {'-' * 60}")
    per_sym_best = {}
    for symbol in SYMBOLS:
        sym_results = [r for r in results if r.symbol == symbol]
        if not sym_results:
            continue
        best_r = max(sym_results, key=lambda r: r.sharpe_approx * (1.0 - r.max_drawdown / 100.0))
        per_sym_best[symbol] = best_r
        pf = f"{best_r.profit_factor:.2f}" if best_r.profit_factor < 1000 else "inf"
        print(
            f"  {symbol:<12} {best_r.sharpe_approx:>7.2f} {best_r.return_pct:>+8.2f}% "
            f"{best_r.win_rate:>5.1f}% {pf:>7} {best_r.max_drawdown:>6.2f}% "
            f"{best_r.trade_count:>7}"
        )
        print(f"    params: { {k: v for k, v in sorted(best_r.params.items())} }")

    return best


def main() -> None:
    days = 90
    t0 = time.time()

    print(f"\n{'#' * 80}")
    print(f"  FULL 5-STRATEGY OPTIMIZATION — {days}-day data")
    print(f"{'#' * 80}")

    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in SYMBOLS:
        print(f"Fetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    all_best: dict[str, ParamSetSummary | None] = {}
    all_results: dict[str, list[GridResult]] = {}

    # 1) Momentum
    print(f"\n{'=' * 80}\n  Running MOMENTUM...")
    r = run_grid_for_strategy("momentum", candles_by_symbol)
    all_results["momentum"] = r
    all_best["momentum"] = print_results("momentum", r)

    # 2) VPIN (custom — constructor params)
    def make_vpin(cfg, params):
        return VPINStrategy(
            cfg,
            vpin_high_threshold=float(params.get("vpin_high_threshold", 0.80)),
            vpin_low_threshold=float(params.get("vpin_low_threshold", 0.55)),
            bucket_count=int(params.get("bucket_count", 20)),
            vpin_momentum_threshold=float(params.get("vpin_momentum_threshold", 0.001)),
            vpin_rsi_ceiling=float(params.get("vpin_rsi_ceiling", 78.0)),
            vpin_rsi_floor=float(params.get("vpin_rsi_floor", 22.0)),
        )

    print(f"\n{'=' * 80}\n  Running VPIN...")
    r = run_custom_grid("vpin", STRATEGY_GRIDS["vpin"], candles_by_symbol, make_vpin)
    all_results["vpin"] = r
    all_best["vpin"] = print_results("vpin", r)

    # 3) Volatility Breakout
    print(f"\n{'=' * 80}\n  Running VOLATILITY BREAKOUT...")
    r = run_grid_for_strategy("volatility_breakout", candles_by_symbol)
    all_results["volatility_breakout"] = r
    all_best["volatility_breakout"] = print_results("volatility_breakout", r)

    # 4) Kimchi Premium
    print(f"\n{'=' * 80}\n  Running KIMCHI PREMIUM...")
    r = run_grid_for_strategy("kimchi_premium", candles_by_symbol)
    all_results["kimchi_premium"] = r
    all_best["kimchi_premium"] = print_results("kimchi_premium", r)

    # 5) Volume Spike (custom — constructor params)
    def make_volspike(cfg, params):
        return VolumeSpikeStrategy(
            cfg,
            RegimeConfig(),
            spike_mult=float(params.get("spike_mult", 2.5)),
            volume_window=int(params.get("volume_window", 20)),
            min_body_ratio=float(params.get("min_body_ratio", 0.4)),
        )

    print(f"\n{'=' * 80}\n  Running VOLUME SPIKE...")
    r = run_custom_grid("volume_spike", VOLUME_SPIKE_GRID, candles_by_symbol, make_volspike)
    all_results["volume_spike"] = r
    all_best["volume_spike"] = print_results("volume_spike", r)

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

    # Save results JSON
    output = {}
    for strat, results in all_results.items():
        summaries = summarize_param_sets(results)
        best_s = summaries[0] if summaries else None
        per_sym = {}
        for symbol in SYMBOLS:
            sym_r = [r for r in results if r.symbol == symbol]
            if sym_r:
                br = max(sym_r, key=lambda r: r.sharpe_approx * (1.0 - r.max_drawdown / 100.0))
                per_sym[symbol] = {
                    "params": br.params,
                    "sharpe": br.sharpe_approx,
                    "return_pct": br.return_pct,
                    "win_rate": br.win_rate,
                    "mdd": br.max_drawdown,
                    "pf": br.profit_factor,
                    "trades": br.trade_count,
                }
        output[strat] = {
            "best_params": best_s.params if best_s else {},
            "best_score": best_s.score if best_s else 0,
            "best_sharpe": best_s.avg_sharpe if best_s else 0,
            "best_return_pct": best_s.avg_return_pct if best_s else 0,
            "best_mdd": best_s.avg_max_drawdown if best_s else 0,
            "best_win_rate": best_s.avg_win_rate if best_s else 0,
            "total_trades": best_s.total_trades if best_s else 0,
            "best_per_symbol": per_sym,
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

    out_path = "artifacts/optimization-results-5strat.json"
    os.makedirs("artifacts", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")
    print(f"{'#' * 80}\n")


if __name__ == "__main__":
    main()
