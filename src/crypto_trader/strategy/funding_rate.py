from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.data.funding_rate_client import FundingRatePoint, UpbitFundingRateClient
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import momentum, rsi

logger = logging.getLogger(__name__)


def build_proxy_funding_history(symbol: str, candles: list[Candle]) -> list[FundingRatePoint]:
    """Build a deterministic funding proxy from price extension when real history is unavailable."""
    points: list[FundingRatePoint] = []
    if len(candles) < 24:
        return points

    window = 8
    for index in range(window, len(candles), 8):
        closes = [c.close for c in candles[max(0, index - 24) : index + 1]]
        if len(closes) < window + 1:
            continue
        recent_return = (closes[-1] - closes[-window]) / max(1.0, closes[-window])
        mean_close = sum(closes) / len(closes)
        extension = (closes[-1] - mean_close) / max(1.0, mean_close)
        proxy_rate = max(-0.0008, min(0.0008, (recent_return * 0.015) + (extension * 0.01)))
        points.append(
            FundingRatePoint(
                symbol=symbol,
                funding_rate=proxy_rate,
                funding_time=_as_utc(candles[index].timestamp),
            )
        )
    return points


class FundingRateStrategy:
    """Contrarian funding-rate strategy keyed by Upbit spot symbols."""

    supports_short_positions = True

    DEFAULT_HIGH_FUNDING = 0.0003
    DEFAULT_EXTREME_FUNDING = 0.0005
    DEFAULT_NEGATIVE_FUNDING = -0.0001
    DEFAULT_DEEP_NEGATIVE = -0.0003

    def __init__(
        self,
        config: StrategyConfig,
        funding_client: UpbitFundingRateClient | None = None,
        *,
        high_funding_threshold: float = DEFAULT_HIGH_FUNDING,
        extreme_funding_threshold: float = DEFAULT_EXTREME_FUNDING,
        negative_funding_threshold: float = DEFAULT_NEGATIVE_FUNDING,
        deep_negative_threshold: float = DEFAULT_DEEP_NEGATIVE,
        rsi_oversold: float = 35.0,
        rsi_overbought: float = 70.0,
        momentum_lookback: int = 10,
        min_confidence: float = 0.5,
        max_holding_bars: int = 48,
        cooldown_bars: int = 6,
    ) -> None:
        self._config = config
        self._funding_client = funding_client or UpbitFundingRateClient()
        self._high_funding = high_funding_threshold
        self._extreme_funding = extreme_funding_threshold
        self._negative_funding = negative_funding_threshold
        self._deep_negative = deep_negative_threshold
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._momentum_lookback = momentum_lookback
        self._min_confidence = min_confidence
        self._max_holding_bars = max_holding_bars
        self._cooldown_bars = cooldown_bars
        self._injected_funding_rate: float | None = None
        self._funding_history: list[FundingRatePoint] = []
        self._last_trade_bar: dict[str, int] = {}

    def set_funding_rate(self, rate: float) -> None:
        self._injected_funding_rate = rate

    def set_funding_rate_history(
        self,
        history: Iterable[FundingRatePoint | dict[str, object]],
    ) -> None:
        points: list[FundingRatePoint] = []
        for item in history:
            if isinstance(item, FundingRatePoint):
                points.append(item)
                continue
            raw_time = item.get("funding_time", item.get("fundingTime"))
            if isinstance(raw_time, datetime):
                funding_time = _as_utc(raw_time)
            elif isinstance(raw_time, (int, float)):
                epoch = raw_time / 1000 if raw_time > 1_000_000_000_000 else raw_time
                funding_time = datetime.fromtimestamp(epoch, tz=UTC)
            elif isinstance(raw_time, str):
                funding_time = _as_utc(datetime.fromisoformat(raw_time))
            else:
                continue
            raw_rate = item.get("funding_rate", item.get("fundingRate"))
            if raw_rate is None or not isinstance(raw_rate, (int, float, str)):
                continue
            funding_rate = float(raw_rate)
            points.append(
                FundingRatePoint(
                    symbol=str(item.get("symbol", "")) or "KRW-BTC",
                    funding_rate=funding_rate,
                    funding_time=funding_time,
                )
            )
        self._funding_history = sorted(points, key=lambda point: point.funding_time)

    def prime_backtest_funding(self, symbol: str, candles: list[Candle]) -> None:
        # Keep research/backtest flows fully offline-safe and deterministic.
        self._funding_history = build_proxy_funding_history(symbol, candles)

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        min_bars = max(self._config.rsi_period + 1, self._momentum_lookback + 1, 20)
        if len(candles) < min_bars:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "funding_rate"},
            )

        closes = [c.close for c in candles]
        current_time = candles[-1].timestamp
        rsi_value = rsi(closes, self._config.rsi_period)
        mom_value = momentum(closes, self._momentum_lookback)
        funding, funding_source = self._resolve_funding(symbol or "KRW-BTC", current_time, closes)

        indicators: dict[str, float] = {
            "rsi": rsi_value,
            "momentum": mom_value,
        }
        context: dict[str, str] = {
            "strategy": "funding_rate",
            "funding_source": funding_source,
        }
        if funding is not None:
            indicators["funding_rate"] = funding
            indicators["funding_rate_bps"] = funding * 10000
            context["funding_rate_pct"] = f"{funding * 100:.4f}%"

        current_bar = len(candles) - 1
        cooldown_key = symbol or "default"

        if position is not None:
            context["position_side"] = position.side
            return self._evaluate_exit(
                candles,
                position,
                funding,
                rsi_value,
                mom_value,
                indicators,
                context,
            )

        last_bar = self._last_trade_bar.get(cooldown_key)
        if last_bar is not None and (current_bar - last_bar) < self._cooldown_bars:
            return Signal(
                action=SignalAction.HOLD,
                reason="cooldown_active",
                confidence=0.0,
                indicators=indicators,
                context=context,
            )

        signal = self._evaluate_entry(funding, rsi_value, mom_value, indicators, context)
        if signal.action is not SignalAction.HOLD and signal.confidence >= self._min_confidence:
            self._last_trade_bar[cooldown_key] = current_bar
            return signal
        if signal.action is not SignalAction.HOLD:
            return Signal(
                action=SignalAction.HOLD,
                reason="confidence_below_threshold",
                confidence=signal.confidence,
                indicators=indicators,
                context=context,
            )
        return signal

    def _resolve_funding(
        self,
        symbol: str,
        current_time: datetime,
        closes: list[float],
    ) -> tuple[float | None, str]:
        if self._funding_history:
            candle_time = _as_utc(current_time)
            latest = None
            for point in self._funding_history:
                if point.funding_time <= candle_time:
                    latest = point
                else:
                    break
            if latest is not None:
                return latest.funding_rate, "history"

        if self._injected_funding_rate is not None:
            return self._injected_funding_rate, "injected"

        try:
            live_rate = self._funding_client.get_latest_funding_rate(symbol)
            if live_rate is not None:
                return live_rate, "live"
        except Exception:
            logger.warning("live funding lookup failed for %s", symbol, exc_info=True)

        if _is_historical(current_time) and len(closes) >= self._momentum_lookback + 1:
            proxy_rate = _proxy_funding_rate(closes, self._momentum_lookback)
            return proxy_rate, "proxy"

        return None, "unavailable"

    def _evaluate_entry(
        self,
        funding: float | None,
        rsi_value: float,
        mom_value: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        if funding is None:
            return Signal(
                action=SignalAction.HOLD,
                reason="funding_data_unavailable",
                confidence=0.0,
                indicators=indicators,
                context=context,
            )

        if funding <= self._deep_negative and rsi_value <= self._rsi_oversold:
            confidence = min(
                1.0,
                0.65 + abs(funding) * 500 + (self._rsi_oversold - rsi_value) / 100,
            )
            return Signal(
                action=SignalAction.BUY,
                reason="funding_deep_negative_rsi_oversold",
                confidence=confidence,
                indicators=indicators,
                context=context,
            )

        if funding <= self._negative_funding and (rsi_value <= 50.0 or mom_value > -0.01):
            confidence = min(
                0.9,
                0.5 + abs(funding) * 300 + max(0.0, 50.0 - rsi_value) / 200,
            )
            return Signal(
                action=SignalAction.BUY,
                reason="funding_negative_long_bias",
                confidence=confidence,
                indicators=indicators,
                context=context,
            )

        if funding >= self._extreme_funding and (rsi_value >= 60.0 or mom_value <= 0.01):
            confidence = min(1.0, 0.65 + funding * 400 + max(0.0, rsi_value - 60.0) / 100)
            return Signal(
                action=SignalAction.SELL,
                reason="funding_extreme_positive_short_bias",
                confidence=confidence,
                indicators=indicators,
                context=context,
            )

        if funding >= self._high_funding and (rsi_value >= self._rsi_overbought or mom_value <= 0):
            confidence = min(0.9, 0.5 + funding * 350 + max(0.0, rsi_value - 55.0) / 150)
            return Signal(
                action=SignalAction.SELL,
                reason="funding_high_positive_short_bias",
                confidence=confidence,
                indicators=indicators,
                context=context,
            )

        return Signal(
            action=SignalAction.HOLD,
            reason="no_funding_edge",
            confidence=0.2,
            indicators=indicators,
            context=context,
        )

    def _evaluate_exit(
        self,
        candles: list[Candle],
        position: Position,
        funding: float | None,
        rsi_value: float,
        mom_value: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        if position.entry_index is not None:
            holding_bars = len(candles) - position.entry_index - 1
        else:
            elapsed_hours = (candles[-1].timestamp - position.entry_time).total_seconds() / 3600.0
            holding_bars = int(elapsed_hours)

        if holding_bars >= self._max_holding_bars:
            return Signal(
                action=SignalAction.BUY if position.is_short else SignalAction.SELL,
                reason="max_holding_period",
                confidence=1.0,
                indicators=indicators,
                context=context,
            )

        if position.is_short:
            if funding is not None and funding <= self._deep_negative:
                return Signal(
                    action=SignalAction.BUY,
                    reason="funding_deep_negative_cover",
                    confidence=min(1.0, 0.6 + abs(funding) * 400),
                    indicators=indicators,
                    context=context,
                )
            if (
                funding is not None
                and funding <= self._negative_funding
                and rsi_value <= self._rsi_oversold
            ):
                return Signal(
                    action=SignalAction.BUY,
                    reason="funding_negative_rsi_oversold_cover",
                    confidence=min(1.0, 0.5 + abs(funding) * 250),
                    indicators=indicators,
                    context=context,
                )
            if rsi_value <= max(5.0, self._rsi_oversold - 5.0) and mom_value > 0:
                return Signal(
                    action=SignalAction.BUY,
                    reason="short_take_profit_rsi_reset",
                    confidence=min(1.0, 0.45 + (self._rsi_oversold - rsi_value) / 100),
                    indicators=indicators,
                    context=context,
                )
        else:
            if funding is not None and funding >= self._extreme_funding:
                return Signal(
                    action=SignalAction.SELL,
                    reason="funding_extreme_overheated",
                    confidence=min(1.0, 0.6 + funding * 500),
                    indicators=indicators,
                    context=context,
                )
            if (
                funding is not None
                and funding >= self._high_funding
                and rsi_value >= self._rsi_overbought
            ):
                return Signal(
                    action=SignalAction.SELL,
                    reason="funding_high_rsi_overbought",
                    confidence=min(1.0, 0.5 + rsi_value / 100),
                    indicators=indicators,
                    context=context,
                )
            if rsi_value >= self._rsi_overbought + 5:
                return Signal(
                    action=SignalAction.SELL,
                    reason="rsi_overbought",
                    confidence=min(1.0, rsi_value / 100),
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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_historical(current_time: datetime) -> bool:
    return _as_utc(current_time) < datetime.now(tz=UTC) - timedelta(hours=12)


def _proxy_funding_rate(closes: list[float], lookback: int) -> float:
    base_price = closes[-lookback - 1]
    recent_return = (closes[-1] - base_price) / max(1.0, base_price)
    extension = (closes[-1] - (sum(closes[-lookback:]) / lookback)) / max(1.0, closes[-1])
    return max(-0.0008, min(0.0008, (recent_return * 0.015) + (extension * 0.01)))
