from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import (
    DailyPerformanceReport,
    PositionSnapshot,
    PositionStatus,
    TradeRecord,
)
from crypto_trader.storage import SqliteStore, TradeRow


class PaperTradeJournal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def append_many(
        self,
        trades: list[TradeRecord],
        wallet_name: str = "",
        session_id: str = "",
    ) -> None:
        if not trades:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            for trade in trades:
                payload = asdict(trade)
                payload["entry_time"] = trade.entry_time.isoformat()
                payload["exit_time"] = trade.exit_time.isoformat()
                if wallet_name:
                    payload["wallet"] = wallet_name
                if session_id:
                    payload["session_id"] = session_id
                handle.write(json.dumps(payload, ensure_ascii=True))
                handle.write("\n")

    def load_all(self) -> list[TradeRecord]:
        if not self._path.exists():
            return []
        trades: list[TradeRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            payload["entry_time"] = datetime.fromisoformat(payload["entry_time"])
            payload["exit_time"] = datetime.fromisoformat(payload["exit_time"])
            trades.append(TradeRecord(**payload))
        return trades


class PositionSnapshotStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def save(self, snapshot: PositionSnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(snapshot), indent=2), encoding="utf-8")


class DailyPerformanceStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def save(self, report: DailyPerformanceReport) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")


class PaperTradingOperations:
    def __init__(
        self,
        trade_journal_path: str | Path,
        position_snapshot_path: str | Path,
        daily_performance_path: str | Path,
        *,
        sqlite_store_path: str | Path | None = None,
        wallet_name: str = "",
        session_id: str = "",
    ) -> None:
        self._trade_journal = PaperTradeJournal(trade_journal_path)
        self._position_snapshot_store = PositionSnapshotStore(position_snapshot_path)
        self._daily_performance_store = DailyPerformanceStore(daily_performance_path)
        self._persisted_trade_count = 0
        self._wallet_name = wallet_name
        self._session_id = session_id
        self._sqlite_store: SqliteStore | None = (
            SqliteStore(sqlite_store_path) if sqlite_store_path else None
        )

    def sync(self, broker: PaperBroker, latest_prices: dict[str, float]) -> None:
        new_trades = broker.closed_trades[self._persisted_trade_count :]
        self._trade_journal.append_many(
            new_trades,
            wallet_name=self._wallet_name,
            session_id=self._session_id,
        )
        if self._sqlite_store is not None and new_trades:
            for trade in new_trades:
                self._sqlite_store.insert_trade(
                    TradeRow(
                        wallet=self._wallet_name,
                        symbol=trade.symbol,
                        entry_time=trade.entry_time.isoformat(),
                        exit_time=trade.exit_time.isoformat(),
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        quantity=trade.quantity,
                        pnl=trade.pnl,
                        pnl_pct=trade.pnl_pct,
                        exit_reason=trade.exit_reason,
                        session_id=self._session_id,
                    )
                )
        self._persisted_trade_count = len(broker.closed_trades)
        trades = self._trade_journal.load_all()
        snapshot = build_position_snapshot(broker, latest_prices)
        report = build_daily_performance_report(broker, trades, latest_prices)
        self._position_snapshot_store.save(snapshot)
        self._daily_performance_store.save(report)


def build_position_snapshot(
    broker: PaperBroker,
    latest_prices: dict[str, float],
) -> PositionSnapshot:
    positions = []
    for symbol, position in broker.positions.items():
        market_price = latest_prices.get(symbol, position.entry_price)
        unrealized_pnl = (market_price - position.entry_price) * position.quantity
        positions.append(
            PositionStatus(
                symbol=symbol,
                quantity=position.quantity,
                entry_price=position.entry_price,
                market_price=market_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=(
                    unrealized_pnl / max(1.0, position.entry_price * position.quantity)
                ),
            )
        )
    return PositionSnapshot(
        generated_at=datetime.now(UTC).isoformat(),
        positions=positions,
        open_position_count=len(positions),
        mark_to_market_equity=broker.equity(latest_prices),
    )


def build_daily_performance_report(
    broker: PaperBroker,
    trades: list[TradeRecord],
    latest_prices: dict[str, float],
) -> DailyPerformanceReport:
    winning_trade_count = sum(1 for trade in trades if trade.pnl > 0)
    losing_trade_count = sum(1 for trade in trades if trade.pnl < 0)
    trade_count = len(trades)
    win_rate = winning_trade_count / trade_count if trade_count else 0.0
    mark_to_market_equity = broker.equity(latest_prices)
    starting_equity = broker.cash - broker.realized_pnl
    realized_return_pct = broker.realized_pnl / max(1.0, starting_equity)
    return DailyPerformanceReport(
        generated_at=datetime.now(UTC).isoformat(),
        trade_count=trade_count,
        winning_trade_count=winning_trade_count,
        losing_trade_count=losing_trade_count,
        realized_pnl=broker.realized_pnl,
        realized_return_pct=realized_return_pct,
        win_rate=win_rate,
        open_position_count=len(broker.positions),
        mark_to_market_equity=mark_to_market_equity,
    )
