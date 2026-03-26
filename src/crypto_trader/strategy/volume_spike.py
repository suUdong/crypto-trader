"""Volume Spike strategy: enters on abnormal volume with price confirmation."""
from __future__ import annotations

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import (
    _ema,
    average_directional_index,
    chaikin_money_flow,
    macd,
    momentum,
    obv_slope,
    rolling_vwap,
    rsi,
    volume_sma,
)
from crypto_trader.strategy.regime import RegimeDetector


class VolumeSpikeStrategy:
    """Detects abnormal volume spikes with directional price confirmation.

    Entry: volume > spike_mult * avg_volume AND price direction confirms
    (momentum > 0, RSI not overbought, bullish candle body).

    This captures institutional accumulation events and breakout moves
    that are often preceded or accompanied by volume surges.
    """

    def __init__(
        self,
        config: StrategyConfig,
        regime_config: RegimeConfig | None = None,
        spike_mult: float = 2.5,
        volume_window: int = 20,
        min_body_ratio: float = 0.4,
    ) -> None:
        self._config = config
        self._regime_detector = RegimeDetector(regime_config or RegimeConfig())
        self._spike_mult = spike_mult
        self._volume_window = volume_window
        # Min candle body ratio: (close-open)/(high-low) — filters doji/indecision
        self._min_body_ratio = min_body_ratio

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        regime = self._regime_detector.detect(candles)
        effective = self._regime_detector.adjust(self._config, regime)
        minimum = max(
            self._volume_window + 1,
            effective.momentum_lookback + 1,
            effective.rsi_period + 1,
        )
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "volume_spike", "market_regime": regime.value},
            )

        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]
        current = candles[-1]

        momentum_value = momentum(closes, effective.momentum_lookback)
        rsi_value = rsi(closes, effective.rsi_period)
        vol_avg = volume_sma(volumes[:-1], min(self._volume_window, len(volumes) - 1))
        vol_ratio = current.volume / vol_avg if vol_avg > 0 else 0.0

        # Candle body ratio: bullish body strength
        candle_range = current.high - current.low
        if candle_range > 0:
            body_ratio = (current.close - current.open) / candle_range
        else:
            body_ratio = 0.0

        indicators: dict[str, float] = {
            "momentum": momentum_value,
            "rsi": rsi_value,
            "volume_ratio": vol_ratio,
            "volume_avg": vol_avg,
            "body_ratio": body_ratio,
        }
        context = {"strategy": "volume_spike", "market_regime": regime.value}

        # MACD confirmation
        macd_bullish = False
        if len(closes) >= 35:
            try:
                _, _, macd_hist = macd(closes)
                indicators["macd_histogram"] = macd_hist
                macd_bullish = macd_hist > 0
            except ValueError:
                pass

        # ADX trend strength
        adx_value: float | None = None
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            adx_value = average_directional_index(highs, lows, closes, effective.adx_period)
            indicators["adx"] = adx_value
        except ValueError:
            pass

        # OBV slope for accumulation confirmation
        obv_trend: float | None = None
        try:
            obv_trend = obv_slope(closes, volumes, lookback=10)
            indicators["obv_slope"] = obv_trend
        except ValueError:
            pass

        # CMF buying pressure
        cmf_value: float | None = None
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            cmf_value = chaikin_money_flow(highs, lows, closes, volumes)
            indicators["cmf"] = cmf_value
        except ValueError:
            pass

        # VWAP
        vwap_value: float | None = None
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            vwap_value = rolling_vwap(highs, lows, closes, volumes, window=20)
            indicators["vwap"] = vwap_value
        except ValueError:
            pass

        # EMA(50) macro trend
        macro_trend_up = False
        if len(closes) >= 50:
            ema50 = _ema(closes, 50)[-1]
            indicators["ema50"] = ema50
            macro_trend_up = closes[-1] > ema50

        if position is not None:
            return self._evaluate_exit(
                candles, position, effective, momentum_value, rsi_value,
                vol_ratio, indicators, context,
            )

        return self._evaluate_entry(
            effective, momentum_value, rsi_value, vol_ratio, body_ratio,
            macd_bullish, adx_value, obv_trend, cmf_value, vwap_value,
            macro_trend_up, closes[-1], indicators, context,
        )

    def _evaluate_entry(
        self,
        effective: StrategyConfig,
        momentum_value: float,
        rsi_value: float,
        vol_ratio: float,
        body_ratio: float,
        macd_bullish: bool,
        adx_value: float | None,
        obv_trend: float | None,
        cmf_value: float | None,
        vwap_value: float | None,
        macro_trend_up: bool,
        current_price: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        # Primary condition: volume spike detected
        if vol_ratio < self._spike_mult:
            return Signal(
                action=SignalAction.HOLD,
                reason="no_volume_spike",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )

        # Direction confirmation: bullish candle body
        if body_ratio < self._min_body_ratio:
            return Signal(
                action=SignalAction.HOLD,
                reason="weak_candle_body",
                confidence=0.2,
                indicators=indicators,
                context=context,
            )

        # Momentum must be positive
        if momentum_value < 0:
            return Signal(
                action=SignalAction.HOLD,
                reason="negative_momentum",
                confidence=0.2,
                indicators=indicators,
                context=context,
            )

        # RSI filter: not overbought
        if rsi_value >= effective.rsi_overbought:
            return Signal(
                action=SignalAction.HOLD,
                reason="rsi_overbought",
                confidence=0.2,
                indicators=indicators,
                context=context,
            )

        # ADX filter: need some trend strength
        if adx_value is not None and adx_value < effective.adx_threshold:
            return Signal(
                action=SignalAction.HOLD,
                reason="adx_too_weak",
                confidence=0.2,
                indicators=indicators,
                context=context,
            )

        # Build confidence from multiple confirmations
        # Base confidence from volume spike magnitude
        base_conf = min(1.0, 0.4 + (vol_ratio - self._spike_mult) * 0.1)

        if macd_bullish:
            base_conf = min(1.0, base_conf + 0.1)
        if macro_trend_up:
            base_conf = min(1.0, base_conf + 0.05)
        if obv_trend is not None and obv_trend > 0.3:
            base_conf = min(1.0, base_conf + 0.05)
        if cmf_value is not None and cmf_value > 0.05:
            base_conf = min(1.0, base_conf + 0.05)
        if vwap_value is not None and current_price > vwap_value:
            base_conf = min(1.0, base_conf + 0.05)
        # Stronger body = more conviction
        if body_ratio > 0.7:
            base_conf = min(1.0, base_conf + 0.05)

        return Signal(
            action=SignalAction.BUY,
            reason="volume_spike_bullish",
            confidence=base_conf,
            indicators=indicators,
            context=context,
        )

    def _evaluate_exit(
        self,
        candles: list[Candle],
        position: Position,
        effective: StrategyConfig,
        momentum_value: float,
        rsi_value: float,
        vol_ratio: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
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

        # Momentum reversal exit
        if momentum_value <= effective.momentum_exit_threshold:
            return Signal(
                action=SignalAction.SELL,
                reason="momentum_reversal",
                confidence=min(1.0, 0.5 + abs(momentum_value)),
                indicators=indicators,
                context=context,
            )

        # RSI overbought exit
        if rsi_value >= effective.rsi_overbought:
            return Signal(
                action=SignalAction.SELL,
                reason="rsi_overbought",
                confidence=min(1.0, rsi_value / 100.0),
                indicators=indicators,
                context=context,
            )

        # Reverse volume spike while holding: large sell volume = exit
        if vol_ratio >= self._spike_mult:
            current = candles[-1]
            if current.close < current.open:  # bearish candle on high volume
                return Signal(
                    action=SignalAction.SELL,
                    reason="bearish_volume_spike",
                    confidence=min(1.0, 0.5 + (vol_ratio - self._spike_mult) * 0.1),
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
