"""Execution-quality reporting from historical fill artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExecutionFill:
    timestamp: str
    wallet_name: str
    strategy_type: str
    symbol: str
    side: str
    quantity: float
    fill_price: float
    market_price: float
    fee_paid: float
    fee_rate: float
    slippage_pct: float
    order_type: str
    source: str


@dataclass(slots=True)
class ExecutionMetric:
    name: str
    fills: int
    avg_slippage_pct: float
    max_slippage_pct: float
    total_slippage_cost: float
    total_fees: float
    avg_fee_rate: float


@dataclass(slots=True)
class ExecutionQualityReport:
    generated_at: str
    lookback_hours: int | None
    total_fills: int
    avg_slippage_pct: float
    max_slippage_pct: float
    total_slippage_cost: float
    total_fees: float
    market_share_pct: float
    limit_share_pct: float
    fills: list[ExecutionFill] = field(default_factory=list)
    order_type_breakdown: list[ExecutionMetric] = field(default_factory=list)
    wallet_breakdown: list[ExecutionMetric] = field(default_factory=list)
    symbol_breakdown: list[ExecutionMetric] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class ExecutionQualityReportGenerator:
    _MATCH_WINDOW = timedelta(seconds=2)

    def generate(
        self,
        events_path: str | Path,
        strategy_run_path: str | Path,
        *,
        lookback_hours: int | None = None,
    ) -> ExecutionQualityReport:
        fills = self._load_fills(events_path, strategy_run_path, lookback_hours=lookback_hours)
        report = ExecutionQualityReport(
            generated_at=datetime.now(UTC).isoformat(),
            lookback_hours=lookback_hours,
            total_fills=len(fills),
            avg_slippage_pct=self._avg_slippage_pct(fills),
            max_slippage_pct=max((fill.slippage_pct for fill in fills), default=0.0),
            total_slippage_cost=round(
                sum(abs(fill.fill_price - fill.market_price) * fill.quantity for fill in fills),
                2,
            ),
            total_fees=round(sum(fill.fee_paid for fill in fills), 2),
            market_share_pct=self._order_type_share(fills, "market"),
            limit_share_pct=self._order_type_share(fills, "limit"),
            fills=fills,
            order_type_breakdown=self._breakdown(
                fills,
                key=lambda fill: fill.order_type,
            ),
            wallet_breakdown=self._breakdown(
                fills,
                key=lambda fill: fill.wallet_name,
            ),
            symbol_breakdown=self._breakdown(
                fills,
                key=lambda fill: fill.symbol,
            ),
        )
        report.recommendations = self._recommendations(report)
        return report

    def default_output_path(self) -> Path:
        return Path("artifacts/execution-quality-report.md")

    def save(self, report: ExecutionQualityReport, output_path: str | Path) -> None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(report), encoding="utf-8")
        target.with_suffix(".json").write_text(
            json.dumps(asdict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def to_markdown(self, report: ExecutionQualityReport) -> str:
        lines = [
            "## Execution Quality Report",
            "",
            f"Generated: {report.generated_at}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total fills | {report.total_fills} |",
            f"| Avg slippage | {report.avg_slippage_pct * 100:.4f}% |",
            f"| Max slippage | {report.max_slippage_pct * 100:.4f}% |",
            f"| Total slippage cost | {report.total_slippage_cost:,.2f} KRW |",
            f"| Total fees | {report.total_fees:,.2f} KRW |",
            f"| Market share | {report.market_share_pct:.1f}% |",
            f"| Limit share | {report.limit_share_pct:.1f}% |",
            "",
            "### Order Type Breakdown",
            "",
        ]
        lines.extend(self._metric_table(report.order_type_breakdown))
        lines.extend(
            [
                "",
                "### Wallet Breakdown",
                "",
            ]
        )
        lines.extend(self._metric_table(report.wallet_breakdown[:10]))
        lines.extend(
            [
                "",
                "### Symbol Breakdown",
                "",
            ]
        )
        lines.extend(self._metric_table(report.symbol_breakdown[:10]))
        lines.extend(
            [
                "",
                "### Recommendations",
                "",
            ]
        )
        if report.recommendations:
            lines.extend(f"- {line}" for line in report.recommendations)
        else:
            lines.append("- No execution recommendations available yet.")
        return "\n".join(lines) + "\n"

    def _metric_table(self, rows: list[ExecutionMetric]) -> list[str]:
        lines = [
            "| Name | Fills | Avg Slip | Max Slip | Fees | Slip Cost | Avg Fee Rate |",
            "|------|-------|----------|----------|------|-----------|--------------|",
        ]
        if not rows:
            lines.append("| n/a | 0 | 0.0000% | 0.0000% | 0.00 | 0.00 | 0.0000% |")
            return lines
        for row in rows:
            lines.append(
                f"| {row.name} | {row.fills} | {row.avg_slippage_pct * 100:.4f}% | "
                f"{row.max_slippage_pct * 100:.4f}% | {row.total_fees:,.2f} | "
                f"{row.total_slippage_cost:,.2f} | {row.avg_fee_rate * 100:.4f}% |"
            )
        return lines

    def _load_fills(
        self,
        events_path: str | Path,
        strategy_run_path: str | Path,
        *,
        lookback_hours: int | None,
    ) -> list[ExecutionFill]:
        cutoff = (
            datetime.now(UTC) - timedelta(hours=lookback_hours)
            if lookback_hours is not None and lookback_hours > 0
            else None
        )
        events = self._load_jsonl(Path(events_path))
        filled_runs = self._load_jsonl(Path(strategy_run_path))
        indexed_runs = self._index_runs(filled_runs, cutoff=cutoff)
        fills: list[ExecutionFill] = []
        for event in events:
            if event.get("event_type") != "trade":
                continue
            event_ts = self._parse_timestamp(event.get("timestamp"))
            if cutoff is not None and event_ts is not None and event_ts < cutoff:
                continue
            fill = self._event_to_fill(event, event_ts, indexed_runs)
            if fill is not None:
                fills.append(fill)
        return sorted(fills, key=lambda fill: fill.timestamp)

    def _event_to_fill(
        self,
        event: dict[str, Any],
        event_ts: datetime | None,
        indexed_runs: dict[tuple[str, str, str], list[dict[str, Any]]],
    ) -> ExecutionFill | None:
        wallet_name = str(event.get("wallet_name", ""))
        symbol = str(event.get("symbol", ""))
        side = str(event.get("side", ""))
        fill_price = float(event.get("fill_price", 0.0) or 0.0)
        quantity = float(event.get("quantity", 0.0) or 0.0)
        market_price = float(event.get("market_price", 0.0) or 0.0)
        slippage_pct = event.get("slippage_pct")
        if market_price <= 0 or slippage_pct is None:
            matched = self._match_run(indexed_runs, wallet_name, symbol, side, event_ts)
            if matched is not None:
                market_price = float(matched.get("latest_price", 0.0) or 0.0)
                if market_price > 0:
                    slippage_pct = self._compute_slippage_pct(side, market_price, fill_price)
        if market_price <= 0 or slippage_pct is None or quantity <= 0 or fill_price <= 0:
            return None
        fee_paid = float(event.get("fee_paid", 0.0) or 0.0)
        fee_rate = event.get("fee_rate")
        if fee_rate is None:
            fee_rate = fee_paid / max(1.0, fill_price * quantity)
        return ExecutionFill(
            timestamp=str(event.get("timestamp") or ""),
            wallet_name=wallet_name,
            strategy_type=str(event.get("strategy_type", "")),
            symbol=symbol,
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            market_price=market_price,
            fee_paid=fee_paid,
            fee_rate=float(fee_rate or 0.0),
            slippage_pct=float(slippage_pct),
            order_type=str(event.get("order_type") or "market"),
            source="event_direct" if event.get("market_price") is not None else "event_join",
        )

    def _index_runs(
        self,
        runs: list[dict[str, Any]],
        *,
        cutoff: datetime | None,
    ) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
        indexed: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for index, row in enumerate(runs):
            if row.get("order_status") != "filled":
                continue
            run_ts = self._parse_timestamp(row.get("recorded_at"))
            if cutoff is not None and run_ts is not None and run_ts < cutoff:
                continue
            wallet_name = str(row.get("wallet_name", ""))
            symbol = str(row.get("symbol", ""))
            side = str(row.get("order_side", ""))
            if not wallet_name or not symbol or not side:
                continue
            key = (wallet_name, symbol, side)
            indexed.setdefault(key, []).append(
                {
                    "index": index,
                    "timestamp": run_ts,
                    "latest_price": row.get("latest_price"),
                }
            )
        return indexed

    def _match_run(
        self,
        indexed_runs: dict[tuple[str, str, str], list[dict[str, Any]]],
        wallet_name: str,
        symbol: str,
        side: str,
        event_ts: datetime | None,
    ) -> dict[str, Any] | None:
        if event_ts is None:
            return None
        candidates = indexed_runs.get((wallet_name, symbol, side), [])
        if not candidates:
            return None
        best: tuple[timedelta, dict[str, Any]] | None = None
        for candidate in candidates:
            timestamp = candidate.get("timestamp")
            if not isinstance(timestamp, datetime):
                continue
            delta = abs(timestamp - event_ts)
            if delta > self._MATCH_WINDOW:
                continue
            if best is None or delta < best[0]:
                best = (delta, candidate)
        return best[1] if best is not None else None

    def _breakdown(
        self,
        fills: list[ExecutionFill],
        *,
        key: Callable[[ExecutionFill], str],
    ) -> list[ExecutionMetric]:
        grouped: dict[str, list[ExecutionFill]] = {}
        for fill in fills:
            grouped.setdefault(str(key(fill)), []).append(fill)
        metrics = [
            ExecutionMetric(
                name=name,
                fills=len(rows),
                avg_slippage_pct=self._avg_slippage_pct(rows),
                max_slippage_pct=max((row.slippage_pct for row in rows), default=0.0),
                total_slippage_cost=round(
                    sum(abs(row.fill_price - row.market_price) * row.quantity for row in rows),
                    2,
                ),
                total_fees=round(sum(row.fee_paid for row in rows), 2),
                avg_fee_rate=(
                    sum(row.fee_rate for row in rows) / len(rows)
                    if rows
                    else 0.0
                ),
            )
            for name, rows in grouped.items()
        ]
        return sorted(metrics, key=lambda row: (-row.fills, row.name))

    def _recommendations(self, report: ExecutionQualityReport) -> list[str]:
        if report.total_fills == 0:
            return [
                "No historical fills were recoverable from the supplied artifacts.",
            ]
        recommendations: list[str] = []
        market_metrics = next(
            (row for row in report.order_type_breakdown if row.name == "market"),
            None,
        )
        limit_metrics = next(
            (row for row in report.order_type_breakdown if row.name == "limit"),
            None,
        )
        if report.market_share_pct >= 70.0 and report.avg_slippage_pct > 0.0004:
            recommendations.append(
                "Recent fills are still market-dominated with noticeable adverse slippage; "
                "keep limit-first entries enabled for non-urgent strategies."
            )
        if report.total_fees > report.total_slippage_cost:
            recommendations.append(
                "Fee drag is larger than slippage cost in the current sample; "
                "tighten the execution-cost gate on low-confidence entries and prefer "
                "maker-style entries when possible."
            )
        if limit_metrics is None:
            recommendations.append(
                "Historical artifacts contain no explicit limit-order fills yet; "
                "new runtime metadata is needed to validate limit-vs-market improvements over time."
            )
        elif (
            market_metrics is not None
            and limit_metrics.avg_slippage_pct < market_metrics.avg_slippage_pct
        ):
            recommendations.append(
                "Recorded limit fills are improving slippage relative to market fills; "
                "keep market-only exits, but use limit entries where urgency is low."
            )
        if not recommendations:
            recommendations.append(
                "Execution costs are within the current heuristic budget; "
                "continue collecting fills to tighten thresholds."
            )
        return recommendations

    @staticmethod
    def _load_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _compute_slippage_pct(side: str, market_price: float, fill_price: float) -> float:
        if market_price <= 0:
            return 0.0
        if side == "buy":
            return (fill_price - market_price) / market_price
        return (market_price - fill_price) / market_price

    @staticmethod
    def _avg_slippage_pct(fills: list[ExecutionFill]) -> float:
        if not fills:
            return 0.0
        return sum(fill.slippage_pct for fill in fills) / len(fills)

    @staticmethod
    def _order_type_share(fills: list[ExecutionFill], order_type: str) -> float:
        if not fills:
            return 0.0
        return 100.0 * sum(1 for fill in fills if fill.order_type == order_type) / len(fills)


def generate_execution_quality_report(
    strategy_run_path: str | Path,
    events_path: str | Path,
    *,
    lookback_hours: int | None = None,
) -> ExecutionQualityReport:
    return ExecutionQualityReportGenerator().generate(
        events_path=events_path,
        strategy_run_path=strategy_run_path,
        lookback_hours=lookback_hours,
    )


def save_execution_quality_report(
    report: ExecutionQualityReport,
    output_path: str | Path,
) -> None:
    ExecutionQualityReportGenerator().save(report, output_path)


def to_markdown(report: ExecutionQualityReport) -> str:
    return ExecutionQualityReportGenerator().to_markdown(report)
