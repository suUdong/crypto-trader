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

        entry_bar: int = 0
        last_exit_bar: int = -10  # allow immediate first trade
        min_bars_between_trades: int = 2

        for index in range(len(candles)):
            window = candles[: index + 1]
            current = window[-1]
            market_price = current.close

            if index >= 15:
                self._risk_manager.update_atr_from_candles(window)

            self._risk_manager.tick_cooldown()

            if open_position is not None:
                holding_bars = index - entry_bar
                exit_reason = self._risk_manager.exit_reason(
                    open_position, market_price, holding_bars=holding_bars,
                )
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
                    last_exit_bar = index
                    open_position = None

            if open_position is None:
                signal = self._strategy.evaluate(window, None)
                can_open = self._risk_manager.can_open(
                    active_positions=0,
                    realized_pnl=realized_pnl,
                    starting_equity=self._config.initial_capital,
                )
                bars_since_exit = index - last_exit_bar
                if (
                    can_open
                    and not self._risk_manager.in_cooldown
                    and not self._risk_manager.is_auto_paused
                    and bars_since_exit >= min_bars_between_trades
                    and signal.action is SignalAction.BUY
                ):
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
                            entry_bar = index
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

        # Streak analysis
        max_consec_loss = 0
        max_consec_win = 0
        cur_loss = 0
        cur_win = 0
        for trade in trades:
            if trade.pnl < 0:
                cur_loss += 1
                max_consec_loss = max(max_consec_loss, cur_loss)
                cur_win = 0
            else:
                cur_win += 1
                max_consec_win = max(max_consec_win, cur_win)
                cur_loss = 0

        # Trade duration (in hours = bars for hourly candles)
        durations = []
        for trade in trades:
            dt = trade.exit_time - trade.entry_time
            durations.append(dt.total_seconds() / 3600.0)
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        max_duration = int(max(durations)) if durations else 0

        # Payoff ratio: avg win / avg loss
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [abs(t.pnl) for t in trades if t.pnl < 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        payoff = avg_win / avg_loss if avg_loss > 0 else 0.0

        # Expected value per trade: EV = (win_rate * avg_win) - ((1-win_rate) * avg_loss)
        ev_per_trade = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss) if trades else 0.0

        # Recovery factor: net profit / max drawdown
        net_profit = final_equity - self._config.initial_capital
        recovery = (
            net_profit / (max_drawdown * self._config.initial_capital)
            if max_drawdown > 0
            else 0.0
        )

        # Tail ratio: 95th percentile gain / abs(5th percentile loss)
        pnl_pcts = sorted([t.pnl_pct for t in trades])
        if len(pnl_pcts) >= 10:
            idx_5 = max(0, int(len(pnl_pcts) * 0.05))
            idx_95 = min(len(pnl_pcts) - 1, int(len(pnl_pcts) * 0.95))
            p5 = pnl_pcts[idx_5]
            p95 = pnl_pcts[idx_95]
            tail = p95 / abs(p5) if p5 < 0 else 0.0
        else:
            tail = 0.0

        # Sharpe ratio: annualized from equity curve periodic returns
        sharpe = _sharpe_ratio(equity_curve)
        sortino = _sortino_ratio(equity_curve)
        calmar = _calmar_ratio(equity_curve)
        rar = (
            total_return_pct / max_drawdown
            if max_drawdown > 0
            else (float("inf") if total_return_pct > 0 else 0.0)
        )

        return BacktestResult(
            initial_capital=self._config.initial_capital,
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            trade_log=trades,
            equity_curve=equity_curve,
            max_consecutive_losses=max_consec_loss,
            max_consecutive_wins=max_consec_win,
            avg_trade_duration_bars=avg_duration,
            max_trade_duration_bars=max_duration,
            payoff_ratio=payoff,
            expected_value_per_trade=ev_per_trade,
            recovery_factor=recovery,
            tail_ratio=tail,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            risk_adjusted_return=rar,
        )


def _sharpe_ratio(equity_curve: list[float], periods_per_year: float = 8760.0) -> float:
    """Annualized Sharpe ratio from equity curve.

    Assumes hourly bars (8760 hours/year). Uses excess returns (rf=0 for crypto).
    """
    if len(equity_curve) < 3:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std_ret = variance ** 0.5
    if std_ret == 0:
        return 0.0
    return float((mean_ret / std_ret) * (periods_per_year ** 0.5))


def _sortino_ratio(equity_curve: list[float], periods_per_year: float = 8760.0) -> float:
    """Annualized Sortino ratio from equity curve.

    Like Sharpe but only penalizes downside volatility (negative returns).
    """
    if len(equity_curve) < 3:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    downside = [r for r in returns if r < 0]
    if not downside:
        return float("inf") if mean_ret > 0 else 0.0
    downside_variance = sum(r ** 2 for r in downside) / len(returns)
    downside_std = downside_variance ** 0.5
    if downside_std == 0:
        return 0.0
    return float((mean_ret / downside_std) * (periods_per_year ** 0.5))


def _calmar_ratio(equity_curve: list[float], periods_per_year: float = 8760.0) -> float:
    """Annualized Calmar ratio: annualized return / max drawdown."""
    if len(equity_curve) < 3:
        return 0.0
    total_return = (equity_curve[-1] / equity_curve[0]) - 1.0
    n_periods = len(equity_curve) - 1
    if n_periods <= 0:
        return 0.0
    annualized_return = total_return * (periods_per_year / n_periods)
    mdd = _max_drawdown(equity_curve)
    if mdd <= 0:
        return float("inf") if annualized_return > 0 else 0.0
    return annualized_return / mdd


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = 0.0 if peak == 0 else (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown
