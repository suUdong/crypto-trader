from __future__ import annotations

from crypto_trader.config import RiskConfig
from crypto_trader.models import Candle, Position
from crypto_trader.strategy.indicators import average_true_range


class RiskManager:
    def __init__(
        self,
        config: RiskConfig,
        trailing_stop_pct: float = 0.0,
        atr_stop_multiplier: float = 0.0,
        max_holding_bars: int = 48,
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

    def size_position(
        self, equity: float, price: float, macro_multiplier: float = 1.0,
    ) -> float:
        if equity <= 0 or price <= 0:
            return 0.0
        if equity > self._peak_equity:
            self._peak_equity = equity
        kelly = self.kelly_fraction()
        if kelly is not None and kelly > 0:
            risk_budget = equity * kelly
            quantity = risk_budget / price
            quantity *= macro_multiplier
            max_affordable = equity / price
            base_quantity = max(0.0, min(quantity, max_affordable))
        else:
            risk_budget = equity * self._config.risk_per_trade_pct
            stop_distance = price * self._config.stop_loss_pct
            if stop_distance <= 0:
                return 0.0
            quantity = risk_budget / stop_distance
            quantity *= macro_multiplier
            max_affordable = equity / price
            base_quantity = max(0.0, min(quantity, max_affordable))
        drawdown_pct = (
            (self._peak_equity - equity) / self._peak_equity
            if self._peak_equity > 0
            else 0.0
        )
        max_daily_loss_pct = self._config.max_daily_loss_pct
        scale = (
            1.0
            - (drawdown_pct / max_daily_loss_pct)
            * self._config.drawdown_reduction_pct
            if max_daily_loss_pct > 0
            else 1.0
        )
        scale = max(0.1, min(scale, 1.0))
        # Win-streak boost: +15% after 3+ consecutive wins (max 1.3x)
        streak_mult = 1.0
        if self._consecutive_wins >= 3:
            streak_mult = min(1.3, 1.0 + 0.05 * self._consecutive_wins)
        sized = base_quantity * scale * streak_mult
        # Let streak sizing and notional cap scale together so a boost can
        # actually increase size without bypassing the configured ceiling.
        max_position_value = equity * self._config.max_position_pct * streak_mult
        max_qty_by_cap = max_position_value / price if price > 0 else 0.0
        return min(sized, max_qty_by_cap)

    def portfolio_heat(
        self, open_positions: list[tuple[float, float]], equity: float,
    ) -> float:
        """Total portfolio heat: sum of (position_value * stop_loss_pct) / equity.

        Each tuple is (entry_price, quantity).
        """
        if equity <= 0:
            return 0.0
        total_risk = sum(
            entry * qty * self.effective_stop_loss_pct
            for entry, qty in open_positions
        )
        return total_risk / equity

    def can_open(self, active_positions: int, realized_pnl: float, starting_equity: float) -> bool:
        if active_positions >= self._config.max_concurrent_positions:
            return False
        if starting_equity <= 0:
            return False
        loss_limit = starting_equity * self._config.max_daily_loss_pct
        return realized_pnl > -loss_limit

    def should_force_exit(self, realized_pnl: float, starting_equity: float) -> bool:
        """Circuit breaker: force-close all positions when daily loss limit is hit."""
        if starting_equity <= 0:
            return False
        loss_limit = starting_equity * self._config.max_daily_loss_pct
        return realized_pnl <= -loss_limit

    def exit_reason(
        self, position: Position, price: float, holding_bars: int = 0,
    ) -> str | None:
        # Update high watermark for trailing stop
        position.update_watermark(price)

        # Time-decay exit: close underwater positions held > 75% of max bars
        if holding_bars > 0 and self._max_holding_bars > 0:
            bar_ratio = holding_bars / self._max_holding_bars
            pnl_pct = (price - position.entry_price) / position.entry_price
            if bar_ratio >= 0.75 and pnl_pct < 0:
                return "time_decay_exit"

        # Breakeven stop: if position ever gained >= 1.5% (watermark), stop at entry
        watermark_gain = (position.high_watermark - position.entry_price) / position.entry_price
        if watermark_gain >= 0.015 and price <= position.entry_price:
            return "breakeven_stop"

        # ATR-based dynamic stops (if ATR available and multiplier set)
        if self._atr_stop_multiplier > 0 and self._current_atr > 0:
            atr_stop_distance = self._current_atr * self._atr_stop_multiplier
            atr_stop_price = position.entry_price - atr_stop_distance
            atr_tp_price = position.entry_price + atr_stop_distance * 2.0  # 2:1 reward:risk
            if price <= atr_stop_price:
                return "atr_stop_loss"
            if price >= atr_tp_price:
                return "atr_take_profit"
        else:
            # Fixed percentage stops (tightened on losing streaks)
            stop_loss_price = position.entry_price * (1.0 - self.effective_stop_loss_pct)
            take_profit_price = position.entry_price * (1.0 + self._config.take_profit_pct)
            if price <= stop_loss_price:
                return "stop_loss"

            # Partial take-profit: sell a fraction at halfway to TP target
            partial_tp_pct = self._config.partial_tp_pct
            if partial_tp_pct > 0:
                half_tp_price = position.entry_price * (1.0 + self._config.take_profit_pct * 0.5)
                if price >= half_tp_price and not position.partial_tp_taken:
                    return "partial_take_profit"

            if price >= take_profit_price:
                return "take_profit"

        # Trailing stop: exit when price drops trailing_pct below high watermark
        # After partial TP, auto-activate trailing stop at 2% if not already set
        effective_trailing = self._trailing_stop_pct
        if position.partial_tp_taken and effective_trailing <= 0:
            effective_trailing = 0.02  # 2% trailing after partial TP
        if effective_trailing > 0 and position.high_watermark > position.entry_price:
            trailing_stop_price = position.high_watermark * (1.0 - effective_trailing)
            if price <= trailing_stop_price:
                return "trailing_stop"

        # Profit-lock trailing: after 3%+ gain with no trailing stop configured,
        # activate tight 1.5% trailing from watermark to lock profits
        if effective_trailing <= 0 and watermark_gain >= 0.03:
            profit_lock_price = position.high_watermark * (1.0 - 0.015)
            if price <= profit_lock_price:
                return "profit_lock_trailing"

        return None
