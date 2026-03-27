from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.indicators import momentum

KST = timezone(timedelta(hours=9))

WEEKEND_POSITION_MULTIPLIER = 0.5


class MarketRegime(StrEnum):
    BULL = "bull"
    SIDEWAYS = "sideways"
    BEAR = "bear"


@dataclass(slots=True)
class RegimeAnalysis:
    regime: MarketRegime
    short_return_pct: float
    long_return_pct: float
    is_weekend: bool = False


def is_weekend_kst(dt: datetime) -> bool:
    """Check if datetime falls in weekend low-liquidity window (Sat 00:00 - Mon 09:00 KST)."""
    kst_time = (
        dt.astimezone(KST) if dt.tzinfo is not None else dt.replace(tzinfo=UTC).astimezone(KST)
    )
    weekday = kst_time.weekday()  # 0=Mon, 5=Sat, 6=Sun
    if weekday == 5 or weekday == 6:
        return True
    if weekday == 0 and kst_time.hour < 9:
        return True
    return False


class RegimeDetector:
    def __init__(self, config: RegimeConfig) -> None:
        self._config = config

    def detect(self, candles: list[Candle]) -> MarketRegime:
        return self.analyze(candles).regime

    def analyze(self, candles: list[Candle]) -> RegimeAnalysis:
        closes = [candle.close for candle in candles]
        minimum = max(self._config.short_lookback + 1, self._config.long_lookback + 1)
        weekend = is_weekend_kst(candles[-1].timestamp) if candles else False
        if len(closes) < minimum:
            return RegimeAnalysis(
                regime=MarketRegime.SIDEWAYS,
                short_return_pct=0.0,
                long_return_pct=0.0,
                is_weekend=weekend,
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
            is_weekend=weekend,
        )

    def adjust(
        self,
        strategy: StrategyConfig,
        regime: MarketRegime,
        is_weekend: bool = False,
    ) -> StrategyConfig:
        if regime is MarketRegime.BULL:
            adjusted = replace(
                strategy,
                momentum_entry_threshold=max(0.0, strategy.momentum_entry_threshold - 0.003),
                rsi_recovery_ceiling=min(75.0, strategy.rsi_recovery_ceiling + 10.0),
                rsi_overbought=min(85.0, strategy.rsi_overbought + 10.0),
                max_holding_bars=strategy.max_holding_bars + 8,
            )
        elif regime is MarketRegime.BEAR:
            adjusted = replace(
                strategy,
                momentum_entry_threshold=strategy.momentum_entry_threshold + 0.01,
                momentum_exit_threshold=max(0.0, strategy.momentum_exit_threshold),
                rsi_recovery_ceiling=max(30.0, strategy.rsi_recovery_ceiling - 10.0),
                rsi_overbought=max(55.0, strategy.rsi_overbought - 10.0),
                max_holding_bars=max(8, strategy.max_holding_bars - 8),
            )
        else:
            adjusted = strategy

        if is_weekend:
            adjusted = replace(
                adjusted,
                momentum_entry_threshold=adjusted.momentum_entry_threshold + 0.005,
                rsi_recovery_ceiling=max(30.0, adjusted.rsi_recovery_ceiling - 5.0),
                rsi_overbought=max(55.0, adjusted.rsi_overbought - 5.0),
                max_holding_bars=max(8, adjusted.max_holding_bars // 2),
            )

        return adjusted
