"""Consensus strategy: only enters when multiple sub-strategies agree."""
from __future__ import annotations

from collections.abc import Sequence

from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.evaluator import evaluate_strategy


class ConsensusStrategy:
    """Multi-strategy consensus filter with weighted voting.

    Supports two modes:
    1. Count-based (classic): BUY when >= min_agree sub-strategies signal BUY.
    2. Weighted quorum: BUY when weighted score >= quorum_threshold (0.0-1.0).

    Exit modes:
    - "any" (default): SELL when ANY sub-strategy signals SELL (conservative).
    - "majority": SELL only when majority of sub-strategies signal SELL.

    Per-strategy weights allow prioritizing stronger strategies in the vote.
    """

    def __init__(
        self,
        strategies: Sequence[object],
        min_agree: int = 2,
        min_confidence_sum: float = 0.0,
        weights: Sequence[float] | None = None,
        quorum_threshold: float = 0.0,
        exit_mode: str = "any",
    ) -> None:
        if not strategies:
            raise ValueError("ConsensusStrategy requires at least one sub-strategy")
        self._strategies = list(strategies)
        self._min_agree = max(1, min(min_agree, len(strategies)))
        self._min_confidence_sum = min_confidence_sum
        # Per-strategy weights: default to equal weight (1.0 each)
        if weights is not None:
            if len(weights) != len(strategies):
                raise ValueError("weights length must match strategies length")
            self._weights = [max(0.0, w) for w in weights]
        else:
            self._weights = [1.0] * len(strategies)
        # Weighted quorum: if > 0, uses weighted scoring instead of simple count
        self._quorum_threshold = max(0.0, min(1.0, quorum_threshold))
        # Exit mode: "any" or "majority"
        if exit_mode not in ("any", "majority"):
            raise ValueError(f"exit_mode must be 'any' or 'majority', got '{exit_mode}'")
        self._exit_mode = exit_mode

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        signals: list[Signal] = []
        for strategy in self._strategies:
            sig = evaluate_strategy(strategy, candles, position, symbol=symbol)
            signals.append(sig)

        context = {
            "strategy": "consensus",
            "sub_signals": ",".join(s.action.value for s in signals),
            "min_agree": str(self._min_agree),
        }

        # If holding a position, evaluate exit
        if position is not None:
            return self._evaluate_exit(signals, context)

        # Entry: evaluate buy consensus
        return self._evaluate_entry(signals, context)

    def _evaluate_exit(
        self,
        signals: list[Signal],
        context: dict[str, str],
    ) -> Signal:
        sell_signals = [s for s in signals if s.action is SignalAction.SELL]

        if self._exit_mode == "majority":
            # Majority exit: need > 50% of weighted votes to SELL
            total_weight = sum(self._weights)
            sell_weight = sum(
                self._weights[i]
                for i, s in enumerate(signals)
                if s.action is SignalAction.SELL
            )
            if total_weight > 0 and sell_weight > total_weight * 0.5 and sell_signals:
                best_sell = max(sell_signals, key=lambda s: s.confidence)
                return Signal(
                    action=SignalAction.SELL,
                    reason=f"consensus_majority_exit:{best_sell.reason}",
                    confidence=best_sell.confidence,
                    indicators=best_sell.indicators,
                    context=context,
                )
        else:
            # Any exit (conservative): any SELL triggers exit
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

    def _evaluate_entry(
        self,
        signals: list[Signal],
        context: dict[str, str],
    ) -> Signal:
        buy_signals = [s for s in signals if s.action is SignalAction.BUY]
        buy_indices = [i for i, s in enumerate(signals) if s.action is SignalAction.BUY]

        # Check weighted quorum if enabled
        if self._quorum_threshold > 0:
            total_weight = sum(self._weights)
            if total_weight > 0:
                # Weighted score: sum of (weight * confidence) for BUY signals / total weight
                weighted_buy_score = sum(
                    self._weights[i] * signals[i].confidence
                    for i in buy_indices
                ) / total_weight
                context["weighted_score"] = f"{weighted_buy_score:.3f}"
                context["quorum_threshold"] = f"{self._quorum_threshold:.3f}"

                if weighted_buy_score >= self._quorum_threshold:
                    return self._build_buy_signal(buy_signals, buy_indices, signals, context)

                return Signal(
                    action=SignalAction.HOLD,
                    reason=f"consensus_quorum_not_met:{weighted_buy_score:.3f}/{self._quorum_threshold:.3f}",
                    confidence=0.1,
                    context=context,
                )

        # Classic count-based consensus
        confidence_sum = sum(s.confidence for s in buy_signals)
        meets_count = len(buy_signals) >= self._min_agree
        meets_confidence = (
            self._min_confidence_sum <= 0
            or confidence_sum >= self._min_confidence_sum
        )

        if meets_count and meets_confidence:
            return self._build_buy_signal(buy_signals, buy_indices, signals, context)

        return Signal(
            action=SignalAction.HOLD,
            reason=f"consensus_insufficient:{len(buy_signals)}/{self._min_agree}",
            confidence=0.1,
            context=context,
        )

    def _build_buy_signal(
        self,
        buy_signals: list[Signal],
        buy_indices: list[int],
        all_signals: list[Signal],
        context: dict[str, str],
    ) -> Signal:
        # Weighted confidence: factor in per-strategy weights
        total_weight = sum(self._weights[i] for i in buy_indices)
        if total_weight > 0:
            weighted_conf = sum(
                self._weights[i] * all_signals[i].confidence ** 2
                for i in buy_indices
            ) / total_weight
        else:
            weighted_conf = 0.0

        # Agreement ratio boost: more strategies agreeing = higher confidence
        agree_ratio = len(buy_signals) / len(all_signals)
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
