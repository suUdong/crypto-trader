from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone

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
from crypto_trader.strategy.evaluator import evaluate_strategy

KST = timezone(timedelta(hours=9))
# Block new entries during low-liquidity / high-drift KST windows.
# 00:00-07:59 KST was the original "Asian off-hours" block. 2026-05-11 audit
# (research/reports/fire-w11-ct-paper-audit.md) attributes ₩-117,938 of paper
# loss to 23:00-02:00 KST entries — hour 23 escaped the original window, so
# extend the blackout set to include it.
_BLACKOUT_HOURS_KST: frozenset[int] = frozenset({23, 0, 1, 2, 3, 4, 5, 6, 7})
# Kept as legacy aliases for any downstream code referencing the bounds.
_LOW_LIQUIDITY_START = 0  # 00:00 KST
_LOW_LIQUIDITY_END = 8    # 08:00 KST


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
            self._risk_manager.update_atr_from_candles(candles)
            now = candles[-1].timestamp if candles else datetime.utcnow()
            position = self._broker.positions.get(symbol)
            signal = evaluate_strategy(self._strategy, candles, position, symbol=symbol)
            latest_price = candles[-1].close
            order: OrderResult | None = None

            # Block entries during low-liquidity / high-drift KST windows
            # (00:00-07:59 + 23:00 — see _BLACKOUT_HOURS_KST docstring).
            kst_hour = now.astimezone(KST).hour if now.tzinfo else now.replace(
                tzinfo=UTC
            ).astimezone(KST).hour
            low_liquidity = kst_hour in _BLACKOUT_HOURS_KST

            if position is None and signal.action is SignalAction.BUY and low_liquidity:
                self._logger.info(
                    "%s BUY blocked: low-liquidity hours (KST %02d:00)", symbol, kst_hour
                )
                signal = Signal(
                    action=SignalAction.HOLD,
                    reason="low_liquidity_hours",
                    confidence=0.0,
                )

            if position is None and signal.action is SignalAction.BUY:
                marked_equity = self._broker.equity({symbol: latest_price})
                if self._risk_manager.can_open(
                    active_positions=len(self._broker.positions),
                    realized_pnl=self._broker.realized_pnl,
                    starting_equity=self._session_starting_equity,
                    current_equity=marked_equity,
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
                        # Freeze ATR at entry for consistent stop-loss calculation
                        new_pos = self._broker.positions.get(symbol)
                        if new_pos is not None and order is not None and order.status == "filled":
                            new_pos.entry_atr = self._risk_manager._current_atr
            elif position is not None:
                marked_equity = self._broker.equity({symbol: latest_price})
                if self._risk_manager.should_force_exit(
                    self._broker.realized_pnl,
                    self._session_starting_equity,
                    marked_equity,
                ):
                    order = self._broker.submit_order(
                        OrderRequest(
                            symbol=symbol,
                            side=OrderSide.SELL,
                            quantity=position.quantity,
                            requested_at=now,
                            reason="circuit_breaker",
                        ),
                        latest_price,
                    )
                    if order is not None and order.status == "filled":
                        self._risk_manager.record_trade(position.pnl_pct(order.fill_price))
                else:
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
            f"{symbol} price={latest_price:.2f} signal={signal.action.value} reason={signal.reason}"
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
