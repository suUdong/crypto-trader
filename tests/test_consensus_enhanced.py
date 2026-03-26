"""Tests for enhanced ConsensusStrategy — weighted voting, quorum, exit modes."""
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
    def __init__(self, action: SignalAction, confidence: float = 0.7, reason: str = "fake") -> None:
        self._action = action
        self._confidence = confidence
        self._reason = reason

    def evaluate(self, candles: list[Candle], position: Position | None = None, *, symbol: str = "") -> Signal:
        return Signal(action=self._action, reason=self._reason, confidence=self._confidence)


class TestWeightedVoting(unittest.TestCase):
    def test_high_weight_strategy_dominates(self) -> None:
        """Strategy with higher weight contributes more to weighted confidence."""
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.9, "strong"),
            _FakeStrategy(SignalAction.BUY, 0.3, "weak"),
        ]
        # Weight strong strategy 3x
        consensus = ConsensusStrategy(strategies, min_agree=2, weights=[3.0, 1.0])
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.BUY)
        # Weighted conf should be dominated by the high-confidence, high-weight strategy
        self.assertGreater(signal.confidence, 0.7)

    def test_equal_weights_same_as_default(self) -> None:
        """Equal explicit weights produce same result as no weights."""
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.8, "a"),
            _FakeStrategy(SignalAction.BUY, 0.6, "b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "c"),
        ]
        consensus_default = ConsensusStrategy(strategies, min_agree=2)
        consensus_explicit = ConsensusStrategy(strategies, min_agree=2, weights=[1.0, 1.0, 1.0])
        sig1 = consensus_default.evaluate(_build_candles(), None)
        sig2 = consensus_explicit.evaluate(_build_candles(), None)
        self.assertEqual(sig1.action, sig2.action)
        self.assertAlmostEqual(sig1.confidence, sig2.confidence, places=5)

    def test_weights_length_mismatch_raises(self) -> None:
        strategies = [_FakeStrategy(SignalAction.BUY, 0.8)]
        with self.assertRaises(ValueError):
            ConsensusStrategy(strategies, min_agree=1, weights=[1.0, 2.0])


class TestQuorumThreshold(unittest.TestCase):
    def test_quorum_triggers_buy(self) -> None:
        """Weighted quorum mode: high confidence BUY triggers even with only 1/3 strategies."""
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.9, "strong"),
            _FakeStrategy(SignalAction.HOLD, 0.1, "b"),
            _FakeStrategy(SignalAction.HOLD, 0.1, "c"),
        ]
        # quorum_threshold=0.25: weighted score = (1.0 * 0.9) / 3.0 = 0.3 >= 0.25
        consensus = ConsensusStrategy(strategies, min_agree=2, quorum_threshold=0.25)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_quorum_blocks_weak_signal(self) -> None:
        """Low confidence BUY doesn't meet quorum."""
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.2, "weak"),
            _FakeStrategy(SignalAction.HOLD, 0.1, "b"),
            _FakeStrategy(SignalAction.HOLD, 0.1, "c"),
        ]
        # weighted score = (1.0 * 0.2) / 3.0 = 0.067 < 0.25
        consensus = ConsensusStrategy(strategies, min_agree=2, quorum_threshold=0.25)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertIn("quorum_not_met", signal.reason)

    def test_weighted_quorum_with_custom_weights(self) -> None:
        """Heavy-weighted BUY strategy meets quorum."""
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.7, "important"),
            _FakeStrategy(SignalAction.HOLD, 0.1, "filler"),
        ]
        # weight=[5.0, 1.0], total=6.0, weighted_score = 5.0 * 0.7 / 6.0 = 0.583
        consensus = ConsensusStrategy(
            strategies, min_agree=2, weights=[5.0, 1.0], quorum_threshold=0.5,
        )
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_quorum_zero_falls_through_to_count(self) -> None:
        """quorum_threshold=0 uses classic count-based mode."""
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.8, "a"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "b"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2, quorum_threshold=0.0)
        signal = consensus.evaluate(_build_candles(), None)
        # Only 1 BUY, need 2 → HOLD (classic mode)
        self.assertEqual(signal.action, SignalAction.HOLD)


class TestExitModes(unittest.TestCase):
    def _position(self) -> Position:
        return Position(
            symbol="KRW-BTC", quantity=0.01,
            entry_price=100_000.0, entry_time=datetime(2025, 1, 1), entry_index=0,
        )

    def test_any_exit_mode_default(self) -> None:
        """Default 'any' exit: single SELL triggers exit."""
        strategies = [
            _FakeStrategy(SignalAction.HOLD, 0.2, "a"),
            _FakeStrategy(SignalAction.SELL, 0.9, "b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        signal = consensus.evaluate(_build_candles(), self._position())
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertIn("consensus_exit", signal.reason)

    def test_majority_exit_blocks_single_sell(self) -> None:
        """Majority exit: 1/3 SELL is not majority → HOLD."""
        strategies = [
            _FakeStrategy(SignalAction.HOLD, 0.2, "a"),
            _FakeStrategy(SignalAction.SELL, 0.9, "b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2, exit_mode="majority")
        signal = consensus.evaluate(_build_candles(), self._position())
        self.assertEqual(signal.action, SignalAction.HOLD)

    def test_majority_exit_triggers_on_majority(self) -> None:
        """Majority exit: 2/3 SELL triggers exit."""
        strategies = [
            _FakeStrategy(SignalAction.SELL, 0.8, "a"),
            _FakeStrategy(SignalAction.SELL, 0.9, "b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2, exit_mode="majority")
        signal = consensus.evaluate(_build_candles(), self._position())
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertIn("consensus_majority_exit", signal.reason)

    def test_majority_exit_with_weights(self) -> None:
        """Weighted majority: heavy SELL weight triggers even with minority count."""
        strategies = [
            _FakeStrategy(SignalAction.SELL, 0.9, "important"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "filler1"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "filler2"),
        ]
        # Weight SELL strategy at 5, others at 1. Total=7, sell_weight=5 > 3.5
        consensus = ConsensusStrategy(
            strategies, min_agree=2, weights=[5.0, 1.0, 1.0], exit_mode="majority",
        )
        signal = consensus.evaluate(_build_candles(), self._position())
        self.assertEqual(signal.action, SignalAction.SELL)

    def test_invalid_exit_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConsensusStrategy([_FakeStrategy(SignalAction.BUY, 0.8)], exit_mode="invalid")


class TestBackwardCompatibility(unittest.TestCase):
    """Ensure old behavior still works without new parameters."""

    def test_classic_2_of_3(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.8, "a"),
            _FakeStrategy(SignalAction.BUY, 0.6, "b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertIn("consensus_agree", signal.reason)

    def test_classic_insufficient(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.8, "a"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "b"),
            _FakeStrategy(SignalAction.HOLD, 0.2, "c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.HOLD)

    def test_min_confidence_sum_still_works(self) -> None:
        strategies = [
            _FakeStrategy(SignalAction.BUY, 0.5, "a"),
            _FakeStrategy(SignalAction.BUY, 0.5, "b"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2, min_confidence_sum=1.2)
        signal = consensus.evaluate(_build_candles(), None)
        self.assertEqual(signal.action, SignalAction.HOLD)


if __name__ == "__main__":
    unittest.main()
