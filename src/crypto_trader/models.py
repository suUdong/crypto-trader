from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class Signal:
    action: SignalAction
    reason: str
    confidence: float
    indicators: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float
    entry_price: float
    entry_time: datetime
    entry_index: int | None = None
    entry_fee_paid: float = 0.0


@dataclass(slots=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: float
    requested_at: datetime
    reason: str


@dataclass(slots=True)
class OrderResult:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    fill_price: float
    fee_paid: float
    executed_at: datetime
    status: str
    reason: str


@dataclass(slots=True)
class TradeRecord:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    exit_reason: str


@dataclass(slots=True)
class BacktestResult:
    initial_capital: float
    final_equity: float
    total_return_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    trade_log: list[TradeRecord]
    equity_curve: list[float]


@dataclass(slots=True)
class PipelineResult:
    symbol: str
    signal: Signal
    order: OrderResult | None
    message: str
    error: str | None = None
