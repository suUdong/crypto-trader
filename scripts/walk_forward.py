#!/usr/bin/env python3
"""Walk-forward validation for strategy tuning on cached/live candle data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from crypto_trader.models import Candle  # noqa: E402
from scripts.auto_tune import (  # noqa: E402
    DEFAULT_STRATEGIES,
    SYMBOLS,
    TuneResult,
    collect_baseline_results,
    evaluate_strategy_params,
    fetch_candles,
    tune_strategy,
    write_optimized_toml,
)


@dataclass
class FoldResult:
    fold_index: int
    strategy: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    tuned_params: dict[str, float | int]
    tuned_risk_params: dict[str, float]
    train_sharpe: float
    train_return_pct: float
    train_mdd_pct: float
    test_sharpe: float
    test_return_pct: float
    test_mdd_pct: float
    test_win_rate: float
    test_profit_factor: float
    test_total_trades: int
    candidate_rank: int


def build_walk_forward_windows(
    candles_by_symbol: dict[str, list[Candle]],
    train_bars: int,
    test_bars: int,
) -> list[tuple[dict[str, list[Candle]], dict[str, list[Candle]]]]:
    """Build rolling train/test windows using the shared shortest history."""
    if not candles_by_symbol:
        return []

    min_len = min(len(candles) for candles in candles_by_symbol.values())
    if min_len < train_bars + test_bars:
        return []

    windows: list[tuple[dict[str, list[Candle]], dict[str, list[Candle]]]] = []
    start = 0
    while start + train_bars + test_bars <= min_len:
        train_slice: dict[str, list[Candle]] = {}
        test_slice: dict[str, list[Candle]] = {}
        for symbol, candles in candles_by_symbol.items():
            aligned = candles[-min_len:]
            train_slice[symbol] = aligned[start : start + train_bars]
            test_slice[symbol] = aligned[start + train_bars : start + train_bars + test_bars]
        windows.append((train_slice, test_slice))
        start += test_bars

    return windows


def summarize_fold_with_boundaries(
    fold_index: int,
    strategy: str,
    tuned_result,
    train_slice: dict[str, list[Candle]],
    test_slice: dict[str, list[Candle]],
    test_evaluation: dict[str, object],
) -> FoldResult:
    symbol = next(iter(train_slice))
    return FoldResult(
        fold_index=fold_index,
        strategy=strategy,
        train_start=train_slice[symbol][0].timestamp.isoformat(),
        train_end=train_slice[symbol][-1].timestamp.isoformat(),
        test_start=test_slice[symbol][0].timestamp.isoformat(),
        test_end=test_slice[symbol][-1].timestamp.isoformat(),
        tuned_params=tuned_result.params,
        tuned_risk_params=tuned_result.risk_params,
        train_sharpe=tuned_result.avg_sharpe,
        train_return_pct=tuned_result.avg_return_pct,
        train_mdd_pct=tuned_result.avg_mdd_pct,
        test_sharpe=float(test_evaluation["avg_sharpe"]),
        test_return_pct=float(test_evaluation["avg_return_pct"]),
        test_mdd_pct=float(test_evaluation["avg_mdd_pct"]),
        test_win_rate=float(test_evaluation["avg_win_rate"]),
        test_profit_factor=float(test_evaluation["avg_profit_factor"]),
        test_total_trades=int(test_evaluation["total_trades"]),
        candidate_rank=tuned_result.candidate_rank,
    )


def aggregate_fold_results(folds: list[FoldResult]) -> dict[str, float | int]:
    """Aggregate walk-forward folds into one summary row."""
    if not folds:
        return {
            "fold_count": 0,
            "avg_train_sharpe": 0.0,
            "avg_test_sharpe": 0.0,
            "avg_test_return_pct": 0.0,
            "avg_test_mdd_pct": 0.0,
            "avg_test_win_rate": 0.0,
            "avg_test_profit_factor": 0.0,
            "total_test_trades": 0,
        }

    count = len(folds)
    return {
        "fold_count": count,
        "avg_train_sharpe": sum(fold.train_sharpe for fold in folds) / count,
        "avg_test_sharpe": sum(fold.test_sharpe for fold in folds) / count,
        "avg_test_return_pct": sum(fold.test_return_pct for fold in folds) / count,
        "avg_test_mdd_pct": sum(fold.test_mdd_pct for fold in folds) / count,
        "avg_test_win_rate": sum(fold.test_win_rate for fold in folds) / count,
        "avg_test_profit_factor": sum(fold.test_profit_factor for fold in folds) / count,
        "total_test_trades": sum(fold.test_total_trades for fold in folds),
    }


def write_walk_forward_json(
    output_path: str,
    folds_by_strategy: dict[str, list[FoldResult]],
    baseline_results: list[dict[str, object]],
    total_days: int,
    train_days: int,
    test_days: int,
) -> None:
    payload = {
        "total_days": total_days,
        "train_days": train_days,
        "test_days": test_days,
        "baseline_results": baseline_results,
        "strategies": {
            strategy: {
                "aggregate": aggregate_fold_results(folds),
                "folds": [asdict(fold) for fold in folds],
            }
            for strategy, folds in folds_by_strategy.items()
        },
    }
    Path(output_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Walk-forward results written to: {output_path}")


def select_validated_strategy(
    folds_by_strategy: dict[str, list[FoldResult]],
) -> tuple[str, FoldResult, dict[str, float | int]] | None:
    """Pick the best strategy by aggregate out-of-sample Sharpe and latest fold params."""
    ranked: list[tuple[str, FoldResult, dict[str, float | int]]] = []
    for strategy, folds in folds_by_strategy.items():
        if not folds:
            continue
        aggregate = aggregate_fold_results(folds)
        latest_fold = max(folds, key=lambda fold: fold.fold_index)
        ranked.append((strategy, latest_fold, aggregate))

    if not ranked:
        return None

    return max(
        ranked,
        key=lambda item: (
            float(item[2]["avg_test_sharpe"]),
            float(item[2]["avg_test_return_pct"]),
            int(item[2]["total_test_trades"]),
        ),
    )


def validation_gate_status(
    aggregate: dict[str, float | int],
    min_test_sharpe: float,
    min_test_return_pct: float,
    min_total_trades: int,
) -> tuple[bool, list[str]]:
    """Check whether a walk-forward aggregate is strong enough to deploy."""
    reasons: list[str] = []
    if float(aggregate["avg_test_sharpe"]) <= min_test_sharpe:
        reasons.append(
            f"avg_test_sharpe {float(aggregate['avg_test_sharpe']):.2f} <= {min_test_sharpe:.2f}"
        )
    if float(aggregate["avg_test_return_pct"]) <= min_test_return_pct:
        reasons.append(
            f"avg_test_return_pct {float(aggregate['avg_test_return_pct']):+.2f}% <= "
            f"{min_test_return_pct:+.2f}%"
        )
    if int(aggregate["total_test_trades"]) < min_total_trades:
        reasons.append(
            f"total_test_trades {int(aggregate['total_test_trades'])} < {min_total_trades}"
        )
    return len(reasons) == 0, reasons


def walk_forward_efficiency_ratio(aggregate: dict[str, float | int]) -> float:
    """Approximate generalization efficiency via test/train Sharpe ratio."""
    train_sharpe = float(aggregate["avg_train_sharpe"])
    test_sharpe = float(aggregate["avg_test_sharpe"])
    if train_sharpe == 0.0:
        return 0.0 if test_sharpe == 0.0 else float("inf")
    return test_sharpe / train_sharpe


def write_grid_summary_json(
    output_path: str,
    folds_by_strategy: dict[str, list[FoldResult]],
    total_days: int,
    symbols: list[str],
    top_n: int,
    gate_thresholds: tuple[float, float, int],
) -> None:
    """Write a legacy-compatible walk-forward summary for downstream reporting."""
    min_test_sharpe, min_test_return_pct, min_total_trades = gate_thresholds
    strategy_rows: list[dict[str, object]] = []

    for strategy, folds in sorted(folds_by_strategy.items()):
        aggregate = aggregate_fold_results(folds)
        gate_passed, _ = validation_gate_status(
            aggregate,
            min_test_sharpe,
            min_test_return_pct,
            min_total_trades,
        )
        latest_fold = max(folds, key=lambda fold: fold.fold_index) if folds else None
        best = None
        if latest_fold is not None:
            best = {
                "params": latest_fold.tuned_params,
                "risk_params": latest_fold.tuned_risk_params,
                "avg_sharpe": float(aggregate["avg_test_sharpe"]),
                "avg_return_pct": float(aggregate["avg_test_return_pct"]),
                "total_trades": int(aggregate["total_test_trades"]),
                "avg_profit_factor": float(aggregate["avg_test_profit_factor"]),
                "validated": gate_passed,
                "wf_avg_efficiency_ratio": walk_forward_efficiency_ratio(aggregate),
                "wf_oos_win_rate": float(aggregate["avg_test_win_rate"]) / 100.0,
            }

        strategy_rows.append(
            {
                "strategy": strategy,
                "candidates_tested": top_n,
                "candidates_validated": 1 if gate_passed else 0,
                "best": best,
                "aggregate": aggregate,
            }
        )

    validated_rows = [
        row
        for row in strategy_rows
        if isinstance(row.get("best"), dict) and row["best"]["validated"]
    ]
    ranked_rows = [
        row
        for row in strategy_rows
        if isinstance(row.get("best"), dict)
    ]

    def _rank_key(row: dict[str, object]) -> tuple[float, float, int]:
        best = row["best"]
        assert isinstance(best, dict)
        return (
            float(best["avg_sharpe"]),
            float(best["avg_return_pct"]),
            int(best["total_trades"]),
        )

    payload = {
        "dataset_days": total_days,
        "symbols": symbols,
        "strategies": strategy_rows,
        "validated_count": len(validated_rows),
        "best_validated": max(validated_rows, key=_rank_key) if validated_rows else None,
        "best_research_candidate": max(ranked_rows, key=_rank_key) if ranked_rows else None,
    }
    Path(output_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Walk-forward summary written to: {output_path}")


def write_walk_forward_markdown(
    output_path: str,
    folds_by_strategy: dict[str, list[FoldResult]],
    total_days: int,
    train_days: int,
    test_days: int,
    selection: tuple[str, FoldResult, dict[str, float | int]] | None,
    gate_result: tuple[bool, list[str]] | None,
    gate_thresholds: tuple[float, float, int],
) -> None:
    lines = [
        "# Walk-Forward Validation Results",
        "",
        f"- Total days: `{total_days}`",
        f"- Train window: `{train_days}` days",
        f"- Test window: `{test_days}` days",
        "",
        (
            "| Strategy | Folds | Avg Train Sharpe | Avg Test Sharpe | "
            "Avg Test Return | Avg Test MDD | Total Test Trades |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for strategy, folds in sorted(folds_by_strategy.items()):
        aggregate = aggregate_fold_results(folds)
        lines.append(
            f"| {strategy} | {int(aggregate['fold_count'])} | "
            f"{float(aggregate['avg_train_sharpe']):.2f} | "
            f"{float(aggregate['avg_test_sharpe']):.2f} | "
            f"{float(aggregate['avg_test_return_pct']):+.2f}% | "
            f"{float(aggregate['avg_test_mdd_pct']):.2f}% | "
            f"{int(aggregate['total_test_trades'])} |"
        )

    if selection is not None:
        strategy, latest_fold, aggregate = selection
        gate_passed = gate_result[0] if gate_result is not None else False
        lines.extend(
            [
                "",
                "## Validation Decision",
                "",
                f"- Top candidate strategy: `{strategy}`",
                (
                    "- Selection basis: highest aggregate out-of-sample Sharpe "
                    f"(`{float(aggregate['avg_test_sharpe']):.2f}`)"
                ),
                f"- Gate status: `{'PASS' if gate_passed else 'FAIL'}`",
                (
                    "- Gate thresholds: "
                    f"`avg_test_sharpe > {gate_thresholds[0]:.2f}`, "
                    f"`avg_test_return_pct > {gate_thresholds[1]:+.2f}%`, "
                    f"`total_test_trades >= {gate_thresholds[2]}`"
                ),
            ]
        )
        if gate_result is not None and gate_result[1]:
            lines.append(f"- Gate reasons: `{'; '.join(gate_result[1])}`")
        if gate_passed:
            lines.extend(
                [
                    f"- Latest deployment fold: `#{latest_fold.fold_index}`",
                    f"- Latest fold test return: `{latest_fold.test_return_pct:+.2f}%`",
                    f"- Latest fold tuned params: `{latest_fold.tuned_params}`",
                    f"- Latest fold tuned risk: `{latest_fold.tuned_risk_params}`",
                ]
            )
        else:
            lines.append("- Validated config output: `skipped`")

    lines.append("")
    lines.append("## Fold Detail")
    for strategy, folds in sorted(folds_by_strategy.items()):
        lines.append("")
        lines.append(f"### {strategy}")
        if not folds:
            lines.append("- No valid folds")
            continue
        for fold in folds:
            lines.append(
                f"- Fold #{fold.fold_index}: train_sharpe={fold.train_sharpe:.2f}, "
                f"test_sharpe={fold.test_sharpe:.2f}, "
                f"test_return={fold.test_return_pct:+.2f}%, "
                f"test_mdd={fold.test_mdd_pct:.2f}%, "
                f"trades={fold.test_total_trades}"
            )

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Walk-forward report written to: {output_path}")


def write_validated_config(
    output_path: str,
    selection: tuple[str, FoldResult, dict[str, float | int]] | None,
    base_toml: str,
    gate_passed: bool,
) -> None:
    if selection is None:
        return
    if not gate_passed:
        print("Validated config not written because the validation gate failed.")
        return

    strategy, latest_fold, aggregate = selection
    result = TuneResult(
        strategy=strategy,
        params=latest_fold.tuned_params,
        risk_params=latest_fold.tuned_risk_params,
        avg_return_pct=float(aggregate["avg_test_return_pct"]),
        avg_sharpe=float(aggregate["avg_test_sharpe"]),
        avg_mdd_pct=float(aggregate["avg_test_mdd_pct"]),
        avg_win_rate=0.0,
        avg_profit_factor=float(aggregate["avg_test_profit_factor"]),
        total_trades=int(aggregate["total_test_trades"]),
        best_score=float(aggregate["avg_test_sharpe"]),
        candidate_rank=latest_fold.candidate_rank,
        top_candidates=[],
        per_symbol={},
    )
    write_optimized_toml([result], output_path, base_toml=base_toml)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run walk-forward validation on tuned strategies.")
    parser.add_argument("total_days", nargs="?", type=int, default=120)
    parser.add_argument("--train-days", dest="train_days", type=int, default=60)
    parser.add_argument("--test-days", dest="test_days", type=int, default=15)
    parser.add_argument("--top-n", dest="top_n", type=int, default=3)
    parser.add_argument("--json-out", dest="json_out", default="artifacts/walk-forward.json")
    parser.add_argument(
        "--grid-summary-out",
        dest="grid_summary_out",
        default="artifacts/walk-forward-90d/grid-wf-summary.json",
    )
    parser.add_argument("--report-out", dest="report_out", default="docs/walk-forward-results.md")
    parser.add_argument(
        "--validated-config-out",
        dest="validated_config_out",
        default="config/validated.toml",
    )
    parser.add_argument("--base-toml", dest="base_toml", default="config/optimized.toml")
    parser.add_argument("--min-test-sharpe", dest="min_test_sharpe", type=float, default=0.0)
    parser.add_argument(
        "--min-test-return-pct",
        dest="min_test_return_pct",
        type=float,
        default=0.0,
    )
    parser.add_argument("--min-total-trades", dest="min_total_trades", type=int, default=20)
    parser.add_argument("--cache-dir", dest="cache_dir")
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=DEFAULT_STRATEGIES,
        help="Strategies to validate.",
    )
    args = parser.parse_args()

    if args.cache_dir:
        os.environ["CT_CANDLE_CACHE_DIR"] = args.cache_dir

    total_days = args.total_days
    train_bars = args.train_days * 24
    test_bars = args.test_days * 24
    print(f"\n{'=' * 80}")
    print(
        f"  WALK-FORWARD VALIDATION ({total_days}d total / "
        f"{args.train_days}d train / {args.test_days}d test)"
    )
    print(f"{'=' * 80}")

    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ({total_days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, total_days)
        print(f"{len(candles)} candles")
        if len(candles) >= train_bars + test_bars:
            candles_by_symbol[symbol] = candles

    windows = build_walk_forward_windows(candles_by_symbol, train_bars, test_bars)
    if not windows:
        raise RuntimeError("Insufficient data for the requested walk-forward windows.")

    baseline_results = collect_baseline_results(args.strategies, candles_by_symbol)
    folds_by_strategy: dict[str, list[FoldResult]] = {strategy: [] for strategy in args.strategies}

    for strategy in args.strategies:
        print(f"\n{'─' * 60}")
        print(f"  Walk-forward: {strategy}")
        print(f"{'─' * 60}")
        for fold_index, (train_slice, test_slice) in enumerate(windows, start=1):
            print(f"  Fold #{fold_index}: tuning on train window")
            tuned = tune_strategy(strategy, train_slice, top_n=args.top_n, verbose=False)
            if tuned is None:
                continue
            test_evaluation = evaluate_strategy_params(
                strategy,
                tuned.params,
                tuned.risk_params,
                test_slice,
            )
            if test_evaluation is None:
                continue
            fold = summarize_fold_with_boundaries(
                fold_index,
                strategy,
                tuned,
                train_slice,
                test_slice,
                test_evaluation,
            )
            folds_by_strategy[strategy].append(fold)
            print(
                f"    train_sharpe={fold.train_sharpe:.2f} "
                f"test_sharpe={fold.test_sharpe:.2f} "
                f"test_return={fold.test_return_pct:+.2f}%"
            )

    print(f"\n{'=' * 80}")
    print("  WALK-FORWARD SUMMARY")
    print(f"{'=' * 80}")
    print(
        f"\n  {'Strategy':<20} {'Folds':>5} {'TrainSharpe':>12} "
        f"{'TestSharpe':>11} {'TestRet%':>10} {'TestMDD%':>9} {'Trades':>8}"
    )
    print(f"  {'─' * 81}")
    for strategy in args.strategies:
        aggregate = aggregate_fold_results(folds_by_strategy[strategy])
        print(
            f"  {strategy:<20} {int(aggregate['fold_count']):>5} "
            f"{float(aggregate['avg_train_sharpe']):>11.2f} "
            f"{float(aggregate['avg_test_sharpe']):>10.2f} "
            f"{float(aggregate['avg_test_return_pct']):>+9.2f}% "
            f"{float(aggregate['avg_test_mdd_pct']):>8.2f}% "
            f"{int(aggregate['total_test_trades']):>8}"
        )

    selection = select_validated_strategy(folds_by_strategy)
    gate_result: tuple[bool, list[str]] | None = None
    if selection is not None:
        gate_result = validation_gate_status(
            selection[2],
            args.min_test_sharpe,
            args.min_test_return_pct,
            args.min_total_trades,
        )
        print(
            f"\nTop candidate strategy: {selection[0]} "
            f"(avg_test_sharpe={float(selection[2]['avg_test_sharpe']):.2f})"
        )
        print(f"Validation gate: {'PASS' if gate_result[0] else 'FAIL'}")
        if gate_result[1]:
            print(f"Gate reasons: {'; '.join(gate_result[1])}")

    write_walk_forward_json(
        args.json_out,
        folds_by_strategy,
        baseline_results,
        total_days,
        args.train_days,
        args.test_days,
    )
    write_walk_forward_markdown(
        args.report_out,
        folds_by_strategy,
        total_days,
        args.train_days,
        args.test_days,
        selection,
        gate_result,
        (args.min_test_sharpe, args.min_test_return_pct, args.min_total_trades),
    )
    write_grid_summary_json(
        args.grid_summary_out,
        folds_by_strategy,
        total_days,
        sorted(candles_by_symbol),
        args.top_n,
        (args.min_test_sharpe, args.min_test_return_pct, args.min_total_trades),
    )
    write_validated_config(
        args.validated_config_out,
        selection,
        args.base_toml,
        gate_result[0] if gate_result is not None else False,
    )


if __name__ == "__main__":
    main()
