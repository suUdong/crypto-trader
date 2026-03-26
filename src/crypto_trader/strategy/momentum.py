from __future__ import annotations

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import average_directional_index, momentum, rsi, volume_sma
from crypto_trader.strategy.regime import RegimeDetector


class MomentumStrategy:
    def __init__(self, config: StrategyConfig, regime_config: RegimeConfig | None = None) -> None:
        self._config = config
        self._regime_detector = RegimeDetector(regime_config or RegimeConfig())

    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal:
        regime = self._regime_detector.detect(candles)
        effective = self._regime_detector.adjust(self._config, regime)
        minimum = max(effective.momentum_lookback + 1, effective.rsi_period + 1)
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"market_regime": regime.value, "strategy": "momentum"},
            )

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        momentum_value = momentum(closes, effective.momentum_lookback)
        rsi_value = rsi(closes, effective.rsi_period)
        indicators = {"momentum": momentum_value, "rsi": rsi_value}
        context = {"market_regime": regime.value, "strategy": "momentum"}

        # ADX trend strength filter
        adx_value: float | None = None
        try:
            adx_value = average_directional_index(highs, lows, closes, effective.adx_period)
            indicators["adx"] = adx_value
        except ValueError:
            pass

        if position is None:
            # Adaptive RSI ceiling: strong momentum widens the acceptable RSI range.
            # When base ceiling < 80 and momentum exceeds entry threshold, widen
            # up to 80 so strong-trend entries aren't blocked by narrow RSI window.
            rsi_ceiling = effective.rsi_recovery_ceiling
            if rsi_ceiling < 80.0 and momentum_value > effective.momentum_entry_threshold:
                excess = momentum_value - effective.momentum_entry_threshold
                rsi_ceiling = min(80.0, rsi_ceiling + excess * 1000.0)
            indicators["rsi_ceiling"] = rsi_ceiling

            if (
                momentum_value >= effective.momentum_entry_threshold
                and effective.rsi_oversold_floor <= rsi_value <= rsi_ceiling
            ):
                # ADX filter: skip entry in choppy/trendless markets
                if adx_value is not None and adx_value < effective.adx_threshold:
                    return Signal(
                        action=SignalAction.HOLD,
                        reason="adx_too_weak",
                        confidence=0.2,
                        indicators=indicators,
                        context=context,
                    )
                # Volume filter: require above-average volume for entry
                if effective.volume_filter_mult > 0:
                    volumes = [c.volume for c in candles]
                    try:
                        vol_avg = volume_sma(volumes, min(20, len(volumes)))
                        indicators["volume_ratio"] = volumes[-1] / vol_avg if vol_avg > 0 else 0.0
                        if volumes[-1] < vol_avg * effective.volume_filter_mult:
                            return Signal(
                                action=SignalAction.HOLD,
                                reason="volume_too_low",
                                confidence=0.2,
                                indicators=indicators,
                                context=context,
                            )
                    except ValueError:
                        pass
                return Signal(
                    action=SignalAction.BUY,
                    reason="momentum_rsi_alignment",
                    confidence=min(1.0, 0.5 + abs(momentum_value)),
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

        holding_bars = (
            0 if position.entry_index is None else len(candles) - position.entry_index - 1
        )
        if holding_bars >= effective.max_holding_bars:
            return Signal(
                action=SignalAction.SELL,
                reason="max_holding_period",
                confidence=1.0,
                indicators=indicators,
                context=context,
            )
        if momentum_value <= effective.momentum_exit_threshold:
            return Signal(
                action=SignalAction.SELL,
                reason="momentum_reversal",
                confidence=min(1.0, 0.5 + abs(momentum_value)),
                indicators=indicators,
                context=context,
            )
        if rsi_value >= effective.rsi_overbought:
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
