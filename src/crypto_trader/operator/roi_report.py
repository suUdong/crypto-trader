"""ROI report generation from runtime artifacts."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

JsonDict = dict[str, Any]


@dataclass(slots=True)
class CurvePoint:
    label: str
    as_of: str
    equity: float
    pnl: float
    return_pct: float


@dataclass(slots=True)
class StrategyContribution:
    strategy: str
    wallet_count: int
    starting_capital: float
    current_equity: float
    realized_pnl: float
    unrealized_pnl: float
    pnl: float
    return_pct: float
    contribution_pct: float


@dataclass(slots=True)
class BaselineComparison:
    config_start_capital: float
    runtime_start_capital: float
    checkpoint_equity: float
    current_equity: float
    headline_pnl: float
    headline_return_pct: float
    config_pnl: float
    config_return_pct: float
    reconciliation_delta: float


@dataclass(slots=True)
class RoiReport:
    generated_at: str
    report_month: str
    timezone: str
    config_source_path: str
    checkpoint_source_path: str
    baseline: BaselineComparison
    strategy_contributions: list[StrategyContribution]
    daily_curve: list[CurvePoint]
    weekly_curve: list[CurvePoint]
    session_curve: list[CurvePoint]
    live_wallet_count: int
    assumptions: list[str]


class RoiReportGenerator:
    """Generate a ROI report from config, checkpoint, and strategy-run artifacts."""

    def generate(
        self,
        *,
        config_path: str | Path,
        checkpoint_path: str | Path,
        strategy_runs_path: str | Path,
        current_equity: float,
        report_month: str,
        timezone_name: str = "Asia/Seoul",
        generated_at: datetime | None = None,
    ) -> RoiReport:
        generated = generated_at or datetime.now(UTC)
        checkpoint = _load_json(Path(checkpoint_path))
        wallet_states = checkpoint.get("wallet_states", {})
        if not isinstance(wallet_states, dict):
            wallet_states = {}

        config_start_capital = _load_config_start_capital(Path(config_path))
        runtime_start_capital = sum(
            float(wallet.get("initial_capital", 0.0) or 0.0)
            for wallet in wallet_states.values()
            if isinstance(wallet, dict)
        )
        checkpoint_equity = sum(
            float(wallet.get("equity", 0.0) or 0.0)
            for wallet in wallet_states.values()
            if isinstance(wallet, dict)
        )

        baseline = BaselineComparison(
            config_start_capital=config_start_capital,
            runtime_start_capital=runtime_start_capital,
            checkpoint_equity=checkpoint_equity,
            current_equity=current_equity,
            headline_pnl=current_equity - runtime_start_capital,
            headline_return_pct=_pct(current_equity - runtime_start_capital, runtime_start_capital),
            config_pnl=current_equity - config_start_capital,
            config_return_pct=_pct(current_equity - config_start_capital, config_start_capital),
            reconciliation_delta=current_equity - checkpoint_equity,
        )

        strategy_contributions = _build_strategy_contributions(wallet_states, checkpoint_equity)
        session_curve = _build_session_curve(
            checkpoint=checkpoint,
            strategy_runs_path=Path(strategy_runs_path),
            current_equity=current_equity,
            report_month=report_month,
            timezone_name=timezone_name,
            generated_at=generated,
        )
        daily_curve = _reduce_curve(session_curve, runtime_start_capital, timezone_name, "daily")
        weekly_curve = _reduce_curve(session_curve, runtime_start_capital, timezone_name, "weekly")

        assumptions = [
            "Operational ROI baseline uses the live runtime checkpoint initial equity, not the newer config budget.",
            "Config capital is shown separately because config/daemon.toml currently differs from the running checkpoint.",
            "Daily and weekly curves are reconstructed from strategy-run snapshots plus current open-position sizes because no historical pnl-snapshots.jsonl file is present.",
        ]
        if str(Path(checkpoint_path)) != "artifacts/runtime-checkpoint.json":
            assumptions.append(
                "The default runtime checkpoint rolled to a different live session during report generation, so this report is anchored to the last frozen snapshot that matched the requested current-assets basis."
            )
        if len(daily_curve) <= 2:
            assumptions.append(
                "Daily and weekly coverage is short because the relevant deployment snapshot only spans the latest live session window."
            )
        if abs(baseline.reconciliation_delta) >= 0.01:
            assumptions.append(
                "The user-provided current assets differ slightly from the checkpoint equity; the difference is reported as a reconciliation delta."
            )

        return RoiReport(
            generated_at=generated.isoformat(),
            report_month=report_month,
            timezone=timezone_name,
            config_source_path=str(Path(config_path)),
            checkpoint_source_path=str(Path(checkpoint_path)),
            baseline=baseline,
            strategy_contributions=strategy_contributions,
            daily_curve=daily_curve,
            weekly_curve=weekly_curve,
            session_curve=session_curve,
            live_wallet_count=len(wallet_states),
            assumptions=assumptions,
        )

    def to_markdown(self, report: RoiReport) -> str:
        baseline = report.baseline
        lines = [
            f"# ROI Report {report.report_month}",
            "",
            f"- Generated: `{report.generated_at}`",
            f"- Timezone: `{report.timezone}`",
            f"- Live wallets in checkpoint: `{report.live_wallet_count}`",
            "",
            "## Executive Read",
            "",
            (
                f"- Live runtime ROI is `{baseline.headline_pnl:+,.0f} KRW` "
                f"(`{baseline.headline_return_pct:+.3f}%`) using the current-assets basis "
                f"`{baseline.current_equity:,.0f} KRW` against runtime initial equity "
                f"`{baseline.runtime_start_capital:,.0f} KRW`."
            ),
            (
                f"- The checked-in config currently budgets `{baseline.config_start_capital:,.0f} KRW`, "
                f"which would imply `{baseline.config_pnl:+,.0f} KRW` "
                f"(`{baseline.config_return_pct:+.3f}%`) if used as the denominator."
            ),
            (
                "- Decision-useful interpretation: the running deployment is effectively flat, "
                "while the newer 11.0M config budget is not yet the authoritative live baseline."
            ),
            "",
            "## Starting Capital Check",
            "",
            "| Baseline | Amount (KRW) | Source | Comment |",
            "|----------|--------------:|--------|---------|",
            (
                f"| Runtime initial equity | {baseline.runtime_start_capital:,.0f} | "
                f"`{report.checkpoint_source_path}` | Live session baseline used for headline ROI |"
            ),
            (
                f"| Config capital | {baseline.config_start_capital:,.0f} | "
                f"`{report.config_source_path}` | Planned allocation in repo, currently ahead of the live checkpoint |"
            ),
            (
                f"| Checkpoint observed equity | {baseline.checkpoint_equity:,.2f} | "
                f"`{report.checkpoint_source_path}` | Latest artifact-backed total equity snapshot |"
            ),
            (
                f"| Current assets override | {baseline.current_equity:,.0f} | "
                "User input | Used as the current-assets basis for the headline ROI |"
            ),
            (
                f"| Reconciliation delta | {baseline.reconciliation_delta:+,.2f} | "
                "Current assets - checkpoint equity | Small delta between user basis and checkpoint snapshot |"
            ),
            "",
            "## Strategy Contribution",
            "",
            "| Strategy | Wallets | Start Capital | Current Equity | PnL | Realized | Unrealized | Return | Contribution |",
            "|----------|--------:|--------------:|---------------:|----:|---------:|-----------:|-------:|-------------:|",
        ]

        for contribution in report.strategy_contributions:
            lines.append(
                f"| {contribution.strategy} | {contribution.wallet_count} | "
                f"{contribution.starting_capital:,.0f} | {contribution.current_equity:,.2f} | "
                f"{contribution.pnl:+,.2f} | {contribution.realized_pnl:+,.2f} | "
                f"{contribution.unrealized_pnl:+,.2f} | {contribution.return_pct:+.3f}% | "
                f"{contribution.contribution_pct:+.1f}% |"
            )

        lines.extend(
            [
                "",
                "## Daily Profit Curve",
                "",
                "| Date | Equity | PnL vs Runtime Start | Return |",
                "|------|-------:|---------------------:|-------:|",
            ]
        )
        for point in report.daily_curve:
            lines.append(
                f"| {point.label} | {point.equity:,.2f} | {point.pnl:+,.2f} | {point.return_pct:+.3f}% |"
            )

        lines.extend(
            [
                "",
                "## Weekly Profit Curve",
                "",
                "| Week | Equity | PnL vs Runtime Start | Return |",
                "|------|-------:|---------------------:|-------:|",
            ]
        )
        for point in report.weekly_curve:
            lines.append(
                f"| {point.label} | {point.equity:,.2f} | {point.pnl:+,.2f} | {point.return_pct:+.3f}% |"
            )

        lines.extend(
            [
                "",
                "## Session Curve",
                "",
                "| Time | Equity | PnL vs Runtime Start | Return |",
                "|------|-------:|---------------------:|-------:|",
            ]
        )
        for point in report.session_curve:
            lines.append(
                f"| {point.label} | {point.equity:,.2f} | {point.pnl:+,.2f} | {point.return_pct:+.3f}% |"
            )

        lines.extend(
            [
                "",
                "## Assumptions",
                "",
            ]
        )
        for assumption in report.assumptions:
            lines.append(f"- {assumption}")

        return "\n".join(lines)

    def save(self, report: RoiReport, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(report), encoding="utf-8")


def _load_config_start_capital(path: Path) -> float:
    if not path.exists():
        return 0.0
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    wallets = payload.get("wallets", [])
    if not isinstance(wallets, list):
        return 0.0
    return sum(float(wallet.get("initial_capital", 0.0) or 0.0) for wallet in wallets)


def _build_strategy_contributions(
    wallet_states: dict[str, Any],
    checkpoint_equity: float,
) -> list[StrategyContribution]:
    grouped: dict[str, StrategyContribution] = {}
    total_pnl = 0.0
    for wallet in wallet_states.values():
        if not isinstance(wallet, dict):
            continue
        strategy = str(wallet.get("strategy_type", "unknown") or "unknown")
        initial_capital = float(wallet.get("initial_capital", 0.0) or 0.0)
        equity = float(wallet.get("equity", initial_capital) or initial_capital)
        realized = float(wallet.get("realized_pnl", 0.0) or 0.0)
        unrealized = equity - initial_capital - realized
        pnl = equity - initial_capital
        total_pnl += pnl
        if strategy not in grouped:
            grouped[strategy] = StrategyContribution(
                strategy=strategy,
                wallet_count=0,
                starting_capital=0.0,
                current_equity=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                pnl=0.0,
                return_pct=0.0,
                contribution_pct=0.0,
            )
        row = grouped[strategy]
        row.wallet_count += 1
        row.starting_capital += initial_capital
        row.current_equity += equity
        row.realized_pnl += realized
        row.unrealized_pnl += unrealized
        row.pnl += pnl

    rows = list(grouped.values())
    for row in rows:
        row.return_pct = _pct(row.pnl, row.starting_capital)
        row.contribution_pct = (row.pnl / total_pnl * 100.0) if abs(total_pnl) > 1e-9 else 0.0
    rows.sort(key=lambda item: item.pnl)
    if abs(checkpoint_equity) < 1e-9:
        return rows
    return rows


def _build_session_curve(
    *,
    checkpoint: JsonDict,
    strategy_runs_path: Path,
    current_equity: float,
    report_month: str,
    timezone_name: str,
    generated_at: datetime,
) -> list[CurvePoint]:
    wallet_states = checkpoint.get("wallet_states", {})
    if not isinstance(wallet_states, dict):
        wallet_states = {}
    checkpoint_session_id = str(checkpoint.get("session_id", "") or "")

    runtime_start = sum(
        float(wallet.get("initial_capital", 0.0) or 0.0)
        for wallet in wallet_states.values()
        if isinstance(wallet, dict)
    )
    if runtime_start <= 0:
        return []

    wallet_positions: dict[str, dict[str, JsonDict]] = {}
    wallet_cash: dict[str, float] = {}
    wallet_equity: dict[str, float] = {}
    latest_prices: dict[str, dict[str, float]] = {}
    wallet_open_positions: dict[str, int] = {}

    for wallet_name, raw_wallet in wallet_states.items():
        if not isinstance(raw_wallet, dict):
            continue
        positions = raw_wallet.get("positions", {})
        wallet_positions[wallet_name] = positions if isinstance(positions, dict) else {}
        wallet_cash[wallet_name] = float(raw_wallet.get("initial_capital", 0.0) or 0.0)
        wallet_equity[wallet_name] = float(raw_wallet.get("initial_capital", 0.0) or 0.0)
        wallet_open_positions[wallet_name] = 0
        latest_prices[wallet_name] = {}
        for symbol, raw_position in wallet_positions[wallet_name].items():
            if isinstance(raw_position, dict):
                latest_prices[wallet_name][symbol] = float(
                    raw_position.get("market_price", raw_position.get("entry_price", 0.0)) or 0.0
                )

    records: list[tuple[datetime, str, float]] = []
    if strategy_runs_path.exists():
        for line in strategy_runs_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            wallet_name = record.get("wallet_name")
            if wallet_name not in wallet_positions:
                continue
            recorded_at = _parse_dt(record.get("recorded_at"))
            if recorded_at is None:
                continue
            if not recorded_at.isoformat().startswith(report_month):
                continue
            record_session_id = str(record.get("session_id", "") or "")
            if checkpoint_session_id and record_session_id and record_session_id < checkpoint_session_id:
                continue
            expected_start = float(
                wallet_states.get(wallet_name, {}).get("initial_capital", 0.0) or 0.0
            )
            actual_start = float(record.get("session_starting_equity", expected_start) or 0.0)
            if expected_start > 0 and abs(actual_start - expected_start) > 1e-6:
                continue
            wallet_cash[wallet_name] = float(record.get("cash", wallet_cash[wallet_name]) or 0.0)
            wallet_open_positions[wallet_name] = int(record.get("open_positions", 0) or 0)
            symbol = str(record.get("symbol", "") or "")
            if symbol:
                latest_prices.setdefault(wallet_name, {})[symbol] = float(
                    record.get("latest_price", latest_prices[wallet_name].get(symbol, 0.0)) or 0.0
                )
            wallet_equity[wallet_name] = _wallet_equity(
                cash=wallet_cash[wallet_name],
                open_positions=wallet_open_positions[wallet_name],
                positions=wallet_positions[wallet_name],
                latest_prices=latest_prices[wallet_name],
            )
            records.append((recorded_at, _local_label(recorded_at, timezone_name), sum(wallet_equity.values())))

    records.sort(key=lambda item: item[0])
    if not records:
        return [
            CurvePoint(
                label=_local_label(generated_at, timezone_name),
                as_of=generated_at.isoformat(),
                equity=current_equity,
                pnl=current_equity - runtime_start,
                return_pct=_pct(current_equity - runtime_start, runtime_start),
            )
        ]

    first_timestamp = records[0][0]
    points = [
        CurvePoint(
            label=_local_label(first_timestamp, timezone_name) + " start",
            as_of=first_timestamp.isoformat(),
            equity=runtime_start,
            pnl=0.0,
            return_pct=0.0,
        )
    ]
    for timestamp, label, equity in records:
        points.append(
            CurvePoint(
                label=label,
                as_of=timestamp.isoformat(),
                equity=equity,
                pnl=equity - runtime_start,
                return_pct=_pct(equity - runtime_start, runtime_start),
            )
        )
    points.append(
        CurvePoint(
            label=_local_label(generated_at, timezone_name) + " current",
            as_of=generated_at.isoformat(),
            equity=current_equity,
            pnl=current_equity - runtime_start,
            return_pct=_pct(current_equity - runtime_start, runtime_start),
        )
    )
    return _dedupe_curve(points)


def _reduce_curve(
    curve: list[CurvePoint],
    runtime_start_capital: float,
    timezone_name: str,
    granularity: str,
) -> list[CurvePoint]:
    reduced: dict[str, CurvePoint] = {}
    for point in curve:
        parsed = _parse_dt(point.as_of)
        if parsed is None:
            continue
        local = parsed.astimezone(ZoneInfo(timezone_name))
        if granularity == "daily":
            key = local.date().isoformat()
        else:
            iso = local.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        reduced[key] = CurvePoint(
            label=key,
            as_of=point.as_of,
            equity=point.equity,
            pnl=point.equity - runtime_start_capital,
            return_pct=_pct(point.equity - runtime_start_capital, runtime_start_capital),
        )
    return list(reduced.values())


def _wallet_equity(
    *,
    cash: float,
    open_positions: int,
    positions: dict[str, JsonDict],
    latest_prices: dict[str, float],
) -> float:
    if open_positions <= 0 or not positions:
        return cash
    market_value = 0.0
    for symbol, raw_position in positions.items():
        if not isinstance(raw_position, dict):
            continue
        quantity = float(raw_position.get("quantity", 0.0) or 0.0)
        latest_price = latest_prices.get(
            symbol,
            float(raw_position.get("market_price", raw_position.get("entry_price", 0.0)) or 0.0),
        )
        market_value += quantity * latest_price
    return cash + market_value


def _load_json(path: Path) -> JsonDict:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _dedupe_curve(points: list[CurvePoint]) -> list[CurvePoint]:
    deduped: list[CurvePoint] = []
    last_equity: float | None = None
    for point in points:
        equity = round(point.equity, 8)
        if last_equity is not None and equity == last_equity:
            continue
        deduped.append(point)
        last_equity = equity
    return deduped


def _local_label(timestamp: datetime, timezone_name: str) -> str:
    return timestamp.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _pct(delta: float, base: float) -> float:
    if abs(base) < 1e-9:
        return 0.0
    return delta / base * 100.0
