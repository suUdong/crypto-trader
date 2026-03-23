from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import PipelineResult


@dataclass(slots=True)
class HealthSnapshot:
    updated_at: str
    success: bool
    consecutive_failures: int
    last_error: str | None
    last_signal: str
    last_order_status: str | None
    cash: float
    open_positions: int


class HealthMonitor:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._consecutive_failures = 0

    def record(self, result: PipelineResult, broker: PaperBroker) -> HealthSnapshot:
        if result.error is None:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

        snapshot = HealthSnapshot(
            updated_at=datetime.now(UTC).isoformat(),
            success=result.error is None,
            consecutive_failures=self._consecutive_failures,
            last_error=result.error,
            last_signal=result.signal.action.value,
            last_order_status=None if result.order is None else result.order.status,
            cash=broker.cash,
            open_positions=len(broker.positions),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(snapshot), indent=2), encoding="utf-8")
        return snapshot
