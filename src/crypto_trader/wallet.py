from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol

from crypto_trader.config import (
    AppConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
    WalletConfig,
)
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
from crypto_trader.strategy.consensus import ConsensusStrategy
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.strategy.evaluator import evaluate_strategy
from crypto_trader.strategy.kimchi_premium import KimchiPremiumStrategy
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy
from crypto_trader.strategy.momentum import MomentumStrategy
from crypto_trader.strategy.obi import OBIStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy
from crypto_trader.strategy.volume_spike import VolumeSpikeStrategy
from crypto_trader.strategy.vpin import VPINStrategy


class StrategyProtocol(Protocol):
    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal: ...


def create_strategy(
    strategy_type: str,
    strategy_config: StrategyConfig,
    regime_config: RegimeConfig,
    extra_params: Mapping[str, Any] | None = None,
) -> StrategyProtocol:
    params = extra_params or {}
    if strategy_type == "momentum":
        return MomentumStrategy(strategy_config, regime_config)
    if strategy_type == "mean_reversion":
        return MeanReversionStrategy(strategy_config, regime_config)
    if strategy_type == "kimchi_premium":
        return KimchiPremiumStrategy(
            strategy_config,
            min_trade_interval_bars=int(params.get("min_trade_interval_bars", 12)),
            min_confidence=float(params.get("min_confidence", 0.6)),
            cooldown_hours=float(params.get("cooldown_hours", 24.0)),
        )
    if strategy_type == "obi":
        return OBIStrategy(strategy_config)
    if strategy_type == "vpin":
        return VPINStrategy(
            strategy_config,
            vpin_high_threshold=float(params.get("vpin_high_threshold", 0.7)),
            vpin_low_threshold=float(params.get("vpin_low_threshold", 0.45)),
            bucket_count=int(params.get("bucket_count", 20)),
            vpin_momentum_threshold=float(params.get("vpin_momentum_threshold", 0.01)),
            vpin_rsi_ceiling=float(params.get("vpin_rsi_ceiling", 70.0)),
            vpin_rsi_floor=float(params.get("vpin_rsi_floor", 30.0)),
        )
    if strategy_type == "ema_crossover":
        return EMACrossoverStrategy(strategy_config)
    if strategy_type == "volatility_breakout":
        return VolatilityBreakoutStrategy(
            strategy_config,
            k_base=strategy_config.k_base,
            noise_lookback=strategy_config.noise_lookback,
            ma_filter_period=strategy_config.ma_filter_period,
            max_holding_bars=strategy_config.max_holding_bars,
        )
    if strategy_type == "volume_spike":
        return VolumeSpikeStrategy(
            strategy_config,
            regime_config,
            spike_mult=float(params.get("spike_mult", 2.5)),
            volume_window=int(params.get("volume_window", 20)),
            min_body_ratio=float(params.get("min_body_ratio", 0.4)),
        )
    if strategy_type == "consensus":
        sub_strategy_names = params.get("sub_strategies", ["momentum", "vpin", "ema_crossover"])
        min_agree = int(params.get("min_agree", 2))
        sub_strategies = [
            create_strategy(name, strategy_config, regime_config, extra_params=params)
            for name in sub_strategy_names
            if name != "consensus"  # prevent recursion
        ]
        min_confidence_sum = float(params.get("min_confidence_sum", 0.0))
        weights_raw = params.get("weights")
        weights = [float(w) for w in weights_raw] if weights_raw else None
        quorum_threshold = float(params.get("quorum_threshold", 0.0))
        exit_mode = str(params.get("exit_mode", "any"))
        return ConsensusStrategy(
            sub_strategies,
            min_agree=min_agree,
            min_confidence_sum=min_confidence_sum,
            weights=weights,
            quorum_threshold=quorum_threshold,
            exit_mode=exit_mode,
        )
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
        self.allowed_symbols: set[str] = (
            set(wallet_config.symbols) if wallet_config.symbols else set()
        )
        self.session_starting_equity = broker.cash
        self._logger = logging.getLogger(f"{__name__}.{self.name}")
        self._macro_multiplier: float = 1.0

    def set_macro_multiplier(self, multiplier: float) -> None:
        self._macro_multiplier = multiplier

    def run_once(self, symbol: str, candles: list[Candle]) -> PipelineResult:
        try:
            self.risk_manager.update_atr_from_candles(candles)
            self.risk_manager.tick_cooldown()
            position = self.broker.positions.get(symbol)
            signal = evaluate_strategy(self.strategy, candles, position, symbol=symbol)
            latest_price = candles[-1].close
            order: OrderResult | None = None

            if (
                position is None
                and signal.action is SignalAction.BUY
                and signal.confidence >= self.risk_manager.effective_min_confidence
                and not self.risk_manager.in_cooldown
                and not self.risk_manager.is_auto_paused
            ):
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
                            candle_index=len(candles) - 1,
                        )
            elif position is not None:
                # Circuit breaker: force-close when daily loss limit hit
                if self.risk_manager.should_force_exit(
                    self.broker.realized_pnl, self.session_starting_equity,
                ):
                    now = candles[-1].timestamp
                    order = self.broker.submit_order(
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
                        entry_value = position.entry_price * position.quantity
                        if entry_value > 0:
                            pnl_pct = (
                                order.fill_price - position.entry_price
                            ) / position.entry_price
                            self.risk_manager.record_trade(pnl_pct)
                    message = (
                        f"[{self.name}] {symbol} price={latest_price:.2f} "
                        f"signal=CIRCUIT_BREAKER reason=daily_loss_limit"
                    )
                    if order is not None:
                        message += (
                            f" order={order.status} side={order.side.value} "
                            f"qty={order.quantity:.8f} fill={order.fill_price:.2f}"
                        )
                    return PipelineResult(
                        symbol=symbol,
                        signal=Signal(
                            action=SignalAction.SELL,
                            reason="circuit_breaker",
                            confidence=1.0,
                        ),
                        order=order,
                        message=message,
                        latest_price=latest_price,
                    )

                holding_bars = (
                    0 if position.entry_index is None
                    else len(candles) - position.entry_index - 1
                )
                exit_reason = self.risk_manager.exit_reason(
                    position, latest_price, holding_bars=holding_bars,
                )
                should_sell = signal.action is SignalAction.SELL or exit_reason is not None
                if should_sell:
                    now = candles[-1].timestamp
                    # Partial take-profit: sell only a fraction, mark position
                    if exit_reason == "partial_take_profit":
                        sell_qty = position.quantity * self.risk_manager._config.partial_tp_pct
                        sell_qty = max(sell_qty, 1e-8)  # floor
                    else:
                        sell_qty = position.quantity
                    order = self.broker.submit_order(
                        OrderRequest(
                            symbol=symbol,
                            side=OrderSide.SELL,
                            quantity=sell_qty,
                            requested_at=now,
                            reason=exit_reason or signal.reason,
                        ),
                        latest_price,
                    )
                    # Mark partial TP taken so it doesn't re-trigger
                    if (
                        exit_reason == "partial_take_profit"
                        and order is not None
                        and order.status == "filled"
                    ):
                        remaining_pos = self.broker.positions.get(symbol)
                        if remaining_pos is not None:
                            remaining_pos.partial_tp_taken = True
                    if (
                        order is not None
                        and order.status == "filled"
                        and order.side is OrderSide.SELL
                    ):
                        entry_value = position.entry_price * position.quantity
                        if entry_value > 0:
                            pnl_pct = (
                                order.fill_price - position.entry_price
                            ) / position.entry_price
                            self.risk_manager.record_trade(pnl_pct)

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
        strategy_config = _strategy_config_for_wallet(config.strategy, wc)
        risk_config = _risk_config_for_wallet(config, wc)
        strategy = create_strategy(
            wc.strategy,
            strategy_config,
            config.regime,
            wc.strategy_overrides,
        )
        broker = PaperBroker(
            starting_cash=wc.initial_capital,
            fee_rate=config.backtest.fee_rate,
            slippage_pct=config.backtest.slippage_pct,
        )
        risk_manager = RiskManager(
            risk_config,
            trailing_stop_pct=risk_config.trailing_stop_pct,
            atr_stop_multiplier=risk_config.atr_stop_multiplier,
        )
        wallets.append(StrategyWallet(wc, strategy, broker, risk_manager))
    return wallets


def _strategy_config_for_wallet(
    base: StrategyConfig,
    wallet_config: WalletConfig,
) -> StrategyConfig:
    strategy_fields = set(StrategyConfig.__dataclass_fields__)
    overrides = {
        key: value
        for key, value in wallet_config.strategy_overrides.items()
        if key in strategy_fields
    }
    return replace(base, **overrides)


def _risk_config_for_wallet(config: AppConfig, wallet_config: WalletConfig) -> RiskConfig:
    risk_fields = set(type(config.risk).__dataclass_fields__)
    overrides = {
        key: value
        for key, value in wallet_config.risk_overrides.items()
        if key in risk_fields
    }
    return replace(config.risk, **overrides)
