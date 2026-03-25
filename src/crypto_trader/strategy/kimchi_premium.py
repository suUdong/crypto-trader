from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.data.binance_client import BinancePriceClient
from crypto_trader.data.fx_client import FXRateClient
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import rsi


class KimchiPremiumStrategy:
    """Kimchi premium filter/strategy.

    Compares Upbit KRW price vs Binance USD price * FX rate.
    Premium < -1%: contrarian BUY (undervalued on Upbit).
    Premium > 7%: EXIT signal (overheated domestic market).
    Premium 0-5%: safe zone for entries with RSI confirmation.
    Premium > 5%: avoid new entries.
    """

    def __init__(
        self,
        config: StrategyConfig,
        binance_client: BinancePriceClient | None = None,
        fx_client: FXRateClient | None = None,
        min_trade_interval_bars: int = 4,
        min_confidence: float = 0.5,
    ) -> None:
        self._config = config
        self._binance = binance_client or BinancePriceClient()
        self._fx = fx_client or FXRateClient()
        self._premium_entry_ceiling = 0.05
        self._premium_exit_floor = 0.07
        self._contrarian_buy_threshold = -0.01
        self._cached_premium: float | None = None
        self._min_trade_interval_bars = min_trade_interval_bars
        self._min_confidence = min_confidence
        self._last_trade_bar: int | None = None

    def evaluate(
        self, candles: list[Candle], position: Position | None = None
    ) -> Signal:
        minimum = self._config.rsi_period + 1
        if len(candles) < minimum:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0,
                context={"strategy": "kimchi_premium"},
            )

        closes = [c.close for c in candles]
        upbit_price = closes[-1]
        rsi_value = rsi(closes, self._config.rsi_period)
        premium = self._calculate_premium(upbit_price)
        indicators = {"rsi": rsi_value}
        if premium is not None:
            indicators["kimchi_premium"] = premium

        context = {"strategy": "kimchi_premium"}
        if premium is not None:
            context["premium_pct"] = f"{premium:.4f}"

        current_bar = len(candles) - 1

        if position is not None:
            signal = self._evaluate_exit(
                candles, position, premium, rsi_value, indicators, context
            )
            if signal.action is SignalAction.SELL:
                self._last_trade_bar = current_bar
            return signal

        if self._last_trade_bar is not None:
            bars_since = current_bar - self._last_trade_bar
            if bars_since < self._min_trade_interval_bars:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="cooldown_active",
                    confidence=0.0,
                    indicators=indicators,
                    context=context,
                )

        signal = self._evaluate_entry(premium, rsi_value, indicators, context)
        if signal.action is SignalAction.BUY:
            if signal.confidence < self._min_confidence:
                return Signal(
                    action=SignalAction.HOLD,
                    reason="confidence_below_threshold",
                    confidence=signal.confidence,
                    indicators=indicators,
                    context=context,
                )
            self._last_trade_bar = current_bar
        return signal

    def _evaluate_entry(
        self,
        premium: float | None,
        rsi_value: float,
        indicators: dict[str, float],
        context: dict[str, str],
    ) -> Signal:
        if premium is None:
            return Signal(
                action=SignalAction.HOLD,
                reason="premium_data_unavailable",
                confidence=0.0,
                indicators=indicators,
                context=context,
            )

        if premium <= self._contrarian_buy_threshold:
            return Signal(
                action=SignalAction.BUY,
                reason="kimchi_premium_contrarian_buy",
                confidence=min(1.0, 0.5 + abs(premium) * 5),
                indicators=indicators,
                context=context,
            )

        if premium > self._premium_entry_ceiling:
            return Signal(
                action=SignalAction.HOLD,
                reason="premium_too_high_for_entry",
                confidence=0.3,
                indicators=indicators,
                context=context,
            )

        if (
            self._config.rsi_oversold_floor
            <= rsi_value
            <= self._config.rsi_recovery_ceiling
        ):
            return Signal(
                action=SignalAction.BUY,
                reason="kimchi_premium_safe_zone_rsi_entry",
                confidence=min(1.0, 0.4 + (0.05 - premium) * 5),
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
        premium: float | None,
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

        if premium is not None and premium >= self._premium_exit_floor:
            return Signal(
                action=SignalAction.SELL,
                reason="kimchi_premium_overheated",
                confidence=min(1.0, 0.5 + premium * 5),
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

    def _calculate_premium(self, upbit_krw_price: float) -> float | None:
        binance_usd = self._binance.get_btc_usdt_price()
        if binance_usd is None:
            return self._cached_premium

        fx_rate = self._fx.get_usd_krw_rate()
        if fx_rate is None:
            return self._cached_premium

        global_krw_price = binance_usd * fx_rate
        if global_krw_price <= 0:
            return self._cached_premium

        premium = (upbit_krw_price - global_krw_price) / global_krw_price
        self._cached_premium = premium
        return premium
