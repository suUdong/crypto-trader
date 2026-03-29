#!/usr/bin/env python3
"""P0 Parameter Optimization: ATR stop, confidence, RSI, take-profit + strategy-specific.

Targets active wallets: vpin (ETH/SOL), momentum (SOL), volume_spike (BTC).
Sweeps risk + strategy params on 90-day hourly Upbit data.
Outputs JSON results + markdown report.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import time
from dataclasses import dataclass
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
from crypto_trader.strategy.volume_spike import VolumeSpikeStrategy  # noqa: E402
from crypto_trader.strategy.vpin import VPINStrategy  # noqa: E402
from crypto_trader.wallet import create_strategy  # noqa: E402

INTERVAL = "minute60"
DAYS = 90
BACKTEST_CAPITAL = 1_000_000.0


@dataclass
class OptResult:
    wallet: str
    strategy: str
    symbol: str
    risk_params: dict[str, float]
    strategy_params: dict[str, float | int]
    return_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    trade_count: int
    sharpe: float
    sortino: float
    calmar: float
    avg_trade_duration: float
    exit_reasons: dict[str, int]


# ── Risk parameter sweep (cross-product with each strategy grid) ──

RISK_GRID = {
    "atr_stop_multiplier": [1.5, 2.0, 2.5, 3.0],
    "min_entry_confidence": [0.45, 0.6, 0.7, 0.8],
    "take_profit_pct": [0.04, 0.06, 0.08, 0.10],
}
# 4×4×4 = 64 total, sample down to 8

# Force unbuffered progress output
import functools
print = functools.partial(print, flush=True)  # type: ignore[assignment]

# ── Strategy-specific grids ──

MOMENTUM_SOL_GRID = {
    "momentum_lookback": [12, 20],
    "momentum_entry_threshold": [0.003, 0.005],
    "rsi_overbought": [65.0, 72.0, 80.0],
    "max_holding_bars": [36, 60],
    "adx_threshold": [12.0, 20.0],
}
# 2×2×3×2×2 = 48

VPIN_SOL_GRID = {
    "vpin_low_threshold": [0.40, 0.55],
    "vpin_high_threshold": [0.70, 0.80],
    "vpin_momentum_threshold": [0.0003, 0.001],
    "max_holding_bars": [24, 36],
    "bucket_count": [20],
}
# 2×2×2×2×1 = 16

VPIN_ETH_GRID = {
    "vpin_low_threshold": [0.35, 0.50],
    "vpin_high_threshold": [0.65, 0.80],
    "vpin_momentum_threshold": [0.0003, 0.001],
    "max_holding_bars": [18, 30],
    "bucket_count": [20],
}
# 2×2×2×2×1 = 16

VOLSPIKE_BTC_GRID = {
    "spike_mult": [2.0, 3.0],
    "min_body_ratio": [0.2, 0.3],
    "rsi_overbought": [68.0, 78.0],
    "max_holding_bars": [24, 36],
    "adx_threshold": [15.0, 25.0],
}
# 2×2×2×2×2 = 32

# Wallet definitions: (wallet_name, strategy_type, symbols, strategy_grid)
WALLETS = [
    ("momentum_sol", "momentum", ["KRW-SOL"], MOMENTUM_SOL_GRID),
    ("vpin_sol", "vpin", ["KRW-SOL"], VPIN_SOL_GRID),
    ("vpin_eth", "vpin", ["KRW-ETH"], VPIN_ETH_GRID),
    ("volspike_btc", "volume_spike", ["KRW-BTC"], VOLSPIKE_BTC_GRID),
]


def fetch_candles(symbol: str) -> list[Candle]:
    return fetch_upbit_candles(
        symbol, DAYS, interval=INTERVAL,
        cache_dir=os.environ.get("CT_CANDLE_CACHE_DIR"),
    )


def _make_strategy(strategy_type: str, strategy_config: StrategyConfig, params: dict):
    """Create strategy instance with extra constructor params where needed."""
    regime_config = RegimeConfig()
    if strategy_type == "vpin":
        return VPINStrategy(
            strategy_config,
            vpin_high_threshold=float(params.get("vpin_high_threshold", 0.75)),
            vpin_low_threshold=float(params.get("vpin_low_threshold", 0.45)),
            bucket_count=int(params.get("bucket_count", 20)),
            vpin_momentum_threshold=float(params.get("vpin_momentum_threshold", 0.0005)),
            vpin_rsi_ceiling=float(params.get("vpin_rsi_ceiling", 78.0)),
            vpin_rsi_floor=float(params.get("vpin_rsi_floor", 22.0)),
        )
    if strategy_type == "volume_spike":
        return VolumeSpikeStrategy(
            strategy_config,
            regime_config,
            spike_mult=float(params.get("spike_mult", 2.5)),
            volume_window=int(params.get("volume_window", 20)),
            min_body_ratio=float(params.get("min_body_ratio", 0.3)),
        )
    return create_strategy(strategy_type, strategy_config, regime_config, {})


def _sample_combos(grid: dict, max_combos: int = 30) -> list[dict]:
    """Generate all combos from a grid, subsampled if too many."""
    keys = list(grid.keys())
    values = list(grid.values())
    all_combos = [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*values)]
    if len(all_combos) <= max_combos:
        return all_combos
    # Uniform subsample
    step = max(1, len(all_combos) // max_combos)
    return all_combos[::step][:max_combos]


def _sample_risk_combos(max_combos: int = 8) -> list[dict]:
    """Sample risk parameter combinations."""
    keys = list(RISK_GRID.keys())
    values = list(RISK_GRID.values())
    all_combos = [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*values)]
    if len(all_combos) <= max_combos:
        return all_combos
    step = max(1, len(all_combos) // max_combos)
    return all_combos[::step][:max_combos]


def run_wallet_optimization(
    wallet_name: str,
    strategy_type: str,
    symbols: list[str],
    strategy_grid: dict,
    candles_cache: dict[str, list[Candle]],
) -> list[OptResult]:
    """Run cross-product of risk × strategy params for a wallet."""
    risk_combos = _sample_risk_combos(max_combos=16)
    strat_combos = _sample_combos(strategy_grid, max_combos=40)

    total = len(risk_combos) * len(strat_combos) * len(symbols)
    print(f"\n  {wallet_name}: {len(risk_combos)} risk × {len(strat_combos)} strategy "
          f"× {len(symbols)} symbols = {total} backtests")

    results: list[OptResult] = []
    done = 0

    for risk_params in risk_combos:
        risk_config = RiskConfig(
            atr_stop_multiplier=risk_params["atr_stop_multiplier"],
            min_entry_confidence=risk_params["min_entry_confidence"],
            take_profit_pct=risk_params["take_profit_pct"],
            stop_loss_pct=0.03,
            risk_per_trade_pct=0.015,
            partial_tp_pct=0.5,
            max_concurrent_positions=2,
            max_position_pct=0.10,
            cooldown_bars=3,
        )

        for strat_params in strat_combos:
            # Build StrategyConfig from strategy params
            config_fields = set(StrategyConfig.__dataclass_fields__)
            cfg_kwargs = {k: v for k, v in strat_params.items() if k in config_fields}
            strategy_config = StrategyConfig(**cfg_kwargs)

            for symbol in symbols:
                candles = candles_cache.get(symbol)
                if not candles or len(candles) < 50:
                    continue

                strategy = _make_strategy(strategy_type, strategy_config, strat_params)
                risk_manager = RiskManager(risk_config)
                engine = BacktestEngine(
                    strategy=strategy,
                    risk_manager=risk_manager,
                    config=BacktestConfig(
                        initial_capital=BACKTEST_CAPITAL,
                        fee_rate=0.0005,
                        slippage_pct=0.0005,
                    ),
                    symbol=symbol,
                )
                bt = engine.run(candles)

                results.append(OptResult(
                    wallet=wallet_name,
                    strategy=strategy_type,
                    symbol=symbol,
                    risk_params=risk_params,
                    strategy_params=strat_params,
                    return_pct=bt.total_return_pct * 100,
                    win_rate=bt.win_rate * 100,
                    profit_factor=bt.profit_factor,
                    max_drawdown=bt.max_drawdown * 100,
                    trade_count=len(bt.trade_log),
                    sharpe=bt.sharpe_ratio,
                    sortino=bt.sortino_ratio,
                    calmar=bt.calmar_ratio,
                    avg_trade_duration=bt.avg_trade_duration_bars,
                    exit_reasons=bt.exit_reason_counts,
                ))
                done += 1

        if done % 50 == 0 and done > 0:
            print(f"    ... {done}/{total} done")

    print(f"    Done: {len(results)} results")
    return results


def score_result(r: OptResult) -> float:
    """Composite score: Sharpe-heavy with win rate and MDD penalty."""
    if r.trade_count < 3:
        return -999.0
    sharpe_score = r.sharpe * 0.40
    sortino_score = min(r.sortino, 10.0) * 0.20
    wr_score = (r.win_rate / 100.0) * 0.20
    mdd_penalty = max(0, r.max_drawdown - 5.0) * 0.10
    pf_score = min(r.profit_factor, 5.0) / 5.0 * 0.20
    return sharpe_score + sortino_score + wr_score + pf_score - mdd_penalty


def top_results(results: list[OptResult], n: int = 10) -> list[OptResult]:
    """Return top N results by composite score."""
    scored = [(score_result(r), r) for r in results]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:n]]


def generate_report(
    all_results: dict[str, list[OptResult]],
    elapsed: float,
) -> str:
    """Generate markdown optimization report."""
    lines = [
        "# P0 Backtest Parameter Optimization Report",
        "",
        f"Date: 2026-03-29  |  Data: {DAYS}-day hourly Upbit candles  |  "
        f"Runtime: {elapsed:.0f}s",
        "",
        "## Targets",
        "- Sharpe >= 1.0, Win rate >= 55%, MDD <= 5%",
        "- Risk sweep: ATR multiplier [1.5, 2.0, 2.5, 3.0], "
        "confidence [0.45, 0.6, 0.7, 0.8], take profit [4%, 6%, 8%, 10%]",
        "",
    ]

    overall_best: list[tuple[str, OptResult]] = []

    for wallet_name, results in all_results.items():
        if not results:
            lines.append(f"## {wallet_name}\n\nNo results.\n")
            continue

        top = top_results(results, n=5)
        best = top[0] if top else None
        overall_best.append((wallet_name, best))

        lines.extend([
            f"## {wallet_name} ({best.strategy} on {best.symbol})" if best else f"## {wallet_name}",
            "",
        ])

        if best:
            meets_targets = (
                best.sharpe >= 1.0
                and best.win_rate >= 55.0
                and best.max_drawdown <= 5.0
            )
            status = "MEETS TARGETS" if meets_targets else "BELOW TARGETS"
            lines.extend([
                f"**Status: {status}**",
                "",
                "### Best Parameters",
                "",
                "**Risk:**",
                f"- ATR stop multiplier: **{best.risk_params['atr_stop_multiplier']}**",
                f"- Min entry confidence: **{best.risk_params['min_entry_confidence']}**",
                f"- Take profit: **{best.risk_params['take_profit_pct'] * 100:.0f}%**",
                "",
                "**Strategy:**",
            ])
            for k, v in sorted(best.strategy_params.items()):
                lines.append(f"- {k}: **{v}**")

            lines.extend([
                "",
                "### Performance",
                "",
                f"| Metric | Value |",
                f"| --- | ---: |",
                f"| Sharpe | {best.sharpe:.2f} |",
                f"| Sortino | {best.sortino:.2f} |",
                f"| Calmar | {best.calmar:.2f} |",
                f"| Return | {best.return_pct:+.2f}% |",
                f"| Win Rate | {best.win_rate:.1f}% |",
                f"| Max Drawdown | {best.max_drawdown:.2f}% |",
                f"| Profit Factor | {best.profit_factor:.2f} |",
                f"| Trades | {best.trade_count} |",
                f"| Avg Duration | {best.avg_trade_duration:.1f} bars |",
                "",
            ])

            # Exit reason breakdown
            if best.exit_reasons:
                lines.extend(["### Exit Reasons", ""])
                for reason, count in sorted(
                    best.exit_reasons.items(), key=lambda x: -x[1]
                ):
                    lines.append(f"- {reason}: {count}")
                lines.append("")

            # Top 5 alternatives
            lines.extend([
                "### Top 5 Candidates",
                "",
                "| # | Sharpe | Return% | WR% | MDD% | PF | Trades "
                "| ATR | Conf | TP% |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: "
                "| ---: | ---: | ---: |",
            ])
            for i, r in enumerate(top, 1):
                pf = f"{r.profit_factor:.2f}" if r.profit_factor < 999 else "inf"
                lines.append(
                    f"| {i} | {r.sharpe:.2f} | {r.return_pct:+.2f} "
                    f"| {r.win_rate:.1f} | {r.max_drawdown:.2f} | {pf} "
                    f"| {r.trade_count} "
                    f"| {r.risk_params['atr_stop_multiplier']} "
                    f"| {r.risk_params['min_entry_confidence']} "
                    f"| {r.risk_params['take_profit_pct'] * 100:.0f} |"
                )
            lines.append("")

        # ATR sensitivity analysis
        atr_perf: dict[float, list[OptResult]] = {}
        for r in results:
            atr = r.risk_params["atr_stop_multiplier"]
            atr_perf.setdefault(atr, []).append(r)

        lines.extend([
            "### ATR Multiplier Sensitivity",
            "",
            "| ATR | Avg Sharpe | Avg WR% | Avg MDD% | Avg Return% | Avg Trades |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for atr_val in sorted(atr_perf.keys()):
            rr = [x for x in atr_perf[atr_val] if x.trade_count >= 1]
            if not rr:
                continue
            avg_sh = sum(x.sharpe for x in rr) / len(rr)
            avg_wr = sum(x.win_rate for x in rr) / len(rr)
            avg_mdd = sum(x.max_drawdown for x in rr) / len(rr)
            avg_ret = sum(x.return_pct for x in rr) / len(rr)
            avg_trades = sum(x.trade_count for x in rr) / len(rr)
            lines.append(
                f"| {atr_val} | {avg_sh:.2f} | {avg_wr:.1f} "
                f"| {avg_mdd:.2f} | {avg_ret:+.2f} | {avg_trades:.0f} |"
            )
        lines.append("")

        # Confidence sensitivity
        conf_perf: dict[float, list[OptResult]] = {}
        for r in results:
            conf = r.risk_params["min_entry_confidence"]
            conf_perf.setdefault(conf, []).append(r)

        lines.extend([
            "### Confidence Threshold Sensitivity",
            "",
            "| Confidence | Avg Sharpe | Avg WR% | Avg Trades |",
            "| ---: | ---: | ---: | ---: |",
        ])
        for conf_val in sorted(conf_perf.keys()):
            rr = [x for x in conf_perf[conf_val] if x.trade_count >= 1]
            if not rr:
                lines.append(f"| {conf_val} | — | — | 0 |")
                continue
            avg_sh = sum(x.sharpe for x in rr) / len(rr)
            avg_wr = sum(x.win_rate for x in rr) / len(rr)
            avg_trades = sum(x.trade_count for x in rr) / len(rr)
            lines.append(
                f"| {conf_val} | {avg_sh:.2f} | {avg_wr:.1f} | {avg_trades:.0f} |"
            )
        lines.append("")

    # Overall summary
    lines.extend([
        "---",
        "",
        "## Summary & Recommendations",
        "",
        "| Wallet | Strategy | Sharpe | WR% | MDD% | Return% | Meets Target? |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ])
    for wallet_name, best in overall_best:
        if best:
            meets = (
                "YES" if best.sharpe >= 1.0 and best.win_rate >= 55.0
                and best.max_drawdown <= 5.0 else "NO"
            )
            lines.append(
                f"| {wallet_name} | {best.strategy} | {best.sharpe:.2f} "
                f"| {best.win_rate:.1f} | {best.max_drawdown:.2f} "
                f"| {best.return_pct:+.2f} | {meets} |"
            )
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    t0 = time.time()
    print(f"\n{'#' * 80}")
    print(f"  P0 PARAMETER OPTIMIZATION — {DAYS}-day data, {len(WALLETS)} wallets")
    print(f"{'#' * 80}")

    # Fetch candles for all needed symbols
    needed_symbols = set()
    for _, _, syms, _ in WALLETS:
        needed_symbols.update(syms)

    candles_cache: dict[str, list[Candle]] = {}
    for symbol in sorted(needed_symbols):
        print(f"Fetching {symbol} ({DAYS}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_cache[symbol] = candles

    # Run optimization per wallet
    all_results: dict[str, list[OptResult]] = {}
    for wallet_name, strategy_type, symbols, strategy_grid in WALLETS:
        print(f"\n{'=' * 60}")
        print(f"  Optimizing: {wallet_name} ({strategy_type})")
        results = run_wallet_optimization(
            wallet_name, strategy_type, symbols, strategy_grid, candles_cache,
        )
        all_results[wallet_name] = results

        # Print quick summary
        top = top_results(results, n=3)
        if top:
            best = top[0]
            print(f"  BEST: Sharpe={best.sharpe:.2f} WR={best.win_rate:.1f}% "
                  f"MDD={best.max_drawdown:.2f}% Ret={best.return_pct:+.2f}% "
                  f"Trades={best.trade_count}")
            print(f"    Risk: ATR={best.risk_params['atr_stop_multiplier']} "
                  f"Conf={best.risk_params['min_entry_confidence']} "
                  f"TP={best.risk_params['take_profit_pct']}")
            print(f"    Strategy: {best.strategy_params}")

    elapsed = time.time() - t0

    # Generate report
    report = generate_report(all_results, elapsed)
    os.makedirs("artifacts", exist_ok=True)
    report_path = "artifacts/backtest-optimization-report.md"
    Path(report_path).write_text(report, encoding="utf-8")
    print(f"\n  Report saved to {report_path}")

    # Save raw JSON
    json_results: dict = {}
    for wallet_name, results in all_results.items():
        top = top_results(results, n=10)
        json_results[wallet_name] = {
            "total_backtests": len(results),
            "top10": [
                {
                    "score": round(score_result(r), 4),
                    "sharpe": round(r.sharpe, 4),
                    "sortino": round(r.sortino, 4),
                    "calmar": round(r.calmar, 4),
                    "return_pct": round(r.return_pct, 4),
                    "win_rate": round(r.win_rate, 2),
                    "max_drawdown": round(r.max_drawdown, 4),
                    "profit_factor": round(r.profit_factor, 4),
                    "trade_count": r.trade_count,
                    "risk_params": r.risk_params,
                    "strategy_params": {
                        k: round(v, 6) if isinstance(v, float) else v
                        for k, v in r.strategy_params.items()
                    },
                    "exit_reasons": r.exit_reasons,
                }
                for r in top
            ],
        }

    json_path = "artifacts/optimization-p0-results.json"
    Path(json_path).write_text(
        json.dumps(json_results, indent=2, default=str), encoding="utf-8",
    )
    print(f"  JSON saved to {json_path}")

    print(f"\n{'#' * 80}")
    print(f"  DONE in {elapsed:.0f}s — {sum(len(r) for r in all_results.values())} total backtests")
    print(f"{'#' * 80}\n")


if __name__ == "__main__":
    main()
