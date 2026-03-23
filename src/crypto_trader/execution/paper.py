from __future__ import annotations

from collections.abc import Mapping

from crypto_trader.models import OrderRequest, OrderResult, OrderSide, Position


class PaperBroker:
    def __init__(self, starting_cash: float, fee_rate: float, slippage_pct: float) -> None:
        self.cash = starting_cash
        self._fee_rate = fee_rate
        self._slippage_pct = slippage_pct
        self.positions: dict[str, Position] = {}
        self.realized_pnl = 0.0
        self._sequence = 0

    def submit_order(self, request: OrderRequest, market_price: float) -> OrderResult:
        self._sequence += 1
        fill_price = self._apply_slippage(request.side, market_price)
        notional = fill_price * request.quantity
        fee = notional * self._fee_rate

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
                )
            self.cash -= total_cost
            self.positions[request.symbol] = Position(
                symbol=request.symbol,
                quantity=request.quantity,
                entry_price=fill_price,
                entry_time=request.requested_at,
                entry_fee_paid=fee,
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
            )

        proceeds = notional - fee
        self.cash += proceeds
        entry_fee_allocated = position.entry_fee_paid * (request.quantity / position.quantity)
        pnl = (fill_price - position.entry_price) * request.quantity - fee - entry_fee_allocated
        self.realized_pnl += pnl
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
        )

    def equity(self, prices: Mapping[str, float]) -> float:
        return self.cash + sum(
            position.quantity * prices.get(symbol, position.entry_price)
            for symbol, position in self.positions.items()
        )

    def _apply_slippage(self, side: OrderSide, market_price: float) -> float:
        if side is OrderSide.BUY:
            return market_price * (1.0 + self._slippage_pct)
        return market_price * (1.0 - self._slippage_pct)
