from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import OrderRequest, OrderSide, OrderType
from crypto_trader.operator.paper_trading import (
    PaperTradeJournal,
    PaperTradingOperations,
    build_daily_performance_report,
    build_position_snapshot,
)
from crypto_trader.storage import SqliteStore


class PaperTradingOperationsTests(unittest.TestCase):
    def test_paper_trade_journal_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0)
            broker.submit_order(
                OrderRequest(
                    symbol="KRW-BTC",
                    side=OrderSide.BUY,
                    quantity=1.0,
                    requested_at=datetime(2025, 1, 1, 0, 0, 0),
                    reason="entry",
                    confidence=0.73,
                    order_type=OrderType.LIMIT,
                ),
                market_price=100.0,
            )
            broker.submit_order(
                OrderRequest(
                    symbol="KRW-BTC",
                    side=OrderSide.SELL,
                    quantity=1.0,
                    requested_at=datetime(2025, 1, 1, 1, 0, 0),
                    reason="exit",
                    order_type=OrderType.MARKET,
                ),
                market_price=110.0,
            )
            journal = PaperTradeJournal(Path(temp_dir) / "trades.jsonl")
            journal.append_many(broker.closed_trades, session_id="session-1")
            trades = journal.load_all()
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0].exit_reason, "exit")
            self.assertEqual(trades[0].session_id, "session-1")
            self.assertEqual(trades[0].entry_confidence, 0.73)
            self.assertEqual(trades[0].entry_order_type, OrderType.LIMIT)
            self.assertEqual(trades[0].exit_order_type, OrderType.MARKET)

    def test_build_position_snapshot_tracks_open_positions(self) -> None:
        broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0)
        broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=1.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="entry",
            ),
            market_price=100.0,
        )
        snapshot = build_position_snapshot(broker, {"KRW-BTC": 110.0})
        self.assertEqual(snapshot.open_position_count, 1)
        self.assertAlmostEqual(snapshot.positions[0].unrealized_pnl, 10.0)

    def test_build_daily_performance_report_summarizes_trades_and_equity(self) -> None:
        broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0)
        broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=1.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="entry",
            ),
            market_price=100.0,
        )
        broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.SELL,
                quantity=1.0,
                requested_at=datetime(2025, 1, 1, 1, 0, 0),
                reason="exit",
            ),
            market_price=110.0,
        )
        report = build_daily_performance_report(broker, broker.closed_trades, {"KRW-BTC": 110.0})
        self.assertEqual(report.trade_count, 1)
        self.assertEqual(report.winning_trade_count, 1)

    def test_operations_sync_writes_trade_position_and_performance_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0)
            broker.submit_order(
                OrderRequest(
                    symbol="KRW-BTC",
                    side=OrderSide.BUY,
                    quantity=1.0,
                    requested_at=datetime(2025, 1, 1, 0, 0, 0),
                    reason="entry",
                ),
                market_price=100.0,
            )
            operations = PaperTradingOperations(
                Path(temp_dir) / "trades.jsonl",
                Path(temp_dir) / "positions.json",
                Path(temp_dir) / "daily.json",
            )
            operations.sync(broker, {"KRW-BTC": 101.0})
            self.assertTrue((Path(temp_dir) / "positions.json").exists())
            self.assertTrue((Path(temp_dir) / "daily.json").exists())

    def test_operations_sync_dual_writes_closed_trades_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0)
            broker.submit_order(
                OrderRequest(
                    symbol="KRW-BTC",
                    side=OrderSide.BUY,
                    quantity=1.0,
                    requested_at=datetime(2025, 1, 1, 0, 0, 0),
                    reason="entry",
                ),
                market_price=100.0,
            )
            broker.submit_order(
                OrderRequest(
                    symbol="KRW-BTC",
                    side=OrderSide.SELL,
                    quantity=1.0,
                    requested_at=datetime(2025, 1, 1, 1, 0, 0),
                    reason="take_profit",
                ),
                market_price=110.0,
            )
            sqlite_path = Path(temp_dir) / "trades.db"
            operations = PaperTradingOperations(
                Path(temp_dir) / "trades.jsonl",
                Path(temp_dir) / "positions.json",
                Path(temp_dir) / "daily.json",
                sqlite_store_path=sqlite_path,
                wallet_name="vpin_eth",
                session_id="session-42",
            )
            operations.sync(broker, {"KRW-BTC": 110.0})
            # Second sync is idempotent: no new trades, no duplicate SQLite rows.
            operations.sync(broker, {"KRW-BTC": 110.0})

            store = SqliteStore(sqlite_path)
            rows = store.query_trades()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].wallet, "vpin_eth")
            self.assertEqual(rows[0].session_id, "session-42")
            self.assertEqual(rows[0].exit_reason, "take_profit")
            self.assertEqual(rows[0].symbol, "KRW-BTC")
