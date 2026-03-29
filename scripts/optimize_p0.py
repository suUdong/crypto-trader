#!/usr/bin/env python3
"""P0 Parameter Optimization — lean version.

Targets active wallets with focused parameter sweeps.
Total ~200 backtests for fast execution.
"""

from __future__ import annotations

import functools
import itertools
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

print = functools.partial(print, flush=True)  # type: ignore[assignment]

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


@dataclass
class Result:
    wallet: str
    strategy: str
    symbol: str
    params: dict
    return_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    trade_count: int
    sharpe: float
    sortino: float
    calmar: float
    avg_duration: float
    exit_reasons: dict


def fetch(symbol: str) -> list[Candle]:
    return fetch_upbit_candles(
        symbol, DAYS, interval=INTERVAL,
        cache_dir=os.environ.get("CT_CANDLE_CACHE_DIR"),
    )


def run_one(
    wallet: str, strategy_type: str, symbol: str,
    candles: list[Candle], params: dict,
) -> Result:
    """Run a single backtest with given params."""
    cfg_fields = set(StrategyConfig.__dataclass_fields__)
    cfg_kwargs = {k: v for k, v in params.items() if k in cfg_fields}
    scfg = StrategyConfig(**cfg_kwargs)

    rcfg = RiskConfig(
        atr_stop_multiplier=params.get("atr_stop_multiplier", 2.0),
        min_entry_confidence=params.get("min_entry_confidence", 0.6),
        take_profit_pct=params.get("take_profit_pct", 0.06),
        stop_loss_pct=params.get("stop_loss_pct", 0.03),
        risk_per_trade_pct=0.015,
        partial_tp_pct=0.5,
        max_concurrent_positions=2,
        max_position_pct=0.10,
        cooldown_bars=3,
    )

    if strategy_type == "vpin":
        strat = VPINStrategy(
            scfg,
            vpin_high_threshold=float(params.get("vpin_high_threshold", 0.75)),
            vpin_low_threshold=float(params.get("vpin_low_threshold", 0.45)),
            bucket_count=int(params.get("bucket_count", 20)),
            vpin_momentum_threshold=float(params.get("vpin_momentum_threshold", 0.0005)),
            vpin_rsi_ceiling=float(params.get("vpin_rsi_ceiling", 78.0)),
            vpin_rsi_floor=float(params.get("vpin_rsi_floor", 22.0)),
        )
    elif strategy_type == "volume_spike":
        strat = VolumeSpikeStrategy(
            scfg, RegimeConfig(),
            spike_mult=float(params.get("spike_mult", 2.5)),
            volume_window=int(params.get("volume_window", 20)),
            min_body_ratio=float(params.get("min_body_ratio", 0.3)),
        )
    else:
        strat = create_strategy(strategy_type, scfg, RegimeConfig(), {})

    engine = BacktestEngine(
        strategy=strat,
        risk_manager=RiskManager(rcfg),
        config=BacktestConfig(initial_capital=1_000_000, fee_rate=0.0005, slippage_pct=0.0005),
        symbol=symbol,
    )
    bt = engine.run(candles)
    return Result(
        wallet=wallet, strategy=strategy_type, symbol=symbol, params=params,
        return_pct=bt.total_return_pct * 100, win_rate=bt.win_rate * 100,
        profit_factor=bt.profit_factor, max_drawdown=bt.max_drawdown * 100,
        trade_count=len(bt.trade_log), sharpe=bt.sharpe_ratio,
        sortino=bt.sortino_ratio, calmar=bt.calmar_ratio,
        avg_duration=bt.avg_trade_duration_bars, exit_reasons=bt.exit_reason_counts,
    )


def grid_combos(grid: dict) -> list[dict]:
    keys = list(grid.keys())
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*grid.values())]


def score(r: Result) -> float:
    if r.trade_count < 3:
        return -999.0
    return (
        r.sharpe * 0.40
        + min(r.sortino, 10) * 0.20
        + (r.win_rate / 100) * 0.20
        + min(r.profit_factor, 5) / 5 * 0.20
        - max(0, r.max_drawdown - 5) * 0.10
    )


# ── Wallet configs: each is (name, strategy, symbol, param_grid) ──
# Grid merged with risk params per combo. Keep grids tiny.

WALLETS = [
    ("momentum_sol", "momentum", "KRW-SOL", {
        "atr_stop_multiplier": [1.5, 2.0, 2.5, 3.0],
        "min_entry_confidence": [0.45, 0.6, 0.7],
        "take_profit_pct": [0.06, 0.08, 0.10],
        "momentum_lookback": [12, 20],
        "momentum_entry_threshold": [0.005],
        "rsi_overbought": [70.0, 75.0],
        "max_holding_bars": [48],
        "adx_threshold": [12.0],
    }),
    # 4×3×3×2×1×2×1×1 = 144

    ("vpin_sol", "vpin", "KRW-SOL", {
        "atr_stop_multiplier": [1.5, 2.0, 2.5, 3.0],
        "min_entry_confidence": [0.45, 0.6],
        "take_profit_pct": [0.04, 0.06, 0.08],
        "vpin_low_threshold": [0.40, 0.55],
        "vpin_high_threshold": [0.75, 0.85],
        "vpin_momentum_threshold": [0.0005],
        "max_holding_bars": [36],
        "bucket_count": [20],
    }),
    # 4×2×3×2×2×1×1×1 = 96

    ("vpin_eth", "vpin", "KRW-ETH", {
        "atr_stop_multiplier": [1.5, 2.0, 2.5, 3.0],
        "min_entry_confidence": [0.45, 0.6],
        "take_profit_pct": [0.04, 0.06, 0.08],
        "vpin_low_threshold": [0.35, 0.50],
        "vpin_high_threshold": [0.65, 0.80],
        "vpin_momentum_threshold": [0.0003],
        "max_holding_bars": [24],
        "bucket_count": [24],
    }),
    # 4×2×3×2×2×1×1×1 = 96

    ("volspike_btc", "volume_spike", "KRW-BTC", {
        "atr_stop_multiplier": [1.5, 2.0, 3.0],
        "min_entry_confidence": [0.45, 0.6],
        "take_profit_pct": [0.06, 0.08],
        "spike_mult": [2.0, 3.0],
        "min_body_ratio": [0.2, 0.3],
        "rsi_overbought": [72.0],
        "max_holding_bars": [36],
        "adx_threshold": [20.0],
    }),
    # 3×2×2×2×2×1×1×1 = 48
]
# TOTAL: 144 + 96 + 96 + 48 = 384 backtests


def run_wallet(
    name: str, strategy: str, symbol: str,
    grid: dict, candles: list[Candle],
) -> list[Result]:
    combos = grid_combos(grid)
    print(f"\n  {name}: {len(combos)} backtests on {symbol}")
    results = []
    for i, params in enumerate(combos):
        results.append(run_one(name, strategy, symbol, candles, params))
        if (i + 1) % 50 == 0:
            print(f"    ... {i + 1}/{len(combos)}")
    print(f"    Done: {len(results)} results")
    return results


def fmt(v: float, cap: float = 999) -> str:
    if abs(v) > cap or v != v:
        return "inf" if v > 0 else "-inf"
    return f"{v:.2f}"


def generate_report(all_results: dict[str, list[Result]], elapsed: float) -> str:
    lines = [
        "# P0 Backtest Parameter Optimization Report",
        "",
        f"Date: 2026-03-29 | Data: {DAYS}-day hourly Upbit | Runtime: {elapsed:.0f}s",
        f"Total backtests: {sum(len(r) for r in all_results.values())}",
        "",
        "## Targets: Sharpe >= 1.0, Win rate >= 55%, MDD <= 5%",
        "",
    ]

    summary_rows = []

    for wallet, results in all_results.items():
        if not results:
            continue

        ranked = sorted(results, key=score, reverse=True)
        best = ranked[0]
        meets = best.sharpe >= 1.0 and best.win_rate >= 55 and best.max_drawdown <= 5
        status = "MEETS TARGETS" if meets else "BELOW TARGETS"
        summary_rows.append((wallet, best, meets))

        lines.extend([
            f"## {wallet} ({best.strategy} / {best.symbol})",
            f"**{status}**",
            "",
            "### Best Parameters",
            "",
            "| Parameter | Value |",
            "| --- | ---: |",
            f"| ATR stop multiplier | **{best.params.get('atr_stop_multiplier', '—')}** |",
            f"| Min entry confidence | **{best.params.get('min_entry_confidence', '—')}** |",
            f"| Take profit | **{best.params.get('take_profit_pct', 0) * 100:.0f}%** |",
        ])
        skip = {"atr_stop_multiplier", "min_entry_confidence", "take_profit_pct", "stop_loss_pct"}
        for k, v in sorted(best.params.items()):
            if k not in skip:
                lines.append(f"| {k} | **{v}** |")

        lines.extend([
            "",
            "### Performance",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Sharpe | {fmt(best.sharpe)} |",
            f"| Sortino | {fmt(best.sortino)} |",
            f"| Calmar | {fmt(best.calmar)} |",
            f"| Return | {best.return_pct:+.2f}% |",
            f"| Win Rate | {best.win_rate:.1f}% |",
            f"| Max Drawdown | {best.max_drawdown:.2f}% |",
            f"| Profit Factor | {fmt(best.profit_factor)} |",
            f"| Trades | {best.trade_count} |",
            f"| Avg Duration | {best.avg_duration:.1f} bars |",
            "",
        ])

        if best.exit_reasons:
            lines.append("**Exit Reasons:** " + ", ".join(
                f"{k}: {v}" for k, v in sorted(best.exit_reasons.items(), key=lambda x: -x[1])
            ))
            lines.append("")

        # Top 5
        lines.extend([
            "### Top 5 Candidates",
            "",
            "| # | Sharpe | Ret% | WR% | MDD% | PF | Trades | ATR | Conf | TP% |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for i, r in enumerate(ranked[:5], 1):
            lines.append(
                f"| {i} | {fmt(r.sharpe)} | {r.return_pct:+.2f} | {r.win_rate:.1f} "
                f"| {r.max_drawdown:.2f} | {fmt(r.profit_factor)} | {r.trade_count} "
                f"| {r.params.get('atr_stop_multiplier', '—')} "
                f"| {r.params.get('min_entry_confidence', '—')} "
                f"| {r.params.get('take_profit_pct', 0) * 100:.0f} |"
            )
        lines.append("")

        # ATR sensitivity
        atr_groups: dict[float, list[Result]] = {}
        for r in results:
            atr_groups.setdefault(r.params.get("atr_stop_multiplier", 0), []).append(r)
        lines.extend([
            "### ATR Multiplier Sensitivity",
            "",
            "| ATR | Avg Sharpe | Avg WR% | Avg MDD% | Avg Ret% | Avg Trades |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for atr_val in sorted(atr_groups):
            rr = [x for x in atr_groups[atr_val] if x.trade_count >= 1]
            if not rr:
                continue
            n = len(rr)
            lines.append(
                f"| {atr_val} | {sum(x.sharpe for x in rr)/n:.2f} "
                f"| {sum(x.win_rate for x in rr)/n:.1f} "
                f"| {sum(x.max_drawdown for x in rr)/n:.2f} "
                f"| {sum(x.return_pct for x in rr)/n:+.2f} "
                f"| {sum(x.trade_count for x in rr)/n:.0f} |"
            )
        lines.append("")

        # Confidence sensitivity
        conf_groups: dict[float, list[Result]] = {}
        for r in results:
            conf_groups.setdefault(r.params.get("min_entry_confidence", 0), []).append(r)
        lines.extend([
            "### Confidence Threshold Sensitivity",
            "",
            "| Conf | Avg Sharpe | Avg WR% | Avg Trades |",
            "| ---: | ---: | ---: | ---: |",
        ])
        for cv in sorted(conf_groups):
            rr = [x for x in conf_groups[cv] if x.trade_count >= 1]
            if not rr:
                lines.append(f"| {cv} | — | — | 0 |")
                continue
            n = len(rr)
            lines.append(
                f"| {cv} | {sum(x.sharpe for x in rr)/n:.2f} "
                f"| {sum(x.win_rate for x in rr)/n:.1f} "
                f"| {sum(x.trade_count for x in rr)/n:.0f} |"
            )
        lines.append("")

    # Overall summary
    lines.extend([
        "---",
        "## Summary",
        "",
        "| Wallet | Strategy | Sharpe | WR% | MDD% | Ret% | Meets? |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ])
    for w, b, m in summary_rows:
        lines.append(
            f"| {w} | {b.strategy} | {fmt(b.sharpe)} | {b.win_rate:.1f} "
            f"| {b.max_drawdown:.2f} | {b.return_pct:+.2f} | {'YES' if m else 'NO'} |"
        )
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    t0 = time.time()
    total_bt = sum(
        len(list(itertools.product(*g.values()))) for _, _, _, g in WALLETS
    )
    print(f"\n{'#' * 70}")
    print(f"  P0 OPTIMIZATION — {DAYS}d data, {len(WALLETS)} wallets, ~{total_bt} backtests")
    print(f"{'#' * 70}")

    # Fetch candles
    needed = {s for _, _, s, _ in WALLETS}
    candles: dict[str, list[Candle]] = {}
    for sym in sorted(needed):
        print(f"Fetching {sym} ({DAYS}d)...", end=" ")
        c = fetch(sym)
        print(f"{len(c)} candles")
        candles[sym] = c

    # Run
    all_results: dict[str, list[Result]] = {}
    for name, strat, sym, grid in WALLETS:
        print(f"\n{'=' * 50}")
        results = run_wallet(name, strat, sym, grid, candles[sym])
        all_results[name] = results
        top = sorted(results, key=score, reverse=True)[:3]
        if top:
            b = top[0]
            print(f"  BEST: Sharpe={fmt(b.sharpe)} WR={b.win_rate:.1f}% "
                  f"MDD={b.max_drawdown:.2f}% Ret={b.return_pct:+.2f}% T={b.trade_count}")

    elapsed = time.time() - t0

    os.makedirs("artifacts", exist_ok=True)

    # Report
    report = generate_report(all_results, elapsed)
    Path("artifacts/backtest-optimization-report.md").write_text(report, encoding="utf-8")
    print("\n  Report: artifacts/backtest-optimization-report.md")

    # JSON
    json_out: dict = {}
    for w, results in all_results.items():
        ranked = sorted(results, key=score, reverse=True)[:10]
        json_out[w] = {
            "total": len(results),
            "top10": [
                {
                    "score": round(score(r), 4),
                    "sharpe": round(r.sharpe, 4),
                    "sortino": round(r.sortino, 4),
                    "return_pct": round(r.return_pct, 4),
                    "win_rate": round(r.win_rate, 2),
                    "max_drawdown": round(r.max_drawdown, 4),
                    "profit_factor": round(r.profit_factor, 4),
                    "trade_count": r.trade_count,
                    "params": r.params,
                    "exit_reasons": r.exit_reasons,
                }
                for r in ranked
            ],
        }
    Path("artifacts/optimization-p0-results.json").write_text(
        json.dumps(json_out, indent=2, default=str), encoding="utf-8",
    )
    print("  JSON: artifacts/optimization-p0-results.json")
    print(f"\n  Done in {elapsed:.0f}s — {total_bt} backtests")


if __name__ == "__main__":
    main()
