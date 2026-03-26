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
        min_confidence_sum: float = 0.0,
    ) -> None:
        if not strategies:
            raise ValueError("ConsensusStrategy requires at least one sub-strategy")
        self._strategies = strategies
        self._min_agree = max(1, min(min_agree, len(strategies)))
        self._min_confidence_sum = min_confidence_sum

    def evaluate(self, candles: list[Candle], position: Position | None = None, *, symbol: str = "") -> Signal:
        signals: list[Signal] = []
        for strategy in self._strategies:
            sig = strategy.evaluate(candles, position, symbol=symbol)
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

        confidence_sum = sum(s.confidence for s in buy_signals)
        meets_count = len(buy_signals) >= self._min_agree
        meets_confidence = (
            self._min_confidence_sum <= 0
            or confidence_sum >= self._min_confidence_sum
        )

        if meets_count and meets_confidence:
            # Weighted confidence: higher-confidence strategies contribute more
            total_weight = sum(s.confidence for s in buy_signals)
            if total_weight > 0:
                weighted_conf = sum(s.confidence ** 2 for s in buy_signals) / total_weight
            else:
                weighted_conf = 0.0
            # Agreement ratio boost: more strategies agreeing = higher confidence
            agree_ratio = len(buy_signals) / len(signals)
            final_conf = min(1.0, weighted_conf + agree_ratio * 0.1)
            # Merge indicators from all agreeing strategies (prefix to avoid collision)
            merged_indicators: dict[str, float] = {}
            for idx, sig in enumerate(buy_signals):
                if sig.indicators:
                    prefix = sig.reason.split("_")[0] if sig.reason else f"s{idx}"
                    for k, v in sig.indicators.items():
                        merged_indicators[f"{prefix}_{k}"] = v
            merged_indicators["agreement_ratio"] = agree_ratio
            merged_indicators["weighted_confidence"] = weighted_conf
            reasons = [s.reason for s in buy_signals]
            return Signal(
                action=SignalAction.BUY,
                reason=f"consensus_agree:{'+'.join(reasons)}",
                confidence=final_conf,
                indicators=merged_indicators,
                context=context,
            )

        return Signal(
            action=SignalAction.HOLD,
            reason=f"consensus_insufficient:{len(buy_signals)}/{self._min_agree}",
            confidence=0.1,
            context=context,
        )
