from __future__ import annotations

import logging
from datetime import datetime

from crypto_trader.config import AppConfig
from crypto_trader.data.base import MarketDataClient
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import (
    OrderRequest,
    OrderResult,
    OrderSide,
    PipelineResult,
    Signal,
    SignalAction,
)
from crypto_trader.notifications.telegram import Notifier
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy


class TradingPipeline:
    def __init__(
        self,
        config: AppConfig,
        market_data: MarketDataClient,
        strategy: CompositeStrategy,
        risk_manager: RiskManager,
        broker: PaperBroker,
        notifier: Notifier,
    ) -> None:
        self._config = config
        self._market_data = market_data
        self._strategy = strategy
        self._risk_manager = risk_manager
        self._broker = broker
        self._notifier = notifier
        self._logger = logging.getLogger(__name__)
        self._session_starting_equity = broker.cash

    @property
    def broker(self) -> PaperBroker:
        return self._broker

    @property
    def session_starting_equity(self) -> float:
        return self._session_starting_equity

    def run_once(self) -> PipelineResult:
        symbol = self._config.trading.symbol
        try:
            candles = self._market_data.get_ohlcv(
                symbol=symbol,
                interval=self._config.trading.interval,
                count=self._config.trading.candle_count,
            )
            now = candles[-1].timestamp if candles else datetime.utcnow()
            position = self._broker.positions.get(symbol)
            signal = self._strategy.evaluate(candles, position)
            latest_price = candles[-1].close
            order: OrderResult | None = None

            if position is None and signal.action is SignalAction.BUY:
                if self._risk_manager.can_open(
                    active_positions=len(self._broker.positions),
                    realized_pnl=self._broker.realized_pnl,
                    starting_equity=self._session_starting_equity,
                ):
                    quantity = self._risk_manager.size_position(self._broker.cash, latest_price)
                    if quantity > 0:
                        order = self._broker.submit_order(
                            OrderRequest(
                                symbol=symbol,
                                side=OrderSide.BUY,
                                quantity=quantity,
                                requested_at=now,
                                reason=signal.reason,
                            ),
                            latest_price,
                        )
            elif position is not None:
                exit_reason = self._risk_manager.exit_reason(position, latest_price)
                should_sell = signal.action is SignalAction.SELL or exit_reason is not None
                if should_sell:
                    order = self._broker.submit_order(
                        OrderRequest(
                            symbol=symbol,
                            side=OrderSide.SELL,
                            quantity=position.quantity,
                            requested_at=now,
                            reason=exit_reason or signal.reason,
                        ),
                        latest_price,
                    )

            message = self._format_message(symbol, latest_price, signal, order)
            self._safe_notify(message)
            return PipelineResult(
                symbol=symbol,
                signal=signal,
                order=order,
                message=message,
                latest_price=latest_price,
            )
        except Exception as exc:
            self._logger.exception("Pipeline iteration failed for %s", symbol)
            signal = Signal(
                action=SignalAction.HOLD,
                reason="pipeline_error",
                confidence=0.0,
            )
            message = f"{symbol} signal=hold reason=pipeline_error error={exc}"
            self._safe_notify(message)
            return PipelineResult(
                symbol=symbol,
                signal=signal,
                order=None,
                message=message,
                latest_price=None,
                error=str(exc),
            )

    def _format_message(
        self,
        symbol: str,
        latest_price: float,
        signal: Signal,
        order: OrderResult | None,
    ) -> str:
        base = (
            f"{symbol} price={latest_price:.2f} signal={signal.action.value} "
            f"reason={signal.reason}"
        )
        if order is None:
            return base
        return (
            f"{base} order_status={order.status} side={order.side.value} "
            f"qty={order.quantity:.8f} fill={order.fill_price:.2f}"
        )

    def _safe_notify(self, message: str) -> None:
        try:
            self._notifier.send_message(message)
        except Exception:
            self._logger.exception("Notification delivery failed")
