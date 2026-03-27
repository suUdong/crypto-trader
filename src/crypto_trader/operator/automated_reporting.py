"""Unified daily and weekly automated reporting from runtime artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_trader.monitoring.performance_reporter import PerformanceReporter, StrategyPerformance
from crypto_trader.operator.wallet_performance import WalletPerformanceReportGenerator

JsonDict = dict[str, Any]


@dataclass(slots=True)
class ReportPosition:
    symbol: str
    quantity: float
    entry_price: float
    latest_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


@dataclass(slots=True)
class AutomatedWalletReport:
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
    positions: list[ReportPosition]


@dataclass(slots=True)
class AutomatedPerformanceReport:
    generated_at: str
    period: str
    period_hours: int
    period_start: str
    period_end: str
    wallets: list[AutomatedWalletReport]
    strategies: list[StrategyPerformance]
    portfolio_return_pct: float
    portfolio_sharpe: float
    portfolio_mdd_pct: float
    total_equity: float
    total_initial_capital: float
    total_realized_pnl: float
    total_unrealized_pnl: float
    total_open_positions: int
    portfolio_pnl: float
    portfolio_trades: int
    portfolio_win_rate: float


class AutomatedReportGenerator:
    """Generate saved operator reports for daily and weekly review."""

    def generate(
        self,
        *,
        checkpoint_path: str | Path,
        strategy_run_journal_path: str | Path,
        trade_journal_path: str | Path,
        period: str,
        hours: int,
    ) -> AutomatedPerformanceReport:
        wallet_report = WalletPerformanceReportGenerator().generate(
            checkpoint_path=checkpoint_path,
            strategy_run_journal_path=strategy_run_journal_path,
            trade_journal_path=trade_journal_path,
            lookback_hours=hours,
        )
        strategy_summary = PerformanceReporter(
            trade_journal_path=trade_journal_path,
            strategy_journal_path=strategy_run_journal_path,
        ).generate(period=period, hours=hours)

        checkpoint = _load_json(Path(checkpoint_path))
        raw_wallet_states = checkpoint.get("wallet_states", {})
        wallet_states = raw_wallet_states if isinstance(raw_wallet_states, dict) else {}
        latest_prices = _load_latest_prices(
            Path(strategy_run_journal_path),
            wallet_names=set(wallet_states.keys()),
        )

        wallets: list[AutomatedWalletReport] = []
        total_realized_pnl = 0.0
        total_unrealized_pnl = 0.0
        total_open_positions = 0

        for wallet in wallet_report.wallets:
            state = wallet_states.get(wallet.wallet, {})
            positions = _build_positions(
                wallet_name=wallet.wallet,
                state=state if isinstance(state, dict) else {},
                latest_prices=latest_prices,
            )
            wallets.append(
                AutomatedWalletReport(
                    wallet=wallet.wallet,
                    strategy=wallet.strategy,
                    initial_capital=wallet.initial_capital,
                    ending_equity=wallet.ending_equity,
                    realized_pnl=wallet.realized_pnl,
                    unrealized_pnl=wallet.unrealized_pnl,
                    return_pct=wallet.return_pct,
                    sharpe_ratio=wallet.sharpe_ratio,
                    max_drawdown_pct=wallet.max_drawdown_pct,
                    trade_count=wallet.trade_count,
                    win_count=wallet.win_count,
                    loss_count=wallet.loss_count,
                    open_positions=wallet.open_positions,
                    positions=positions,
                )
            )
            total_realized_pnl += wallet.realized_pnl
            total_unrealized_pnl += wallet.unrealized_pnl
            total_open_positions += wallet.open_positions

        return AutomatedPerformanceReport(
            generated_at=wallet_report.generated_at,
            period=period,
            period_hours=hours,
            period_start=wallet_report.period_start,
            period_end=wallet_report.period_end,
            wallets=wallets,
            strategies=strategy_summary.strategies,
            portfolio_return_pct=wallet_report.portfolio_return_pct,
            portfolio_sharpe=wallet_report.portfolio_sharpe,
            portfolio_mdd_pct=wallet_report.portfolio_mdd_pct,
            total_equity=wallet_report.total_equity,
            total_initial_capital=wallet_report.total_initial_capital,
            total_realized_pnl=total_realized_pnl,
            total_unrealized_pnl=total_unrealized_pnl,
            total_open_positions=total_open_positions,
            portfolio_pnl=strategy_summary.portfolio_pnl,
            portfolio_trades=strategy_summary.portfolio_trades,
            portfolio_win_rate=strategy_summary.portfolio_win_rate,
        )

    def to_markdown(self, report: AutomatedPerformanceReport) -> str:
        title = "Daily Performance Report" if report.period == "daily" else "Weekly Summary Report"
        lines = [
            f"# {title}",
            "",
            f"- Generated: `{report.generated_at}`",
            f"- Window: `{report.period_start}` -> `{report.period_end}`",
            f"- Lookback: `{report.period_hours}h`",
            "",
            "## Portfolio Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Equity | {report.total_equity:,.0f} KRW |",
            f"| Portfolio Return | {report.portfolio_return_pct:+.3f}% |",
            f"| Sharpe | {report.portfolio_sharpe:.2f} |",
            f"| Max Drawdown | {report.portfolio_mdd_pct:.3f}% |",
            f"| Realized P&L | {report.total_realized_pnl:+,.0f} KRW |",
            f"| Unrealized P&L | {report.total_unrealized_pnl:+,.0f} KRW |",
            f"| Trades | {report.portfolio_trades} |",
            f"| Win Rate | {report.portfolio_win_rate * 100:.1f}% |",
            f"| Open Positions | {report.total_open_positions} |",
            "",
            "## Wallet Breakdown",
            "",
            (
                "| Wallet | Strategy | Return% | Sharpe | MDD% | Trades | W/L | Open | "
                "Equity | Realized | Unrealized |"
            ),
            "|--------|----------|---------|--------|------|--------|-----|------|--------|----------|------------|",
        ]
        for wallet in report.wallets:
            lines.append(
                f"| {wallet.wallet} | {wallet.strategy} | {wallet.return_pct:+.3f}% | "
                f"{wallet.sharpe_ratio:.2f} | {wallet.max_drawdown_pct:.3f}% | "
                f"{wallet.trade_count} | "
                f"{wallet.win_count}/{wallet.loss_count} | {wallet.open_positions} | "
                f"{wallet.ending_equity:,.0f} | {wallet.realized_pnl:+,.0f} | "
                f"{wallet.unrealized_pnl:+,.0f} |"
            )

        lines.extend(["", "## Open Position Status", ""])
        has_positions = False
        for wallet in report.wallets:
            if not wallet.positions:
                continue
            has_positions = True
            lines.append(f"### {wallet.wallet}")
            lines.append("")
            lines.append("| Symbol | Qty | Entry | Latest | Unrealized P&L | Unrealized % |")
            lines.append("|--------|-----|-------|--------|----------------|--------------|")
            for position in wallet.positions:
                lines.append(
                    f"| {position.symbol} | {position.quantity:.6f} | "
                    f"{position.entry_price:,.0f} | "
                    f"{position.latest_price:,.0f} | {position.unrealized_pnl:+,.0f} | "
                    f"{position.unrealized_pnl_pct:+.3f}% |"
                )
            lines.append("")
        if not has_positions:
            lines.append("- No open positions in the current snapshot.")
            lines.append("")

        lines.extend(
            [
                "## Strategy Summary",
                "",
                "| Wallet | Strategy | P&L | Trades | Win Rate | Avg Confidence |",
                "|--------|----------|-----|--------|----------|----------------|",
            ]
        )
        for strategy in report.strategies:
            lines.append(
                f"| {strategy.wallet_name} | {strategy.strategy_type} | "
                f"{strategy.total_pnl:+,.0f} KRW | "
                f"{strategy.trades_executed} | {strategy.win_rate * 100:.1f}% | "
                f"{strategy.avg_confidence:.2f} |"
            )
        if not report.strategies:
            lines.append("| - | - | +0 KRW | 0 | 0.0% | 0.00 |")
        return "\n".join(lines)

    def save(self, report: AutomatedPerformanceReport, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(report), encoding="utf-8")
        target.with_suffix(".json").write_text(
            json.dumps(asdict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def default_output_path(self, *, period: str, artifacts_dir: str | Path = "artifacts") -> Path:
        return Path(artifacts_dir) / f"{period}-report.md"


def build_legacy_daily_performance_summary(
    report: AutomatedPerformanceReport,
    *,
    report_path: str | Path,
    weekly_report_path: str | Path | None = None,
) -> JsonDict:
    winning_trade_count = sum(wallet.win_count for wallet in report.wallets)
    losing_trade_count = sum(wallet.loss_count for wallet in report.wallets)
    realized_return_pct = (
        report.total_realized_pnl / report.total_initial_capital
        if report.total_initial_capital > 0
        else 0.0
    )
    payload: JsonDict = {
        "generated_at": report.generated_at,
        "period": report.period,
        "period_hours": report.period_hours,
        "trade_count": report.portfolio_trades,
        "winning_trade_count": winning_trade_count,
        "losing_trade_count": losing_trade_count,
        "realized_pnl": report.total_realized_pnl,
        "realized_return_pct": realized_return_pct,
        "win_rate": report.portfolio_win_rate,
        "open_position_count": report.total_open_positions,
        "mark_to_market_equity": report.total_equity,
        "initial_capital": report.total_initial_capital,
        "portfolio_return_pct": report.portfolio_return_pct,
        "portfolio_sharpe": report.portfolio_sharpe,
        "portfolio_mdd_pct": report.portfolio_mdd_pct,
        "mode": "multi_symbol",
        "report_path": str(report_path),
        "report_json_path": str(Path(report_path).with_suffix(".json")),
    }
    if weekly_report_path is not None:
        payload["weekly_report_path"] = str(weekly_report_path)
        payload["weekly_report_json_path"] = str(Path(weekly_report_path).with_suffix(".json"))
    return payload


def _load_json(path: Path) -> JsonDict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_latest_prices(
    path: Path,
    *,
    wallet_names: set[str],
) -> dict[tuple[str, str], float]:
    latest_by_key: dict[tuple[str, str], tuple[datetime, float]] = {}
    if not path.exists():
        return {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        wallet_name = str(row.get("wallet_name", "") or "")
        symbol = str(row.get("symbol", "") or "")
        if wallet_name not in wallet_names or not symbol:
            continue
        latest_price = row.get("latest_price")
        if not isinstance(latest_price, (int, float)):
            continue
        recorded_at = _parse_dt(row.get("recorded_at")) or datetime.min.replace(tzinfo=UTC)
        key = (wallet_name, symbol)
        previous = latest_by_key.get(key)
        if previous is None or recorded_at >= previous[0]:
            latest_by_key[key] = (recorded_at, float(latest_price))
    return {key: price for key, (_, price) in latest_by_key.items()}


def _build_positions(
    *,
    wallet_name: str,
    state: JsonDict,
    latest_prices: dict[tuple[str, str], float],
) -> list[ReportPosition]:
    raw_positions = state.get("positions", {})
    if not isinstance(raw_positions, dict):
        return []

    positions: list[ReportPosition] = []
    for symbol, raw_position in raw_positions.items():
        if not isinstance(raw_position, dict):
            continue
        quantity = float(raw_position.get("quantity", 0.0) or 0.0)
        entry_price = float(raw_position.get("entry_price", 0.0) or 0.0)
        latest_price = latest_prices.get((wallet_name, str(symbol)), entry_price)
        unrealized_pnl = (latest_price - entry_price) * quantity
        unrealized_pnl_pct = (
            ((latest_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
        )
        positions.append(
            ReportPosition(
                symbol=str(symbol),
                quantity=quantity,
                entry_price=entry_price,
                latest_price=latest_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
            )
        )
    positions.sort(key=lambda position: abs(position.unrealized_pnl), reverse=True)
    return positions
