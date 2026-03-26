#!/usr/bin/env python3
"""Comprehensive backtest analysis: baseline + grid search + optimal params for 4 core strategies.

Targets: momentum, vpin, volatility_breakout, kimchi_premium
Based on tuned parameters from commit 6dffded.
"""
from __future__ import annotations

import itertools
import json
import os
import sys
import time
from dataclasses import dataclass
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

try:
    from scripts.grid_search import (  # noqa: E402
        _approx_sharpe,
        _create_strategy_for_grid,
        _setup_kimchi_premium_mock,
    )
except ModuleNotFoundError:
    from grid_search import (  # type: ignore[no-redef]  # noqa: E402
        _approx_sharpe,
        _create_strategy_for_grid,
        _setup_kimchi_premium_mock,
    )

SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
INTERVAL = "minute60"
DAYS = 90

# Target strategies for this analysis
TARGET_STRATEGIES = ["momentum", "vpin", "volatility_breakout", "kimchi_premium"]

# Expanded grids incorporating tuned values from 6dffded
MOMENTUM_GRID = {
    "momentum_lookback": [10, 15, 20, 25],
    "momentum_entry_threshold": [0.001, 0.002, 0.003, 0.005, 0.008],
    "rsi_period": [10, 14, 18],
    "rsi_overbought": [65.0, 70.0, 72.0, 75.0],
    "max_holding_bars": [36, 48, 60],
}

VPIN_GRID = {
    "rsi_period": [10, 14, 18],
    "momentum_lookback": [10, 12, 15, 20],
    "max_holding_bars": [36, 48, 60],
}

VOLATILITY_BREAKOUT_GRID = {
    "k_base": [0.25, 0.30, 0.35, 0.40, 0.50, 0.60],
    "noise_lookback": [10, 15, 20],
    "ma_filter_period": [5, 10, 15, 20],
    "max_holding_bars": [24, 36, 48],
}

KIMCHI_PREMIUM_GRID = {
    "rsi_period": [10, 14, 18],
    "rsi_recovery_ceiling": [45.0, 55.0, 65.0, 75.0],
    "rsi_overbought": [65.0, 70.0, 75.0],
    "max_holding_bars": [24, 36, 48],
    "min_trade_interval_bars": [4, 8, 12],
    "min_confidence": [0.3, 0.4, 0.5, 0.6],
}

STRATEGY_GRIDS = {
    "momentum": MOMENTUM_GRID,
    "vpin": VPIN_GRID,
    "volatility_breakout": VOLATILITY_BREAKOUT_GRID,
    "kimchi_premium": KIMCHI_PREMIUM_GRID,
}

# Risk configs for grid search
RISK_GRIDS = {
    "conservative": RiskConfig(stop_loss_pct=0.03, take_profit_pct=0.08, risk_per_trade_pct=0.008),
    "moderate": RiskConfig(stop_loss_pct=0.04, take_profit_pct=0.10, risk_per_trade_pct=0.01),
    "aggressive": RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.12, risk_per_trade_pct=0.015),
}


@dataclass
class StrategyResult:
    strategy: str
    params: dict
    risk_profile: str
    symbol: str
    return_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    trade_count: int
    sharpe: float
    sortino: float
    calmar: float
    avg_trade_duration: float
    max_consecutive_losses: int
    payoff_ratio: float
    ev_per_trade: float
    recovery_factor: float


def fetch_all_candles() -> dict[str, list[Candle]]:
    candles_by_symbol: dict[str, list[Candle]] = {}
    cache_dir = "artifacts/candle-cache"
    os.environ["CT_CANDLE_CACHE_DIR"] = cache_dir
    for symbol in SYMBOLS:
        print(f"  Fetching {symbol} ({DAYS}d)...", end=" ", flush=True)
        candles = fetch_upbit_candles(symbol, DAYS, interval=INTERVAL, cache_dir=cache_dir)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles
    return candles_by_symbol


def run_single(
    strategy_type: str,
    params: dict,
    risk_config: RiskConfig,
    candles: list[Candle],
    symbol: str,
    risk_profile: str = "moderate",
) -> StrategyResult:
    strategy_config_fields = {f for f in StrategyConfig.__dataclass_fields__}
    config_kwargs = {k: v for k, v in params.items() if k in strategy_config_fields}
    strategy_config = StrategyConfig(**config_kwargs)
    regime_config = RegimeConfig()
    backtest_config = BacktestConfig(
        initial_capital=1_000_000.0,
        fee_rate=0.0005,
        slippage_pct=0.0005,
    )

    strategy = _create_strategy_for_grid(strategy_type, params, strategy_config, regime_config)
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

    return StrategyResult(
        strategy=strategy_type,
        params=params,
        risk_profile=risk_profile,
        symbol=symbol,
        return_pct=result.total_return_pct * 100,
        win_rate=result.win_rate * 100,
        profit_factor=result.profit_factor,
        max_drawdown=result.max_drawdown * 100,
        trade_count=len(result.trade_log),
        sharpe=sharpe,
        sortino=result.sortino_ratio,
        calmar=result.calmar_ratio,
        avg_trade_duration=result.avg_trade_duration_bars,
        max_consecutive_losses=result.max_consecutive_losses,
        payoff_ratio=result.payoff_ratio,
        ev_per_trade=result.expected_value_per_trade,
        recovery_factor=result.recovery_factor,
    )


def score_result(r: StrategyResult) -> float:
    """Composite score: Sharpe-weighted, penalized by drawdown."""
    dd_penalty = max(0.0, 1.0 - r.max_drawdown / 100.0)
    trade_bonus = min(1.0, r.trade_count / 20.0)  # need at least 20 trades
    return r.sharpe * dd_penalty * trade_bonus


def run_baseline(candles_by_symbol: dict[str, list[Candle]]) -> list[StrategyResult]:
    """Run all 4 strategies with current daemon.toml defaults."""
    print("\n" + "=" * 80)
    print("  PHASE 1: BASELINE BACKTEST (current tuned params from 6dffded)")
    print("=" * 80)

    results = []
    risk_config = RiskConfig()
    for strategy_type in TARGET_STRATEGIES:
        for symbol, candles in candles_by_symbol.items():
            r = run_single(strategy_type, {}, risk_config, candles, symbol, "default")
            results.append(r)
            pf = f"{r.profit_factor:.2f}" if r.profit_factor < 1000 else "inf"
            print(
                f"  {strategy_type:<20} {symbol:<10} "
                f"ret={r.return_pct:>+7.2f}% mdd={r.max_drawdown:>5.2f}% "
                f"wr={r.win_rate:>5.1f}% pf={pf:>6} sharpe={r.sharpe:>6.2f} "
                f"trades={r.trade_count:>4}"
            )
    return results


def run_grid_search(candles_by_symbol: dict[str, list[Candle]]) -> dict[str, list[StrategyResult]]:
    """Grid search for optimal params per strategy."""
    print("\n" + "=" * 80)
    print("  PHASE 2: GRID SEARCH (expanded parameter space)")
    print("=" * 80)

    all_results: dict[str, list[StrategyResult]] = {}
    risk_config = RiskConfig()  # Use default risk for param search

    for strategy_type in TARGET_STRATEGIES:
        grid = STRATEGY_GRIDS[strategy_type]
        param_names = list(grid.keys())
        param_values = list(grid.values())
        combos = list(itertools.product(*param_values))
        total = len(combos) * len(candles_by_symbol)
        print(
            f"\n  {strategy_type}: {len(combos)} combos x "
            f"{len(candles_by_symbol)} symbols = {total} runs"
        )

        strategy_results: list[StrategyResult] = []
        done = 0
        for combo in combos:
            params = dict(zip(param_names, combo, strict=True))
            for symbol, candles in candles_by_symbol.items():
                r = run_single(strategy_type, params, risk_config, candles, symbol)
                strategy_results.append(r)
                done += 1
            if done % 100 == 0:
                print(f"    progress: {done}/{total}")

        all_results[strategy_type] = strategy_results
        print(f"    completed {len(strategy_results)} runs")

    return all_results


def find_optimal_params(results: list[StrategyResult]) -> dict:
    """Find best param set across all symbols by average score."""
    param_groups: dict[str, list[StrategyResult]] = {}
    for r in results:
        key = json.dumps(sorted(r.params.items()), separators=(",", ":"))
        param_groups.setdefault(key, []).append(r)

    best_key = None
    best_avg_score = -999.0
    for key, group in param_groups.items():
        avg_score = sum(score_result(r) for r in group) / len(group)
        if avg_score > best_avg_score:
            best_avg_score = avg_score
            best_key = key

    if best_key is None:
        return {}

    best_group = param_groups[best_key]
    first = best_group[0]

    per_symbol = {}
    for r in best_group:
        per_symbol[r.symbol] = {
            "return_pct": round(r.return_pct, 2),
            "win_rate": round(r.win_rate, 1),
            "profit_factor": round(r.profit_factor, 2),
            "max_drawdown": round(r.max_drawdown, 2),
            "sharpe": round(r.sharpe, 2),
            "trade_count": r.trade_count,
        }

    return {
        "params": first.params,
        "avg_score": round(best_avg_score, 4),
        "avg_return_pct": round(sum(r.return_pct for r in best_group) / len(best_group), 2),
        "avg_win_rate": round(sum(r.win_rate for r in best_group) / len(best_group), 1),
        "avg_profit_factor": round(sum(r.profit_factor for r in best_group) / len(best_group), 2),
        "avg_max_drawdown": round(sum(r.max_drawdown for r in best_group) / len(best_group), 2),
        "avg_sharpe": round(sum(r.sharpe for r in best_group) / len(best_group), 2),
        "total_trades": sum(r.trade_count for r in best_group),
        "per_symbol": per_symbol,
    }


def find_top_n_params(results: list[StrategyResult], n: int = 5) -> list[dict]:
    """Find top N param sets by average score across symbols."""
    param_groups: dict[str, list[StrategyResult]] = {}
    for r in results:
        key = json.dumps(sorted(r.params.items()), separators=(",", ":"))
        param_groups.setdefault(key, []).append(r)

    scored = []
    for _key, group in param_groups.items():
        avg_score = sum(score_result(r) for r in group) / len(group)
        scored.append((avg_score, group))

    scored.sort(key=lambda x: x[0], reverse=True)

    top = []
    for avg_score, group in scored[:n]:
        first = group[0]
        top.append({
            "params": first.params,
            "avg_score": round(avg_score, 4),
            "avg_return_pct": round(sum(r.return_pct for r in group) / len(group), 2),
            "avg_win_rate": round(sum(r.win_rate for r in group) / len(group), 1),
            "avg_profit_factor": round(sum(r.profit_factor for r in group) / len(group), 2),
            "avg_max_drawdown": round(sum(r.max_drawdown for r in group) / len(group), 2),
            "avg_sharpe": round(sum(r.sharpe for r in group) / len(group), 2),
            "total_trades": sum(r.trade_count for r in group),
        })
    return top


def run_risk_optimization(
    candles_by_symbol: dict[str, list[Candle]],
    optimal_params: dict[str, dict],
) -> dict[str, dict]:
    """Test optimal strategy params against different risk profiles."""
    print("\n" + "=" * 80)
    print("  PHASE 3: RISK PROFILE OPTIMIZATION")
    print("=" * 80)

    risk_results: dict[str, dict] = {}

    for strategy_type in TARGET_STRATEGIES:
        if strategy_type not in optimal_params or not optimal_params[strategy_type].get("params"):
            continue

        params = optimal_params[strategy_type]["params"]
        best_profile = None
        best_score = -999.0
        profile_data = {}

        for profile_name, risk_config in RISK_GRIDS.items():
            results = []
            for symbol, candles in candles_by_symbol.items():
                r = run_single(strategy_type, params, risk_config, candles, symbol, profile_name)
                results.append(r)

            avg_score = sum(score_result(r) for r in results) / len(results)
            avg_ret = sum(r.return_pct for r in results) / len(results)
            avg_wr = sum(r.win_rate for r in results) / len(results)
            avg_mdd = sum(r.max_drawdown for r in results) / len(results)
            avg_sharpe = sum(r.sharpe for r in results) / len(results)

            profile_data[profile_name] = {
                "score": round(avg_score, 4),
                "avg_return_pct": round(avg_ret, 2),
                "avg_win_rate": round(avg_wr, 1),
                "avg_max_drawdown": round(avg_mdd, 2),
                "avg_sharpe": round(avg_sharpe, 2),
                "total_trades": sum(r.trade_count for r in results),
            }

            print(
                f"  {strategy_type:<20} {profile_name:<14} "
                f"score={avg_score:>6.3f} ret={avg_ret:>+6.2f}% mdd={avg_mdd:>5.2f}% "
                f"sharpe={avg_sharpe:>6.2f}"
            )

            if avg_score > best_score:
                best_score = avg_score
                best_profile = profile_name

        risk_results[strategy_type] = {
            "best_profile": best_profile,
            "profiles": profile_data,
        }

    return risk_results


def generate_report(
    baseline: list[StrategyResult],
    optimal_params: dict[str, dict],
    top_params: dict[str, list[dict]],
    risk_results: dict[str, dict],
    elapsed: float,
) -> str:
    """Generate markdown report."""
    lines = [
        "# Crypto-Trader Backtest Analysis Report",
        "",
        "**Date:** 2026-03-27  ",
        f"**Period:** {DAYS}-day hourly candles  ",
        f"**Symbols:** {', '.join(SYMBOLS)}  ",
        f"**Strategies:** {', '.join(TARGET_STRATEGIES)}  ",
        "**Based on:** Parameter tuning commit 6dffded  ",
        f"**Elapsed:** {elapsed:.1f}s  ",
        "",
        "---",
        "",
        "## 1. Baseline Performance (Current Tuned Params)",
        "",
        "| Strategy | Symbol | Return% | MDD% | WinRate% | PF | Sharpe | Trades |",
        "|----------|--------|--------:|-----:|---------:|---:|-------:|-------:|",
    ]

    # Group baseline by strategy
    by_strategy: dict[str, list[StrategyResult]] = {}
    for r in baseline:
        by_strategy.setdefault(r.strategy, []).append(r)

    for strategy_type in TARGET_STRATEGIES:
        results = by_strategy.get(strategy_type, [])
        for r in results:
            pf = f"{r.profit_factor:.2f}" if r.profit_factor < 1000 else "∞"
            lines.append(
                f"| {r.strategy} | {r.symbol} | {r.return_pct:+.2f} | {r.max_drawdown:.2f} | "
                f"{r.win_rate:.1f} | {pf} | {r.sharpe:.2f} | {r.trade_count} |"
            )

    # Strategy summary
    lines.extend(["", "### Strategy Summary (averaged across symbols)", ""])
    lines.append("| Strategy | Avg Return% | Avg MDD% | Avg WinRate% | Avg Sharpe | Total Trades |")
    lines.append("|----------|------------:|---------:|-------------:|-----------:|-------------:|")

    for strategy_type in TARGET_STRATEGIES:
        results = by_strategy.get(strategy_type, [])
        if not results:
            continue
        n = len(results)
        avg_ret = sum(r.return_pct for r in results) / n
        avg_mdd = sum(r.max_drawdown for r in results) / n
        avg_wr = sum(r.win_rate for r in results) / n
        avg_sharpe = sum(r.sharpe for r in results) / n
        total_trades = sum(r.trade_count for r in results)
        lines.append(
            f"| **{strategy_type}** | {avg_ret:+.2f} | {avg_mdd:.2f} | "
            f"{avg_wr:.1f} | {avg_sharpe:.2f} | {total_trades} |"
        )

    # Optimal params section
    lines.extend([
        "",
        "---",
        "",
        "## 2. Optimal Parameters (Grid Search Results)",
        "",
    ])

    for strategy_type in TARGET_STRATEGIES:
        opt = optimal_params.get(strategy_type, {})
        if not opt:
            lines.append(f"### {strategy_type}\n\nNo viable parameters found.\n")
            continue

        lines.append(f"### {strategy_type}")
        lines.append("")
        lines.append(f"**Best Score:** {opt['avg_score']}  ")
        lines.append(f"**Avg Return:** {opt['avg_return_pct']:+.2f}%  ")
        lines.append(f"**Avg Win Rate:** {opt['avg_win_rate']:.1f}%  ")
        lines.append(f"**Avg MDD:** {opt['avg_max_drawdown']:.2f}%  ")
        lines.append(f"**Avg Sharpe:** {opt['avg_sharpe']:.2f}  ")
        lines.append(f"**Total Trades:** {opt['total_trades']}  ")
        lines.append("")
        lines.append("**Optimal Parameters:**")
        lines.append("```toml")
        for k, v in sorted(opt["params"].items()):
            lines.append(f"{k} = {v}")
        lines.append("```")
        lines.append("")

        # Per-symbol breakdown
        if opt.get("per_symbol"):
            lines.append("**Per-Symbol Breakdown:**")
            lines.append("")
            lines.append("| Symbol | Return% | WinRate% | PF | MDD% | Sharpe | Trades |")
            lines.append("|--------|--------:|---------:|---:|-----:|-------:|-------:|")
            for sym, data in opt["per_symbol"].items():
                pf = f"{data['profit_factor']:.2f}" if data['profit_factor'] < 1000 else "∞"
                lines.append(
                    f"| {sym} | {data['return_pct']:+.2f} | {data['win_rate']:.1f} | "
                    f"{pf} | {data['max_drawdown']:.2f} | {data['sharpe']:.2f} | "
                    f"{data['trade_count']} |"
                )
            lines.append("")

        # Top 5 candidates
        top = top_params.get(strategy_type, [])
        if len(top) > 1:
            lines.append("**Top 5 Parameter Sets:**")
            lines.append("")
            lines.append(
                "| Rank | Score | Return% | WinRate% | MDD% | Sharpe | Trades | Key Params |"
            )
            lines.append("|-----:|------:|--------:|---------:|-----:|-------:|-------:|------------|")
            for i, t in enumerate(top, 1):
                key_params = ", ".join(f"{k}={v}" for k, v in sorted(t["params"].items()))
                lines.append(
                    f"| {i} | {t['avg_score']:.3f} | {t['avg_return_pct']:+.2f} | "
                    f"{t['avg_win_rate']:.1f} | {t['avg_max_drawdown']:.2f} | "
                    f"{t['avg_sharpe']:.2f} | {t['total_trades']} | {key_params} |"
                )
            lines.append("")

    # Risk optimization
    lines.extend([
        "---",
        "",
        "## 3. Risk Profile Optimization",
        "",
        "| Strategy | Profile | Score | Return% | WinRate% | MDD% | Sharpe | Trades |",
        "|----------|---------|------:|--------:|---------:|-----:|-------:|-------:|",
    ])
    for strategy_type in TARGET_STRATEGIES:
        rr = risk_results.get(strategy_type, {})
        profiles = rr.get("profiles", {})
        best = rr.get("best_profile", "")
        for profile_name, data in profiles.items():
            marker = " **←**" if profile_name == best else ""
            lines.append(
                f"| {strategy_type} | {profile_name}{marker} | {data['score']:.3f} | "
                f"{data['avg_return_pct']:+.2f} | {data['avg_win_rate']:.1f} | "
                f"{data['avg_max_drawdown']:.2f} | {data['avg_sharpe']:.2f} | "
                f"{data['total_trades']} |"
            )

    # Recommendations
    lines.extend([
        "",
        "---",
        "",
        "## 4. Recommendations",
        "",
    ])

    for strategy_type in TARGET_STRATEGIES:
        opt = optimal_params.get(strategy_type, {})
        rr = risk_results.get(strategy_type, {})
        best_risk = rr.get("best_profile", "moderate")

        lines.append(f"### {strategy_type}")
        if opt:
            lines.append(f"- **Deploy with:** optimal params above + **{best_risk}** risk profile")
            if opt["avg_sharpe"] > 1.0:
                lines.append(
                    f"- **Status:** ✅ Production-ready (Sharpe {opt['avg_sharpe']:.2f})"
                )
            elif opt["avg_sharpe"] > 0.5:
                lines.append(
                    f"- **Status:** ⚠️ Viable but needs monitoring "
                    f"(Sharpe {opt['avg_sharpe']:.2f})"
                )
            else:
                lines.append(
                    f"- **Status:** ❌ Needs further optimization "
                    f"(Sharpe {opt['avg_sharpe']:.2f})"
                )
            if opt["avg_max_drawdown"] > 10:
                lines.append(
                    f"- **Warning:** High MDD ({opt['avg_max_drawdown']:.1f}%) "
                    "— tighten stops"
                )
        else:
            lines.append("- **Status:** ❌ No viable parameters found")
        lines.append("")

    # Final config recommendations
    lines.extend([
        "---",
        "",
        "## 5. Recommended daemon.toml Updates",
        "",
        "```toml",
        "[strategy]",
    ])
    # Merge optimal params into config recommendation
    for strategy_type in TARGET_STRATEGIES:
        opt = optimal_params.get(strategy_type, {})
        if opt and opt.get("params"):
            lines.append(
                f"# {strategy_type} (Sharpe: {opt['avg_sharpe']:.2f}, "
                f"Score: {opt['avg_score']:.3f})"
            )
            for k, v in sorted(opt["params"].items()):
                lines.append(f"# {k} = {v}")
            lines.append("")

    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    start = time.time()

    print("=" * 80)
    print("  CRYPTO-TRADER COMPREHENSIVE BACKTEST ANALYSIS")
    print(f"  {DAYS}-day | {len(SYMBOLS)} symbols | {len(TARGET_STRATEGIES)} strategies")
    print("=" * 80)

    # Fetch data
    print("\nFetching candle data...")
    candles_by_symbol = fetch_all_candles()

    if not candles_by_symbol:
        print("ERROR: No candle data available")
        sys.exit(1)

    # Phase 1: Baseline
    baseline = run_baseline(candles_by_symbol)

    # Phase 2: Grid search
    grid_results = run_grid_search(candles_by_symbol)

    # Find optimal params per strategy
    optimal_params = {}
    top_params = {}
    for strategy_type, results in grid_results.items():
        optimal_params[strategy_type] = find_optimal_params(results)
        top_params[strategy_type] = find_top_n_params(results, n=5)

        opt = optimal_params[strategy_type]
        if opt:
            print(f"\n  BEST {strategy_type}:")
            print(f"    Score: {opt['avg_score']:.4f}  Sharpe: {opt['avg_sharpe']:.2f}")
            print(f"    Return: {opt['avg_return_pct']:+.2f}%  MDD: {opt['avg_max_drawdown']:.2f}%")
            print(f"    Params: {opt['params']}")

    # Phase 3: Risk profile optimization
    risk_results = run_risk_optimization(candles_by_symbol, optimal_params)

    elapsed = time.time() - start

    # Generate report
    report = generate_report(baseline, optimal_params, top_params, risk_results, elapsed)
    report_path = Path("docs/backtest-analysis-report.md")
    report_path.write_text(report, encoding="utf-8")
    print(f"\n  Report written to: {report_path}")

    # Save raw JSON results
    json_path = Path("artifacts/backtest-grid-90d/comprehensive-analysis.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)

    json_data = {
        "meta": {
            "days": DAYS,
            "symbols": SYMBOLS,
            "strategies": TARGET_STRATEGIES,
            "elapsed_seconds": round(elapsed, 1),
            "date": "2026-03-27",
        },
        "baseline": [
            {
                "strategy": r.strategy,
                "symbol": r.symbol,
                "return_pct": round(r.return_pct, 2),
                "win_rate": round(r.win_rate, 1),
                "profit_factor": round(r.profit_factor, 2) if r.profit_factor < 1000 else 9999,
                "max_drawdown": round(r.max_drawdown, 2),
                "sharpe": round(r.sharpe, 2),
                "trade_count": r.trade_count,
            }
            for r in baseline
        ],
        "optimal_params": optimal_params,
        "top_params": top_params,
        "risk_optimization": risk_results,
    }
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  JSON results written to: {json_path}")

    print(f"\n{'='*80}")
    print(f"  ANALYSIS COMPLETE in {elapsed:.1f}s")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
