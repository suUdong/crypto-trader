"""BB Squeeze Independent Strategy.

Bollinger Band squeeze breakout — completely independent of VPIN.
Validated in cycle 182 (Sharpe +12.291, WR 60.9%, n=336, 3-fold WF)
and confirmed robust in cycle 185 (729/729 combos 100% Sharpe > 5).

Entry logic (all must pass):
  1. BTC regime gate: BTC close > SMA(200)
  2. Momentum: close > EMA(ema_period)
  3. ADX trend: ADX >= adx_threshold
  4. Squeeze history: within last squeeze_lb bars, bandwidth percentile < threshold
  5. Bandwidth expanding: current bw > bw[expansion_lb bars ago]
  6. Upper band breakout: close >= upper_band * upper_ratio

Exit logic (priority order):
  1. Take profit: unrealised gain >= ATR * tp_atr
  2. Stop loss: unrealised loss >= ATR * sl_atr
  3. Trailing stop: if profit >= ATR * min_profit_atr, trail at ATR * trail_atr
  4. Max hold: max_hold bars
"""

from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import (
    average_directional_index,
    average_true_range,
    bollinger_band_width,
    bollinger_bands,
    simple_moving_average,
)


class BBSqueezeIndependentStrategy:
    """BB Squeeze Breakout — non-VPIN independent strategy for portfolio diversification."""

    def __init__(
        self,
        config: StrategyConfig,
        # Grid-optimised params (c182 best):
        squeeze_pctile_th: float = 40.0,
        squeeze_lb: int = 15,
        upper_ratio: float = 0.97,
        adx_threshold: float = 25.0,
        tp_atr: float = 5.0,
        sl_atr: float = 2.0,
        # Fixed params:
        bb_period: int = 20,
        bb_std: float = 2.0,
        bw_pctile_lb: int = 120,
        ema_period: int = 20,
        atr_period: int = 20,
        expansion_lb: int = 4,
        trail_atr: float = 0.3,
        min_profit_atr: float = 1.5,
        max_hold: int = 20,
        btc_sma_period: int = 200,
    ) -> None:
        self._config = config
        self._squeeze_pctile_th = squeeze_pctile_th
        self._squeeze_lb = squeeze_lb
        self._upper_ratio = upper_ratio
        self._adx_threshold = adx_threshold
        self._tp_atr = tp_atr
        self._sl_atr = sl_atr
        self._bb_period = bb_period
        self._bb_std = bb_std
        self._bw_pctile_lb = bw_pctile_lb
        self._ema_period = ema_period
        self._atr_period = atr_period
        self._expansion_lb = expansion_lb
        self._trail_atr = trail_atr
        self._min_profit_atr = min_profit_atr
        self._max_hold = max_hold
        self._btc_sma_period = btc_sma_period

        self._btc_candles: list[Candle] = []

    def set_btc_candles(self, candles: list[Candle]) -> None:
        """Provide BTC candles for the regime gate (BTC > SMA200)."""
        self._btc_candles = candles

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        min_bars = max(
            self._bw_pctile_lb + self._bb_period,
            self._btc_sma_period + 1,
            self._atr_period + 2,
        )
        if len(candles) < min_bars:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "bb_squeeze_independent"},
            )

        if position is not None:
            return self._evaluate_exit(candles, position)
        return self._evaluate_entry(candles)

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def _evaluate_entry(self, candles: list[Candle]) -> Signal:
        indicators: dict[str, float] = {}
        ctx: dict[str, str] = {"strategy": "bb_squeeze_independent"}
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        # Gate 1: BTC regime — BTC close > SMA(200)
        btc_ref = self._btc_candles if self._btc_candles else candles
        if len(btc_ref) > self._btc_sma_period:
            btc_closes = [c.close for c in btc_ref]
            btc_sma = simple_moving_average(btc_closes, self._btc_sma_period)
            indicators["btc_sma200"] = btc_sma
            indicators["btc_close"] = btc_closes[-1]
            if btc_closes[-1] <= btc_sma:
                return Signal(
                    action=SignalAction.HOLD, reason="btc_below_sma200",
                    confidence=0.1, indicators=indicators, context=ctx,
                )

        # Gate 2: Momentum — close > EMA(ema_period)
        ema = self._ema(closes, self._ema_period)
        indicators["ema"] = ema
        indicators["close"] = closes[-1]
        if closes[-1] <= ema:
            return Signal(
                action=SignalAction.HOLD, reason="below_ema",
                confidence=0.1, indicators=indicators, context=ctx,
            )

        # Gate 3: ADX >= threshold
        adx = average_directional_index(highs, lows, closes, period=14)
        indicators["adx"] = adx
        if adx < self._adx_threshold:
            return Signal(
                action=SignalAction.HOLD, reason="adx_too_low",
                confidence=0.1, indicators=indicators, context=ctx,
            )

        # Compute BB bandwidth series for squeeze detection
        bw_series = self._bw_series(closes)
        if len(bw_series) < self._bw_pctile_lb:
            return Signal(
                action=SignalAction.HOLD, reason="insufficient_bw_history",
                confidence=0.0, indicators=indicators, context=ctx,
            )

        # Current bandwidth percentile
        bw_lookback = bw_series[-self._bw_pctile_lb:]
        current_bw = bw_series[-1]
        sorted_bw = sorted(bw_lookback)
        bw_pctile = (sorted_bw.index(current_bw) / len(sorted_bw)) * 100
        indicators["bw_pctile"] = bw_pctile

        # Gate 4: Squeeze history — at least one bar in recent window had low percentile
        squeeze_found = False
        search_end = len(bw_series) - self._expansion_lb
        search_start = max(0, search_end - self._squeeze_lb)
        for i in range(search_start, search_end):
            bw_val = bw_series[i]
            lb_start = max(0, i - self._bw_pctile_lb + 1)
            lb_window = bw_series[lb_start : i + 1]
            if len(lb_window) < 10:
                continue
            rank = sum(1 for v in lb_window if v < bw_val)
            pctile = (rank / len(lb_window)) * 100
            if pctile < self._squeeze_pctile_th:
                squeeze_found = True
                break

        indicators["squeeze_found"] = float(squeeze_found)
        if not squeeze_found:
            return Signal(
                action=SignalAction.HOLD, reason="no_squeeze_history",
                confidence=0.1, indicators=indicators, context=ctx,
            )

        # Gate 5: Bandwidth expanding
        if len(bw_series) <= self._expansion_lb:
            return Signal(
                action=SignalAction.HOLD, reason="insufficient_expansion_data",
                confidence=0.0, indicators=indicators, context=ctx,
            )
        expanding = bw_series[-1] > bw_series[-1 - self._expansion_lb]
        indicators["bw_expanding"] = float(expanding)
        if not expanding:
            return Signal(
                action=SignalAction.HOLD, reason="bw_not_expanding",
                confidence=0.1, indicators=indicators, context=ctx,
            )

        # Gate 6: Upper band breakout — close >= upper * upper_ratio
        upper, _mid, _lower = bollinger_bands(closes, self._bb_period, self._bb_std)
        indicators["bb_upper"] = upper
        if closes[-1] < upper * self._upper_ratio:
            return Signal(
                action=SignalAction.HOLD, reason="no_upper_breakout",
                confidence=0.1, indicators=indicators, context=ctx,
            )

        # All gates passed — BUY
        confidence = min(1.0, 0.5 + (adx / 100.0) * 0.3 + (bw_pctile / 100.0) * 0.2)
        atr = average_true_range(highs, lows, closes, self._atr_period)
        indicators["atr"] = atr
        indicators["tp_price"] = closes[-1] + atr * self._tp_atr
        indicators["sl_price"] = closes[-1] - atr * self._sl_atr
        return Signal(
            action=SignalAction.BUY,
            reason="bb_squeeze_breakout",
            confidence=confidence,
            indicators=indicators,
            context=ctx,
        )

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def _evaluate_exit(self, candles: list[Candle], position: Position) -> Signal:
        indicators: dict[str, float] = {}
        ctx: dict[str, str] = {"strategy": "bb_squeeze_independent"}
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        current_close = closes[-1]

        holding_bars = (
            0 if position.entry_index is None
            else len(candles) - position.entry_index - 1
        )
        indicators["holding_bars"] = float(holding_bars)

        atr = average_true_range(highs, lows, closes, self._atr_period)
        indicators["atr"] = atr

        entry_price = position.entry_price
        unrealised = current_close - entry_price
        indicators["unrealised"] = unrealised

        # Exit 1: Take profit
        tp_distance = atr * self._tp_atr
        if unrealised >= tp_distance:
            return Signal(
                action=SignalAction.SELL, reason="take_profit_atr",
                confidence=1.0, indicators=indicators, context=ctx,
            )

        # Exit 2: Stop loss
        sl_distance = atr * self._sl_atr
        if unrealised <= -sl_distance:
            return Signal(
                action=SignalAction.SELL, reason="stop_loss_atr",
                confidence=1.0, indicators=indicators, context=ctx,
            )

        # Exit 3: Trailing stop
        peak = position.high_watermark if position.high_watermark else entry_price
        peak_profit = peak - entry_price
        min_profit_distance = atr * self._min_profit_atr
        if peak_profit >= min_profit_distance:
            trail_distance = atr * self._trail_atr
            if peak - current_close >= trail_distance:
                indicators["peak"] = peak
                indicators["trail_trigger"] = trail_distance
                return Signal(
                    action=SignalAction.SELL, reason="trailing_stop",
                    confidence=0.9, indicators=indicators, context=ctx,
                )

        # Exit 4: Max hold
        if holding_bars >= self._max_hold:
            return Signal(
                action=SignalAction.SELL, reason="max_hold_reached",
                confidence=0.8, indicators=indicators, context=ctx,
            )

        return Signal(
            action=SignalAction.HOLD, reason="position_open",
            confidence=0.2, indicators=indicators, context=ctx,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _bw_series(self, closes: list[float]) -> list[float]:
        """Compute BB bandwidth for every bar that has enough data."""
        result: list[float] = []
        for i in range(self._bb_period, len(closes) + 1):
            bw = bollinger_band_width(closes[:i], self._bb_period, self._bb_std)
            result.append(bw)
        return result

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        """Exponential moving average of the full series, return last value."""
        if len(values) < period:
            return values[-1] if values else 0.0
        k = 2.0 / (period + 1)
        ema_val = sum(values[:period]) / period
        for v in values[period:]:
            ema_val = v * k + ema_val * (1 - k)
        return ema_val
