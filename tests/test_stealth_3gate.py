"""Tests for Stealth3GateStrategy."""
from __future__ import annotations

from datetime import datetime

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.stealth_3gate import Stealth3GateStrategy


def _make_candles(n: int, close_trend: float = 0.01) -> list[Candle]:
    """Generate synthetic candles with a mild uptrend."""
    candles = []
    price = 1000.0
    for i in range(n):
        price *= 1 + close_trend * (1 if i % 3 != 0 else -0.5)
        candles.append(
            Candle(
                timestamp=i,
                open=price * 0.999,
                high=price * 1.005,
                low=price * 0.995,
                close=price,
                volume=100.0,
            )
        )
    return candles


def _strategy() -> Stealth3GateStrategy:
    return Stealth3GateStrategy(StrategyConfig(), stealth_window=10, stealth_sma_period=5)


def test_insufficient_data() -> None:
    s = _strategy()
    sig = s.evaluate(_make_candles(3))
    assert sig.action == SignalAction.HOLD
    assert sig.reason == "insufficient_data"


def test_entry_signal_all_gates_pass() -> None:
    s = Stealth3GateStrategy(
        StrategyConfig(),
        stealth_window=10,
        stealth_sma_period=5,
        rs_low=0.0,   # open gate 3 wide
        rs_high=1.01,  # include rs_score=1.0 (exclusive upper bound)
        cvd_slope_threshold=-999.0,  # always pass gate 2
        btc_stealth_gate=True,
    )
    candles = _make_candles(30, close_trend=0.02)
    sig = s.evaluate(candles)
    assert sig.action == SignalAction.BUY
    assert sig.confidence >= 0.3


def test_exit_max_holding() -> None:
    cfg = StrategyConfig(max_holding_bars=2)
    s = Stealth3GateStrategy(cfg, stealth_window=10, stealth_sma_period=5)
    candles = _make_candles(30)
    position = Position(
        symbol="KRW-TEST",
        entry_price=1000.0,
        quantity=1.0,
        entry_time=datetime(2026, 1, 1),
        entry_index=len(candles) - 10,  # 9 bars ago → > max_holding_bars=2
    )
    sig = s.evaluate(candles, position)
    assert sig.action == SignalAction.SELL
    assert sig.reason == "max_holding_period"


def test_btc_regime_gate_blocks_bear() -> None:
    s = Stealth3GateStrategy(
        StrategyConfig(),
        stealth_window=10,
        stealth_sma_period=5,
    )
    # Downtrend candles → price below SMA → Gate 1 fails
    candles = _make_candles(30, close_trend=-0.03)
    sig = s.evaluate(candles)
    assert sig.action == SignalAction.HOLD
    assert sig.reason == "btc_regime_bear"
