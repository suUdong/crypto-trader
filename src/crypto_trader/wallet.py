from __future__ import annotations

import logging
from typing import Protocol

from crypto_trader.config import AppConfig, RegimeConfig, StrategyConfig, WalletConfig
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import (
    Candle,
    OrderRequest,
    OrderResult,
    OrderSide,
    PipelineResult,
    Position,
    Signal,
    SignalAction,
)
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.kimchi_premium import KimchiPremiumStrategy
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy
from crypto_trader.strategy.momentum import MomentumStrategy
from crypto_trader.strategy.obi import OBIStrategy
from crypto_trader.strategy.vpin import VPINStrategy


class StrategyProtocol(Protocol):
    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal: ...


def create_strategy(
    strategy_type: str,
    strategy_config: StrategyConfig,
    regime_config: RegimeConfig,
) -> StrategyProtocol:
    if strategy_type == "momentum":
        return MomentumStrategy(strategy_config, regime_config)
    if strategy_type == "mean_reversion":
        return MeanReversionStrategy(strategy_config, regime_config)
    if strategy_type == "kimchi_premium":
        return KimchiPremiumStrategy(strategy_config)
    if strategy_type == "obi":
        return OBIStrategy(strategy_config)
    if strategy_type == "vpin":
        return VPINStrategy(strategy_config)
    return CompositeStrategy(strategy_config, regime_config)


class StrategyWallet:
    def __init__(
        self,
        wallet_config: WalletConfig,
        strategy: StrategyProtocol,
        broker: PaperBroker,
        risk_manager: RiskManager,
    ) -> None:
        self.name = wallet_config.name
        self.strategy_type = wallet_config.strategy
        self.strategy = strategy
        self.broker = broker
        self.risk_manager = risk_manager
        self.session_starting_equity = broker.cash
        self._logger = logging.getLogger(f"{__name__}.{self.name}")
        self._macro_multiplier: float = 1.0

    def set_macro_multiplier(self, multiplier: float) -> None:
        self._macro_multiplier = multiplier

    def run_once(self, symbol: str, candles: list[Candle]) -> PipelineResult:
        try:
            position = self.broker.positions.get(symbol)
            signal = self.strategy.evaluate(candles, position)
            latest_price = candles[-1].close
            order: OrderResult | None = None

            if position is None and signal.action is SignalAction.BUY:
                if self.risk_manager.can_open(
                    active_positions=len(self.broker.positions),
                    realized_pnl=self.broker.realized_pnl,
                    starting_equity=self.session_starting_equity,
                ):
                    quantity = self.risk_manager.size_position(
                        self.broker.cash, latest_price, self._macro_multiplier,
                    )
                    if quantity > 0:
                        now = candles[-1].timestamp
                        order = self.broker.submit_order(
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
                exit_reason = self.risk_manager.exit_reason(position, latest_price)
                should_sell = signal.action is SignalAction.SELL or exit_reason is not None
                if should_sell:
                    now = candles[-1].timestamp
                    order = self.broker.submit_order(
                        OrderRequest(
                            symbol=symbol,
                            side=OrderSide.SELL,
                            quantity=position.quantity,
                            requested_at=now,
                            reason=exit_reason or signal.reason,
                        ),
                        latest_price,
                    )

            message = (
                f"[{self.name}] {symbol} price={latest_price:.2f} "
                f"signal={signal.action.value} reason={signal.reason}"
            )
            if order is not None:
                message += (
                    f" order={order.status} side={order.side.value} "
                    f"qty={order.quantity:.8f} fill={order.fill_price:.2f}"
                )
            return PipelineResult(
                symbol=symbol,
                signal=signal,
                order=order,
                message=message,
                latest_price=latest_price,
            )
        except Exception as exc:
            self._logger.exception("Wallet %s failed for %s", self.name, symbol)
            signal = Signal(action=SignalAction.HOLD, reason="wallet_error", confidence=0.0)
            return PipelineResult(
                symbol=symbol,
                signal=signal,
                order=None,
                message=f"[{self.name}] {symbol} error={exc}",
                latest_price=None,
                error=str(exc),
            )


def build_wallets(config: AppConfig) -> list[StrategyWallet]:
    wallets: list[StrategyWallet] = []
    for wc in config.wallets:
        strategy = create_strategy(wc.strategy, config.strategy, config.regime)
        broker = PaperBroker(
            starting_cash=wc.initial_capital,
            fee_rate=config.backtest.fee_rate,
            slippage_pct=config.backtest.slippage_pct,
        )
        risk_manager = RiskManager(config.risk)
        wallets.append(StrategyWallet(wc, strategy, broker, risk_manager))
    return wallets
