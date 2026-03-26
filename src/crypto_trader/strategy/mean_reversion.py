from __future__ import annotations

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import bollinger_bands, macd, noise_ratio, rsi, rsi_divergence
from crypto_trader.strategy.regime import RegimeDetector


class MeanReversionStrategy:
    def __init__(self, config: StrategyConfig, regime_config: RegimeConfig | None = None) -> None:
        self._config = config
        self._regime_detector = RegimeDetector(regime_config or RegimeConfig())

    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal:
        regime = self._regime_detector.detect(candles)
        effective = self._regime_detector.adjust(self._config, regime)
        minimum = max(effective.bollinger_window + 1, effective.rsi_period + 1)
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"market_regime": regime.value, "strategy": "mean_reversion"},
            )

        closes = [c.close for c in candles]
        latest_close = closes[-1]
        previous_close = closes[-2]
        upper_band, middle_band, lower_band = bollinger_bands(
            closes, effective.bollinger_window, effective.bollinger_stddev
        )
        previous_upper, previous_middle, previous_lower = bollinger_bands(
            closes[:-1], effective.bollinger_window, effective.bollinger_stddev
        )
        rsi_value = rsi(closes, effective.rsi_period)

        # MACD confirmation (optional, needs 35+ candles)
        macd_bullish = False
        macd_hist_val = 0.0
        if len(closes) >= 35:
            try:
                _, _, macd_hist_val = macd(closes)
                macd_bullish = macd_hist_val > 0
            except ValueError:
                pass

        # RSI divergence detection
        bullish_div = False
        bearish_div = False
        try:
            bullish_div, bearish_div = rsi_divergence(closes, effective.rsi_period, lookback=20)
        except (ValueError, IndexError):
            pass

        indicators = {
            "upper_band": upper_band,
            "middle_band": middle_band,
            "lower_band": lower_band,
            "rsi": rsi_value,
            "macd_histogram": macd_hist_val,
            "rsi_bullish_divergence": 1.0 if bullish_div else 0.0,
            "rsi_bearish_divergence": 1.0 if bearish_div else 0.0,
        }
        context = {"market_regime": regime.value, "strategy": "mean_reversion"}

        # Band distance scoring: how far below lower band (deeper = better entry)
        band_width = upper_band - lower_band
        if band_width > 0:
            band_distance = (lower_band - latest_close) / band_width
            indicators["band_distance"] = max(0.0, band_distance)
        else:
            band_distance = 0.0
            indicators["band_distance"] = 0.0

        # Noise ratio: high noise = choppy/ranging (good for MR), low noise = trending (bad)
        nr_value: float | None = None
        try:
            nr_value = noise_ratio(closes, effective.noise_lookback)
            indicators["noise_ratio"] = nr_value
        except ValueError:
            pass

        crossed_back_above_lower = previous_close < previous_lower and latest_close > lower_band
        near_lower_band = latest_close <= lower_band or crossed_back_above_lower

        if position is None:
            # Noise ratio filter: skip entry in strongly trending markets (bad for MR)
            if nr_value is not None and nr_value < 0.5:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="market_too_trendy",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            # RSI confirmation: require RSI below oversold_floor + 10 to avoid false bottoms
            rsi_entry_limit = effective.rsi_oversold_floor + 10.0
            if near_lower_band and rsi_value <= rsi_entry_limit:
                base_conf = min(1.0, 0.5 + (middle_band - latest_close) / max(1.0, middle_band))
                if macd_bullish:
                    base_conf = min(1.0, base_conf + 0.1)
                if bullish_div:
                    base_conf = min(1.0, base_conf + 0.15)
                # Deeper dip below lower band = higher confidence
                if band_distance > 0:
                    base_conf = min(1.0, base_conf + band_distance * 0.3)
                return Signal(
                    action=SignalAction.BUY,
                    reason="bollinger_mean_reversion",
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
        # Middle band target: take profit when price reaches middle band with decent profit
        pnl_pct = (latest_close - position.entry_price) / position.entry_price
        if latest_close >= middle_band * 0.99 and latest_close < upper_band and pnl_pct >= 0.02:
            return Signal(
                action=SignalAction.SELL,
                reason="middle_band_target",
                confidence=0.65,
                indicators=indicators,
                context=context,
            )
        if latest_close >= upper_band:
            return Signal(
                action=SignalAction.SELL,
                reason="bollinger_upper_touch",
                confidence=0.8,
                indicators=indicators,
                context=context,
            )
        if latest_close >= middle_band and rsi_value >= effective.rsi_overbought:
            return Signal(
                action=SignalAction.SELL,
                reason="mean_reversion_target",
                confidence=0.7,
                indicators=indicators,
                context=context,
            )
        if bearish_div:
            return Signal(
                action=SignalAction.SELL,
                reason="rsi_bearish_divergence",
                confidence=0.75,
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
