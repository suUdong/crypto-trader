from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import bollinger_bands, momentum, rsi


class CompositeStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self._config = config

    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal:
        minimum = max(
            self._config.bollinger_window + 1,
            self._config.momentum_lookback + 1,
            self._config.rsi_period + 1,
        )
        if len(candles) < minimum:
            return Signal(action=SignalAction.HOLD, reason="insufficient_data", confidence=0.0)

        closes = [candle.close for candle in candles]
        latest_close = closes[-1]
        previous_close = closes[-2]
        momentum_value = momentum(closes, self._config.momentum_lookback)
        upper_band, middle_band, lower_band = bollinger_bands(
            closes,
            self._config.bollinger_window,
            self._config.bollinger_stddev,
        )
        previous_upper, previous_middle, previous_lower = bollinger_bands(
            closes[:-1],
            self._config.bollinger_window,
            self._config.bollinger_stddev,
        )
        rsi_value = rsi(closes, self._config.rsi_period)
        indicators = {
            "momentum": momentum_value,
            "upper_band": upper_band,
            "middle_band": middle_band,
            "lower_band": lower_band,
            "previous_upper_band": previous_upper,
            "previous_middle_band": previous_middle,
            "previous_lower_band": previous_lower,
            "rsi": rsi_value,
        }

        crossed_back_above_lower = previous_close < previous_lower and latest_close > lower_band
        near_lower_band = latest_close <= lower_band or crossed_back_above_lower

        if position is None:
            entry_ready = (
                momentum_value >= self._config.momentum_entry_threshold
                and near_lower_band
                and self._config.rsi_oversold_floor
                <= rsi_value
                <= self._config.rsi_recovery_ceiling
            )
            if entry_ready:
                return Signal(
                    action=SignalAction.BUY,
                    reason="momentum_bollinger_rsi_alignment",
                    confidence=min(1.0, 0.5 + abs(momentum_value)),
                    indicators=indicators,
                )
            return Signal(
                action=SignalAction.HOLD,
                reason="entry_conditions_not_met",
                confidence=0.2,
                indicators=indicators,
            )

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
            )
        if momentum_value <= self._config.momentum_exit_threshold:
            return Signal(
                action=SignalAction.SELL,
                reason="momentum_reversal",
                confidence=min(1.0, 0.5 + abs(momentum_value)),
                indicators=indicators,
            )
        if rsi_value >= self._config.rsi_overbought:
            return Signal(
                action=SignalAction.SELL,
                reason="rsi_overbought",
                confidence=min(1.0, rsi_value / 100.0),
                indicators=indicators,
            )
        return Signal(
            action=SignalAction.HOLD,
            reason="position_open_waiting",
            confidence=0.2,
            indicators=indicators,
        )
