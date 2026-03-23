from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.indicators import momentum


class MarketRegime(StrEnum):
    BULL = "bull"
    SIDEWAYS = "sideways"
    BEAR = "bear"


@dataclass(slots=True)
class RegimeAnalysis:
    regime: MarketRegime
    short_return_pct: float
    long_return_pct: float


class RegimeDetector:
    def __init__(self, config: RegimeConfig) -> None:
        self._config = config

    def detect(self, candles: list[Candle]) -> MarketRegime:
        return self.analyze(candles).regime

    def analyze(self, candles: list[Candle]) -> RegimeAnalysis:
        closes = [candle.close for candle in candles]
        minimum = max(self._config.short_lookback + 1, self._config.long_lookback + 1)
        if len(closes) < minimum:
            return RegimeAnalysis(
                regime=MarketRegime.SIDEWAYS,
                short_return_pct=0.0,
                long_return_pct=0.0,
            )

        short_return = momentum(closes, self._config.short_lookback)
        long_return = momentum(closes, self._config.long_lookback)

        if (
            short_return >= self._config.bull_threshold_pct
            and long_return >= self._config.bull_threshold_pct
        ):
            regime = MarketRegime.BULL
        elif (
            short_return <= self._config.bear_threshold_pct
            and long_return <= self._config.bear_threshold_pct
        ):
            regime = MarketRegime.BEAR
        else:
            regime = MarketRegime.SIDEWAYS

        return RegimeAnalysis(
            regime=regime,
            short_return_pct=short_return,
            long_return_pct=long_return,
        )

    def adjust(self, strategy: StrategyConfig, regime: MarketRegime) -> StrategyConfig:
        if regime is MarketRegime.BULL:
            return replace(
                strategy,
                momentum_entry_threshold=max(0.0, strategy.momentum_entry_threshold - 0.01),
                rsi_recovery_ceiling=min(60.0, strategy.rsi_recovery_ceiling + 10.0),
                rsi_overbought=min(85.0, strategy.rsi_overbought + 10.0),
                max_holding_bars=strategy.max_holding_bars + 8,
            )
        if regime is MarketRegime.BEAR:
            return replace(
                strategy,
                momentum_entry_threshold=strategy.momentum_entry_threshold + 0.02,
                momentum_exit_threshold=max(0.0, strategy.momentum_exit_threshold),
                rsi_recovery_ceiling=max(30.0, strategy.rsi_recovery_ceiling - 10.0),
                rsi_overbought=max(55.0, strategy.rsi_overbought - 10.0),
                max_holding_bars=max(8, strategy.max_holding_bars - 8),
            )
        return strategy
