from __future__ import annotations

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import (
    _ema,
    average_directional_index,
    bollinger_bands,
    chaikin_money_flow,
    momentum,
    obv_slope,
    rolling_vwap,
    rsi,
    williams_percent_r,
)
from crypto_trader.strategy.regime import RegimeDetector


class MomentumPullbackStrategy:
    """Buy controlled pullbacks inside an established uptrend."""

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
        analysis = self._regime_detector.analyze(candles)
        regime = analysis.regime
        effective = self._regime_detector.adjust(
            self._config,
            regime,
            is_weekend=analysis.is_weekend,
        )
        minimum = max(
            50,
            effective.momentum_lookback + 1,
            effective.bollinger_window + 1,
            effective.rsi_period + 1,
        )
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"market_regime": regime.value, "strategy": "momentum_pullback"},
            )

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]
        latest_close = closes[-1]
        previous_close = closes[-2]

        momentum_value = momentum(closes, effective.momentum_lookback)
        trend_lookback = min(
            len(closes) - 1,
            max(effective.momentum_lookback * 2, effective.momentum_lookback + 5),
        )
        trend_momentum = momentum(closes, trend_lookback)
        rsi_value = rsi(closes, effective.rsi_period)
        upper_band, middle_band, lower_band = bollinger_bands(
            closes,
            effective.bollinger_window,
            effective.bollinger_stddev,
        )
        ema20 = _ema(closes, 20)[-1]
        ema50 = _ema(closes, 50)[-1]

        indicators = {
            "momentum": momentum_value,
            "trend_momentum": trend_momentum,
            "rsi": rsi_value,
            "upper_band": upper_band,
            "middle_band": middle_band,
            "lower_band": lower_band,
            "ema20": ema20,
            "ema50": ema50,
        }
        context = {"market_regime": regime.value, "strategy": "momentum_pullback"}

        adx_value: float | None = None
        try:
            adx_value = average_directional_index(highs, lows, closes, effective.adx_period)
            indicators["adx"] = adx_value
        except ValueError:
            pass

        vwap_value: float | None = None
        try:
            vwap_value = rolling_vwap(highs, lows, closes, volumes, window=20)
            indicators["vwap"] = vwap_value
        except ValueError:
            pass

        obv_trend: float | None = None
        try:
            obv_trend = obv_slope(closes, volumes, lookback=10)
            indicators["obv_slope"] = obv_trend
        except ValueError:
            pass

        cmf_value: float | None = None
        try:
            cmf_value = chaikin_money_flow(highs, lows, closes, volumes, period=20)
            indicators["cmf"] = cmf_value
        except ValueError:
            pass

        wpr_value: float | None = None
        try:
            wpr_value = williams_percent_r(highs, lows, closes, period=min(14, len(closes)))
            indicators["williams_r"] = wpr_value
        except ValueError:
            pass

        recent_high = max(closes[-effective.momentum_lookback :])
        pullback_depth = (recent_high - latest_close) / recent_high if recent_high > 0 else 0.0
        indicators["pullback_depth"] = pullback_depth

        pullback_rsi_ceiling = effective.rsi_recovery_ceiling
        if trend_momentum > effective.momentum_entry_threshold * 3.0:
            pullback_rsi_ceiling = min(75.0, pullback_rsi_ceiling + 10.0)
        indicators["pullback_rsi_ceiling"] = pullback_rsi_ceiling

        trend_up = (
            latest_close > ema50
            and ema20 > ema50
            and trend_momentum >= effective.momentum_entry_threshold
            and momentum_value > min(-0.03, effective.momentum_exit_threshold * 2.0)
        )
        pullback_zone = latest_close <= middle_band * 1.03 and latest_close >= lower_band * 0.97
        above_structure = latest_close >= ema50 * 0.995
        vwap_discount = (
            vwap_value is None or latest_close <= vwap_value * 1.02 or pullback_depth >= 0.015
        )
        pullback_reset = effective.rsi_oversold_floor <= rsi_value <= pullback_rsi_ceiling
        pullback_depth_ok = (
            max(0.008, effective.momentum_entry_threshold * 1.5) <= pullback_depth <= 0.08
        )
        recent_pullback_low = min(closes[-3:])
        orderly_pullback = (
            latest_close <= previous_close
            or latest_close <= ema20 * 1.02
            or recent_pullback_low <= ema20
        )

        if position is None:
            if not trend_up:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="trend_not_established",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            if adx_value is not None and adx_value < effective.adx_threshold:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="trend_strength_too_weak",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            if not (
                pullback_zone
                and above_structure
                and vwap_discount
                and pullback_reset
                and pullback_depth_ok
                and orderly_pullback
            ):
                return Signal(
                    action=SignalAction.HOLD,
                    reason="pullback_conditions_not_met",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            if obv_trend is not None and obv_trend < -0.35:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="distribution_risk",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )
            if cmf_value is not None and cmf_value < -0.2:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="cashflow_too_negative",
                    confidence=0.2,
                    indicators=indicators,
                    context=context,
                )

            confidence = 0.55
            confidence += min(0.15, max(0.0, trend_momentum) * 3.0)
            if adx_value is not None and adx_value >= effective.adx_threshold + 5.0:
                confidence += 0.05
            if pullback_depth <= 0.04:
                confidence += 0.05
            if obv_trend is not None and obv_trend > 0.0:
                confidence += 0.05
            if cmf_value is not None and cmf_value >= 0.0:
                confidence += 0.05
            if wpr_value is not None and wpr_value < -70.0:
                confidence += 0.05
            return Signal(
                action=SignalAction.BUY,
                reason="trend_pullback_entry",
                confidence=min(1.0, confidence),
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
        if momentum_value <= effective.momentum_exit_threshold or latest_close < ema50 * 0.995:
            return Signal(
                action=SignalAction.SELL,
                reason="trend_failure",
                confidence=0.8,
                indicators=indicators,
                context=context,
            )
        if latest_close >= upper_band:
            return Signal(
                action=SignalAction.SELL,
                reason="pullback_recovery_target",
                confidence=0.8,
                indicators=indicators,
                context=context,
            )
        if latest_close >= middle_band and rsi_value >= effective.rsi_overbought:
            return Signal(
                action=SignalAction.SELL,
                reason="pullback_overbought_exit",
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
