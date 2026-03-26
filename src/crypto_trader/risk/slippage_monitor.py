"""Slippage and spread monitoring for trade execution quality."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW = 100
_DEFAULT_ALERT_MULT = 3.0


@dataclass(slots=True)
class SlippageRecord:
    symbol: str
    side: str
    market_price: float
    fill_price: float
    expected_slippage_pct: float
    actual_slippage_pct: float
    is_anomaly: bool = False


@dataclass(slots=True)
class SlippageStats:
    total_trades: int = 0
    anomaly_count: int = 0
    avg_slippage_pct: float = 0.0
    max_slippage_pct: float = 0.0
    total_slippage_cost: float = 0.0


class SlippageMonitor:
    """Tracks actual vs expected slippage and flags anomalies."""

    def __init__(
        self,
        expected_slippage_pct: float = 0.0005,
        window: int = _DEFAULT_WINDOW,
        alert_multiplier: float = _DEFAULT_ALERT_MULT,
    ) -> None:
        self._expected_slippage_pct = expected_slippage_pct
        self._window = window
        self._alert_multiplier = alert_multiplier
        self._records: deque[SlippageRecord] = deque(maxlen=window)
        self._per_symbol: dict[str, deque[SlippageRecord]] = {}

    def record_fill(
        self,
        symbol: str,
        side: str,
        market_price: float,
        fill_price: float,
        quantity: float = 0.0,
    ) -> SlippageRecord:
        """Record a trade fill and check for slippage anomaly."""
        if market_price <= 0:
            actual_pct = 0.0
        elif side == "buy":
            actual_pct = (fill_price - market_price) / market_price
        else:
            actual_pct = (market_price - fill_price) / market_price

        is_anomaly = actual_pct > self._expected_slippage_pct * self._alert_multiplier

        record = SlippageRecord(
            symbol=symbol,
            side=side,
            market_price=market_price,
            fill_price=fill_price,
            expected_slippage_pct=self._expected_slippage_pct,
            actual_slippage_pct=actual_pct,
            is_anomaly=is_anomaly,
        )
        self._records.append(record)

        if symbol not in self._per_symbol:
            self._per_symbol[symbol] = deque(maxlen=self._window)
        self._per_symbol[symbol].append(record)

        if is_anomaly:
            slippage_cost = abs(fill_price - market_price) * quantity
            logger.warning(
                "SLIPPAGE ANOMALY: %s %s market=%.2f fill=%.2f "
                "actual=%.4f%% expected=%.4f%% cost=%.2f",
                side.upper(), symbol, market_price, fill_price,
                actual_pct * 100, self._expected_slippage_pct * 100,
                slippage_cost,
            )

        return record

    def get_stats(self, symbol: str | None = None) -> SlippageStats:
        """Get slippage statistics, optionally filtered by symbol."""
        records = list(self._per_symbol.get(symbol, [])) if symbol else list(self._records)
        if not records:
            return SlippageStats()

        slippages = [r.actual_slippage_pct for r in records]
        anomalies = sum(1 for r in records if r.is_anomaly)
        costs = sum(
            abs(r.fill_price - r.market_price) for r in records
        )
        return SlippageStats(
            total_trades=len(records),
            anomaly_count=anomalies,
            avg_slippage_pct=sum(slippages) / len(slippages),
            max_slippage_pct=max(slippages),
            total_slippage_cost=costs,
        )

    @property
    def anomaly_rate(self) -> float:
        """Fraction of recent trades with anomalous slippage."""
        if not self._records:
            return 0.0
        return sum(1 for r in self._records if r.is_anomaly) / len(self._records)

    @property
    def recent_records(self) -> list[SlippageRecord]:
        return list(self._records)
