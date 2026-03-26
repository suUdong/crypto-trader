"""EMA crossover strategy: fast/slow EMA trend-following."""
from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import (
    _ema,
    average_directional_index,
    macd,
    rsi,
    stochastic_rsi,
    volume_sma,
)


class EMACrossoverStrategy:
    """Trend-following strategy using EMA(9)/EMA(21) crossover.

    BUY when fast EMA crosses above slow EMA with RSI confirmation.
    SELL when fast EMA crosses below slow EMA or RSI overbought.
    MACD histogram adds confidence boost when aligned.
    """

    def __init__(
        self,
        config: StrategyConfig,
        fast_period: int = 9,
        slow_period: int = 21,
    ) -> None:
        self._config = config
        self._fast_period = fast_period
        self._slow_period = slow_period

    def evaluate(
        self, candles: list[Candle], position: Position | None = None,
    ) -> Signal:
        minimum = max(self._slow_period + 2, self._config.rsi_period + 1, self._config.adx_period + 2)
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "ema_crossover"},
            )

        closes = [c.close for c in candles]
        fast_ema = _ema(closes, self._fast_period)
        slow_ema = _ema(closes, self._slow_period)
        rsi_value = rsi(closes, self._config.rsi_period)

        # Current and previous EMA values for crossover detection
        fast_now = fast_ema[-1]
        slow_now = slow_ema[-1]
        fast_prev = fast_ema[-2]
        slow_prev = slow_ema[-2]

        cross_up = fast_prev <= slow_prev and fast_now > slow_now
        cross_down = fast_prev >= slow_prev and fast_now < slow_now
        spread = (fast_now - slow_now) / slow_now if slow_now > 0 else 0.0

        # MACD confirmation
        macd_bullish = False
        macd_hist_val = 0.0
        if len(closes) >= 35:
            try:
                _, _, macd_hist_val = macd(closes)
                macd_bullish = macd_hist_val > 0
            except ValueError:
                pass

        # Stochastic RSI for overbought/oversold sensitivity
        stoch_rsi_val = 50.0
        if len(closes) >= 30:
            try:
                stoch_rsi_val = stochastic_rsi(closes, self._config.rsi_period, 14)
            except ValueError:
                pass

        # ADX trend strength filter
        adx_value: float | None = None
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            adx_value = average_directional_index(highs, lows, closes, self._config.adx_period)
        except ValueError:
            pass

        indicators = {
            "ema_fast": fast_now,
            "ema_slow": slow_now,
            "ema_spread": spread,
            "rsi": rsi_value,
            "stoch_rsi": stoch_rsi_val,
            "macd_histogram": macd_hist_val,
        }
        if adx_value is not None:
            indicators["adx"] = adx_value
        context = {"strategy": "ema_crossover"}

        if position is not None:
            return self._evaluate_exit(
                candles, position, cross_down, rsi_value, indicators, context,
            )

        return self._evaluate_entry(
            candles,
            cross_up,
            spread,
            rsi_value,
            stoch_rsi_val,
            macd_bullish,
            adx_value,
            indicators,
            context,
        )

    def _evaluate_entry(
        self,
        candles: list[Candle],
        cross_up: bool,
        spread: float,
        rsi_value: float,
        stoch_rsi_value: float,
        macd_bullish: bool,
        adx_value: float | None,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        # Entry: EMA crossover + RSI not overbought + StochRSI not extreme
        if (
            cross_up
            and rsi_value < self._config.rsi_overbought
            and stoch_rsi_value < 80.0
        ):
            # ADX filter: skip entry in choppy/trendless markets
            if adx_value is not None and adx_value < self._config.adx_threshold:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="adx_too_weak",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            # Volume filter: require above-average volume for entry
            if self._config.volume_filter_mult > 0:
                volumes = [c.volume for c in candles]
                try:
                    vol_avg = volume_sma(volumes, min(20, len(volumes)))
                    indicators["volume_ratio"] = volumes[-1] / vol_avg if vol_avg > 0 else 0.0
                    if volumes[-1] < vol_avg * self._config.volume_filter_mult:
                        return Signal(
                            action=SignalAction.HOLD,
                            reason="volume_too_low",
                            confidence=0.2,
                            indicators=indicators,
                            context=context,
                        )
                except ValueError:
                    pass
            base_conf = min(1.0, 0.5 + abs(spread) * 50)
            if macd_bullish:
                base_conf = min(1.0, base_conf + 0.1)
            return Signal(
                action=SignalAction.BUY,
                reason="ema_crossover_buy",
                confidence=base_conf,
                indicators=indicators,
                context=context,
            )

        # Also enter on strong uptrend (fast well above slow) with RSI confirmation
        if (
            spread > 0.005
            and self._config.rsi_oversold_floor <= rsi_value <= 60.0
            and stoch_rsi_value < 80.0
        ):
            # ADX filter for trend continuation too
            if adx_value is not None and adx_value < self._config.adx_threshold:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="adx_too_weak",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            base_conf = min(1.0, 0.4 + spread * 30)
            if macd_bullish:
                base_conf = min(1.0, base_conf + 0.1)
            return Signal(
                action=SignalAction.BUY,
                reason="ema_trend_continuation",
                confidence=base_conf,
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
        cross_down: bool,
        rsi_value: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        holding_bars = (
            0 if position.entry_index is None
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

        if cross_down:
            return Signal(
                action=SignalAction.SELL,
                reason="ema_crossover_sell",
                confidence=0.8,
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
