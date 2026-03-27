"""Wallet-level performance report over a recent lookback window."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]


@dataclass(slots=True)
class WalletPerformanceMetrics:
    wallet: str
    strategy: str
    initial_capital: float
    ending_equity: float
    realized_pnl: float
    unrealized_pnl: float
    return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    trade_count: int
    win_count: int
    loss_count: int
    open_positions: int


@dataclass(slots=True)
class WalletPerformanceReport:
    generated_at: str
    period_hours: int
    period_start: str
    period_end: str
    wallets: list[WalletPerformanceMetrics]
    portfolio_return_pct: float
    portfolio_sharpe: float
    portfolio_mdd_pct: float
    total_equity: float
    total_initial_capital: float


class WalletPerformanceReportGenerator:
    """Build a recent wallet performance report from runtime artifacts."""

    def generate(
        self,
        checkpoint_path: str | Path,
        strategy_run_journal_path: str | Path,
        trade_journal_path: str | Path,
        lookback_hours: int = 168,
    ) -> WalletPerformanceReport:
        checkpoint_file = Path(checkpoint_path)
        if not checkpoint_file.exists():
            return self._empty_report(lookback_hours)

        checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        wallet_states = checkpoint.get("wallet_states", {})
        if not isinstance(wallet_states, dict):
            return self._empty_report(lookback_hours)

        period_end = _parse_dt(checkpoint.get("generated_at")) or datetime.now(UTC)
        period_start = period_end - timedelta(hours=lookback_hours)
        wallet_names = set(wallet_states.keys())

        price_events = _load_price_events(
            strategy_run_journal_path,
            wallet_names=wallet_names,
            period_start=period_start,
            period_end=period_end,
        )
        trade_events = _load_trade_events(
            trade_journal_path,
            wallet_names=wallet_names,
            period_start=period_start,
            period_end=period_end,
        )

        wallet_curves: dict[str, list[tuple[datetime, float]]] = {}
        wallet_rows: list[WalletPerformanceMetrics] = []
        total_equity = 0.0
        total_initial_capital = 0.0

        for wallet_name, raw_state in wallet_states.items():
            if not isinstance(raw_state, dict):
                continue

            state = raw_state
            initial_capital = float(state.get("initial_capital", 1_000_000.0) or 1_000_000.0)
            current_equity = float(state.get("equity", initial_capital) or initial_capital)
            current_realized = float(state.get("realized_pnl", 0.0) or 0.0)
            current_unrealized = current_equity - initial_capital - current_realized
            open_positions = int(state.get("open_positions", 0) or 0)

            positions = state.get("positions", {})
            if not isinstance(positions, dict):
                positions = {}

            wallet_trade_events = trade_events.get(wallet_name, [])
            equity_curve = _build_wallet_curve(
                initial_capital=initial_capital,
                current_equity=current_equity,
                current_positions=positions,
                trade_events=wallet_trade_events,
                price_events=price_events,
                wallet_name=wallet_name,
                period_start=period_start,
                period_end=period_end,
            )
            wallet_curves[wallet_name] = equity_curve

            curve_values = [equity for _, equity in equity_curve]
            start_equity = curve_values[0] if curve_values else initial_capital
            return_pct = (
                ((current_equity - start_equity) / start_equity) * 100.0
                if start_equity > 0
                else 0.0
            )

            wins = sum(1 for trade in wallet_trade_events if float(trade.get("pnl", 0.0)) > 0.0)
            losses = sum(1 for trade in wallet_trade_events if float(trade.get("pnl", 0.0)) <= 0.0)

            wallet_rows.append(
                WalletPerformanceMetrics(
                    wallet=wallet_name,
                    strategy=str(state.get("strategy_type", "unknown") or "unknown"),
                    initial_capital=initial_capital,
                    ending_equity=current_equity,
                    realized_pnl=current_realized,
                    unrealized_pnl=current_unrealized,
                    return_pct=return_pct,
                    sharpe_ratio=_compute_sharpe_ratio(curve_values),
                    max_drawdown_pct=_compute_max_drawdown_pct(curve_values),
                    trade_count=len(wallet_trade_events),
                    win_count=wins,
                    loss_count=losses,
                    open_positions=open_positions,
                )
            )

            total_equity += current_equity
            total_initial_capital += initial_capital

        wallet_rows.sort(key=lambda row: (row.return_pct, row.sharpe_ratio), reverse=True)
        portfolio_curve = _build_portfolio_curve(wallet_curves)
        portfolio_values = [equity for _, equity in portfolio_curve]
        portfolio_start = portfolio_values[0] if portfolio_values else total_initial_capital
        portfolio_return = (
            ((total_equity - portfolio_start) / portfolio_start) * 100.0
            if portfolio_start > 0
            else 0.0
        )

        return WalletPerformanceReport(
            generated_at=datetime.now(UTC).isoformat(),
            period_hours=lookback_hours,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            wallets=wallet_rows,
            portfolio_return_pct=portfolio_return,
            portfolio_sharpe=_compute_sharpe_ratio(portfolio_values),
            portfolio_mdd_pct=_compute_max_drawdown_pct(portfolio_values),
            total_equity=total_equity,
            total_initial_capital=total_initial_capital,
        )

    def to_markdown(self, report: WalletPerformanceReport) -> str:
        lines = [
            f"# Wallet Performance Report ({report.period_hours}h)",
            "",
            f"- Generated: `{report.generated_at}`",
            f"- Window: `{report.period_start}` -> `{report.period_end}`",
            "",
            "## Portfolio Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Wallets | {len(report.wallets)} |",
            f"| Total Equity | {report.total_equity:,.0f} KRW |",
            f"| Total Return | {report.portfolio_return_pct:+.3f}% |",
            f"| Sharpe | {report.portfolio_sharpe:.2f} |",
            f"| Max Drawdown | {report.portfolio_mdd_pct:.3f}% |",
            "",
            "## Per-Wallet Breakdown",
            "",
            "| Wallet | Strategy | Return% | Sharpe | MDD% | Trades | Open | Equity | "
            "Realized | Unrealized |",
            "|--------|----------|---------|--------|------|--------|------|--------|----------|------------|",
        ]
        for wallet in report.wallets:
            lines.append(
                f"| {wallet.wallet} | {wallet.strategy} | {wallet.return_pct:+.3f}% | "
                f"{wallet.sharpe_ratio:.2f} | {wallet.max_drawdown_pct:.3f}% | "
                f"{wallet.trade_count} | {wallet.open_positions} | {wallet.ending_equity:,.0f} | "
                f"{wallet.realized_pnl:+,.0f} | {wallet.unrealized_pnl:+,.0f} |"
            )
        return "\n".join(lines)

    def save(self, report: WalletPerformanceReport, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(report), encoding="utf-8")
        target.with_suffix(".json").write_text(
            json.dumps(
                {
                    "generated_at": report.generated_at,
                    "period_hours": report.period_hours,
                    "period_start": report.period_start,
                    "period_end": report.period_end,
                    "portfolio_return_pct": report.portfolio_return_pct,
                    "portfolio_sharpe": report.portfolio_sharpe,
                    "portfolio_mdd_pct": report.portfolio_mdd_pct,
                    "total_equity": report.total_equity,
                    "total_initial_capital": report.total_initial_capital,
                    "wallets": [asdict(wallet) for wallet in report.wallets],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def default_output_path(self) -> Path:
        return Path("artifacts") / "wallet-performance-7d.md"

    def _empty_report(self, lookback_hours: int) -> WalletPerformanceReport:
        now = datetime.now(UTC)
        return WalletPerformanceReport(
            generated_at=now.isoformat(),
            period_hours=lookback_hours,
            period_start=(now - timedelta(hours=lookback_hours)).isoformat(),
            period_end=now.isoformat(),
            wallets=[],
            portfolio_return_pct=0.0,
            portfolio_sharpe=0.0,
            portfolio_mdd_pct=0.0,
            total_equity=0.0,
            total_initial_capital=0.0,
        )


def _load_price_events(
    strategy_run_journal_path: str | Path,
    *,
    wallet_names: set[str],
    period_start: datetime,
    period_end: datetime,
) -> dict[tuple[str, str], list[tuple[datetime, float]]]:
    events: dict[tuple[str, str], list[tuple[datetime, float]]] = {}
    journal_path = Path(strategy_run_journal_path)
    if not journal_path.exists():
        return events

    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        wallet = str(row.get("wallet_name", "") or "")
        symbol = str(row.get("symbol", "") or "")
        if wallet not in wallet_names or not symbol:
            continue
        ts = _parse_dt(row.get("recorded_at"))
        if ts is None or ts < period_start or ts > period_end:
            continue
        latest_price = float(row.get("latest_price", 0.0) or 0.0)
        if latest_price <= 0:
            continue
        events.setdefault((wallet, symbol), []).append((ts, latest_price))

    for values in events.values():
        values.sort(key=lambda item: item[0])
    return events


def _load_trade_events(
    trade_journal_path: str | Path,
    *,
    wallet_names: set[str],
    period_start: datetime,
    period_end: datetime,
) -> dict[str, list[JsonDict]]:
    events: dict[str, list[JsonDict]] = {}
    journal_path = Path(trade_journal_path)
    if not journal_path.exists():
        return events

    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        trade = json.loads(line)
        wallet = str(trade.get("wallet", "") or "")
        if wallet not in wallet_names:
            continue
        exit_dt = _parse_dt(trade.get("exit_time")) or _parse_dt(trade.get("timestamp"))
        if exit_dt is None or exit_dt < period_start or exit_dt > period_end:
            continue
        trade["_exit_dt"] = exit_dt.isoformat()
        events.setdefault(wallet, []).append(trade)

    for values in events.values():
        values.sort(key=lambda item: _parse_dt(item.get("_exit_dt")) or period_start)
    return events


def _build_wallet_curve(
    *,
    initial_capital: float,
    current_equity: float,
    current_positions: dict[str, JsonDict],
    trade_events: list[JsonDict],
    price_events: dict[tuple[str, str], list[tuple[datetime, float]]],
    wallet_name: str,
    period_start: datetime,
    period_end: datetime,
) -> list[tuple[datetime, float]]:
    event_times: set[datetime] = {period_start, period_end}

    for trade in trade_events:
        exit_dt = _parse_dt(trade.get("_exit_dt"))
        if exit_dt is not None:
            event_times.add(exit_dt)

    normalized_positions: dict[str, dict[str, Any]] = {}
    for symbol, raw_position in current_positions.items():
        if not isinstance(raw_position, dict):
            continue
        entry_dt = _parse_dt(raw_position.get("entry_time")) or period_start
        normalized_positions[symbol] = {
            "entry_dt": entry_dt,
            "entry_price": float(raw_position.get("entry_price", 0.0) or 0.0),
            "quantity": float(raw_position.get("quantity", 0.0) or 0.0),
            "entry_fee_paid": float(raw_position.get("entry_fee_paid", 0.0) or 0.0),
        }
        event_times.add(entry_dt)
        for ts, _ in price_events.get((wallet_name, symbol), []):
            if ts >= entry_dt:
                event_times.add(ts)

    sorted_times = sorted(event_times)
    curve: list[tuple[datetime, float]] = []
    for point_dt in sorted_times:
        realized = 0.0
        for trade in trade_events:
            exit_dt = _parse_dt(trade.get("_exit_dt"))
            if exit_dt is not None and exit_dt <= point_dt:
                realized += float(trade.get("pnl", 0.0) or 0.0)

        unrealized = 0.0
        for symbol, position in normalized_positions.items():
            entry_dt = position["entry_dt"]
            if point_dt < entry_dt:
                continue
            latest_price = _latest_price_before(
                price_events.get((wallet_name, symbol), []),
                point_dt,
                fallback=position["entry_price"],
            )
            unrealized += (
                (latest_price - position["entry_price"]) * position["quantity"]
                - position["entry_fee_paid"]
            )

        equity = initial_capital + realized + unrealized
        if point_dt == period_end:
            equity = current_equity
        curve.append((point_dt, equity))

    if len(curve) == 1:
        curve.append((period_end, current_equity))
    return curve


def _build_portfolio_curve(
    wallet_curves: dict[str, list[tuple[datetime, float]]],
) -> list[tuple[datetime, float]]:
    if not wallet_curves:
        return []

    timeline = sorted({point_dt for curve in wallet_curves.values() for point_dt, _ in curve})
    cursor = {wallet: 0 for wallet in wallet_curves}
    last_value = {wallet: curve[0][1] for wallet, curve in wallet_curves.items() if curve}
    portfolio_curve: list[tuple[datetime, float]] = []

    for point_dt in timeline:
        total = 0.0
        for wallet, curve in wallet_curves.items():
            while cursor[wallet] + 1 < len(curve) and curve[cursor[wallet] + 1][0] <= point_dt:
                cursor[wallet] += 1
                last_value[wallet] = curve[cursor[wallet]][1]
            total += last_value.get(wallet, 0.0)
        portfolio_curve.append((point_dt, total))
    return portfolio_curve


def _latest_price_before(
    events: list[tuple[datetime, float]],
    point_dt: datetime,
    *,
    fallback: float,
) -> float:
    latest = fallback
    for ts, price in events:
        if ts > point_dt:
            break
        latest = price
    return latest


def _compute_max_drawdown_pct(curve: list[float]) -> float:
    if not curve:
        return 0.0
    peak = curve[0]
    max_drawdown = 0.0
    for equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown * 100.0


def _compute_sharpe_ratio(curve: list[float]) -> float:
    if len(curve) < 3:
        return 0.0
    returns = [
        (current / previous) - 1.0
        for previous, current in zip(curve, curve[1:], strict=False)
        if previous > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / (len(returns) - 1)
    std_dev = math.sqrt(max(variance, 0.0))
    if std_dev <= 0:
        return 0.0
    return (mean / std_dev) * math.sqrt(min(len(returns), 252))


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
