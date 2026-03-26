"""Per-strategy daily/weekly performance auto-report from JSONL artifacts."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(slots=True)
class StrategyPerformance:
    wallet_name: str
    strategy_type: str
    period: str  # "daily" or "weekly"
    period_start: str  # ISO
    period_end: str  # ISO
    total_signals: int
    buy_signals: int
    sell_signals: int
    hold_signals: int
    trades_executed: int
    trades_rejected: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    total_pnl_pct: float
    avg_trade_pnl: float
    best_trade_pnl: float
    worst_trade_pnl: float
    avg_confidence: float


@dataclass(slots=True)
class PerformanceSummary:
    generated_at: str
    period: str
    period_start: str
    period_end: str
    strategies: list[StrategyPerformance]
    portfolio_pnl: float
    portfolio_trades: int
    portfolio_win_rate: float


class PerformanceReporter:
    """Generates per-strategy performance summaries from JSONL artifact files."""

    def __init__(
        self,
        trade_journal_path: str | Path,
        strategy_journal_path: str | Path,
    ) -> None:
        self._trade_path = Path(trade_journal_path)
        self._strategy_path = Path(strategy_journal_path)

    def generate(self, period: str = "daily", hours: int = 24) -> PerformanceSummary:
        """Generate a performance summary for the last N hours.

        Args:
            period: Label for the period ("daily" or "weekly").
            hours: Number of hours to look back from now.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=hours)
        period_start = cutoff.isoformat()
        period_end = now.isoformat()

        strategy_records = self._load_strategy_records(cutoff)
        trade_records = self._load_trade_records(cutoff)

        # Group strategy runs by (wallet_name, strategy_type)
        groups: dict[tuple[str, str], list[dict]] = {}
        for rec in strategy_records:
            key = (rec.get("wallet_name", "unknown"), rec.get("strategy_type", "unknown"))
            groups.setdefault(key, []).append(rec)

        # Group trades by wallet
        trades_by_wallet: dict[str, list[dict]] = {}
        for trade in trade_records:
            wallet = trade.get("wallet", "unknown")
            trades_by_wallet.setdefault(wallet, []).append(trade)

        strategies: list[StrategyPerformance] = []
        for (wallet_name, strategy_type), runs in groups.items():
            perf = self._compute_strategy_performance(
                wallet_name=wallet_name,
                strategy_type=strategy_type,
                period=period,
                period_start=period_start,
                period_end=period_end,
                runs=runs,
                wallet_trades=trades_by_wallet.get(wallet_name, []),
            )
            strategies.append(perf)

        # Sort by total_pnl descending for consistent output
        strategies.sort(key=lambda s: s.total_pnl, reverse=True)

        portfolio_pnl = sum(s.total_pnl for s in strategies)
        portfolio_trades = sum(s.trades_executed for s in strategies)
        total_wins = sum(s.wins for s in strategies)
        total_losses = sum(s.losses for s in strategies)
        portfolio_win_rate = total_wins / max(1, total_wins + total_losses)

        return PerformanceSummary(
            generated_at=now.isoformat(),
            period=period,
            period_start=period_start,
            period_end=period_end,
            strategies=strategies,
            portfolio_pnl=portfolio_pnl,
            portfolio_trades=portfolio_trades,
            portfolio_win_rate=portfolio_win_rate,
        )

    def to_notification_text(self, summary: PerformanceSummary) -> str:
        """Format summary as a compact notification message (Telegram/Slack-ready)."""
        period_label = "Daily" if summary.period == "daily" else "Weekly"
        try:
            start_dt = datetime.fromisoformat(summary.period_start)
            end_dt = datetime.fromisoformat(summary.period_end)
            start_str = start_dt.strftime("%Y-%m-%d")
            end_str = end_dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            start_str = summary.period_start[:10]
            end_str = summary.period_end[:10]

        pnl_sign = "+" if summary.portfolio_pnl >= 0 else ""
        win_pct = f"{summary.portfolio_win_rate * 100:.1f}%"

        lines = [
            f"\U0001f4ca {period_label} Performance Report",
            f"Period: {start_str} \u2192 {end_str}",
            (
                f"Portfolio: {pnl_sign}{summary.portfolio_pnl:,.0f} KRW"
                f" | {summary.portfolio_trades} trades"
                f" | Win: {win_pct}"
            ),
            "---",
        ]

        for s in summary.strategies:
            pnl_sign = "+" if s.total_pnl >= 0 else ""
            strat_win_pct = f"{s.win_rate * 100:.0f}%"
            lines.append(
                f"{s.wallet_name}: {pnl_sign}{s.total_pnl:,.0f} KRW"
                f" | {s.trades_executed}t W:{strat_win_pct}"
                f" | Avg conf: {s.avg_confidence:.2f}"
            )

        return "\n".join(lines)

    def save_json(self, summary: PerformanceSummary, path: str | Path) -> None:
        """Save the performance summary as a JSON file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(summary)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_strategy_records(self, cutoff: datetime) -> list[dict]:
        """Load strategy-run records newer than cutoff."""
        if not self._strategy_path.exists():
            return []
        records: list[dict] = []
        for line in self._strategy_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            recorded_at_str = rec.get("recorded_at", "")
            if not recorded_at_str:
                continue
            try:
                recorded_at = datetime.fromisoformat(recorded_at_str)
                if recorded_at.tzinfo is None:
                    recorded_at = recorded_at.replace(tzinfo=UTC)
                if recorded_at < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            records.append(rec)
        return records

    def _load_trade_records(self, cutoff: datetime) -> list[dict]:
        """Load trade records whose exit_time is newer than cutoff."""
        if not self._trade_path.exists():
            return []
        records: list[dict] = []
        for line in self._trade_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            exit_time_str = rec.get("exit_time", "")
            if not exit_time_str:
                continue
            try:
                exit_time = datetime.fromisoformat(exit_time_str)
                if exit_time.tzinfo is None:
                    exit_time = exit_time.replace(tzinfo=UTC)
                if exit_time < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            records.append(rec)
        return records

    @staticmethod
    def _compute_strategy_performance(
        wallet_name: str,
        strategy_type: str,
        period: str,
        period_start: str,
        period_end: str,
        runs: list[dict],
        wallet_trades: list[dict],
    ) -> StrategyPerformance:
        """Derive StrategyPerformance from per-run and per-trade records."""
        # Signal counts
        buy_signals = sum(1 for r in runs if r.get("signal_action") == "buy")
        sell_signals = sum(1 for r in runs if r.get("signal_action") == "sell")
        hold_signals = sum(1 for r in runs if r.get("signal_action") == "hold")
        total_signals = len(runs)

        # Executed vs rejected orders
        trades_executed = sum(1 for r in runs if r.get("order_status") == "filled")
        trades_rejected = sum(
            1 for r in runs
            if r.get("signal_action") in ("buy", "sell")
            and r.get("order_status") != "filled"
        )

        # Confidence
        confidences = [
            r["signal_confidence"]
            for r in runs
            if isinstance(r.get("signal_confidence"), (int, float))
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # PnL from trade journal (more accurate than signal records)
        pnls = [t.get("pnl", 0.0) for t in wallet_trades]
        pnl_pcts = [t.get("pnl_pct", 0.0) for t in wallet_trades]

        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        win_rate = wins / max(1, wins + losses) if wallet_trades else 0.0

        total_pnl = sum(pnls)
        total_pnl_pct = sum(pnl_pcts) * 100.0  # convert fraction to pct
        avg_trade_pnl = total_pnl / len(pnls) if pnls else 0.0
        best_trade_pnl = max(pnls) if pnls else 0.0
        worst_trade_pnl = min(pnls) if pnls else 0.0

        return StrategyPerformance(
            wallet_name=wallet_name,
            strategy_type=strategy_type,
            period=period,
            period_start=period_start,
            period_end=period_end,
            total_signals=total_signals,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            hold_signals=hold_signals,
            trades_executed=trades_executed,
            trades_rejected=trades_rejected,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            avg_trade_pnl=avg_trade_pnl,
            best_trade_pnl=best_trade_pnl,
            worst_trade_pnl=worst_trade_pnl,
            avg_confidence=avg_confidence,
        )
