"""Symbol-level circuit breaker (CT P1 audit item 4).

Auto-disables a symbol when the recent loss footprint crosses one of two
thresholds:

1. **Loss burst** — ``loss_threshold`` losses inside a rolling ``window_hours``
   window (e.g. 3 losses in 48h).
2. **Expectancy** — mean ``pnl_pct`` across the window drops below
   ``expectancy_threshold_pct`` once at least ``min_trades_for_expectancy``
   trades have closed.

A disable enters a ``cooldown_hours`` cooling-off period. Cooldown is checked
lazily on every ``is_disabled`` call, so re-enable happens the next time the
daemon evaluates the symbol (no scheduler required). State is JSON-persisted
to ``artifacts/symbol-circuit.json`` (same pattern as ``kill-switch.json``)
so circuit decisions survive daemon restarts.

State transitions emit two side channels for downstream observability:

* ``on_state_change(symbol, transition, reason)`` callback — used by the
  daemon to fire ``TradeAlertManager`` notifications.
* JSONL append to ``events_path`` (default
  ``artifacts/circuit-breaker-events.jsonl``) — consumed by fire-monitor's
  P0 alert collector.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

StateChangeCallback = Callable[[str, str, str], None]


@dataclass(slots=True)
class SymbolCircuitConfig:
    loss_threshold: int = 3
    window_hours: float = 48.0
    cooldown_hours: float = 24.0
    expectancy_threshold_pct: float = -0.005
    min_trades_for_expectancy: int = 5


@dataclass(slots=True)
class _SymbolState:
    trades: list[tuple[str, float]] = field(default_factory=list)
    disabled_until: str = ""
    last_reason: str = ""


def _ensure_utc(ts: datetime) -> datetime:
    return ts.astimezone(UTC) if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _iso(ts: datetime) -> str:
    return _ensure_utc(ts).isoformat()


def _parse_iso(value: str) -> datetime:
    return _ensure_utc(datetime.fromisoformat(value))


class SymbolCircuitBreaker:
    """Per-symbol rolling-window loss tracker with auto-disable + cooldown."""

    def __init__(
        self,
        config: SymbolCircuitConfig | None = None,
        *,
        on_state_change: StateChangeCallback | None = None,
        events_path: Path | str | None = None,
    ) -> None:
        self._config = config or SymbolCircuitConfig()
        self._on_state_change = on_state_change
        self._events_path = Path(events_path) if events_path else None
        self._state: dict[str, _SymbolState] = {}

    @property
    def config(self) -> SymbolCircuitConfig:
        return self._config

    def record_trade(self, symbol: str, pnl_pct: float, closed_at: datetime) -> None:
        closed_at = _ensure_utc(closed_at)
        state = self._state.setdefault(symbol, _SymbolState())
        state.trades.append((_iso(closed_at), float(pnl_pct)))
        self._evict_old(state, closed_at)
        # Only losses (strictly negative pnl_pct) can trip the burst counter.
        if pnl_pct < 0:
            self._maybe_disable(symbol, state, closed_at)

    def is_disabled(self, symbol: str, now: datetime) -> bool:
        now = _ensure_utc(now)
        state = self._state.get(symbol)
        if state is None or not state.disabled_until:
            return False
        unlock_at = _parse_iso(state.disabled_until)
        if now <= unlock_at:
            return True
        # Cooldown elapsed — re-enable. Clear the window so old losses don't
        # immediately re-disable on the next loss.
        reason = state.last_reason
        state.disabled_until = ""
        state.last_reason = ""
        state.trades.clear()
        self._emit("re_enabled", symbol, reason or "cooldown_elapsed", now)
        return False

    def disable_reason(self, symbol: str) -> str:
        state = self._state.get(symbol)
        return state.last_reason if state else ""

    def cooldown_seconds_remaining(self, symbol: str, now: datetime) -> float:
        now = _ensure_utc(now)
        state = self._state.get(symbol)
        if state is None or not state.disabled_until:
            return 0.0
        unlock_at = _parse_iso(state.disabled_until)
        delta = (unlock_at - now).total_seconds()
        return max(0.0, delta)

    def save(self, path: Path | str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "config": {
                "loss_threshold": self._config.loss_threshold,
                "window_hours": self._config.window_hours,
                "cooldown_hours": self._config.cooldown_hours,
                "expectancy_threshold_pct": self._config.expectancy_threshold_pct,
                "min_trades_for_expectancy": self._config.min_trades_for_expectancy,
            },
            "symbols": {
                symbol: {
                    "trades": list(state.trades),
                    "disabled_until": state.disabled_until,
                    "last_reason": state.last_reason,
                }
                for symbol, state in self._state.items()
            },
        }
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self, path: Path | str) -> None:
        target = Path(path)
        if not target.exists():
            return
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("symbol circuit state load failed: %s", exc)
            return
        for symbol, raw in (data.get("symbols") or {}).items():
            trades_raw = raw.get("trades") or []
            trades = [(str(ts), float(pnl)) for ts, pnl in trades_raw]
            self._state[symbol] = _SymbolState(
                trades=trades,
                disabled_until=str(raw.get("disabled_until", "")),
                last_reason=str(raw.get("last_reason", "")),
            )

    def _evict_old(self, state: _SymbolState, now: datetime) -> None:
        window_start = now.timestamp() - self._config.window_hours * 3600
        state.trades = [
            (ts, pnl) for ts, pnl in state.trades if _parse_iso(ts).timestamp() >= window_start
        ]

    def _maybe_disable(self, symbol: str, state: _SymbolState, now: datetime) -> None:
        if state.disabled_until:
            return  # already disabled — don't re-emit
        losses = [pnl for _, pnl in state.trades if pnl < 0]
        reason = ""
        if len(losses) >= self._config.loss_threshold:
            reason = (
                f"loss_burst: {len(losses)} losses in last "
                f"{self._config.window_hours:.0f}h"
            )
        elif (
            len(state.trades) >= self._config.min_trades_for_expectancy
            and self._mean_pnl(state) < self._config.expectancy_threshold_pct
        ):
            reason = (
                f"expectancy: mean pnl_pct {self._mean_pnl(state):.4f} below "
                f"{self._config.expectancy_threshold_pct:.4f} over "
                f"{len(state.trades)} trades"
            )
        if not reason:
            return
        unlock_at = now.timestamp() + self._config.cooldown_hours * 3600
        state.disabled_until = _iso(datetime.fromtimestamp(unlock_at, UTC))
        state.last_reason = reason
        self._emit("disabled", symbol, reason, now)
        logger.warning(
            "SYMBOL CIRCUIT BREAKER tripped: %s — %s (cooldown_until=%s)",
            symbol,
            reason,
            state.disabled_until,
        )

    @staticmethod
    def _mean_pnl(state: _SymbolState) -> float:
        if not state.trades:
            return 0.0
        return sum(pnl for _, pnl in state.trades) / len(state.trades)

    def _emit(
        self, transition: str, symbol: str, reason: str, now: datetime
    ) -> None:
        if self._on_state_change is not None:
            try:
                self._on_state_change(symbol, transition, reason)
            except Exception as exc:
                logger.warning("symbol circuit on_state_change callback failed: %s", exc)
        events_path = self._events_path
        if events_path is not None:
            self._append_event(events_path, transition, symbol, reason, now)

    @staticmethod
    def _append_event(
        events_path: Path,
        transition: str,
        symbol: str,
        reason: str,
        now: datetime,
    ) -> None:
        try:
            events_path.parent.mkdir(parents=True, exist_ok=True)
            event = {
                "category": "circuit_breaker",
                "system": "crypto-trader",
                "severity": "P0" if transition == "disabled" else "INFO",
                "symbol": symbol,
                "transition": transition,
                "reason": reason,
                "detected_at": _iso(now),
            }
            with events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("symbol circuit event append failed: %s", exc)
