from __future__ import annotations

from typing import Protocol

from crypto_trader.config import BacktestConfig, RegimeConfig
from crypto_trader.models import BacktestResult, Candle, Position, Signal, SignalAction, TradeRecord
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.regime import MarketRegime, RegimeDetector


class _StrategyProtocol(Protocol):
    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal: ...


class BacktestEngine:
    REGIME_SIZE_MULT = {
        MarketRegime.BULL: 1.2,
        MarketRegime.SIDEWAYS: 1.0,
        MarketRegime.BEAR: 0.6,
    }

    def __init__(
        self,
        strategy: _StrategyProtocol,
        risk_manager: RiskManager,
        config: BacktestConfig,
        symbol: str,
        regime_aware: bool = False,
    ) -> None:
        self._strategy = strategy
        self._risk_manager = risk_manager
        self._config = config
        self._symbol = symbol
        self._regime_aware = regime_aware
        self._regime_detector = RegimeDetector(RegimeConfig()) if regime_aware else None

    def run(self, candles: list[Candle]) -> BacktestResult:
        cash = self._config.initial_capital
        equity_curve: list[float] = [cash]
        trades: list[TradeRecord] = []
        open_position: Position | None = None
        realized_pnl = 0.0

        for index in range(len(candles)):
            window = candles[: index + 1]
            current = window[-1]
            market_price = current.close

            if index >= 15:
                self._risk_manager.update_atr_from_candles(window)

            if open_position is not None:
                exit_reason = self._risk_manager.exit_reason(open_position, market_price)
                signal = self._strategy.evaluate(window, open_position)
                if exit_reason is None and signal.action is SignalAction.SELL:
                    exit_reason = signal.reason

                if exit_reason is not None:
                    exit_price = market_price * (1.0 - self._config.slippage_pct)
                    gross = open_position.quantity * exit_price
                    exit_fee = gross * self._config.fee_rate
                    cash += gross - exit_fee
                    pnl = (
                        (exit_price - open_position.entry_price) * open_position.quantity
                        - exit_fee
                        - open_position.entry_fee_paid
                    )
                    realized_pnl += pnl
                    pnl_pct = (
                        pnl
                        / max(
                            1.0,
                            (open_position.entry_price * open_position.quantity)
                            + open_position.entry_fee_paid,
                        )
                    )
                    trades.append(
                        TradeRecord(
                            symbol=self._symbol,
                            entry_time=open_position.entry_time,
                            exit_time=current.timestamp,
                            entry_price=open_position.entry_price,
                            exit_price=exit_price,
                            quantity=open_position.quantity,
                            pnl=pnl,
                            pnl_pct=pnl_pct,
                            exit_reason=exit_reason,
                        )
                    )
                    self._risk_manager.record_trade(pnl_pct)
                    open_position = None

            if open_position is None:
                signal = self._strategy.evaluate(window, None)
                can_open = self._risk_manager.can_open(
                    active_positions=0,
                    realized_pnl=realized_pnl,
                    starting_equity=self._config.initial_capital,
                )
                if can_open and signal.action is SignalAction.BUY:
                    fill_price = market_price * (1.0 + self._config.slippage_pct)
                    regime_mult = 1.0
                    if self._regime_aware and self._regime_detector is not None and index >= 31:
                        regime = self._regime_detector.detect(window)
                        regime_mult = self.REGIME_SIZE_MULT.get(regime, 1.0)
                    quantity = self._risk_manager.size_position(cash, fill_price, regime_mult)
                    if quantity > 0:
                        gross = quantity * fill_price
                        fee = gross * self._config.fee_rate
                        total_cost = gross + fee
                        if total_cost <= cash:
                            cash -= total_cost
                            open_position = Position(
                                symbol=self._symbol,
                                quantity=quantity,
                                entry_price=fill_price,
                                entry_time=current.timestamp,
                                entry_index=index,
                                entry_fee_paid=fee,
                            )

            marked_equity = cash
            if open_position is not None:
                marked_equity += open_position.quantity * market_price
            equity_curve.append(marked_equity)

        if open_position is not None:
            final_candle = candles[-1]
            exit_price = final_candle.close * (1.0 - self._config.slippage_pct)
            gross = open_position.quantity * exit_price
            exit_fee = gross * self._config.fee_rate
            cash += gross - exit_fee
            pnl = (
                (exit_price - open_position.entry_price) * open_position.quantity
                - exit_fee
                - open_position.entry_fee_paid
            )
            trades.append(
                TradeRecord(
                    symbol=self._symbol,
                    entry_time=open_position.entry_time,
                    exit_time=final_candle.timestamp,
                    entry_price=open_position.entry_price,
                    exit_price=exit_price,
                    quantity=open_position.quantity,
                    pnl=pnl,
                    pnl_pct=(
                        pnl
                        / max(
                            1.0,
                            (open_position.entry_price * open_position.quantity)
                            + open_position.entry_fee_paid,
                        )
                    ),
                    exit_reason="forced_close_end_of_backtest",
                )
            )
            equity_curve[-1] = cash

        final_equity = cash
        gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
        gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
        win_count = sum(1 for trade in trades if trade.pnl > 0)
        win_rate = win_count / len(trades) if trades else 0.0
        if gross_loss:
            profit_factor = gross_profit / gross_loss
        elif gross_profit:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0
        max_drawdown = _max_drawdown(equity_curve)
        total_return_pct = (final_equity / self._config.initial_capital) - 1.0
        return BacktestResult(
            initial_capital=self._config.initial_capital,
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            trade_log=trades,
            equity_curve=equity_curve,
        )


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = 0.0 if peak == 0 else (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown
