from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import (
    average_directional_index,
    bollinger_band_width,
    bollinger_bands,
    rsi,
    rsi_divergence,
    volume_sma,
)


class BollingerMeanReversionStrategy:
    """Bollinger Band mean reversion for range-bound markets.

    Entry: lower band touch + RSI oversold + low ADX + volume confirm
    Exit: middle band reversion, RSI recovery, max holding, or trend shift
    """

    def __init__(
        self,
        config: StrategyConfig,
        *,
        adx_ceiling: float = 25.0,
        squeeze_lookback: int = 50,
        squeeze_threshold_pct: float = 20.0,
    ) -> None:
        self._config = config
        self._adx_ceiling = adx_ceiling
        self._squeeze_lookback = squeeze_lookback
        self._squeeze_threshold_pct = squeeze_threshold_pct

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        cfg = self._config
        minimum = max(
            cfg.bollinger_window + 1,
            cfg.rsi_period + 1,
            cfg.adx_period + 2,
            self._squeeze_lookback + cfg.bollinger_window,
        )
        if len(candles) < minimum:
            return self._hold("insufficient_data")

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]

        upper, middle, lower = bollinger_bands(
            closes, cfg.bollinger_window, cfg.bollinger_stddev
        )
        rsi_value = rsi(closes, cfg.rsi_period)
        adx_value = average_directional_index(
            highs, lows, closes, cfg.adx_period
        )
        bbw = bollinger_band_width(
            closes, cfg.bollinger_window, cfg.bollinger_stddev
        )
        bbw_pct = self._bbw_percentile(candles)

        indicators = {
            "bb_upper": upper,
            "bb_middle": middle,
            "bb_lower": lower,
            "rsi": rsi_value,
            "adx": adx_value,
            "bbw": bbw,
            "bbw_percentile": bbw_pct,
        }
        ctx = {"strategy": "bollinger_mr"}

        # --- EXIT logic (evaluated first when holding) ---
        if position is not None:
            return self._evaluate_exit(
                candles, position, closes, highs, lows,
                upper, middle, rsi_value, adx_value, indicators, ctx,
            )

        # --- ENTRY logic ---
        return self._evaluate_entry(
            candles, closes, volumes,
            lower, rsi_value, adx_value, bbw_pct, indicators, ctx,
        )

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------
    def _evaluate_entry(
        self,
        candles: list[Candle],
        closes: list[float],
        volumes: list[float],
        lower: float,
        rsi_value: float,
        adx_value: float,
        bbw_pct: float,
        indicators: dict[str, float],
        ctx: dict[str, str],
    ) -> Signal:
        cfg = self._config
        close = closes[-1]
        prev_close = closes[-2]

        # 1. Band touch: close <= lower OR crossed back above lower
        prev_lower = bollinger_bands(
            closes[:-1], cfg.bollinger_window, cfg.bollinger_stddev
        )[2]
        band_touch = close <= lower or (
            prev_close < prev_lower and close > lower
        )
        if not band_touch:
            return self._hold("no_band_touch", indicators)

        # 2. RSI oversold window
        if not (cfg.rsi_oversold_floor <= rsi_value <= cfg.rsi_recovery_ceiling):
            return self._hold("rsi_out_of_range", indicators)

        # 3. ADX regime filter (range-bound only)
        if adx_value >= self._adx_ceiling:
            return self._hold("adx_too_high", indicators)

        # 4. Squeeze awareness
        squeeze_active = bbw_pct < self._squeeze_threshold_pct
        expanding_from_squeeze = self._is_expanding_from_squeeze(candles)
        if not (squeeze_active or expanding_from_squeeze):
            return self._hold("no_squeeze_context", indicators)

        # 5. Volume confirmation
        vol_threshold = cfg.volume_filter_mult
        if vol_threshold > 0:
            vol_avg = volume_sma(volumes, 20)
            if volumes[-1] < vol_avg * vol_threshold:
                return self._hold("low_volume", indicators)

        # --- Confidence scoring ---
        confidence = 0.55
        # Band distance bonus: how far below lower band (0 to +0.20)
        if lower > 0:
            band_dist = (lower - close) / lower
            confidence += min(band_dist * 10.0, 0.20)
        # RSI depth bonus (0 to +0.15)
        rsi_depth = max(0.0, cfg.rsi_recovery_ceiling - rsi_value)
        rsi_range = cfg.rsi_recovery_ceiling - cfg.rsi_oversold_floor
        if rsi_range > 0:
            confidence += (rsi_depth / rsi_range) * 0.15
        # Squeeze bonus
        if expanding_from_squeeze:
            confidence += 0.10
        # Divergence bonus
        bull_div, _ = rsi_divergence(closes, cfg.rsi_period)
        if bull_div:
            confidence += 0.10

        confidence = min(confidence, 1.0)

        return Signal(
            action=SignalAction.BUY,
            reason="bb_lower_touch_oversold",
            confidence=confidence,
            indicators=indicators,
            context=ctx,
        )

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------
    def _evaluate_exit(
        self,
        candles: list[Candle],
        position: Position,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        upper: float,
        middle: float,
        rsi_value: float,
        adx_value: float,
        indicators: dict[str, float],
        ctx: dict[str, str],
    ) -> Signal:
        close = closes[-1]
        entry_price = position.entry_price
        pnl = (close - entry_price) / entry_price if entry_price > 0 else 0.0
        indicators["pnl"] = pnl

        # Holding bars
        holding_bars = 0
        if position.entry_index is not None:
            holding_bars = len(candles) - 1 - position.entry_index
        indicators["holding_bars"] = float(holding_bars)

        max_hold = self._config.max_holding_bars

        # 1. Max holding period
        if holding_bars >= max_hold:
            return self._sell("max_holding_reached", 0.8, indicators, ctx)

        # 2. Middle band reversion with minimum PnL
        if close >= middle * 0.995 and pnl >= 0.003:
            return self._sell("middle_band_reversion", 0.85, indicators, ctx)

        # 3. Upper band overshoot
        if close >= upper:
            return self._sell("upper_band_reached", 0.9, indicators, ctx)

        # 4. RSI overbought
        if rsi_value >= self._config.rsi_overbought:
            return self._sell("rsi_overbought", 0.75, indicators, ctx)

        # 5. Bearish divergence
        _, bear_div = rsi_divergence(closes, self._config.rsi_period)
        if bear_div and pnl > 0:
            return self._sell("bearish_divergence", 0.7, indicators, ctx)

        # 6. Trend shift (ADX crossed above 30)
        if adx_value > 30.0:
            return self._sell("trend_shift", 0.7, indicators, ctx)

        return self._hold("holding_position", indicators)

    # ------------------------------------------------------------------
    # BBW percentile helpers
    # ------------------------------------------------------------------
    def _bbw_percentile(self, candles: list[Candle]) -> float:
        """Current BBW's percentile rank over squeeze_lookback bars."""
        cfg = self._config
        lookback = self._squeeze_lookback
        needed = lookback + cfg.bollinger_window
        if len(candles) < needed:
            return 50.0

        closes = [c.close for c in candles]
        current_bbw = bollinger_band_width(
            closes, cfg.bollinger_window, cfg.bollinger_stddev
        )
        bbw_history: list[float] = []
        for i in range(lookback):
            end = len(closes) - lookback + i + 1
            if end > cfg.bollinger_window:
                bbw_history.append(
                    bollinger_band_width(
                        closes[:end], cfg.bollinger_window, cfg.bollinger_stddev
                    )
                )
        if not bbw_history:
            return 50.0
        count_below = sum(1 for b in bbw_history if b < current_bbw)
        return (count_below / len(bbw_history)) * 100.0

    def _is_expanding_from_squeeze(self, candles: list[Candle]) -> bool:
        """True if BBW was in squeeze recently and is now expanding."""
        cfg = self._config
        if len(candles) < cfg.bollinger_window + 5:
            return False
        closes = [c.close for c in candles]
        current_bbw = bollinger_band_width(
            closes, cfg.bollinger_window, cfg.bollinger_stddev
        )
        prev_bbw = bollinger_band_width(
            closes[:-3], cfg.bollinger_window, cfg.bollinger_stddev
        )
        # Previous was narrow, current is wider → expanding from squeeze
        prev_closes = [c.close for c in candles[:-3]]
        prev_pct = 50.0
        if len(prev_closes) >= self._squeeze_lookback + cfg.bollinger_window:
            # Approximate previous percentile
            prev_pct = self._bbw_percentile(candles[:-3])
        return prev_pct < self._squeeze_threshold_pct and current_bbw > prev_bbw

    # ------------------------------------------------------------------
    # Signal builders
    # ------------------------------------------------------------------
    def _hold(
        self,
        reason: str,
        indicators: dict[str, float] | None = None,
    ) -> Signal:
        return Signal(
            action=SignalAction.HOLD,
            reason=reason,
            confidence=0.0,
            indicators=indicators or {},
            context={"strategy": "bollinger_mr"},
        )

    def _sell(
        self,
        reason: str,
        confidence: float,
        indicators: dict[str, float],
        ctx: dict[str, str],
    ) -> Signal:
        return Signal(
            action=SignalAction.SELL,
            reason=reason,
            confidence=confidence,
            indicators=indicators,
            context=ctx,
        )
