"""Execution engines."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from crypto_trader.models import OrderRequest, OrderResult, OrderType, Position, TradeRecord


@runtime_checkable
class Broker(Protocol):
    """Protocol for order execution brokers (paper and live)."""

    cash: float
    positions: dict[str, Position]
    closed_trades: list[TradeRecord]
    realized_pnl: float

    def submit_order(
        self,
        request: OrderRequest,
        market_price: float,
        candle_index: int | None = None,
        volume_ratio: float = 1.0,
    ) -> OrderResult: ...

    def equity(self, prices: Mapping[str, float]) -> float: ...

    def estimate_entry_cost_pct(
        self,
        order_type: OrderType,
        volume_ratio: float = 1.0,
    ) -> float: ...

    def estimate_round_trip_cost_pct(
        self,
        entry_order_type: OrderType,
        volume_ratio: float = 1.0,
        exit_order_type: OrderType = OrderType.MARKET,
    ) -> float: ...
