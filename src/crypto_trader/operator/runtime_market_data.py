from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from crypto_trader.data.base import MarketDataClient
from crypto_trader.models import Candle


@dataclass(frozen=True, slots=True)
class CandleKey:
    symbol: str
    interval: str
    count: int


class WalletMarketDataTarget(Protocol):
    def market_data_spec(
        self,
        default_interval: str,
        default_count: int,
    ) -> tuple[str, int, bool]: ...


def wallet_market_data_spec(
    wallet: object,
    default_interval: str,
    default_count: int,
) -> tuple[str, int, bool]:
    spec_fn = getattr(wallet, "market_data_spec", None)
    if callable(spec_fn):
        try:
            spec = spec_fn(default_interval, default_count)
            if isinstance(spec, tuple) and len(spec) == 3:
                interval, count, closed_only = spec
                return str(interval), int(count), bool(closed_only)
        except Exception:
            pass
    return default_interval, default_count, False


def interval_timedelta(interval: str) -> timedelta | None:
    if interval == "day":
        return timedelta(days=1)
    if interval.startswith("minute"):
        try:
            minutes = int(interval.removeprefix("minute"))
        except ValueError:
            return None
        return timedelta(minutes=minutes)
    return None


def trim_open_candle(
    candles: list[Candle],
    interval: str,
    *,
    now: datetime | None = None,
) -> list[Candle]:
    if len(candles) < 2:
        return candles
    duration = interval_timedelta(interval)
    if duration is None:
        return candles
    current_time = now or datetime.now(UTC)
    latest_ts = candles[-1].timestamp
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=UTC)
    if latest_ts + duration > current_time:
        return candles[:-1]
    return candles


class RuntimeCandleCache:
    def __init__(self, market_data: MarketDataClient) -> None:
        self._market_data = market_data
        self._cache: dict[CandleKey, list[Candle]] = {}

    def get(self, symbol: str, interval: str, count: int) -> list[Candle]:
        key = CandleKey(symbol, interval, count)
        if key not in self._cache:
            self._cache[key] = self._market_data.get_ohlcv(
                symbol=symbol,
                interval=interval,
                count=count,
            )
        return self._cache[key]

    def set(self, symbol: str, interval: str, count: int, candles: list[Candle]) -> None:
        self._cache[CandleKey(symbol, interval, count)] = candles

    def peek(self, symbol: str, interval: str, count: int) -> list[Candle]:
        return self._cache.get(CandleKey(symbol, interval, count), [])

    def default_map(
        self,
        symbols: list[str],
        interval: str,
        count: int,
    ) -> dict[str, list[Candle]]:
        return {symbol: self.peek(symbol, interval, count) for symbol in symbols}


def wallet_candles_for(
    cache: RuntimeCandleCache,
    wallet: object,
    symbol: str,
    *,
    default_interval: str,
    default_count: int,
    default_candles: list[Candle],
    now: datetime | None = None,
) -> list[Candle]:
    wallet_interval, wallet_count, wallet_closed_only = wallet_market_data_spec(
        wallet,
        default_interval,
        default_count,
    )
    candles = default_candles
    if wallet_interval != default_interval or wallet_count != default_count:
        candles = cache.get(symbol, wallet_interval, wallet_count)
    if wallet_closed_only:
        candles = trim_open_candle(candles, wallet_interval, now=now)
    return candles
