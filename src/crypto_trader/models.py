from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class VerdictStatus(StrEnum):
    CONTINUE_PAPER = "continue_paper"
    REDUCE_RISK = "reduce_risk"
    PAUSE_STRATEGY = "pause_strategy"
    CANDIDATE_FOR_PROMOTION = "candidate_for_promotion"


class DriftStatus(StrEnum):
    INSUFFICIENT_DATA = "insufficient_data"
    ON_TRACK = "on_track"
    CAUTION = "caution"
    OUT_OF_SYNC = "out_of_sync"


class PromotionStatus(StrEnum):
    STAY_IN_PAPER = "stay_in_paper"
    CANDIDATE_FOR_PROMOTION = "candidate_for_promotion"
    DO_NOT_PROMOTE = "do_not_promote"


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
    context: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float
    entry_price: float
    entry_time: datetime
    entry_index: int | None = None
    entry_fee_paid: float = 0.0
    high_watermark: float = 0.0
    partial_tp_taken: bool = False

    def __post_init__(self) -> None:
        if self.high_watermark <= 0:
            self.high_watermark = self.entry_price

    def update_watermark(self, price: float) -> None:
        if price > self.high_watermark:
            self.high_watermark = price


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
    wallet: str = ""
    entry_confidence: float = 0.0


@dataclass(slots=True)
class PositionStatus:
    symbol: str
    quantity: float
    entry_price: float
    market_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


@dataclass(slots=True)
class PositionSnapshot:
    generated_at: str
    positions: list[PositionStatus]
    open_position_count: int
    mark_to_market_equity: float


@dataclass(slots=True)
class DailyPerformanceReport:
    generated_at: str
    trade_count: int
    winning_trade_count: int
    losing_trade_count: int
    realized_pnl: float
    realized_return_pct: float
    win_rate: float
    open_position_count: int
    mark_to_market_equity: float


@dataclass(slots=True)
class RegimeReport:
    generated_at: str
    symbol: str
    market_regime: str
    short_return_pct: float
    long_return_pct: float
    base_parameters: dict[str, float | int]
    adjusted_parameters: dict[str, float | int]
    reasons: list[str]


@dataclass(slots=True)
class DriftCalibrationEntry:
    regime: str
    sample_count: int
    average_abs_return_gap_pct: float
    suggested_return_tolerance_pct: float
    observed_error_rate: float
    suggested_error_rate_threshold: float


@dataclass(slots=True)
class DriftCalibrationReport:
    generated_at: str
    symbol: str
    entries: list[DriftCalibrationEntry]


@dataclass(slots=True)
class OperatorReport:
    generated_at: str
    symbol: str
    market_regime: str
    drift_status: str
    promotion_status: str
    report_markdown: str


@dataclass(slots=True)
class RuntimeCheckpoint:
    generated_at: str
    iteration: int
    symbols: list[str]
    wallet_states: dict[str, Any]
    session_id: str = ""
    config_path: str = ""
    wallet_names: list[str] = field(default_factory=list)


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
    max_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    avg_trade_duration_bars: float = 0.0
    max_trade_duration_bars: int = 0
    payoff_ratio: float = 0.0
    expected_value_per_trade: float = 0.0
    recovery_factor: float = 0.0
    tail_ratio: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    risk_adjusted_return: float = 0.0
    avg_entry_confidence: float = 0.0
    high_confidence_win_rate: float = 0.0
    low_confidence_win_rate: float = 0.0
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    exit_reason_avg_pnl: dict[str, float] = field(default_factory=dict)
    max_drawdown_duration_bars: int = 0
    regime_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(slots=True)
class BacktestBaseline:
    generated_at: str
    symbol: str
    interval: str
    candle_count: int
    config_fingerprint: str
    total_return_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    trade_count: int
    average_trade_pnl_pct: float


@dataclass(slots=True)
class StrategyVerdict:
    status: VerdictStatus
    confidence: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StrategyRunRecord:
    recorded_at: str
    symbol: str
    latest_price: float | None
    market_regime: str | None
    signal_action: str
    signal_reason: str
    signal_confidence: float
    order_status: str | None
    order_side: str | None
    session_starting_equity: float
    cash: float
    open_positions: int
    realized_pnl: float
    success: bool
    error: str | None
    consecutive_failures: int
    verdict_status: str
    verdict_confidence: float
    verdict_reasons: list[str] = field(default_factory=list)
    wallet_name: str = ""
    strategy_type: str = ""
    signal_indicators: dict[str, float] = field(default_factory=dict)
    signal_context: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class DriftReport:
    generated_at: str
    symbol: str
    status: DriftStatus
    reasons: list[str]
    backtest_total_return_pct: float
    backtest_win_rate: float
    backtest_max_drawdown: float
    backtest_trade_count: int
    paper_run_count: int
    paper_error_rate: float
    paper_buy_rate: float
    paper_sell_rate: float
    paper_hold_rate: float
    paper_realized_pnl_pct: float


@dataclass(slots=True)
class PromotionGateDecision:
    generated_at: str
    symbol: str
    status: PromotionStatus
    reasons: list[str]
    minimum_paper_runs_required: int
    observed_paper_runs: int
    backtest_total_return_pct: float
    paper_realized_pnl_pct: float
    drift_status: DriftStatus


@dataclass(slots=True)
class PortfolioPromotionDecision:
    generated_at: str
    status: PromotionStatus
    reasons: list[str]
    wallet_count: int
    total_equity: float
    total_realized_pnl: float
    portfolio_return_pct: float
    profitable_wallets: int
    total_trades: int
    paper_days: int
    per_wallet: dict[str, dict[str, float | int]]


@dataclass(slots=True)
class OrderbookEntry:
    price: float
    size: float


@dataclass(slots=True)
class OrderbookSnapshot:
    symbol: str
    bids: list[OrderbookEntry]
    asks: list[OrderbookEntry]
    timestamp: datetime | None = None


@dataclass(slots=True)
class PipelineResult:
    symbol: str
    signal: Signal
    order: OrderResult | None
    message: str
    latest_price: float | None = None
    error: str | None = None
