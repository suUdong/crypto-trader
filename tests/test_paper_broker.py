from __future__ import annotations

import unittest
from datetime import datetime

from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import OrderRequest, OrderSide


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
