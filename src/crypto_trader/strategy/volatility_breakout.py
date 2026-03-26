from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import (
    average_directional_index,
    bollinger_band_width,
    macd,
    noise_ratio,
    simple_moving_average,
    volume_sma,
)


class VolatilityBreakoutStrategy:
    """Larry Williams-style volatility breakout for Upbit KRW pairs.

    BUY when price > prev_close + k * prev_range.
    k is dynamically adjusted by noise ratio (lower noise = higher k).
    MA filter avoids entries against the trend.
    """

    def __init__(
        self,
        config: StrategyConfig,
        k_base: float = 0.5,
        noise_lookback: int = 20,
        ma_filter_period: int = 20,
        max_holding_bars: int | None = None,
    ) -> None:
        self._config = config
        self._k_base = k_base
        self._noise_lookback = noise_lookback
        self._ma_filter_period = ma_filter_period
        self._max_holding_bars = max_holding_bars if max_holding_bars is not None else config.max_holding_bars

    def evaluate(
        self, candles: list[Candle], position: Position | None = None
    ) -> Signal:
        minimum = max(self._noise_lookback + 2, self._ma_filter_period + 1, 3)
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "volatility_breakout"},
            )

        closes = [c.close for c in candles]
        current_price = closes[-1]
        prev_candle = candles[-2]
        prev_range = prev_candle.high - prev_candle.low

        context = {"strategy": "volatility_breakout"}
        indicators: dict[str, float] = {}

        # Dynamic k based on noise ratio
        nr = noise_ratio(closes, self._noise_lookback)
        k = self._k_base * (1.0 - nr * 0.5)  # lower noise → higher k (stricter)
        k = max(0.1, min(0.9, k))
        indicators["noise_ratio"] = nr
        indicators["k"] = k

        breakout_level = prev_candle.close + k * prev_range
        indicators["breakout_level"] = breakout_level

        # MA trend filter
        ma = simple_moving_average(closes, self._ma_filter_period)
        indicators["ma_filter"] = ma

        # ADX trend strength filter
        adx_value: float | None = None
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            adx_value = average_directional_index(highs, lows, closes, self._config.adx_period)
            indicators["adx"] = adx_value
        except ValueError:
            pass

        # Bollinger Band width (squeeze detection)
        bb_w = 0.0
        squeeze = False
        try:
            bb_w = bollinger_band_width(closes, 20, 2.0)
            indicators["bb_width"] = bb_w
            # Squeeze: width below 0.04 (tight bands = breakout imminent)
            squeeze = bb_w < 0.04
        except ValueError:
            pass

        # MACD confirmation
        macd_bullish = False
        macd_hist_val = 0.0
        if len(closes) >= 35:
            try:
                _, _, macd_hist_val = macd(closes)
                macd_bullish = macd_hist_val > 0
                indicators["macd_histogram"] = macd_hist_val
            except ValueError:
                pass

        # Volume filter: compute ratio before entry check
        volume_ok = True
        vol_mult = self._config.volume_filter_mult
        if vol_mult > 0:
            volumes = [c.volume for c in candles]
            try:
                vol_avg = volume_sma(volumes, min(20, len(volumes)))
                indicators["volume_ratio"] = volumes[-1] / vol_avg if vol_avg > 0 else 0.0
                if volumes[-1] < vol_avg * vol_mult:
                    volume_ok = False
            except ValueError:
                pass

        if position is not None:
            return self._evaluate_exit(candles, position, current_price, indicators, context)

        return self._evaluate_entry(current_price, breakout_level, ma, adx_value, volume_ok, macd_bullish, squeeze, indicators, context)

    def _evaluate_entry(
        self,
        current_price: float,
        breakout_level: float,
        ma: float,
        adx_value: float | None,
        volume_ok: bool,
        macd_bullish: bool,
        squeeze: bool,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        # MA filter: only buy above MA (trend confirmation)
        if current_price < ma:
            return Signal(
                action=SignalAction.HOLD,
                reason="below_ma_filter",
                confidence=0.2,
                indicators=indicators,
                context=context,
            )

        if current_price >= breakout_level:
            # ADX filter: skip entry in choppy/trendless markets
            if adx_value is not None and adx_value < self._config.adx_threshold:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="adx_too_weak",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            # Volume filter
            if not volume_ok:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="volume_too_low",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            # Confidence based on how far above breakout level
            excess = (current_price - breakout_level) / breakout_level if breakout_level > 0 else 0
            confidence = min(1.0, 0.6 + excess * 10)
            if macd_bullish:
                confidence = min(1.0, confidence + 0.1)
            if squeeze:
                confidence = min(1.0, confidence + 0.1)
            return Signal(
                action=SignalAction.BUY,
                reason="volatility_breakout",
                confidence=confidence,
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
        current_price: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        # Time-based exit: holding too long
        if position.entry_index is not None:
            holding_bars = len(candles) - position.entry_index - 1
        else:
            elapsed_hours = (candles[-1].timestamp - position.entry_time).total_seconds() / 3600.0
            holding_bars = int(elapsed_hours)

        if holding_bars >= self._max_holding_bars:
            return Signal(
                action=SignalAction.SELL,
                reason="max_holding_period",
                confidence=1.0,
                indicators=indicators,
                context=context,
            )

        # Exit on close below previous candle low (trailing stop logic)
        prev_low = candles[-2].low
        if current_price < prev_low:
            return Signal(
                action=SignalAction.SELL,
                reason="close_below_prev_low",
                confidence=0.8,
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
