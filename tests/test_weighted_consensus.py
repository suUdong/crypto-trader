"""Tests for US-036: Weighted consensus voting with confidence scores."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.models import Candle, Signal, SignalAction
from crypto_trader.strategy.consensus import ConsensusStrategy


class MockStrategy:
    """Mock strategy returning a predetermined signal."""
    def __init__(self, action: SignalAction, confidence: float, reason: str = "mock") -> None:
        self._action = action
        self._confidence = confidence
        self._reason = reason

    def evaluate(self, candles: list[Candle], position=None) -> Signal:
        return Signal(
            action=self._action,
            reason=self._reason,
            confidence=self._confidence,
        )


def _candles(n: int = 5) -> list[Candle]:
    start = datetime(2025, 1, 1)
    return [
        Candle(timestamp=start + timedelta(hours=i), open=100, high=101, low=99, close=100, volume=1000)
        for i in range(n)
    ]


class TestWeightedConsensus(unittest.TestCase):
    def test_high_confidence_sum_triggers_buy(self) -> None:
        """2 strategies with 0.7 confidence each (sum=1.4) triggers BUY."""
        strategies = [
            MockStrategy(SignalAction.BUY, 0.7),
            MockStrategy(SignalAction.BUY, 0.7),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2, min_confidence_sum=1.2)
        signal = consensus.evaluate(_candles())
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_low_confidence_sum_blocks_buy(self) -> None:
        """2 strategies with 0.5 confidence each (sum=1.0) does NOT trigger BUY."""
        strategies = [
            MockStrategy(SignalAction.BUY, 0.5),
            MockStrategy(SignalAction.BUY, 0.5),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2, min_confidence_sum=1.2)
        signal = consensus.evaluate(_candles())
        self.assertEqual(signal.action, SignalAction.HOLD)

    def test_backward_compatible_without_confidence_sum(self) -> None:
        """Without min_confidence_sum, only count-based consensus applies."""
        strategies = [
            MockStrategy(SignalAction.BUY, 0.3),
            MockStrategy(SignalAction.BUY, 0.3),
        ]
        # min_confidence_sum=0 → disabled
        consensus = ConsensusStrategy(strategies, min_agree=2, min_confidence_sum=0.0)
        signal = consensus.evaluate(_candles())
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_count_gate_still_applies(self) -> None:
        """Even with high confidence, need min_agree strategies."""
        strategies = [
            MockStrategy(SignalAction.BUY, 0.9),
            MockStrategy(SignalAction.HOLD, 0.1),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2, min_confidence_sum=0.5)
        signal = consensus.evaluate(_candles())
        # Only 1 BUY, need 2 → HOLD
        self.assertEqual(signal.action, SignalAction.HOLD)

    def test_mixed_confidence_weighted(self) -> None:
        """One strong + one weak strategy above threshold."""
        strategies = [
            MockStrategy(SignalAction.BUY, 0.9),
            MockStrategy(SignalAction.BUY, 0.4),
        ]
        # sum = 1.3 >= 1.2 → triggers
        consensus = ConsensusStrategy(strategies, min_agree=2, min_confidence_sum=1.2)
        signal = consensus.evaluate(_candles())
        self.assertEqual(signal.action, SignalAction.BUY)


if __name__ == "__main__":
    unittest.main()
