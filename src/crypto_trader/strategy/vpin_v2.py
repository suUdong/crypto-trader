from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import _ema, average_directional_index, momentum, rsi
from crypto_trader.strategy.vpin import VPINStrategy


class VPINV2Strategy(VPINStrategy):
    """Score-based VPIN entry variant for paper shadow evaluation."""

    def __init__(
        self,
        config: StrategyConfig,
        vpin_high_threshold: float = 0.7,
        vpin_low_threshold: float = 0.45,
        bucket_count: int = 20,
        vpin_momentum_threshold: float = 0.01,
        vpin_rsi_ceiling: float = 70.0,
        vpin_rsi_floor: float = 30.0,
        ema_trend_period: int = 20,
        adx_threshold: float | None = None,
        ema_weight: float = 0.5,
        entry_score_threshold: float = 3.0,
        vpin_roc_lookback: int = 3,
        vpin_roc_min: float = 0.0,
        rsi_delta_lookback: int = 3,
        rsi_delta_min: float = 0.0,
        ema_slope_lookback: int = 3,
        ema_slope_min: float = 0.0,
    ) -> None:
        super().__init__(
            config=config,
            vpin_high_threshold=vpin_high_threshold,
            vpin_low_threshold=vpin_low_threshold,
            bucket_count=bucket_count,
            vpin_momentum_threshold=vpin_momentum_threshold,
            vpin_rsi_ceiling=vpin_rsi_ceiling,
            vpin_rsi_floor=vpin_rsi_floor,
            ema_trend_period=ema_trend_period,
            adx_threshold=adx_threshold,
            ema_weight=ema_weight,
        )
        self._entry_score_threshold = entry_score_threshold
        self._vpin_roc_lookback = max(1, vpin_roc_lookback)
        self._vpin_roc_min = vpin_roc_min
        self._rsi_delta_lookback = max(1, rsi_delta_lookback)
        self._rsi_delta_min = rsi_delta_min
        self._ema_slope_lookback = max(1, ema_slope_lookback)
        self._ema_slope_min = ema_slope_min

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        minimum = max(
            self._config.rsi_period + self._rsi_delta_lookback + 1,
            self._config.momentum_lookback + 1,
            self._bucket_count + self._vpin_roc_lookback + 1,
            self._ema_trend_period + self._ema_slope_lookback,
        )
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "vpin_v2"},
            )

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        rsi_value = rsi(closes, self._config.rsi_period)
        momentum_value = momentum(closes, self._config.momentum_lookback)
        vpin_value = self._calculate_vpin(candles)

        ema_series = _ema(closes, self._ema_trend_period)
        ema_now = ema_series[-1]
        ema_reference = ema_series[-1 - self._ema_slope_lookback]
        ema_slope = 0.0 if abs(ema_reference) <= 1e-9 else (ema_now - ema_reference) / ema_reference
        price_above_ema = closes[-1] > ema_now

        adx_value: float | None = None
        if self._adx_threshold > 0:
            try:
                adx_value = average_directional_index(
                    highs, lows, closes, self._config.adx_period
                )
            except ValueError:
                adx_value = None

        previous_rsi = rsi(closes[: -self._rsi_delta_lookback], self._config.rsi_period)
        rsi_delta = rsi_value - previous_rsi

        previous_vpin = self._calculate_vpin(candles[: -self._vpin_roc_lookback])
        vpin_roc = previous_vpin - vpin_value

        indicators: dict[str, float] = {
            "vpin": vpin_value,
            "rsi": rsi_value,
            "momentum": momentum_value,
            "ema_trend": ema_now,
            "ema_slope": ema_slope,
            "rsi_delta": rsi_delta,
            "vpin_roc": vpin_roc,
        }
        if adx_value is not None:
            indicators["adx"] = adx_value

        context = {
            "strategy": "vpin_v2",
            "symbol": symbol,
            "vpin_value": f"{vpin_value:.4f}",
        }

        if position is not None:
            return self._evaluate_exit(
                candles,
                position,
                vpin_value,
                rsi_value,
                indicators,
                context,
            )

        if vpin_value >= self._vpin_high:
            return Signal(
                action=SignalAction.HOLD,
                reason="vpin_high_toxicity",
                confidence=0.2,
                indicators=indicators,
                context=context,
            )
        if not (self._vpin_rsi_floor <= rsi_value <= self._vpin_rsi_ceiling):
            return Signal(
                action=SignalAction.HOLD,
                reason="rsi_band_fail",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )
        if (
            self._adx_threshold > 0
            and adx_value is not None
            and adx_value < self._adx_threshold
        ):
            return Signal(
                action=SignalAction.HOLD,
                reason="adx_fail",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )
        if not price_above_ema or ema_slope < self._ema_slope_min:
            return Signal(
                action=SignalAction.HOLD,
                reason="ema_slope_fail",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )
        if momentum_value < self._vpin_momentum_threshold:
            return Signal(
                action=SignalAction.HOLD,
                reason="momentum_fail",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )
        if vpin_roc < self._vpin_roc_min:
            return Signal(
                action=SignalAction.HOLD,
                reason="vpin_roc_fail",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )
        if rsi_delta < self._rsi_delta_min:
            return Signal(
                action=SignalAction.HOLD,
                reason="rsi_delta_fail",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )

        score = self._entry_score(
            vpin_value=vpin_value,
            momentum_value=momentum_value,
            adx_value=adx_value,
            ema_slope=ema_slope,
            rsi_delta=rsi_delta,
            vpin_roc=vpin_roc,
        )
        indicators["entry_score"] = score
        context["entry_score"] = f"{score:.2f}"
        context["entry_score_threshold"] = f"{self._entry_score_threshold:.2f}"

        if score < self._entry_score_threshold:
            return Signal(
                action=SignalAction.HOLD,
                reason="score_below_min",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )

        return Signal(
            action=SignalAction.BUY,
            reason="vpin_v2_entry_score",
            confidence=min(1.0, score / max(self._entry_score_threshold, 1.0)),
            indicators=indicators,
            context=context,
        )

    def _entry_score(
        self,
        *,
        vpin_value: float,
        momentum_value: float,
        adx_value: float | None,
        ema_slope: float,
        rsi_delta: float,
        vpin_roc: float,
    ) -> float:
        score = 0.0
        mid_threshold = (self._vpin_low + self._vpin_high) / 2
        if vpin_value <= self._vpin_low:
            score += 1.0
        elif vpin_value <= mid_threshold:
            score += 0.5

        strong_momentum = max(self._vpin_momentum_threshold, 0.0) + 0.001
        if momentum_value >= strong_momentum:
            score += 1.0
        elif momentum_value >= self._vpin_momentum_threshold:
            score += 0.5

        if vpin_roc >= self._vpin_roc_min + 0.05:
            score += 0.75
        else:
            score += 0.5

        if rsi_delta >= self._rsi_delta_min + 5.0:
            score += 0.75
        else:
            score += 0.5

        if ema_slope >= self._ema_slope_min + 0.001:
            score += 0.75
        else:
            score += 0.5

        if adx_value is not None:
            if adx_value >= self._adx_threshold + 5.0:
                score += 0.5
            else:
                score += 0.25

        return round(score, 3)
