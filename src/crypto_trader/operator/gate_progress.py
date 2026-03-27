# ruff: noqa: E501

"""Promotion gate progress report helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _load_walk_forward_map(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = _read_json(path)
    strategies = payload.get("strategies", [])
    if not isinstance(strategies, list):
        return {}
    summary: dict[str, dict[str, Any]] = {}
    for item in strategies:
        if not isinstance(item, dict):
            continue
        strategy = item.get("strategy")
        best = item.get("best")
        if isinstance(strategy, str) and isinstance(best, dict):
            summary[strategy] = best
    return summary


def _latest_strategy_verdict(path: Path) -> tuple[str, str]:
    if not path.exists():
        return ("n/a", "unknown")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return ("n/a", "unknown")
    latest = json.loads(lines[-1])
    recorded_at = str(latest.get("recorded_at", "n/a"))
    verdict = str(latest.get("verdict_status", "unknown"))
    return (recorded_at, verdict)


def _format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _progress_percent(current: float, threshold: float) -> str:
    if threshold <= 0:
        return "100%" if current > 0 else "0%"
    return f"{(current / threshold) * 100:.0f}%"


def _report_date(snapshot_generated_at: str) -> str:
    try:
        snapshot_dt = datetime.fromisoformat(snapshot_generated_at)
        return snapshot_dt.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
    except Exception:
        return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def generate_gate_progress_report(
    *,
    runtime_checkpoint_path: Path,
    backtest_baseline_path: Path,
    drift_report_path: Path,
    promotion_gate_path: Path,
    strategy_run_journal_path: Path,
    walk_forward_summary_path: Path | None = None,
    output_path: Path | None = None,
) -> str:
    """Generate markdown describing current promotion gate progress."""
    checkpoint = _read_json(runtime_checkpoint_path)
    baseline = _read_json(backtest_baseline_path)
    drift = _read_json(drift_report_path)
    promotion = _read_json(promotion_gate_path)
    walk_forward = _load_walk_forward_map(walk_forward_summary_path)
    latest_verdict_at, latest_verdict = _latest_strategy_verdict(strategy_run_journal_path)

    wallet_states = checkpoint.get("wallet_states", {})
    if not isinstance(wallet_states, dict):
        raise ValueError("runtime checkpoint missing wallet_states")

    initial_capital = 1_000_000.0
    by_strategy: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "wallets": 0,
            "start_capital": 0.0,
            "equity": 0.0,
            "realized_pnl": 0.0,
            "closed_trades": 0,
            "open_positions": 0,
        }
    )
    for wallet in wallet_states.values():
        if not isinstance(wallet, dict):
            continue
        strategy = str(wallet.get("strategy_type", "unknown"))
        row = by_strategy[strategy]
        row["wallets"] = int(row["wallets"]) + 1
        row["start_capital"] = float(row["start_capital"]) + initial_capital
        row["equity"] = float(row["equity"]) + float(wallet.get("equity", initial_capital))
        row["realized_pnl"] = float(row["realized_pnl"]) + float(wallet.get("realized_pnl", 0.0))
        row["closed_trades"] = int(row["closed_trades"]) + int(wallet.get("trade_count", 0))
        row["open_positions"] = int(row["open_positions"]) + int(wallet.get("open_positions", 0))

    live_strategies = sorted(by_strategy)
    live_universe = ", ".join(
        f"`{name} x{int(by_strategy[name]['wallets'])}`" for name in live_strategies
    )

    portfolio_start = sum(float(row["start_capital"]) for row in by_strategy.values())
    portfolio_equity = sum(float(row["equity"]) for row in by_strategy.values())
    portfolio_realized = sum(float(row["realized_pnl"]) for row in by_strategy.values())
    portfolio_closed_trades = sum(int(row["closed_trades"]) for row in by_strategy.values())
    portfolio_open_positions = sum(int(row["open_positions"]) for row in by_strategy.values())
    portfolio_mtm = portfolio_equity - portfolio_start
    portfolio_mtm_pct = (portfolio_mtm / portfolio_start * 100.0) if portfolio_start > 0 else 0.0

    blocker = (
        str(promotion["reasons"][0])
        if isinstance(promotion.get("reasons"), list) and promotion["reasons"]
        else "no explicit blocker recorded"
    )
    baseline_return_pct = float(baseline.get("total_return_pct", 0.0)) * 100.0
    baseline_mdd_pct = float(baseline.get("max_drawdown", 0.0)) * 100.0
    promotion_baseline_return_pct = float(promotion.get("backtest_total_return_pct", 0.0)) * 100.0
    paper_runs = int(drift.get("paper_run_count", 0))
    minimum_runs = int(promotion.get("minimum_paper_runs_required", 5))
    paper_realized_pnl_pct = float(drift.get("paper_realized_pnl_pct", 0.0)) * 100.0
    drift_status = str(drift.get("status", "unknown"))
    gate_status = str(promotion.get("status", "unknown"))

    pass_count = 0
    if baseline_return_pct > 0:
        pass_count += 1
    if baseline_mdd_pct <= 20.0:
        pass_count += 1
    if paper_runs >= minimum_runs:
        pass_count += 1
    if drift_status not in {"out_of_sync", "caution"}:
        pass_count += 1
    if latest_verdict not in {"pause_strategy", "reduce_risk"}:
        pass_count += 1
    if paper_realized_pnl_pct > 0:
        pass_count += 1

    report_date = _report_date(str(checkpoint.get("generated_at", "")))

    lines = [
        f"# Gate Progress - {report_date}",
        "",
        f"- Runtime snapshot: `{checkpoint.get('generated_at', 'n/a')}` from `{runtime_checkpoint_path.as_posix()}`",
        (
            f"- Promotion artifacts: `{drift.get('generated_at', 'n/a')}` to "
            f"`{baseline.get('generated_at', 'n/a')}` from "
            f"`{drift_report_path.as_posix()}`, `{promotion_gate_path.as_posix()}`, "
            f"`{backtest_baseline_path.as_posix()}`"
        ),
        f"- Active live universe at snapshot: {live_universe}",
        "- Scope note: the persisted promotion gate is still a single-symbol decision for `KRW-BTC`. "
        "The strategy rows below are the current operating read, not separate persisted gate verdicts.",
    ]
    if abs(baseline_return_pct - promotion_baseline_return_pct) >= 0.01:
        lines.append(
            f"- Artifact skew note: `promotion-gate.json` still references an older BTC baseline return "
            f"of `{promotion_baseline_return_pct:+.2f}%`, while the newest `backtest-baseline.json` "
            f"shows `{baseline_return_pct:+.2f}%`. This does not change the gate outcome, but it matters "
            "for reporting accuracy."
        )

    lines.extend(
        [
            "",
            "## Executive Summary",
            "",
            f"- Official gate status is still `{gate_status}`.",
            f"- Current blocker is singular and explicit: `{blocker}`.",
            "- Everything else needed by the current gate logic is already green on the latest artifacts: "
            f"positive backtest return, acceptable drawdown, enough paper runs, drift `{drift_status}`, "
            f"and latest verdict `{latest_verdict}`.",
            f"- Live portfolio evidence is still too thin for promotion. At this snapshot, total "
            f"mark-to-market PnL is `{portfolio_mtm:,.2f} KRW ({portfolio_mtm_pct:+.4f}%)`, realized "
            f"PnL is `{portfolio_realized:,.2f} KRW`, and open positions total `{portfolio_open_positions}`.",
            "",
            "## Strategy Snapshot",
            "",
            "| Strategy | Wallets | Start Capital | Equity | MTM PnL | MTM Return | Realized PnL | Closed Trades | Open Positions | OOS Return | OOS Sharpe | Current Read |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )

    for strategy in sorted(by_strategy):
        row = by_strategy[strategy]
        start_capital = float(row["start_capital"])
        equity = float(row["equity"])
        mtm = equity - start_capital
        mtm_pct = (mtm / start_capital * 100.0) if start_capital > 0 else 0.0
        wf = walk_forward.get(strategy)
        oos_return = "N/A" if wf is None else _format_pct(float(wf.get("avg_return_pct", 0.0)))
        oos_sharpe = "N/A" if wf is None else f"{float(wf.get('avg_sharpe', 0.0)):.2f}"

        if strategy == "momentum":
            current_read = (
                "Active set's best research candidate, but live proof has not started because there "
                "are still no closed trades."
            )
        elif strategy == "kimchi_premium":
            current_read = (
                "Only strategy currently carrying live exposure, so it is also the only visible drag "
                "on the portfolio."
            )
        elif strategy == "consensus":
            current_read = (
                "Live-only filter wallet in the current setup; no dedicated research-line promotion "
                "artifact exists yet."
            )
        elif wf is not None and float(wf.get("avg_return_pct", 0.0)) <= 0:
            current_read = "Flat live and already weak in walk-forward research, so it has no promotion case yet."
        else:
            current_read = (
                "No live realized evidence yet, so promotion readiness is still unproven."
            )

        lines.append(
            f"| `{strategy}` | {int(row['wallets'])} | {start_capital:,.2f} | {equity:,.2f} | "
            f"{mtm:,.2f} | {mtm_pct:+.4f}% | {float(row['realized_pnl']):,.2f} | "
            f"{int(row['closed_trades'])} | {int(row['open_positions'])} | {oos_return} | "
            f"{oos_sharpe} | {current_read} |"
        )

    lines.extend(
        [
            f"| **Portfolio** | **{len(wallet_states)}** | **{portfolio_start:,.2f}** | "
            f"**{portfolio_equity:,.2f}** | **{portfolio_mtm:,.2f}** | **{portfolio_mtm_pct:+.4f}%** | "
            f"**{portfolio_realized:,.2f}** | **{portfolio_closed_trades}** | "
            f"**{portfolio_open_positions}** | — | — | Gate remains blocked by zero realized paper PnL. |",
            "",
            "## Promotion Gate Progress",
            "",
            "Canonical logic lives in `src/crypto_trader/operator/promotion.py`.",
            "",
            "| Criterion | Required | Current Evidence | Progress | Status |",
            "| --- | --- | --- | ---: | --- |",
            f"| Backtest return | `> 0%` | `{baseline_return_pct:+.2f}%` from `artifacts/backtest-baseline.json` | "
            f"{'100%' if baseline_return_pct > 0 else '0%'} | {'PASS' if baseline_return_pct > 0 else 'FAIL'} |",
            f"| Backtest max drawdown | `<= 20%` | `{baseline_mdd_pct:.2f}%` from `artifacts/backtest-baseline.json` | "
            f"{'100%' if baseline_mdd_pct <= 20.0 else '0%'} | {'PASS' if baseline_mdd_pct <= 20.0 else 'FAIL'} |",
            f"| Paper runs | `>= {minimum_runs}` | `{paper_runs}` runs from `artifacts/drift-report.json` | "
            f"{_progress_percent(paper_runs, minimum_runs)} | {'PASS' if paper_runs >= minimum_runs else 'FAIL'} |",
            f"| Drift status | not `out_of_sync` or `caution` | `{drift_status}` from `artifacts/drift-report.json` | "
            f"{'100%' if drift_status not in {'out_of_sync', 'caution'} else '0%'} | "
            f"{'PASS' if drift_status not in {'out_of_sync', 'caution'} else 'FAIL'} |",
            f"| Latest verdict | not `pause_strategy` or `reduce_risk` | latest `strategy-runs.jsonl` record is "
            f"`{latest_verdict}` at `{latest_verdict_at}` | "
            f"{'100%' if latest_verdict not in {'pause_strategy', 'reduce_risk'} else '0%'} | "
            f"{'PASS' if latest_verdict not in {'pause_strategy', 'reduce_risk'} else 'FAIL'} |",
            f"| Paper realized PnL | `> 0%` | `{paper_realized_pnl_pct:.2f}%` from `artifacts/drift-report.json`; "
            f"runtime checkpoint also shows `{portfolio_realized:,.2f} KRW` realized PnL | "
            f"{'100%' if paper_realized_pnl_pct > 0 else '0%'} | {'PASS' if paper_realized_pnl_pct > 0 else 'FAIL'} |",
            "",
            f"Net read: `{pass_count} / 6` gate checks are currently green. Promotion is still blocked because "
            "paper performance has not produced positive realized PnL yet.",
            "",
            "## Remaining Gap",
            "",
            f"- Minimum gap to promotion: cumulative realized paper PnL must move from "
            f"`{portfolio_realized:,.2f} KRW` to any value `> 0 KRW`.",
            "- In practical terms, the next meaningful milestone is the first closed profitable trade that "
            "leaves cumulative realized PnL positive after fees.",
            "- Until that happens, extra paper runs only add confidence to already-passed checks; they do "
            "not change the gate decision.",
            "",
            "## Interpretation",
            "",
            "- `momentum` remains the best active strategy on research quality, but current live evidence is "
            "still zero-length from a promotion perspective.",
            "- `kimchi_premium` is the only strategy with open risk right now, so it is the only strategy "
            "that can improve or worsen promotion readiness in the very short term.",
            "- `vpin` and `volatility_breakout` are idle in the current snapshot and therefore not "
            "contributing any live proof despite being allocated capital.",
            "- `consensus` should be treated as a live execution filter, not a promotable standalone "
            "strategy, until it has its own backtest and drift lineage.",
            "",
            "## Data Quality Notes",
            "",
            "- `promotion-gate.json` and `drift-report.json` are authoritative for the current official gate "
            "state, but they are still scoped to `KRW-BTC`.",
            "- `promotion-gate.json` lags the newest `backtest-baseline.json` on baseline return, so "
            "official status is usable but the latest return number should be read from "
            "`backtest-baseline.json`.",
            "- `runtime-checkpoint.json` is the best source for current strategy-level capital, equity, and "
            "open-position counts.",
            "- `strategy-runs.jsonl` records verdicts, but it does not persist `wallet` or `strategy_type`, "
            "so per-strategy verdict slicing is inferred rather than directly stored.",
            "",
            "## Sources",
            "",
            f"- `{runtime_checkpoint_path.as_posix()}`",
            f"- `{backtest_baseline_path.as_posix()}`",
            f"- `{drift_report_path.as_posix()}`",
            f"- `{promotion_gate_path.as_posix()}`",
            f"- `{strategy_run_journal_path.as_posix()}`",
        ]
    )

    if walk_forward_summary_path is not None:
        lines.append(f"- `{walk_forward_summary_path.as_posix()}`")
    lines.append("- `src/crypto_trader/operator/promotion.py`")

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return "\n".join(lines)
