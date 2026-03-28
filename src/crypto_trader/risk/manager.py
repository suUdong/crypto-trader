from __future__ import annotations

import math

from crypto_trader.config import (
    HARD_MAX_DAILY_LOSS_PCT,
    SAFE_MAX_CONSECUTIVE_LOSSES,
    RiskConfig,
)
from crypto_trader.models import Candle, Position
from crypto_trader.risk.edge_schedule import EdgeSchedule
from crypto_trader.strategy.indicators import average_true_range


class RiskManager:
    _MIN_DRAWDOWN_SCALE: float = 0.1
    _MAX_WIN_STREAK_MULT: float = 1.2
    _MIN_LOSS_STREAK_MULT: float = 0.4
    _MAX_CONSECUTIVE_LOSSES_BEFORE_STOP: int = SAFE_MAX_CONSECUTIVE_LOSSES

    def __init__(
        self,
        config: RiskConfig,
        trailing_stop_pct: float = 0.0,
        atr_stop_multiplier: float = 0.0,
        max_holding_bars: int = 48,
        edge_schedule: EdgeSchedule | None = None,
    ) -> None:
        self._config = config
        self._trade_history: list[float] = []
        self._trailing_stop_pct = trailing_stop_pct
        self._atr_stop_multiplier = atr_stop_multiplier
        self._current_atr: float = 0.0
        self.min_entry_confidence: float = config.min_entry_confidence
        self._peak_equity: float = 0.0
        self._max_holding_bars: int = max_holding_bars
        self._bars_since_last_loss: int | None = None  # None = no recent loss
        self._consecutive_losses: int = 0
        self._consecutive_wins: int = 0
        self._paused: bool = False
        self._edge_schedule = edge_schedule or EdgeSchedule()

    def set_atr(self, atr: float) -> None:
        """Update current ATR for dynamic stop calculation."""
        self._current_atr = atr

    def update_atr_from_candles(self, candles: list[Candle], period: int = 14) -> None:
        """Refresh ATR from candle history when enough bars are available."""
        if len(candles) < period + 1:
            return
        highs = [candle.high for candle in candles]
        lows = [candle.low for candle in candles]
        closes = [candle.close for candle in candles]
        try:
            self._current_atr = average_true_range(highs, lows, closes, period)
        except ValueError:
            return

    def record_trade(self, pnl_pct: float) -> None:
        """Record a completed trade's return percentage for Kelly calculation."""
        self._trade_history.append(pnl_pct)
        if pnl_pct < 0:
            self._bars_since_last_loss = 0
            self._consecutive_losses += 1
            self._consecutive_wins = 0
        else:
            self._bars_since_last_loss = None
            self._consecutive_losses = 0
            self._consecutive_wins += 1

    def tick_cooldown(self) -> None:
        """Advance the cooldown counter by one bar."""
        if self._bars_since_last_loss is not None:
            self._bars_since_last_loss += 1

    def adjust_capital_base(self, delta_cash: float) -> None:
        """Shift internal drawdown baseline when external capital is moved."""
        if abs(delta_cash) <= 0:
            return
        if self._peak_equity > 0:
            self._peak_equity = max(0.0, self._peak_equity + delta_cash)

    def rolling_win_rate(self, window: int = 20) -> float | None:
        """Rolling win rate over the last N trades. None if insufficient data."""
        if len(self._trade_history) < 5:
            return None
        recent = self._trade_history[-window:]
        wins = sum(1 for t in recent if t > 0)
        return wins / len(recent)

    @property
    def is_decaying(self) -> bool:
        """True when rolling win rate drops below 35% — strategy losing edge."""
        wr = self.rolling_win_rate()
        if wr is None:
            return False
        return wr < 0.35

    @property
    def effective_stop_loss_pct(self) -> float:
        """Dynamic stop loss: tighten by 20% after 3+ consecutive losses."""
        base = self._config.stop_loss_pct
        if self._consecutive_losses >= 3:
            return base * 0.8  # 20% tighter
        return base

    @property
    def in_cooldown(self) -> bool:
        """True if within cooldown period after a losing trade."""
        if self._bars_since_last_loss is None:
            return False
        return self._bars_since_last_loss < self._config.cooldown_bars

    @property
    def is_auto_paused(self) -> bool:
        """True if rolling profit factor is too low (strategy is persistently losing).

        Requires at least 10 trades. Pauses when PF < 0.7 over the last 20 trades.
        Resumes when PF recovers above 0.8 (hysteresis to avoid flapping).
        """
        min_trades = 10
        window = 20
        if len(self._trade_history) < min_trades:
            return False
        recent = self._trade_history[-window:]
        gross_profit = sum(t for t in recent if t > 0)
        gross_loss = abs(sum(t for t in recent if t <= 0))
        if gross_loss == 0:
            return False  # all winners, don't pause
        pf = gross_profit / gross_loss
        # Hysteresis: pause at 0.7, resume at 0.8
        if self._paused:
            self._paused = pf < 0.8
        else:
            self._paused = pf < 0.7
        return self._paused

    @property
    def is_loss_streak_stopped(self) -> bool:
        return self._consecutive_losses >= self._MAX_CONSECUTIVE_LOSSES_BEFORE_STOP

    @property
    def effective_min_confidence(self) -> float:
        """Adaptive confidence: lowers bar when winning, raises when losing."""
        base = self.min_entry_confidence
        if len(self._trade_history) < 5:
            return base
        recent = self._trade_history[-20:]
        wins = sum(1 for t in recent if t > 0)
        win_rate = wins / len(recent)
        if win_rate > 0.6:
            adjusted = base - 0.1
        elif win_rate < 0.4:
            adjusted = base + 0.1
        else:
            adjusted = base
        return max(0.3, min(0.9, adjusted))

    def kelly_fraction(self, min_trades: int = 10) -> float | None:
        """Compute half-Kelly fraction from trade history.

        Returns None if insufficient history (< min_trades).
        Kelly f* = p - q / (W/L)  where p=win_rate, q=1-p, W=avg_win, L=avg_loss
        We use half-Kelly for safety.
        """
        if len(self._trade_history) < min_trades:
            return None
        wins = [t for t in self._trade_history if t > 0]
        losses = [t for t in self._trade_history if t <= 0]
        if not wins or not losses:
            return None
        win_rate = len(wins) / len(self._trade_history)
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))
        if avg_loss == 0:
            return None
        payoff_ratio = avg_win / avg_loss
        kelly = win_rate - (1.0 - win_rate) / payoff_ratio
        half_kelly = kelly * 0.5
        return max(0.0, min(half_kelly, 0.25))

    def _base_position_quantity(
        self,
        equity: float,
        price: float,
        macro_multiplier: float,
    ) -> float:
        kelly = self.kelly_fraction()
        if kelly is not None and kelly > 0:
            risk_budget = equity * kelly
            quantity = (risk_budget / price) * macro_multiplier
        else:
            risk_budget = equity * self._config.risk_per_trade_pct
            stop_distance = price * self._config.stop_loss_pct
            if stop_distance <= 0:
                return 0.0
            quantity = (risk_budget / stop_distance) * macro_multiplier
        max_affordable = equity / price
        return max(0.0, min(quantity, max_affordable))

    def _current_drawdown_pct(self, equity: float) -> float:
        if self._peak_equity <= 0:
            return 0.0
        return max(0.0, (self._peak_equity - equity) / self._peak_equity)

    def _drawdown_scale(self, equity: float) -> float:
        drawdown_pct = self._current_drawdown_pct(equity)
        max_daily_loss_pct = min(self._config.max_daily_loss_pct, HARD_MAX_DAILY_LOSS_PCT)
        if max_daily_loss_pct <= 0 or drawdown_pct <= 0:
            return 1.0
        drawdown_ratio = min(1.0, drawdown_pct / max_daily_loss_pct)
        exponent = 1.0 + (self._config.drawdown_reduction_pct * 2.0)
        scaled = max(self._MIN_DRAWDOWN_SCALE, (1.0 - drawdown_ratio) ** exponent)
        return float(scaled)

    def _streak_multiplier(self) -> float:
        multiplier = 1.0
        if self._consecutive_wins >= 3:
            multiplier = min(
                self._MAX_WIN_STREAK_MULT,
                1.0 + 0.04 * self._consecutive_wins,
            )
        if self._consecutive_losses >= 2:
            multiplier *= max(
                self._MIN_LOSS_STREAK_MULT,
                1.0 - 0.15 * self._consecutive_losses,
            )
        return multiplier

    def _loss_pressure_ratio(
        self,
        realized_pnl: float,
        starting_equity: float,
        current_equity: float | None = None,
    ) -> float:
        if starting_equity <= 0:
            return 0.0
        realized_loss_ratio = max(0.0, -realized_pnl / starting_equity)
        if current_equity is None:
            return realized_loss_ratio
        mark_to_market_ratio = max(0.0, (starting_equity - current_equity) / starting_equity)
        return max(realized_loss_ratio, mark_to_market_ratio)

    def allowed_concurrent_positions(
        self,
        realized_pnl: float,
        starting_equity: float,
        current_equity: float | None = None,
    ) -> int:
        base_limit = self._config.max_concurrent_positions
        if base_limit <= 0 or starting_equity <= 0:
            return 0
        max_daily_loss_pct = min(self._config.max_daily_loss_pct, HARD_MAX_DAILY_LOSS_PCT)
        if max_daily_loss_pct <= 0:
            return base_limit
        loss_pressure_ratio = self._loss_pressure_ratio(
            realized_pnl,
            starting_equity,
            current_equity,
        )
        if loss_pressure_ratio >= max_daily_loss_pct:
            return 0
        if base_limit == 1:
            return 1
        remaining_capacity = 1.0 - min(1.0, loss_pressure_ratio / max_daily_loss_pct)
        return max(1, math.ceil(base_limit * remaining_capacity))

    def size_position(
        self,
        equity: float,
        price: float,
        macro_multiplier: float = 1.0,
        utc_hour: int | None = None,
    ) -> float:
        if equity <= 0 or price <= 0:
            return 0.0
        if equity > self._peak_equity:
            self._peak_equity = equity
        base_quantity = self._base_position_quantity(equity, price, macro_multiplier)
        edge_mult = self._edge_schedule.hour_multiplier(utc_hour) if utc_hour is not None else 1.0
        sized = base_quantity * self._drawdown_scale(equity) * self._streak_multiplier() * edge_mult
        # Hard cap: max_position_pct is NEVER expanded by edge or streak boost
        max_position_value = equity * self._config.max_position_pct
        max_qty_by_cap = max_position_value / price
        return min(sized, max_qty_by_cap)

    def portfolio_heat(
        self,
        open_positions: list[tuple[float, float]],
        equity: float,
    ) -> float:
        """Total portfolio heat: sum of (position_value * stop_loss_pct) / equity.

        Each tuple is (entry_price, quantity).
        """
        if equity <= 0:
            return 0.0
        total_risk = sum(
            entry * qty * self.effective_stop_loss_pct for entry, qty in open_positions
        )
        return total_risk / equity

    def can_open(
        self,
        active_positions: int,
        realized_pnl: float,
        starting_equity: float,
        current_equity: float | None = None,
    ) -> bool:
        if starting_equity <= 0:
            return False
        if self.is_loss_streak_stopped:
            return False
        allowed_positions = self.allowed_concurrent_positions(
            realized_pnl,
            starting_equity,
            current_equity,
        )
        return active_positions < allowed_positions

    def should_force_exit(
        self,
        realized_pnl: float,
        starting_equity: float,
        current_equity: float | None = None,
    ) -> bool:
        """Circuit breaker: force-close all positions when daily loss limit is hit."""
        if starting_equity <= 0:
            return False
        max_daily_loss_pct = min(self._config.max_daily_loss_pct, HARD_MAX_DAILY_LOSS_PCT)
        if max_daily_loss_pct <= 0:
            return False
        return (
            self._loss_pressure_ratio(
                realized_pnl,
                starting_equity,
                current_equity,
            )
            >= max_daily_loss_pct
        )

    def exit_reason(
        self,
        position: Position,
        price: float,
        holding_bars: int = 0,
    ) -> str | None:
        # Update high watermark for trailing stop
        position.update_watermark(price)

        pnl_pct = position.pnl_pct(price)

        # Time-decay exit: graduated — close sooner if deeper underwater
        if holding_bars > 0 and self._max_holding_bars > 0:
            bar_ratio = holding_bars / self._max_holding_bars
            # At 60% of max bars: exit if loss > 1.5%
            # At 75% of max bars: exit if any loss
            if bar_ratio >= 0.60 and pnl_pct < -0.015:
                return "time_decay_exit"
            if bar_ratio >= 0.75 and pnl_pct < 0:
                return "time_decay_exit"

        # Breakeven stop: if position ever gained >= 1.2% (watermark), stop at entry
        if position.is_short:
            watermark_gain = (position.entry_price - position.high_watermark) / position.entry_price
            breakeven_touched = price >= position.entry_price
        else:
            watermark_gain = (position.high_watermark - position.entry_price) / position.entry_price
            breakeven_touched = price <= position.entry_price
        if watermark_gain >= 0.012 and breakeven_touched:
            return "breakeven_stop"

        # ATR-based dynamic stops (if ATR available and multiplier set)
        if self._atr_stop_multiplier > 0 and self._current_atr > 0:
            atr_stop_distance = self._current_atr * self._atr_stop_multiplier
            if position.is_short:
                atr_stop_price = position.entry_price + atr_stop_distance
                atr_tp_price = position.entry_price - atr_stop_distance * 2.0
                stop_hit = price >= atr_stop_price
                tp_hit = price <= atr_tp_price
            else:
                atr_stop_price = position.entry_price - atr_stop_distance
                atr_tp_price = position.entry_price + atr_stop_distance * 2.0  # 2:1 reward:risk
                stop_hit = price <= atr_stop_price
                tp_hit = price >= atr_tp_price
            if stop_hit:
                return "atr_stop_loss"
            if tp_hit:
                return "atr_take_profit"
        else:
            # Fixed percentage stops (tightened on losing streaks)
            if position.is_short:
                stop_loss_price = position.entry_price * (1.0 + self.effective_stop_loss_pct)
                take_profit_price = position.entry_price * (1.0 - self._config.take_profit_pct)
                stop_hit = price >= stop_loss_price
                take_profit_hit = price <= take_profit_price
                half_tp_price = position.entry_price * (
                    1.0 - self._config.take_profit_pct * 0.5
                )
                half_tp_hit = price <= half_tp_price
            else:
                stop_loss_price = position.entry_price * (1.0 - self.effective_stop_loss_pct)
                take_profit_price = position.entry_price * (1.0 + self._config.take_profit_pct)
                stop_hit = price <= stop_loss_price
                take_profit_hit = price >= take_profit_price
                half_tp_price = position.entry_price * (
                    1.0 + self._config.take_profit_pct * 0.5
                )
                half_tp_hit = price >= half_tp_price
            if stop_hit:
                return "stop_loss"

            # Partial take-profit: sell a fraction at halfway to TP target
            partial_tp_pct = self._config.partial_tp_pct
            if partial_tp_pct > 0:
                if half_tp_hit and not position.partial_tp_taken:
                    return "partial_take_profit"

            if take_profit_hit:
                return "take_profit"

        # Trailing stop: exit when price drops trailing_pct below high watermark
        # After partial TP, auto-activate trailing stop at 2% if not already set
        effective_trailing = self._trailing_stop_pct
        if position.partial_tp_taken and effective_trailing <= 0:
            effective_trailing = 0.02  # 2% trailing after partial TP
        if effective_trailing > 0:
            if position.is_short and position.high_watermark < position.entry_price:
                trailing_stop_price = position.high_watermark * (1.0 + effective_trailing)
                if price >= trailing_stop_price:
                    return "trailing_stop"
            if not position.is_short and position.high_watermark > position.entry_price:
                trailing_stop_price = position.high_watermark * (1.0 - effective_trailing)
                if price <= trailing_stop_price:
                    return "trailing_stop"

        # Profit-lock trailing: after 3%+ gain with no trailing stop configured,
        # activate tight 1.5% trailing from watermark to lock profits
        if effective_trailing <= 0 and watermark_gain >= 0.03:
            if position.is_short:
                profit_lock_price = position.high_watermark * (1.0 + 0.015)
                if price >= profit_lock_price:
                    return "profit_lock_trailing"
            else:
                profit_lock_price = position.high_watermark * (1.0 - 0.015)
                if price <= profit_lock_price:
                    return "profit_lock_trailing"

        return None
