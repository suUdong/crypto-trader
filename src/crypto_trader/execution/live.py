"""Live broker wrapping pyupbit for real order execution on Upbit."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

try:
    import pyupbit
except ImportError:  # pragma: no cover
    pyupbit = None

from crypto_trader.models import (
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    Position,
    TradeRecord,
)

logger = logging.getLogger(__name__)

_ORDER_POLL_INTERVAL = 0.5
_ORDER_POLL_TIMEOUT = 30.0
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.0

# Upbit minimum order amount in KRW
_MIN_ORDER_KRW = 5000


class LiveBroker:
    """Broker that submits real orders to Upbit via pyupbit."""

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        starting_cash: float,
        fee_rate: float = 0.0005,
    ) -> None:
        if not access_key or not secret_key:
            raise ValueError("Upbit API credentials required for LiveBroker")
        if pyupbit is None:
            raise ImportError("pyupbit is required for LiveBroker: pip install pyupbit")
        self._upbit = pyupbit.Upbit(access_key, secret_key)
        self.cash = starting_cash
        self._fee_rate = fee_rate
        self.positions: dict[str, Position] = {}
        self.closed_trades: list[TradeRecord] = []
        self.realized_pnl = 0.0
        self._sequence = 0

    def estimate_entry_cost_pct(
        self,
        order_type: OrderType,
        volume_ratio: float = 1.0,
    ) -> float:
        return self._fee_rate

    def estimate_round_trip_cost_pct(
        self,
        entry_order_type: OrderType,
        volume_ratio: float = 1.0,
        exit_order_type: OrderType = OrderType.MARKET,
    ) -> float:
        return self._fee_rate * 2

    def submit_order(
        self,
        request: OrderRequest,
        market_price: float,
        candle_index: int | None = None,
        volume_ratio: float = 1.0,
    ) -> OrderResult:
        self._sequence += 1
        order_id = f"live-{self._sequence}"

        if request.side is OrderSide.BUY:
            return self._execute_buy(request, market_price, order_id, candle_index)
        return self._execute_sell(request, market_price, order_id)

    def equity(self, prices: Mapping[str, float]) -> float:
        return self.cash + sum(
            pos.quantity * prices.get(symbol, pos.entry_price)
            for symbol, pos in self.positions.items()
        )

    def _execute_buy(
        self,
        request: OrderRequest,
        market_price: float,
        order_id: str,
        candle_index: int | None,
    ) -> OrderResult:
        notional = market_price * request.quantity
        fee = notional * self._fee_rate
        total_cost = notional + fee

        if total_cost > self.cash:
            return self._rejected(request, market_price, order_id, "insufficient_cash")

        if notional < _MIN_ORDER_KRW:
            return self._rejected(request, market_price, order_id, "below_minimum_order")

        # Submit market buy via pyupbit (price param = total KRW to spend)
        upbit_resp = self._submit_with_retry(
            lambda: self._upbit.buy_market_order(request.symbol, notional),
            request.symbol,
            "buy",
        )
        if upbit_resp is None:
            return self._rejected(request, market_price, order_id, "exchange_error")

        upbit_uuid = upbit_resp.get("uuid", order_id)
        fill = self._poll_fill(upbit_uuid)
        fill_price = fill.get("price", market_price)
        fill_qty = fill.get("volume", request.quantity)
        actual_fee = fill.get("paid_fee", fee)

        self.cash -= (fill_price * fill_qty) + actual_fee
        self.positions[request.symbol] = Position(
            symbol=request.symbol,
            quantity=fill_qty,
            entry_price=fill_price,
            entry_time=request.requested_at,
            entry_index=candle_index if candle_index is not None else self._sequence,
            entry_fee_paid=actual_fee,
            entry_confidence=request.confidence,
            entry_order_type=request.order_type,
            entry_reference_price=market_price,
            entry_slippage_pct=(
                (fill_price - market_price) / market_price if market_price > 0 else 0.0
            ),
            entry_fee_rate=self._fee_rate,
        )

        logger.info(
            "BUY filled: %s qty=%.8f price=%.0f fee=%.0f",
            request.symbol,
            fill_qty,
            fill_price,
            actual_fee,
        )

        return OrderResult(
            order_id=upbit_uuid,
            symbol=request.symbol,
            side=request.side,
            quantity=fill_qty,
            fill_price=fill_price,
            fee_paid=actual_fee,
            executed_at=datetime.now(UTC),
            status="filled",
            reason=request.reason,
            order_type=request.order_type,
            reference_price=market_price,
            slippage_pct=(fill_price - market_price) / market_price if market_price > 0 else 0.0,
            fee_rate=self._fee_rate,
        )

    def _execute_sell(
        self,
        request: OrderRequest,
        market_price: float,
        order_id: str,
    ) -> OrderResult:
        position = self.positions.get(request.symbol)
        if position is None or request.quantity > position.quantity:
            return self._rejected(request, market_price, order_id, "insufficient_position")

        # Submit market sell via pyupbit (volume param = quantity to sell)
        upbit_resp = self._submit_with_retry(
            lambda: self._upbit.sell_market_order(request.symbol, request.quantity),
            request.symbol,
            "sell",
        )
        if upbit_resp is None:
            return self._rejected(request, market_price, order_id, "exchange_error")

        upbit_uuid = upbit_resp.get("uuid", order_id)
        fill = self._poll_fill(upbit_uuid)
        fill_price = fill.get("price", market_price)
        fill_qty = fill.get("volume", request.quantity)
        actual_fee = fill.get("paid_fee", self._fee_rate * fill_price * fill_qty)

        proceeds = fill_price * fill_qty - actual_fee
        self.cash += proceeds

        entry_fee_allocated = position.entry_fee_paid * (fill_qty / position.quantity)
        pnl = (fill_price - position.entry_price) * fill_qty - actual_fee - entry_fee_allocated
        self.realized_pnl += pnl

        self.closed_trades.append(
            TradeRecord(
                symbol=request.symbol,
                entry_time=position.entry_time,
                exit_time=datetime.now(UTC),
                entry_price=position.entry_price,
                exit_price=fill_price,
                quantity=fill_qty,
                pnl=pnl,
                pnl_pct=pnl / max(1.0, position.entry_price * fill_qty + entry_fee_allocated),
                exit_reason=request.reason,
                entry_confidence=position.entry_confidence,
                entry_order_type=position.entry_order_type,
                exit_order_type=request.order_type,
                entry_reference_price=position.entry_reference_price,
                exit_reference_price=market_price,
                entry_fee_paid=entry_fee_allocated,
                exit_fee_paid=actual_fee,
                entry_slippage_pct=position.entry_slippage_pct,
                exit_slippage_pct=(
                    (market_price - fill_price) / market_price if market_price > 0 else 0.0
                ),
            )
        )

        remaining = position.quantity - fill_qty
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

        logger.info(
            "SELL filled: %s qty=%.8f price=%.0f pnl=%.0f fee=%.0f",
            request.symbol,
            fill_qty,
            fill_price,
            pnl,
            actual_fee,
        )

        return OrderResult(
            order_id=upbit_uuid,
            symbol=request.symbol,
            side=request.side,
            quantity=fill_qty,
            fill_price=fill_price,
            fee_paid=actual_fee,
            executed_at=datetime.now(UTC),
            status="filled",
            reason=request.reason,
            order_type=request.order_type,
            reference_price=market_price,
            slippage_pct=(
                (market_price - fill_price) / market_price if market_price > 0 else 0.0
            ),
            fee_rate=self._fee_rate,
        )

    def _submit_with_retry(
        self,
        submit_fn: Callable[[], Any],
        symbol: str,
        side: str,
    ) -> dict[str, Any] | None:
        """Submit order with retry on transient failures."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = submit_fn()
                if resp is None:
                    logger.warning(
                        "Upbit %s %s returned None (attempt %d/%d)",
                        side,
                        symbol,
                        attempt,
                        _MAX_RETRIES,
                    )
                    if attempt < _MAX_RETRIES:
                        time.sleep(_RETRY_BACKOFF * attempt)
                        continue
                    return None
                if isinstance(resp, dict) and "error" in resp:
                    logger.error(
                        "Upbit %s %s error: %s (attempt %d/%d)",
                        side,
                        symbol,
                        resp["error"],
                        attempt,
                        _MAX_RETRIES,
                    )
                    if attempt < _MAX_RETRIES:
                        time.sleep(_RETRY_BACKOFF * attempt)
                        continue
                    return None
                result: dict[str, Any] = resp
                return result
            except Exception:
                logger.exception(
                    "Upbit %s %s exception (attempt %d/%d)",
                    side,
                    symbol,
                    attempt,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF * attempt)
        return None

    def _poll_fill(self, uuid: str) -> dict[str, Any]:
        """Poll Upbit for order fill details."""
        deadline = time.monotonic() + _ORDER_POLL_TIMEOUT
        while time.monotonic() < deadline:
            try:
                order = self._upbit.get_order(uuid)
                if order and order.get("state") in ("done", "cancel"):
                    return self._extract_fill(order)
            except Exception:
                logger.warning("Poll order %s failed, retrying", uuid)
            time.sleep(_ORDER_POLL_INTERVAL)

        logger.warning("Order %s poll timed out after %.0fs", uuid, _ORDER_POLL_TIMEOUT)
        return {}

    def _extract_fill(self, order: dict[str, Any]) -> dict[str, Any]:
        """Extract fill price and volume from Upbit order response."""
        trades = order.get("trades", [])
        if not trades:
            return {
                "price": float(order.get("price", 0)),
                "volume": float(order.get("executed_volume", 0)),
                "paid_fee": float(order.get("paid_fee", 0)),
            }
        total_value = sum(float(t["price"]) * float(t["volume"]) for t in trades)
        total_volume = sum(float(t["volume"]) for t in trades)
        avg_price = total_value / total_volume if total_volume > 0 else 0
        return {
            "price": avg_price,
            "volume": total_volume,
            "paid_fee": float(order.get("paid_fee", 0)),
        }

    def _rejected(
        self,
        request: OrderRequest,
        market_price: float,
        order_id: str,
        reason: str,
    ) -> OrderResult:
        return OrderResult(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=0.0,
            fill_price=market_price,
            fee_paid=0.0,
            executed_at=request.requested_at,
            status="rejected",
            reason=reason,
            order_type=request.order_type,
            reference_price=market_price,
            fee_rate=self._fee_rate,
        )
