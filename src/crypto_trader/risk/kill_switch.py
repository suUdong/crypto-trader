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
    warn_threshold_pct: float = 0.5
    reduce_threshold_pct: float = 0.75
    reduce_position_factor: float = 0.5


@dataclass(slots=True)
class KillSwitchState:
    triggered: bool = False
    trigger_reason: str = ""
    triggered_at: str = ""
    consecutive_losses: int = 0
    daily_loss_pct: float = 0.0
    portfolio_drawdown_pct: float = 0.0
    warning_active: bool = False
    position_size_penalty: float = 1.0


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
            # Reset tiered warnings on new day
            self._state.warning_active = False
            self._state.position_size_penalty = 1.0

        # Track peak equity for drawdown
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        # 1. Portfolio drawdown check with tiered response
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - current_equity) / self._peak_equity
            self._state.portfolio_drawdown_pct = drawdown
            self._apply_tiered_response(
                drawdown, self._config.max_portfolio_drawdown_pct, "portfolio_drawdown"
            )
            if drawdown >= self._config.max_portfolio_drawdown_pct:
                self._trigger(
                    f"Portfolio drawdown {drawdown:.2%} exceeds limit "
                    f"{self._config.max_portfolio_drawdown_pct:.2%}"
                )
                return self._state

        # 2. Daily loss check with tiered response
        if self._daily_start_equity > 0:
            daily_loss = (self._daily_start_equity - current_equity) / self._daily_start_equity
            self._state.daily_loss_pct = max(0.0, daily_loss)
            self._apply_tiered_response(
                daily_loss, self._config.max_daily_loss_pct, "daily_loss"
            )
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

    def _apply_tiered_response(
        self, current_pct: float, limit_pct: float, metric: str,
    ) -> None:
        """Apply tiered warning/reduce response before full halt."""
        if limit_pct <= 0:
            return
        ratio = current_pct / limit_pct
        warn_thresh = self._config.warn_threshold_pct
        reduce_thresh = self._config.reduce_threshold_pct

        if ratio >= reduce_thresh:
            self._state.warning_active = True
            self._state.position_size_penalty = self._config.reduce_position_factor
            logger.warning(
                "RISK REDUCE: %s at %.1f%% of limit (%.2f%% / %.2f%%) — "
                "position size reduced to %.0f%%",
                metric, ratio * 100, current_pct * 100, limit_pct * 100,
                self._config.reduce_position_factor * 100,
            )
        elif ratio >= warn_thresh:
            self._state.warning_active = True
            # Linearly interpolate penalty between 1.0 and reduce_factor
            interp = (ratio - warn_thresh) / (reduce_thresh - warn_thresh)
            penalty = 1.0 - interp * (1.0 - self._config.reduce_position_factor)
            self._state.position_size_penalty = max(
                self._config.reduce_position_factor, min(1.0, penalty),
            )
            logger.warning(
                "RISK WARNING: %s at %.1f%% of limit (%.2f%% / %.2f%%) — "
                "position size penalty %.2f",
                metric, ratio * 100, current_pct * 100, limit_pct * 100,
                self._state.position_size_penalty,
            )

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
            "warning_active": self._state.warning_active,
            "position_size_penalty": self._state.position_size_penalty,
            "peak_equity": self._peak_equity,
            "config": {
                "max_portfolio_drawdown_pct": self._config.max_portfolio_drawdown_pct,
                "max_daily_loss_pct": self._config.max_daily_loss_pct,
                "max_consecutive_losses": self._config.max_consecutive_losses,
                "max_strategy_drawdown_pct": self._config.max_strategy_drawdown_pct,
                "cooldown_minutes": self._config.cooldown_minutes,
                "warn_threshold_pct": self._config.warn_threshold_pct,
                "reduce_threshold_pct": self._config.reduce_threshold_pct,
                "reduce_position_factor": self._config.reduce_position_factor,
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
        self._state.warning_active = data.get("warning_active", False)
        self._state.position_size_penalty = data.get("position_size_penalty", 1.0)
        self._peak_equity = data.get("peak_equity", 0.0)
