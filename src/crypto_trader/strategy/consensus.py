"""Consensus strategy: only enters when multiple sub-strategies agree."""
from __future__ import annotations

from crypto_trader.models import Candle, Position, Signal, SignalAction


class ConsensusStrategy:
    """Multi-strategy consensus filter.

    BUY only when >= min_agree sub-strategies signal BUY.
    SELL when any sub-strategy signals SELL (conservative exit).
    Confidence is the weighted average of agreeing strategies.
    """

    def __init__(
        self,
        strategies: list[object],
        min_agree: int = 2,
    ) -> None:
        if not strategies:
            raise ValueError("ConsensusStrategy requires at least one sub-strategy")
        self._strategies = strategies
        self._min_agree = max(1, min(min_agree, len(strategies)))

    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal:
        signals: list[Signal] = []
        for strategy in self._strategies:
            sig = strategy.evaluate(candles, position)
            signals.append(sig)

        context = {
            "strategy": "consensus",
            "sub_signals": ",".join(s.action.value for s in signals),
            "min_agree": str(self._min_agree),
        }

        # If holding a position, exit conservatively: any SELL triggers exit
        if position is not None:
            sell_signals = [s for s in signals if s.action is SignalAction.SELL]
            if sell_signals:
                best_sell = max(sell_signals, key=lambda s: s.confidence)
                return Signal(
                    action=SignalAction.SELL,
                    reason=f"consensus_exit:{best_sell.reason}",
                    confidence=best_sell.confidence,
                    indicators=best_sell.indicators,
                    context=context,
                )
            return Signal(
                action=SignalAction.HOLD,
                reason="consensus_hold_position",
                confidence=0.3,
                context=context,
            )

        # Entry: require min_agree strategies to signal BUY
        buy_signals = [s for s in signals if s.action is SignalAction.BUY]

        if len(buy_signals) >= self._min_agree:
            avg_confidence = sum(s.confidence for s in buy_signals) / len(buy_signals)
            # Merge indicators from all agreeing strategies
            merged_indicators: dict[str, float] = {}
            for sig in buy_signals:
                if sig.indicators:
                    merged_indicators.update(sig.indicators)
            reasons = [s.reason for s in buy_signals]
            return Signal(
                action=SignalAction.BUY,
                reason=f"consensus_agree:{'+'.join(reasons)}",
                confidence=min(1.0, avg_confidence),
                indicators=merged_indicators,
                context=context,
            )

        return Signal(
            action=SignalAction.HOLD,
            reason=f"consensus_insufficient:{len(buy_signals)}/{self._min_agree}",
            confidence=0.1,
            context=context,
        )
