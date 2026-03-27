from __future__ import annotations

import json
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG_DIR = Path("artifacts/logs")
_EVENTS_FILE = _LOG_DIR / "events.jsonl"


class StructuredLogger:
    """Writes structured JSON log events to JSONL files in artifacts/logs/."""

    def __init__(self, log_dir: str | Path = _LOG_DIR) -> None:
        self._log_dir = Path(log_dir)
        self._lock = threading.Lock()
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _events_path(self) -> Path:
        return self._log_dir / "events.jsonl"

    def _strategy_path(self, wallet_name: str) -> Path:
        return self._log_dir / f"{wallet_name}.jsonl"

    def _write(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with self._lock:
            with self._events_path().open("a", encoding="utf-8") as f:
                f.write(line)
            wallet_name = event.get("wallet_name", "unknown")
            with self._strategy_path(wallet_name).open("a", encoding="utf-8") as f:
                f.write(line)

    def log_event(
        self,
        event_type: str,
        wallet_name: str,
        strategy_type: str,
        symbol: str,
        **kwargs: Any,
    ) -> None:
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "wallet_name": wallet_name,
            "strategy_type": strategy_type,
            "symbol": symbol,
            **kwargs,
        }
        self._write(event)

    def log_signal(
        self,
        wallet_name: str,
        strategy_type: str,
        symbol: str,
        action: str,
        reason: str,
        confidence: float,
        indicators: dict[str, Any],
        market_regime: str,
    ) -> None:
        self.log_event(
            "signal",
            wallet_name,
            strategy_type,
            symbol,
            action=action,
            reason=reason,
            confidence=confidence,
            indicators=indicators,
            market_regime=market_regime,
        )

    def log_trade(
        self,
        wallet_name: str,
        strategy_type: str,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        fee_paid: float,
        order_status: str,
        reason: str,
        order_type: str = "market",
        market_price: float | None = None,
        slippage_pct: float | None = None,
        fee_rate: float | None = None,
    ) -> None:
        self.log_event(
            "trade",
            wallet_name,
            strategy_type,
            symbol,
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            fee_paid=fee_paid,
            order_status=order_status,
            reason=reason,
            order_type=order_type,
            market_price=market_price,
            slippage_pct=slippage_pct,
            fee_rate=fee_rate,
        )

    def log_rejection(
        self,
        wallet_name: str,
        strategy_type: str,
        symbol: str,
        side: str,
        reason: str,
        requested_quantity: float,
    ) -> None:
        self.log_event(
            "rejection",
            wallet_name,
            strategy_type,
            symbol,
            side=side,
            reason=reason,
            requested_quantity=requested_quantity,
        )

    def log_error(
        self,
        wallet_name: str,
        strategy_type: str,
        symbol: str,
        error_message: str,
        exc: BaseException | None = None,
    ) -> None:
        tb: str | None = (
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            if exc is not None
            else None
        )
        self.log_event(
            "error",
            wallet_name,
            strategy_type,
            symbol,
            error_message=error_message,
            traceback=tb,
        )

    def log_system(
        self,
        wallet_name: str,
        strategy_type: str,
        symbol: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.log_event(
            "system",
            wallet_name,
            strategy_type,
            symbol,
            message=message,
            details=details or {},
        )
