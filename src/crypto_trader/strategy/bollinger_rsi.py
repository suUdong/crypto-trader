from __future__ import annotations

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import bollinger_bands, rsi
from crypto_trader.strategy.regime import RegimeDetector


class BollingerRsiStrategy:
    """Pure Bollinger Bands + RSI reversal strategy."""

    def __init__(self, config: StrategyConfig, regime_config: RegimeConfig | None = None) -> None:
        self._config = config
        self._regime_detector = RegimeDetector(regime_config or RegimeConfig())

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        regime = self._regime_detector.detect(candles)
        effective = self._regime_detector.adjust(self._config, regime)
        minimum = max(effective.bollinger_window + 1, effective.rsi_period + 1)
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"market_regime": regime.value, "strategy": "bollinger_rsi"},
            )

        closes = [c.close for c in candles]
        latest_close = closes[-1]
        previous_close = closes[-2]
        upper_band, middle_band, lower_band = bollinger_bands(
            closes,
            effective.bollinger_window,
            effective.bollinger_stddev,
        )
        _, _, previous_lower = bollinger_bands(
            closes[:-1],
            effective.bollinger_window,
            effective.bollinger_stddev,
        )
        rsi_value = rsi(closes, effective.rsi_period)
        band_width = max(upper_band - lower_band, 1e-9)
        extension = max(0.0, (lower_band - latest_close) / band_width)
        crossed_back_above_lower = previous_close < previous_lower and latest_close > lower_band
        near_lower_band = latest_close <= lower_band or crossed_back_above_lower

        indicators = {
            "upper_band": upper_band,
            "middle_band": middle_band,
            "lower_band": lower_band,
            "rsi": rsi_value,
            "band_extension": extension,
        }
        context = {"market_regime": regime.value, "strategy": "bollinger_rsi"}

        if position is None:
            entry_ready = (
                near_lower_band
                and effective.rsi_oversold_floor <= rsi_value <= effective.rsi_recovery_ceiling
            )
            if entry_ready:
                rsi_reset = max(0.0, effective.rsi_recovery_ceiling - rsi_value)
                confidence = min(1.0, 0.55 + extension * 0.35 + (rsi_reset / 100.0) * 0.2)
                return Signal(
                    action=SignalAction.BUY,
                    reason="bollinger_rsi_reversion",
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

        pnl_pct = (latest_close - position.entry_price) / max(position.entry_price, 1e-9)
        if latest_close >= upper_band:
            return Signal(
                action=SignalAction.SELL,
                reason="bollinger_upper_touch",
                confidence=0.85,
                indicators=indicators,
                context=context,
            )
        if latest_close >= middle_band and pnl_pct >= 0.01:
            return Signal(
                action=SignalAction.SELL,
                reason="middle_band_target",
                confidence=0.7,
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
