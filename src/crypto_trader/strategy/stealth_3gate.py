"""Stealth 3-Gate Strategy.

Three-gate entry filter combining BTC regime, BTC stealth accumulation, and alt
quality screening via RS score.  Validated parameters: W=36, SMA20, RS [0.5, 1.0),
Sharpe +4.682, WR=31.1%.

Gate logic:
  1. BTC Regime  – BTC price > SMA20 (not in bear regime)
  2. BTC Stealth – BTC CVD slope positive (smart-money accumulation)
  3. Alt Quality – target coin RS score in [rs_low, rs_high)
"""

from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import simple_moving_average


class Stealth3GateStrategy:
    """Stealth 3-Gate entry strategy for alt-coin momentum detection.

    Combines three independent gates to filter high-quality entry signals:
    - Gate 1 (BTC Regime): BTC price above SMA to avoid bear markets.
    - Gate 2 (BTC Stealth): Positive CVD slope on BTC indicates accumulation.
    - Gate 3 (Alt Quality): Target coin RS score in [rs_low, rs_high).

    RS score is the relative strength percentile of the target symbol versus all
    available context within the candle window, normalised to [0, 1].
    CVD (Cumulative Volume Delta) slope: sum of (close-open)/(high-low) * volume
    over the rolling window.
    """

    def __init__(
        self,
        config: StrategyConfig,
        stealth_window: int = 36,
        stealth_sma_period: int = 20,
        rs_low: float = 0.5,
        rs_high: float = 1.0,
        cvd_slope_threshold: float = 0.0,
        btc_stealth_gate: bool = True,
        min_confidence: float = 0.3,
    ) -> None:
        self._config = config
        self._stealth_window = stealth_window
        self._stealth_sma_period = stealth_sma_period
        self._rs_low = rs_low
        self._rs_high = rs_high
        self._cvd_slope_threshold = cvd_slope_threshold
        self._btc_stealth_gate = btc_stealth_gate
        self._min_confidence = min_confidence

        # Internal BTC candle buffer updated via set_btc_candles()
        self._btc_candles: list[Candle] = []

    def set_btc_candles(self, candles: list[Candle]) -> None:
        """Provide BTC candles for Gate 1 and Gate 2 evaluation.

        Call this before evaluate() when the target symbol is not BTC.
        When left empty, Gate 1 and Gate 2 use the passed candles directly
        (i.e. the target is BTC itself).
        """
        self._btc_candles = candles

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        """Evaluate entry / exit signals for the given candles."""
        minimum = max(self._stealth_window, self._stealth_sma_period) + 1
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "stealth_3gate"},
            )

        btc_ref = self._btc_candles if self._btc_candles else candles
        btc_ok_for_gates = len(btc_ref) >= minimum

        # ── Exit path ────────────────────────────────────────────────────────
        if position is not None:
            return self._evaluate_exit(candles, position, btc_ref, btc_ok_for_gates)

        # ── Entry path ───────────────────────────────────────────────────────
        return self._evaluate_entry(candles, btc_ref, btc_ok_for_gates)

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def _evaluate_entry(
        self,
        candles: list[Candle],
        btc_ref: list[Candle],
        btc_ok: bool,
    ) -> Signal:
        indicators: dict[str, float] = {}
        context: dict[str, str] = {"strategy": "stealth_3gate"}

        # Gate 1 – BTC Regime (price > SMA20)
        if btc_ok:
            btc_closes = [c.close for c in btc_ref]
            btc_sma = simple_moving_average(btc_closes, self._stealth_sma_period)
            btc_above_sma = btc_closes[-1] > btc_sma
            indicators["btc_sma"] = btc_sma
            indicators["btc_close"] = btc_closes[-1]
        else:
            btc_above_sma = True  # fallback: don't block when BTC data unavailable

        if not btc_above_sma:
            return Signal(
                action=SignalAction.HOLD,
                reason="btc_regime_bear",
                confidence=0.1,
                indicators=indicators,
                context=context,
            )

        # Gate 2 – BTC Stealth (CVD slope > threshold)
        if self._btc_stealth_gate:
            if btc_ok:
                btc_cvd_slope = self._calculate_cvd_slope(btc_ref, self._stealth_window)
                indicators["btc_cvd_slope"] = btc_cvd_slope
                btc_stealth_ok = btc_cvd_slope > self._cvd_slope_threshold
            else:
                btc_stealth_ok = True  # fallback

            if not btc_stealth_ok:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="btc_stealth_gate_fail",
                    confidence=0.15,
                    indicators=indicators,
                    context=context,
                )

        # Gate 3 – Alt Quality (RS score in [rs_low, rs_high))
        rs_score = self._calculate_rs_score(candles, self._stealth_window)
        indicators["rs_score"] = rs_score

        if not (self._rs_low <= rs_score < self._rs_high):
            return Signal(
                action=SignalAction.HOLD,
                reason="alt_quality_gate_fail",
                confidence=0.15,
                indicators=indicators,
                context=context,
            )

        # All gates passed → BUY
        confidence = min(1.0, max(self._min_confidence, rs_score * 0.7 + 0.3))
        return Signal(
            action=SignalAction.BUY,
            reason="stealth_3gate_entry",
            confidence=confidence,
            indicators=indicators,
            context=context,
        )

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def _evaluate_exit(
        self,
        candles: list[Candle],
        position: Position,
        btc_ref: list[Candle],
        btc_ok: bool,
    ) -> Signal:
        indicators: dict[str, float] = {}
        context: dict[str, str] = {"strategy": "stealth_3gate"}

        holding_bars = (
            0
            if position.entry_index is None
            else len(candles) - position.entry_index - 1
        )
        indicators["holding_bars"] = float(holding_bars)

        if holding_bars >= self._config.max_holding_bars:
            return Signal(
                action=SignalAction.SELL,
                reason="max_holding_period",
                confidence=1.0,
                indicators=indicators,
                context=context,
            )

        rs_score = self._calculate_rs_score(candles, self._stealth_window)
        indicators["rs_score"] = rs_score

        if rs_score < self._rs_low:
            return Signal(
                action=SignalAction.SELL,
                reason="rs_score_deteriorated",
                confidence=0.7,
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

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_cvd_slope(candles: list[Candle], window: int) -> float:
        """Compute CVD slope over the last *window* candles.

        CVD = cumulative sum of (close - open) / (high - low) * volume.
        Slope = (CVD[-1] - CVD[0]) / window.
        Returns 0.0 when the price range is zero or data is insufficient.
        """
        recent = candles[-window:]
        if len(recent) < 2:
            return 0.0

        cvd = 0.0
        cvd_first: float | None = None
        for candle in recent:
            price_range = candle.high - candle.low
            if price_range > 0:
                direction = (candle.close - candle.open) / price_range
            else:
                direction = 0.0
            cvd += direction * candle.volume
            if cvd_first is None:
                cvd_first = cvd

        if cvd_first is None:
            return 0.0
        return (cvd - cvd_first) / window

    @staticmethod
    def _calculate_rs_score(candles: list[Candle], window: int) -> float:
        """Compute relative-strength score normalised to [0, 1].

        The score is the percentile rank of the target symbol's return over
        the window relative to a synthetic basket of sub-windows within the
        same candle series.  When fewer than 5 sub-windows are available the
        raw return is mapped to [0, 1] via a logistic-like clamp.
        """
        if len(candles) < window + 1:
            return 0.0

        recent = candles[-window:]
        if recent[0].close <= 0:
            return 0.0

        target_return = recent[-1].close / recent[0].close - 1.0

        # Build a basket of sub-window returns for percentile ranking
        half = max(2, window // 2)
        basket: list[float] = []
        for start in range(len(candles) - window - half, len(candles) - half):
            if start < 0:
                continue
            base = candles[start].close
            end_price = candles[start + half].close
            if base > 0:
                basket.append(end_price / base - 1.0)

        if len(basket) < 5:
            # Fallback: map return to [0, 1] using simple clamp
            # Typical range [-0.3, 0.3]; centre on 0.5
            clamped = max(-0.3, min(0.3, target_return))
            return round((clamped + 0.3) / 0.6, 4)

        below = sum(1 for r in basket if r < target_return)
        return round(below / len(basket), 4)
