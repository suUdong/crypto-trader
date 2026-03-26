from __future__ import annotations

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import (
    _ema,
    average_directional_index,
    keltner_channels,
    macd,
    momentum,
    noise_ratio,
    obv_slope,
    rolling_vwap,
    rsi,
    volume_sma,
)
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
            "rsi": rsi_value,
            "macd_line": macd_line_val,
            "macd_signal": macd_signal_val,
            "macd_histogram": macd_hist_val,
        }
        context = {"market_regime": regime.value, "strategy": "momentum"}

        # ADX trend strength filter
        adx_value: float | None = None
        try:
            adx_value = average_directional_index(highs, lows, closes, effective.adx_period)
            indicators["adx"] = adx_value
        except ValueError:
            pass

        # OBV trend confirmation
        obv_trend: float | None = None
        try:
            volumes_list = [c.volume for c in candles]
            obv_trend = obv_slope(closes, volumes_list, lookback=10)
            indicators["obv_slope"] = obv_trend
        except ValueError:
            pass

        # Keltner Channels
        kc_upper: float | None = None
        try:
            kc_upper, _, _ = keltner_channels(highs, lows, closes)
            indicators["keltner_upper"] = kc_upper
        except ValueError:
            pass

        # VWAP: price above VWAP = bullish bias
        vwap_value: float | None = None
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            vwap_value = rolling_vwap(highs, lows, closes, volumes_list, window=20)
            indicators["vwap"] = vwap_value
        except ValueError:
            pass

        # Multi-timeframe trend: EMA(50) as macro trend filter
        macro_trend_up = False
        if len(closes) >= 50:
            ema50 = _ema(closes, 50)[-1]
            indicators["ema50"] = ema50
            macro_trend_up = closes[-1] > ema50

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
                base_conf = min(1.0, 0.5 + abs(momentum_value))
                if macd_bullish:
                    base_conf = min(1.0, base_conf + 0.1)
                # Macro trend alignment boosts confidence
                if macro_trend_up:
                    base_conf = min(1.0, base_conf + 0.05)
                # OBV accumulation boosts confidence
                if obv_trend is not None and obv_trend > 0.3:
                    base_conf = min(1.0, base_conf + 0.05)
                # VWAP alignment: price above VWAP confirms bullish bias
                if vwap_value is not None and closes[-1] > vwap_value:
                    base_conf = min(1.0, base_conf + 0.05)
                # Keltner breakout: price above upper Keltner = strong momentum
                if kc_upper is not None and closes[-1] > kc_upper:
                    base_conf = min(1.0, base_conf + 0.05)
                # Volume confirmation: high volume (>2x avg) boosts confidence
                volumes = [c.volume for c in candles]
                try:
                    vol_avg = volume_sma(volumes, min(20, len(volumes)))
                    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
                    if "volume_ratio" not in indicators:
                        indicators["volume_ratio"] = vol_ratio
                    if vol_ratio >= 2.0:
                        base_conf = min(1.0, base_conf + 0.1)
                except ValueError:
                    pass
                return Signal(
                    action=SignalAction.BUY,
                    reason="momentum_rsi_alignment",
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
