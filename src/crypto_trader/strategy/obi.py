from __future__ import annotations

from typing import Protocol

from crypto_trader.config import StrategyConfig
from crypto_trader.models import (
    Candle,
    OrderbookSnapshot,
    Position,
    Signal,
    SignalAction,
)
from crypto_trader.strategy.indicators import rsi


class OrderbookProvider(Protocol):
    def get_orderbook(self, symbol: str) -> OrderbookSnapshot | None: ...


class OBIStrategy:
    """Order Book Imbalance strategy.

    OBI = (bid_volume - ask_volume) / (bid_volume + ask_volume)
    Range: -1.0 (all asks) to +1.0 (all bids).

    BUY when OBI > threshold (strong buying pressure) + RSI confirmation.
    SELL when OBI < -threshold or max holding bars exceeded.
    """

    def __init__(
        self,
        config: StrategyConfig,
        orderbook_provider: OrderbookProvider | None = None,
        obi_buy_threshold: float = 0.3,
        obi_sell_threshold: float = -0.3,
    ) -> None:
        self._config = config
        self._orderbook_provider = orderbook_provider
        self._obi_buy_threshold = obi_buy_threshold
        self._obi_sell_threshold = obi_sell_threshold

    def evaluate(
        self, candles: list[Candle], position: Position | None = None
    ) -> Signal:
        minimum = self._config.rsi_period + 1
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "obi"},
            )

        closes = [c.close for c in candles]
        rsi_value = rsi(closes, self._config.rsi_period)
        obi_value = self._calculate_obi(candles)
        indicators: dict[str, float] = {"rsi": rsi_value}
        if obi_value is not None:
            indicators["obi"] = obi_value

        context = {"strategy": "obi"}
        if obi_value is not None:
            context["obi_value"] = f"{obi_value:.4f}"

        if position is not None:
            return self._evaluate_exit(
                candles, position, obi_value, rsi_value, indicators, context
            )
        return self._evaluate_entry(obi_value, rsi_value, indicators, context)

    def _evaluate_entry(
        self,
        obi_value: float | None,
        rsi_value: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        if obi_value is None:
            return Signal(
                action=SignalAction.HOLD,
                reason="orderbook_data_unavailable",
                confidence=0.0,
                indicators=indicators,
                context=context,
            )

        if obi_value > self._obi_buy_threshold and rsi_value < self._config.rsi_overbought:
            return Signal(
                action=SignalAction.BUY,
                reason="obi_strong_bid_imbalance",
                confidence=min(1.0, 0.4 + obi_value),
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

    def _evaluate_exit(
        self,
        candles: list[Candle],
        position: Position,
        obi_value: float | None,
        rsi_value: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        holding_bars = (
            0
            if position.entry_index is None
            else len(candles) - position.entry_index - 1
        )
        if holding_bars >= self._config.max_holding_bars:
            return Signal(
                action=SignalAction.SELL,
                reason="max_holding_period",
                confidence=1.0,
                indicators=indicators,
                context=context,
            )

        if obi_value is not None and obi_value < self._obi_sell_threshold:
            return Signal(
                action=SignalAction.SELL,
                reason="obi_strong_ask_imbalance",
                confidence=min(1.0, 0.5 + abs(obi_value)),
                indicators=indicators,
                context=context,
            )

        if rsi_value >= self._config.rsi_overbought:
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

    def _calculate_obi(self, candles: list[Candle]) -> float | None:
        if self._orderbook_provider is None:
            return self._estimate_obi_from_candles(candles)

        # Use real orderbook if available
        snapshot = self._orderbook_provider.get_orderbook("placeholder")
        if snapshot is None:
            return self._estimate_obi_from_candles(candles)

        bid_volume = sum(e.size for e in snapshot.bids)
        ask_volume = sum(e.size for e in snapshot.asks)
        total = bid_volume + ask_volume
        if total <= 0:
            return 0.0
        return (bid_volume - ask_volume) / total

    def _estimate_obi_from_candles(self, candles: list[Candle]) -> float:
        """Estimate OBI from candle data when orderbook is unavailable.

        Uses close vs open ratio and volume as a proxy.
        """
        if len(candles) < 5:
            return 0.0

        recent = candles[-5:]
        buy_volume = 0.0
        sell_volume = 0.0
        for c in recent:
            if c.close >= c.open:
                buy_volume += c.volume
            else:
                sell_volume += c.volume

        total = buy_volume + sell_volume
        if total <= 0:
            return 0.0
        return (buy_volume - sell_volume) / total
