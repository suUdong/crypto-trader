from __future__ import annotations

from crypto_trader.config import RiskConfig
from crypto_trader.models import Position


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._trade_history: list[float] = []

    def record_trade(self, pnl_pct: float) -> None:
        """Record a completed trade's return percentage for Kelly calculation."""
        self._trade_history.append(pnl_pct)

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
        kelly = self.kelly_fraction()
        if kelly is not None and kelly > 0:
            risk_budget = equity * kelly
            quantity = risk_budget / price
            quantity *= macro_multiplier
            max_affordable = equity / price
            return max(0.0, min(quantity, max_affordable))
        risk_budget = equity * self._config.risk_per_trade_pct
        stop_distance = price * self._config.stop_loss_pct
        if stop_distance <= 0:
            return 0.0
        quantity = risk_budget / stop_distance
        quantity *= macro_multiplier
        max_affordable = equity / price
        return max(0.0, min(quantity, max_affordable))

    def can_open(self, active_positions: int, realized_pnl: float, starting_equity: float) -> bool:
        if active_positions >= self._config.max_concurrent_positions:
            return False
        if starting_equity <= 0:
            return False
        loss_limit = starting_equity * self._config.max_daily_loss_pct
        return realized_pnl > -loss_limit

    def exit_reason(self, position: Position, price: float) -> str | None:
        stop_loss_price = position.entry_price * (1.0 - self._config.stop_loss_pct)
        take_profit_price = position.entry_price * (1.0 + self._config.take_profit_pct)
        if price <= stop_loss_price:
            return "stop_loss"
        if price >= take_profit_price:
            return "take_profit"
        return None
