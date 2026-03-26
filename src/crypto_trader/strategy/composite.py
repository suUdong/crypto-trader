from __future__ import annotations

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import (
    _ema,
    average_directional_index,
    bollinger_bands,
    macd,
    momentum,
    obv_slope,
    rolling_vwap,
    rsi,
    volume_sma,
)
from crypto_trader.strategy.regime import RegimeDetector


class CompositeStrategy:
    def __init__(self, config: StrategyConfig, regime_config: RegimeConfig | None = None) -> None:
        self._config = config
        self._regime_detector = RegimeDetector(regime_config or RegimeConfig())

    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal:
        regime = self._regime_detector.detect(candles)
        effective = self._regime_detector.adjust(self._config, regime)
        minimum = max(
            effective.bollinger_window + 1,
            effective.momentum_lookback + 1,
            effective.rsi_period + 1,
        )
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"market_regime": regime.value},
            )

        closes = [candle.close for candle in candles]
        latest_close = closes[-1]
        previous_close = closes[-2]
        momentum_value = momentum(closes, effective.momentum_lookback)
        upper_band, middle_band, lower_band = bollinger_bands(
            closes,
            effective.bollinger_window,
            effective.bollinger_stddev,
        )
        previous_upper, previous_middle, previous_lower = bollinger_bands(
            closes[:-1],
            effective.bollinger_window,
            effective.bollinger_stddev,
        )
        rsi_value = rsi(closes, effective.rsi_period)

        # MACD confirmation (optional, needs 35+ candles)
        macd_bullish = False
        macd_line_val = 0.0
        macd_signal_val = 0.0
        macd_hist_val = 0.0
        if len(closes) >= 35:
            try:
                macd_line_val, macd_signal_val, macd_hist_val = macd(closes)
                macd_bullish = macd_hist_val > 0
            except ValueError:
                pass

        indicators = {
            "momentum": momentum_value,
            "upper_band": upper_band,
            "middle_band": middle_band,
            "lower_band": lower_band,
            "previous_upper_band": previous_upper,
            "previous_middle_band": previous_middle,
            "previous_lower_band": previous_lower,
            "rsi": rsi_value,
            "macd_line": macd_line_val,
            "macd_signal": macd_signal_val,
            "macd_histogram": macd_hist_val,
        }

        # ADX trend strength filter
        adx_value: float | None = None
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            adx_value = average_directional_index(highs, lows, closes, effective.adx_period)
            indicators["adx"] = adx_value
        except ValueError:
            pass

        # Multi-timeframe trend: EMA(50) as macro trend filter
        macro_trend_up = False
        if len(closes) >= 50:
            ema50 = _ema(closes, 50)[-1]
            indicators["ema50"] = ema50
            macro_trend_up = latest_close > ema50

        crossed_back_above_lower = previous_close < previous_lower and latest_close > lower_band
        near_lower_band = latest_close <= lower_band or crossed_back_above_lower
        context = {"market_regime": regime.value}

        # OBV trend confirmation
        obv_trend: float | None = None
        try:
            volumes = [c.volume for c in candles]
            obv_trend = obv_slope(closes, volumes, lookback=10)
            indicators["obv_slope"] = obv_trend
        except ValueError:
            pass

        # VWAP: price above VWAP = bullish bias
        vwap_value: float | None = None
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            vwap_value = rolling_vwap(highs, lows, closes, [c.volume for c in candles], window=20)
            indicators["vwap"] = vwap_value
        except ValueError:
            pass

        if position is None:
            entry_ready = (
                momentum_value >= effective.momentum_entry_threshold
                and near_lower_band
                and effective.rsi_oversold_floor
                <= rsi_value
                <= effective.rsi_recovery_ceiling
            )
            if entry_ready:
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
                base_conf = min(1.0, 0.5 + abs(momentum_value))
                # MACD confirmation boosts confidence by 0.1
                if macd_bullish:
                    base_conf = min(1.0, base_conf + 0.1)
                # Macro trend alignment boosts confidence
                if macro_trend_up:
                    base_conf = min(1.0, base_conf + 0.05)
                # OBV accumulation boosts confidence
                if obv_trend is not None and obv_trend > 0.3:
                    base_conf = min(1.0, base_conf + 0.05)
                # VWAP alignment: price above VWAP confirms bullish bias
                if vwap_value is not None and latest_close > vwap_value:
                    base_conf = min(1.0, base_conf + 0.05)
                return Signal(
                    action=SignalAction.BUY,
                    reason="momentum_bollinger_rsi_alignment",
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

        holding_bars = (
            0
            if position.entry_index is None
            else len(candles) - position.entry_index - 1
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
