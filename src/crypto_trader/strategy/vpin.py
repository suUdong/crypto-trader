from __future__ import annotations

import math

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import momentum, rsi


class VPINStrategy:
    """Volume-Synchronized Probability of Informed Trading strategy.

    VPIN measures order flow toxicity using the Bulk Volume Classification
    method adapted for candle data. High VPIN indicates informed trading
    (potential adverse selection risk).

    VPIN > 0.7: high toxicity -> avoid entries, tighten stops on positions.
    VPIN < 0.3: low toxicity -> safe to enter with momentum confirmation.
    """

    def __init__(
        self,
        config: StrategyConfig,
        vpin_high_threshold: float = 0.7,
        vpin_low_threshold: float = 0.45,
        bucket_count: int = 20,
        vpin_momentum_threshold: float = 0.01,
        vpin_rsi_ceiling: float = 70.0,
        vpin_rsi_floor: float = 30.0,
    ) -> None:
        self._config = config
        self._vpin_high = vpin_high_threshold
        self._vpin_low = vpin_low_threshold
        self._bucket_count = bucket_count
        self._vpin_momentum_threshold = vpin_momentum_threshold
        self._vpin_rsi_ceiling = vpin_rsi_ceiling
        self._vpin_rsi_floor = vpin_rsi_floor

    def evaluate(
        self, candles: list[Candle], position: Position | None = None
    ) -> Signal:
        minimum = max(
            self._config.rsi_period + 1,
            self._config.momentum_lookback + 1,
            self._bucket_count + 1,
        )
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "vpin"},
            )

        closes = [c.close for c in candles]
        rsi_value = rsi(closes, self._config.rsi_period)
        momentum_value = momentum(closes, self._config.momentum_lookback)
        vpin_value = self._calculate_vpin(candles)
        indicators = {
            "vpin": vpin_value,
            "rsi": rsi_value,
            "momentum": momentum_value,
        }
        context = {"strategy": "vpin", "vpin_value": f"{vpin_value:.4f}"}

        if position is not None:
            return self._evaluate_exit(
                candles, position, vpin_value, rsi_value, indicators, context
            )
        return self._evaluate_entry(
            vpin_value, momentum_value, rsi_value, indicators, context
        )

    def _evaluate_entry(
        self,
        vpin_value: float,
        momentum_value: float,
        rsi_value: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        if vpin_value >= self._vpin_high:
            return Signal(
                action=SignalAction.HOLD,
                reason="vpin_high_toxicity",
                confidence=0.4,
                indicators=indicators,
                context=context,
            )

        if vpin_value <= self._vpin_low:
            if (
                momentum_value >= self._vpin_momentum_threshold
                and self._vpin_rsi_floor <= rsi_value <= self._vpin_rsi_ceiling
            ):
                return Signal(
                    action=SignalAction.BUY,
                    reason="vpin_safe_momentum_entry",
                    confidence=min(1.0, 0.5 + (self._vpin_low - vpin_value) * 2),
                    indicators=indicators,
                    context=context,
                )

        # Moderate VPIN zone: enter on strong momentum + RSI confirmation
        mid_threshold = (self._vpin_low + self._vpin_high) / 2
        if vpin_value <= mid_threshold:
            strong_momentum = momentum_value >= self._vpin_momentum_threshold * 2
            rsi_ok = self._vpin_rsi_floor <= rsi_value <= self._vpin_rsi_ceiling
            if strong_momentum and rsi_ok:
                return Signal(
                    action=SignalAction.BUY,
                    reason="vpin_moderate_momentum_entry",
                    confidence=min(1.0, 0.4 + momentum_value * 10),
                    indicators=indicators,
                    context=context,
                )

        return Signal(
            action=SignalAction.HOLD,
            reason="entry_conditions_not_met",
            confidence=0.2,
            indicators=indicators,
            context=context,
        )

    def _evaluate_exit(
        self,
        candles: list[Candle],
        position: Position,
        vpin_value: float,
        rsi_value: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        holding_bars = (
            0
            if position.entry_index is None
            else len(candles) - position.entry_index - 1
        )

        if holding_bars >= self._config.max_holding_bars:
            return Signal(
                action=SignalAction.SELL,
                reason="max_holding_period",
                confidence=1.0,
                indicators=indicators,
                context=context,
            )

        if vpin_value >= self._vpin_high:
            return Signal(
                action=SignalAction.SELL,
                reason="vpin_toxicity_exit",
                confidence=min(1.0, 0.5 + vpin_value),
                indicators=indicators,
                context=context,
            )

        if rsi_value >= self._config.rsi_overbought:
            return Signal(
                action=SignalAction.SELL,
                reason="rsi_overbought",
                confidence=min(1.0, rsi_value / 100.0),
                indicators=indicators,
                context=context,
            )

        return Signal(
            action=SignalAction.HOLD,
            reason="position_open_waiting",
            confidence=0.2,
            indicators=indicators,
            context=context,
        )

    def _calculate_vpin(self, candles: list[Candle]) -> float:
        """Calculate VPIN using Bulk Volume Classification on candles.

        Each candle's volume is classified as buy or sell using the
        normalized price change (close - open) / (high - low) mapped
        through the standard normal CDF approximation.
        """
        recent = candles[-self._bucket_count:]
        if not recent:
            return 0.5

        total_volume = sum(c.volume for c in recent)
        if total_volume <= 0:
            return 0.5

        abs_order_imbalance = 0.0
        for candle in recent:
            price_range = candle.high - candle.low
            if price_range <= 0:
                buy_fraction = 0.5
            else:
                z = (candle.close - candle.open) / price_range
                buy_fraction = _normal_cdf(z)

            buy_vol = candle.volume * buy_fraction
            sell_vol = candle.volume * (1.0 - buy_fraction)
            abs_order_imbalance += abs(buy_vol - sell_vol)

        return abs_order_imbalance / total_volume


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
