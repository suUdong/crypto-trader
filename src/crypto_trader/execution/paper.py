from __future__ import annotations

from collections.abc import Mapping

from crypto_trader.models import OrderRequest, OrderResult, OrderSide, OrderType, Position, TradeRecord


class PaperBroker:
    def __init__(
        self,
        starting_cash: float,
        fee_rate: float,
        slippage_pct: float,
        maker_fee_rate: float | None = None,
    ) -> None:
        self.cash = starting_cash
        self._fee_rate = fee_rate
        self._maker_fee_rate = fee_rate if maker_fee_rate is None else maker_fee_rate
        self._slippage_pct = slippage_pct
        self.positions: dict[str, Position] = {}
        self.closed_trades: list[TradeRecord] = []
        self.realized_pnl = 0.0
        self._sequence = 0

    def estimate_entry_cost_pct(
        self,
        order_type: OrderType,
        volume_ratio: float = 1.0,
    ) -> float:
        slippage_pct = self.estimate_slippage_pct(order_type, volume_ratio)
        return self.fee_rate_for(order_type) + max(0.0, slippage_pct)

    def estimate_round_trip_cost_pct(
        self,
        entry_order_type: OrderType,
        volume_ratio: float = 1.0,
        exit_order_type: OrderType = OrderType.MARKET,
    ) -> float:
        return self.estimate_entry_cost_pct(
            entry_order_type,
            volume_ratio,
        ) + self.estimate_entry_cost_pct(exit_order_type, volume_ratio)

    def submit_order(
        self,
        request: OrderRequest,
        market_price: float,
        candle_index: int | None = None,
        volume_ratio: float = 1.0,
    ) -> OrderResult:
        self._sequence += 1
        fee_rate = self.fee_rate_for(request.order_type)
        fill_price = self._execution_price(
            request.side,
            market_price,
            request.order_type,
            volume_ratio,
        )
        notional = fill_price * request.quantity
        fee = notional * fee_rate
        slippage_pct = self.slippage_pct_for(request.side, request.order_type, market_price, fill_price)

        if request.side is OrderSide.BUY:
            total_cost = notional + fee
            if total_cost > self.cash:
                return OrderResult(
                    order_id=f"paper-{self._sequence}",
                    symbol=request.symbol,
                    side=request.side,
                    quantity=0.0,
                    fill_price=fill_price,
                    fee_paid=0.0,
                    executed_at=request.requested_at,
                    status="rejected",
                    reason="insufficient_cash",
                    order_type=request.order_type,
                    reference_price=market_price,
                    fee_rate=fee_rate,
                )
            self.cash -= total_cost
            self.positions[request.symbol] = Position(
                symbol=request.symbol,
                quantity=request.quantity,
                entry_price=fill_price,
                entry_time=request.requested_at,
                entry_index=candle_index if candle_index is not None else self._sequence,
                entry_fee_paid=fee,
                entry_confidence=request.confidence,
                entry_order_type=request.order_type,
                entry_reference_price=market_price,
                entry_slippage_pct=slippage_pct,
                entry_fee_rate=fee_rate,
            )
            return OrderResult(
                order_id=f"paper-{self._sequence}",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                fill_price=fill_price,
                fee_paid=fee,
                executed_at=request.requested_at,
                status="filled",
                reason=request.reason,
                order_type=request.order_type,
                reference_price=market_price,
                slippage_pct=slippage_pct,
                fee_rate=fee_rate,
            )

        position = self.positions.get(request.symbol)
        if position is None or request.quantity > position.quantity:
            return OrderResult(
                order_id=f"paper-{self._sequence}",
                symbol=request.symbol,
                side=request.side,
                quantity=0.0,
                fill_price=fill_price,
                fee_paid=0.0,
                executed_at=request.requested_at,
                status="rejected",
                reason="insufficient_position",
                order_type=request.order_type,
                reference_price=market_price,
                fee_rate=fee_rate,
            )

        proceeds = notional - fee
        self.cash += proceeds
        entry_fee_allocated = position.entry_fee_paid * (request.quantity / position.quantity)
        pnl = (fill_price - position.entry_price) * request.quantity - fee - entry_fee_allocated
        self.realized_pnl += pnl
        self.closed_trades.append(
            TradeRecord(
                symbol=request.symbol,
                entry_time=position.entry_time,
                exit_time=request.requested_at,
                entry_price=position.entry_price,
                exit_price=fill_price,
                quantity=request.quantity,
                pnl=pnl,
                pnl_pct=(
                    pnl / max(1.0, (position.entry_price * request.quantity) + entry_fee_allocated)
                ),
                exit_reason=request.reason,
                entry_confidence=position.entry_confidence,
                entry_order_type=position.entry_order_type,
                exit_order_type=request.order_type,
                entry_reference_price=position.entry_reference_price,
                exit_reference_price=market_price,
                entry_fee_paid=entry_fee_allocated,
                exit_fee_paid=fee,
                entry_slippage_pct=position.entry_slippage_pct,
                exit_slippage_pct=slippage_pct,
            )
        )
        remaining = position.quantity - request.quantity
        if remaining <= 0:
            self.positions.pop(request.symbol, None)
        else:
            self.positions[request.symbol] = Position(
                symbol=position.symbol,
                quantity=remaining,
                entry_price=position.entry_price,
                entry_time=position.entry_time,
                entry_index=position.entry_index,
                entry_fee_paid=position.entry_fee_paid - entry_fee_allocated,
                entry_confidence=position.entry_confidence,
                entry_order_type=position.entry_order_type,
                entry_reference_price=position.entry_reference_price,
                entry_slippage_pct=position.entry_slippage_pct,
                entry_fee_rate=position.entry_fee_rate,
            )

        return OrderResult(
            order_id=f"paper-{self._sequence}",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            fill_price=fill_price,
            fee_paid=fee,
            executed_at=request.requested_at,
            status="filled",
            reason=request.reason,
            order_type=request.order_type,
            reference_price=market_price,
            slippage_pct=slippage_pct,
            fee_rate=fee_rate,
        )

    def equity(self, prices: Mapping[str, float]) -> float:
        return self.cash + sum(
            position.quantity * prices.get(symbol, position.entry_price)
            for symbol, position in self.positions.items()
        )

    def unrealized_positions(self, prices: Mapping[str, float]) -> dict[str, float]:
        return {
            symbol: (prices.get(symbol, position.entry_price) - position.entry_price)
            * position.quantity
            for symbol, position in self.positions.items()
        }

    def fee_rate_for(self, order_type: OrderType) -> float:
        if order_type is OrderType.LIMIT:
            return self._maker_fee_rate
        return self._fee_rate

    def estimate_slippage_pct(
        self,
        order_type: OrderType,
        volume_ratio: float = 1.0,
    ) -> float:
        adjusted = self._slippage_adjustment(volume_ratio)
        if order_type is OrderType.LIMIT:
            return -adjusted * 0.5
        return adjusted

    def slippage_pct_for(
        self,
        side: OrderSide,
        order_type: OrderType,
        market_price: float,
        fill_price: float,
    ) -> float:
        if market_price <= 0:
            return 0.0
        if side is OrderSide.BUY:
            return (fill_price - market_price) / market_price
        return (market_price - fill_price) / market_price

    def _execution_price(
        self,
        side: OrderSide,
        market_price: float,
        order_type: OrderType,
        volume_ratio: float = 1.0,
    ) -> float:
        slippage_pct = self.estimate_slippage_pct(order_type, volume_ratio)
        if side is OrderSide.BUY:
            return market_price * (1.0 + slippage_pct)
        return market_price * (1.0 - slippage_pct)

    def _slippage_adjustment(
        self,
        volume_ratio: float = 1.0,
    ) -> float:
        """Apply slippage adjusted by volume liquidity.

        volume_ratio = current_volume / avg_volume.
        High volume (>2x) → 40% less slippage (deeper liquidity).
        Low volume (<0.5x) → 50% more slippage (thin book).
        """
        adjusted = self._slippage_pct
        if volume_ratio > 2.0:
            adjusted *= 0.6  # 40% reduction in liquid markets
        elif volume_ratio < 0.5:
            adjusted *= 1.5  # 50% penalty in thin markets
        return adjusted

    def _apply_slippage(
        self,
        side: OrderSide,
        market_price: float,
        volume_ratio: float = 1.0,
    ) -> float:
        return self._execution_price(side, market_price, OrderType.MARKET, volume_ratio)
