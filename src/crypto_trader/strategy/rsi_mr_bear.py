"""RSI Mean-Reversion BEAR Strategy.

BEAR-regime mean-reversion — enters on RSI oversold during BTC < SMA(200).
Validated in cycle 187 (Sharpe +12.193, WR 42.2%, n=60, 3-fold WF).
Robustness confirmed in cycle 189 (225 combos, 97.8% PASS, CV 16.6%).

Entry logic (all must pass):
  1. BTC BEAR gate: BTC close < SMA(200) — inverse of BULL strategies
  2. RSI oversold: RSI(14) < rsi_entry

Exit logic (priority order):
  1. Stop loss: unrealised loss >= sl_pct
  2. RSI mean-reversion: RSI(14) > rsi_exit
  3. Max hold: holding_bars >= max_hold

Portfolio role: BEAR-regime complement to BULL-focused VPIN/BB_squeeze.
"""

from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import rsi, simple_moving_average


class RsiMrBearStrategy:
    """RSI Mean-Reversion in BEAR regime — oversold entry, reversion exit."""

    def __init__(
        self,
        config: StrategyConfig,
        rsi_entry: float = 25.0,
        rsi_exit: float = 50.0,
        sl_pct: float = 0.02,
        max_hold: int = 24,
        rsi_period: int = 14,
        btc_sma_period: int = 200,
    ) -> None:
        self._config = config
        self._rsi_entry = rsi_entry
        self._rsi_exit = rsi_exit
        self._sl_pct = sl_pct
        self._max_hold = max_hold
        self._rsi_period = rsi_period
        self._btc_sma_period = btc_sma_period

        self._btc_candles: list[Candle] = []

    def set_btc_candles(self, candles: list[Candle]) -> None:
        """Provide BTC candles for the BEAR regime gate (BTC < SMA200)."""
        self._btc_candles = candles

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        min_bars = max(self._btc_sma_period + 1, self._rsi_period + 2)
        if len(candles) < min_bars:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "rsi_mr_bear"},
            )

        if position is not None:
            return self._evaluate_exit(candles, position)
        return self._evaluate_entry(candles)

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def _evaluate_entry(self, candles: list[Candle]) -> Signal:
        indicators: dict[str, float] = {}
        ctx: dict[str, str] = {"strategy": "rsi_mr_bear"}
        closes = [c.close for c in candles]

        # Gate 1: BTC BEAR regime — BTC close < SMA(200)
        btc_ref = self._btc_candles if self._btc_candles else candles
        if len(btc_ref) > self._btc_sma_period:
            btc_closes = [c.close for c in btc_ref]
            btc_sma = simple_moving_average(btc_closes, self._btc_sma_period)
            indicators["btc_sma200"] = btc_sma
            indicators["btc_close"] = btc_closes[-1]
            if btc_closes[-1] >= btc_sma:
                return Signal(
                    action=SignalAction.HOLD, reason="btc_above_sma200",
                    confidence=0.1, indicators=indicators, context=ctx,
                )

        # Gate 2: RSI oversold — RSI(14) < rsi_entry
        rsi_val = rsi(closes, self._rsi_period)
        indicators["rsi"] = rsi_val
        if rsi_val >= self._rsi_entry:
            return Signal(
                action=SignalAction.HOLD, reason="rsi_not_oversold",
                confidence=0.1, indicators=indicators, context=ctx,
            )

        # All gates passed — BUY (mean-reversion entry)
        confidence = min(1.0, 0.5 + (self._rsi_entry - rsi_val) / 50.0)
        indicators["sl_price"] = closes[-1] * (1 - self._sl_pct)
        return Signal(
            action=SignalAction.BUY,
            reason="rsi_oversold_bear",
            confidence=confidence,
            indicators=indicators,
            context=ctx,
        )

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def _evaluate_exit(self, candles: list[Candle], position: Position) -> Signal:
        indicators: dict[str, float] = {}
        ctx: dict[str, str] = {"strategy": "rsi_mr_bear"}
        closes = [c.close for c in candles]
        current_close = closes[-1]

        holding_bars = (
            0 if position.entry_index is None
            else len(candles) - position.entry_index - 1
        )
        indicators["holding_bars"] = float(holding_bars)

        entry_price = position.entry_price
        unrealised_pct = (current_close - entry_price) / entry_price
        indicators["unrealised_pct"] = unrealised_pct

        # Exit 1: Stop loss
        if unrealised_pct <= -self._sl_pct:
            return Signal(
                action=SignalAction.SELL, reason="stop_loss",
                confidence=1.0, indicators=indicators, context=ctx,
            )

        # Exit 2: RSI mean-reversion achieved
        rsi_val = rsi(closes, self._rsi_period)
        indicators["rsi"] = rsi_val
        if rsi_val > self._rsi_exit:
            return Signal(
                action=SignalAction.SELL, reason="rsi_mean_reversion",
                confidence=0.9, indicators=indicators, context=ctx,
            )

        # Exit 3: Max hold
        if holding_bars >= self._max_hold:
            return Signal(
                action=SignalAction.SELL, reason="max_hold_reached",
                confidence=0.8, indicators=indicators, context=ctx,
            )

        return Signal(
            action=SignalAction.HOLD, reason="position_open",
            confidence=0.2, indicators=indicators, context=ctx,
        )
