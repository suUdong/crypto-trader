"""Tests for ConsensusStrategy — multi-strategy agreement filter."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.consensus import ConsensusStrategy


def _build_candles(n: int = 50) -> list[Candle]:
    base = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=100_000.0 + i * 100,
            high=100_000.0 + i * 100 + 500,
            low=100_000.0 + i * 100 - 500,
            close=100_000.0 + i * 100,
            volume=1000.0,
        )
        for i in range(n)
    ]


class _FakeStrategy:
    """Stub strategy that returns a fixed signal."""

    def __init__(self, action: SignalAction, confidence: float = 0.7, reason: str = "fake") -> None:
        self._action = action
        self._confidence = confidence
        self._reason = reason

    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal:
        return Signal(
            action=self._action,
            reason=self._reason,
            confidence=self._confidence,
        )


class TestConsensusEntry(unittest.TestCase):
    def test_2_of_3_agree_buy(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.8, "strat_a"),
            _FakeStrategy(SignalAction.BUY, 0.6, "strat_b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "strat_c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertIn("consensus_agree", signal.reason)
        # Weighted confidence: (0.8²+0.6²)/(0.8+0.6) + (2/3)*0.1 ≈ 0.781
        self.assertGreater(signal.confidence, 0.7)
        self.assertLess(signal.confidence, 0.85)

    def test_1_of_3_agree_hold(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.8, "strat_a"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "strat_b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "strat_c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertIn("consensus_insufficient", signal.reason)

    def test_3_of_3_agree_buy(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.9, "a"),
            _FakeStrategy(SignalAction.BUY, 0.7, "b"),
            _FakeStrategy(SignalAction.BUY, 0.5, "c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_min_agree_1_any_buy_triggers(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.8, "a"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "b"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=1)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.BUY)


class TestConsensusExit(unittest.TestCase):
    def test_any_sell_triggers_exit(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.HOLD, 0.2, "strat_a"),
            _FakeStrategy(SignalAction.SELL, 0.9, "strat_b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "strat_c"),
        ]
        position = Position(
            symbol="KRW-BTC",
            quantity=0.01,
            entry_price=100_000.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,
        )
        consensus = ConsensusStrategy(strategies, min_agree=2)
        signal = consensus.evaluate(_build_candles(), position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertIn("consensus_exit", signal.reason)

    def test_no_sell_holds_position(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.HOLD, 0.2, "a"),
            _FakeStrategy(SignalAction.HOLD, 0.3, "b"),
        ]
        position = Position(
            symbol="KRW-BTC",
            quantity=0.01,
            entry_price=100_000.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,
        )
        consensus = ConsensusStrategy(strategies, min_agree=2)
        signal = consensus.evaluate(_build_candles(), position)
        self.assertEqual(signal.action, SignalAction.HOLD)


class TestConsensusEdgeCases(unittest.TestCase):
    def test_empty_strategies_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConsensusStrategy([], min_agree=2)

    def test_min_agree_clamped_to_strategy_count(self) -> None:
        strategies = [_FakeStrategy(SignalAction.BUY, 0.8, "a")]
        consensus = ConsensusStrategy(strategies, min_agree=5)
        # min_agree should be clamped to 1 (only 1 strategy)
        self.assertEqual(consensus._min_agree, 1)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.BUY)


class TestConsensusCreateStrategy(unittest.TestCase):
    def test_create_consensus_via_factory(self) -> None:
        from crypto_trader.config import RegimeConfig, StrategyConfig
        from crypto_trader.wallet import create_strategy

        config = StrategyConfig()
        regime = RegimeConfig()
        strategy = create_strategy(
            "consensus", config, regime,
            extra_params={"sub_strategies": ["momentum", "vpin"], "min_agree": 2},
        )
        self.assertIsInstance(strategy, ConsensusStrategy)
        self.assertEqual(len(strategy._strategies), 2)


if __name__ == "__main__":
    unittest.main()
