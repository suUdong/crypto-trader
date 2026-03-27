#!/usr/bin/env python3
"""Run fixed-parameter walk-forward validation across the strategy universe."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from crypto_trader.backtest.candle_cache import fetch_upbit_candles  # noqa: E402
from crypto_trader.backtest.walk_forward import (  # noqa: E402
    WalkForwardReport,
    WalkForwardValidator,
)
from crypto_trader.config import (  # noqa: E402
    BacktestConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
)
from crypto_trader.models import Candle  # noqa: E402
from crypto_trader.wallet import create_strategy  # noqa: E402

SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
STRATEGIES = [
    "momentum",
    "momentum_pullback",
    "mean_reversion",
    "composite",
    "kimchi_premium",
    "obi",
    "vpin",
    "volatility_breakout",
]
INTERVAL = "minute60"


def _setup_kimchi_premium_mock(strategy: Any, candles: list[Candle]) -> None:
    if len(candles) < 50:
        return
    closes = [candle.close for candle in candles]
    ma50 = sum(closes[-50:]) / 50.0
    if ma50 <= 0:
        return
    strategy._cached_premium = (closes[-1] - ma50) / ma50
    strategy._binance.get_btc_usdt_price.return_value = None
    strategy._fx.get_usd_krw_rate.return_value = None


def _aggregate_strategy_reports(
    strategy: str,
    reports: list[WalkForwardReport],
) -> dict[str, Any] | None:
    valid_reports = [report for report in reports if report.total_folds > 0]
    if not valid_reports:
        return None

    count = len(valid_reports)
    passed_count = sum(1 for report in valid_reports if report.passed)
    avg_test_return = sum(report.avg_test_return_pct for report in valid_reports) / count
    avg_train_return = sum(report.avg_train_return_pct for report in valid_reports) / count
    avg_efficiency = sum(report.avg_efficiency_ratio for report in valid_reports) / count
    avg_oos_sharpe = sum(report.avg_oos_sharpe for report in valid_reports) / count
    avg_oos_profit_factor = sum(report.avg_oos_profit_factor for report in valid_reports) / count
    avg_oos_win_rate = sum(report.oos_win_rate for report in valid_reports) / count
    total_trades = sum(
        len(fold.test_result.trade_log)
        for report in valid_reports
        for fold in report.folds
    )
    validated = passed_count >= (count / 2)

    return {
        "strategy": strategy,
        "candidates_tested": 1,
        "candidates_validated": 1 if validated else 0,
        "best": {
            "params": {},
            "avg_sharpe": avg_oos_sharpe,
            "avg_return_pct": avg_test_return,
            "avg_profit_factor": avg_oos_profit_factor,
            "total_trades": total_trades,
            "validated": validated,
            "wf_avg_efficiency_ratio": avg_efficiency,
            "wf_oos_win_rate": avg_oos_win_rate,
            "avg_train_return_pct": avg_train_return,
        },
    }


def write_markdown_report(output_path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Fixed-Parameter Walk-Forward Summary",
        "",
        f"- Dataset: `{payload['dataset_days']}` days",
        f"- Symbols: `{', '.join(payload['symbols'])}`",
        f"- Validated strategies: `{payload['validated_count']}`",
        "",
        (
            "| Strategy | WF Sharpe | WF Return | Train Return | "
            "OOS Win Rate | Efficiency | Validated |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["strategies"]:
        best = row.get("best")
        if not isinstance(best, dict):
            continue
        lines.append(
            f"| {row['strategy']} | {float(best['avg_sharpe']):.2f} | "
            f"{float(best['avg_return_pct']):+.2f}% | "
            f"{float(best.get('avg_train_return_pct', 0.0)):+.2f}% | "
            f"{float(best['wf_oos_win_rate']) * 100:.1f}% | "
            f"{float(best['wf_avg_efficiency_ratio']):.2f} | "
            f"{'YES' if bool(best['validated']) else 'NO'} |"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fixed-parameter walk-forward validation across all strategies.",
    )
    parser.add_argument("days", nargs="?", type=int, default=90)
    parser.add_argument("--cache-dir", dest="cache_dir")
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument(
        "--json-out",
        dest="json_out",
        default="artifacts/walk-forward-90d/grid-wf-summary.json",
    )
    parser.add_argument(
        "--report-out",
        dest="report_out",
        default="artifacts/walk-forward-90d/report.md",
    )
    args = parser.parse_args()

    if args.cache_dir:
        os.environ["CT_CANDLE_CACHE_DIR"] = args.cache_dir

    candles_by_symbol = {
        symbol: fetch_upbit_candles(
            symbol,
            args.days,
            interval=INTERVAL,
            cache_dir=os.environ.get("CT_CANDLE_CACHE_DIR"),
        )
        for symbol in SYMBOLS
    }
    candles_by_symbol = {
        symbol: candles for symbol, candles in candles_by_symbol.items() if len(candles) >= 100
    }
    if not candles_by_symbol:
        raise RuntimeError("No candle data available for walk-forward validation.")

    validator = WalkForwardValidator(
        backtest_config=BacktestConfig(),
        risk_config=RiskConfig(),
        n_folds=args.folds,
        train_pct=0.7,
    )
    strategy_config = StrategyConfig()
    regime_config = RegimeConfig()

    strategies_payload: list[dict[str, Any]] = []
    print(f"\n{'=' * 80}")
    print(f"  FIXED WALK-FORWARD ALL ({args.days}d, folds={args.folds})")
    print(f"{'=' * 80}")

    for strategy in STRATEGIES:
        print(f"\nRunning {strategy}...")
        reports: list[WalkForwardReport] = []
        for symbol, candles in candles_by_symbol.items():
            def _factory(
                strategy_name: str = strategy,
                strategy_candles: list[Candle] = candles,
            ) -> Any:
                built: Any = create_strategy(strategy_name, strategy_config, regime_config)
                if strategy_name == "kimchi_premium":
                    from unittest.mock import MagicMock

                    built._binance = MagicMock()
                    built._fx = MagicMock()
                    _setup_kimchi_premium_mock(built, strategy_candles)
                return built

            report = validator.validate(
                strategy_factory=_factory,
                candles=candles,
                symbol=symbol,
                strategy_name=strategy,
            )
            reports.append(report)
        summary = _aggregate_strategy_reports(strategy, reports)
        if summary is None:
            continue
        strategies_payload.append(summary)
        best = summary["best"]
        print(
            f"  wf_sharpe={float(best['avg_sharpe']):.2f} "
            f"wf_return={float(best['avg_return_pct']):+.2f}% "
            f"validated={'YES' if bool(best['validated']) else 'NO'}"
        )

    ranked = [row for row in strategies_payload if isinstance(row.get("best"), dict)]

    def _rank_key(row: dict[str, Any]) -> tuple[float, float, int]:
        best = row["best"]
        return (
            float(best["avg_sharpe"]),
            float(best["avg_return_pct"]),
            int(best["total_trades"]),
        )

    validated_rows = [row for row in ranked if bool(row["best"]["validated"])]
    payload = {
        "dataset_days": args.days,
        "symbols": sorted(candles_by_symbol),
        "strategies": strategies_payload,
        "validated_count": len(validated_rows),
        "best_validated": max(validated_rows, key=_rank_key) if validated_rows else None,
        "best_research_candidate": max(ranked, key=_rank_key) if ranked else None,
    }

    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown_report(Path(args.report_out), payload)

    print(f"\nSummary written to {json_path}")
    print(f"Report written to {args.report_out}")


if __name__ == "__main__":
    main()
