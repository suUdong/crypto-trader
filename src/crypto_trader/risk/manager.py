from __future__ import annotations

from crypto_trader.config import RiskConfig
from crypto_trader.models import Position


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self._config = config

    def size_position(self, equity: float, price: float) -> float:
        if equity <= 0 or price <= 0:
            return 0.0
        risk_budget = equity * self._config.risk_per_trade_pct
        stop_distance = price * self._config.stop_loss_pct
        if stop_distance <= 0:
            return 0.0
        quantity = risk_budget / stop_distance
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
