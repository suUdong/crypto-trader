from __future__ import annotations

import unittest
from datetime import datetime

from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import OrderRequest, OrderSide, OrderType


class PaperBrokerTests(unittest.TestCase):
    def test_buy_then_sell_round_trip_updates_cash_positions_and_fee_inclusive_pnl(self) -> None:
        broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.01, slippage_pct=0.0)
        buy = broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=2.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="entry",
            ),
            market_price=100.0,
        )
        self.assertEqual(buy.status, "filled")
        self.assertIn("KRW-BTC", broker.positions)

        sell = broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.SELL,
                quantity=2.0,
                requested_at=datetime(2025, 1, 1, 1, 0, 0),
                reason="exit",
            ),
            market_price=110.0,
        )
        self.assertEqual(sell.status, "filled")
        self.assertNotIn("KRW-BTC", broker.positions)
        self.assertAlmostEqual(broker.cash, 1_015.8)
        self.assertAlmostEqual(broker.realized_pnl, 15.8)

    def test_candle_index_sets_entry_index_on_position(self) -> None:
        """Regression: entry_index must use candle_index, not broker sequence."""
        broker = PaperBroker(starting_cash=100_000.0, fee_rate=0.0005, slippage_pct=0.0)
        broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=1.0,
                requested_at=datetime(2025, 1, 1),
                reason="test",
            ),
            market_price=100.0,
            candle_index=199,
        )
        pos = broker.positions["KRW-BTC"]
        self.assertEqual(pos.entry_index, 199)

    def test_entry_index_falls_back_to_sequence_without_candle_index(self) -> None:
        broker = PaperBroker(starting_cash=100_000.0, fee_rate=0.0005, slippage_pct=0.0)
        broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=1.0,
                requested_at=datetime(2025, 1, 1),
                reason="test",
            ),
            market_price=100.0,
        )
        pos = broker.positions["KRW-BTC"]
        # Falls back to sequence number (1) when no candle_index given
        self.assertEqual(pos.entry_index, 1)

    def test_limit_order_gets_better_fill_and_tracks_order_type_metadata(self) -> None:
        market_broker = PaperBroker(
            starting_cash=1_000_000.0,
            fee_rate=0.001,
            slippage_pct=0.001,
            maker_fee_rate=0.0004,
        )
        limit_broker = PaperBroker(
            starting_cash=1_000_000.0,
            fee_rate=0.001,
            slippage_pct=0.001,
            maker_fee_rate=0.0004,
        )
        market_order = market_broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=1.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="market_entry",
                order_type=OrderType.MARKET,
            ),
            market_price=100.0,
        )
        limit_order = limit_broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=1.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="limit_entry",
                order_type=OrderType.LIMIT,
            ),
            market_price=100.0,
        )

        self.assertLess(limit_order.fill_price, market_order.fill_price)
        self.assertEqual(limit_order.order_type, OrderType.LIMIT)
        self.assertAlmostEqual(limit_order.fee_rate, 0.0004)
        self.assertEqual(limit_broker.positions["KRW-BTC"].entry_order_type, OrderType.LIMIT)

    def test_closed_trade_preserves_entry_and_exit_execution_metadata(self) -> None:
        broker = PaperBroker(
            starting_cash=1_000.0,
            fee_rate=0.01,
            slippage_pct=0.01,
            maker_fee_rate=0.005,
        )
        broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=2.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="entry",
                order_type=OrderType.LIMIT,
            ),
            market_price=100.0,
        )
        broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.SELL,
                quantity=2.0,
                requested_at=datetime(2025, 1, 1, 1, 0, 0),
                reason="exit",
                order_type=OrderType.MARKET,
            ),
            market_price=110.0,
        )

        trade = broker.closed_trades[0]
        self.assertEqual(trade.entry_order_type, OrderType.LIMIT)
        self.assertEqual(trade.exit_order_type, OrderType.MARKET)
        self.assertGreater(trade.entry_reference_price, 0.0)
        self.assertGreater(trade.exit_reference_price, 0.0)
