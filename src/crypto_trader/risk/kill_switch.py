"""Kill switch for live trading safety."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class KillSwitchConfig:
    max_portfolio_drawdown_pct: float = 0.05
    max_daily_loss_pct: float = 0.03
    max_consecutive_losses: int = 5
    max_strategy_drawdown_pct: float = 0.08
    cooldown_minutes: int = 60


@dataclass(slots=True)
class KillSwitchState:
    triggered: bool = False
    trigger_reason: str = ""
    triggered_at: str = ""
    consecutive_losses: int = 0
    daily_loss_pct: float = 0.0
    portfolio_drawdown_pct: float = 0.0


class KillSwitch:
    """Emergency kill switch that halts all trading when risk limits are breached."""

    def __init__(self, config: KillSwitchConfig | None = None) -> None:
        self._config = config or KillSwitchConfig()
        self._state = KillSwitchState()
        self._peak_equity: float = 0.0
        self._daily_start_equity: float = 0.0
        self._last_reset_date: str = ""

    @property
    def is_triggered(self) -> bool:
        return self._state.triggered

    @property
    def state(self) -> KillSwitchState:
        return self._state

    def reset(self) -> None:
        """Manually reset the kill switch after review."""
        self._state = KillSwitchState()
        logger.info("Kill switch manually reset")

    def check(
        self,
        current_equity: float,
        starting_equity: float,
        realized_pnl: float,
        trade_won: bool | None = None,
    ) -> KillSwitchState:
        """Check all kill switch conditions and trigger if any are breached.

        Args:
            current_equity: Current total portfolio equity
            starting_equity: Starting equity for drawdown calculation
            realized_pnl: Today's realized PnL
            trade_won: Whether last trade was a win (None if no recent trade)
        """
        if self._state.triggered:
            return self._state

        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")

        # Reset daily tracking at day boundary
        if today != self._last_reset_date:
            self._daily_start_equity = current_equity
            self._last_reset_date = today

        # Track peak equity for drawdown
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        # 1. Portfolio drawdown check
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - current_equity) / self._peak_equity
            self._state.portfolio_drawdown_pct = drawdown
            if drawdown >= self._config.max_portfolio_drawdown_pct:
                self._trigger(
                    f"Portfolio drawdown {drawdown:.2%} exceeds limit "
                    f"{self._config.max_portfolio_drawdown_pct:.2%}"
                )
                return self._state

        # 2. Daily loss check
        if self._daily_start_equity > 0:
            daily_loss = (self._daily_start_equity - current_equity) / self._daily_start_equity
            self._state.daily_loss_pct = max(0.0, daily_loss)
            if daily_loss >= self._config.max_daily_loss_pct:
                self._trigger(
                    f"Daily loss {daily_loss:.2%} exceeds limit "
                    f"{self._config.max_daily_loss_pct:.2%}"
                )
                return self._state

        # 3. Consecutive losses check
        if trade_won is not None:
            if trade_won:
                self._state.consecutive_losses = 0
            else:
                self._state.consecutive_losses += 1

            if self._state.consecutive_losses >= self._config.max_consecutive_losses:
                self._trigger(
                    f"max_consecutive_losses_exceeded: {self._state.consecutive_losses} consecutive losses "
                    f"(limit {self._config.max_consecutive_losses})"
                )
                return self._state

        return self._state

    def _trigger(self, reason: str) -> None:
        self._state.triggered = True
        self._state.trigger_reason = reason
        self._state.triggered_at = datetime.now(UTC).isoformat()
        logger.critical("KILL SWITCH TRIGGERED: %s", reason)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "triggered": self._state.triggered,
            "trigger_reason": self._state.trigger_reason,
            "triggered_at": self._state.triggered_at,
            "consecutive_losses": self._state.consecutive_losses,
            "daily_loss_pct": self._state.daily_loss_pct,
            "portfolio_drawdown_pct": self._state.portfolio_drawdown_pct,
            "peak_equity": self._peak_equity,
            "config": {
                "max_portfolio_drawdown_pct": self._config.max_portfolio_drawdown_pct,
                "max_daily_loss_pct": self._config.max_daily_loss_pct,
                "max_consecutive_losses": self._config.max_consecutive_losses,
                "max_strategy_drawdown_pct": self._config.max_strategy_drawdown_pct,
                "cooldown_minutes": self._config.cooldown_minutes,
            },
        }
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self, path: str | Path) -> None:
        target = Path(path)
        if not target.exists():
            return
        data = json.loads(target.read_text(encoding="utf-8"))
        self._state.triggered = data.get("triggered", False)
        self._state.trigger_reason = data.get("trigger_reason", "")
        self._state.triggered_at = data.get("triggered_at", "")
        self._state.consecutive_losses = data.get("consecutive_losses", 0)
        self._peak_equity = data.get("peak_equity", 0.0)
