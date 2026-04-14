from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from crypto_trader.models import Candle
from crypto_trader.operator.runtime_market_data import (
    RuntimeCandleCache,
    interval_timedelta,
    trim_open_candle,
    wallet_candles_for,
)


class _RecordingMarketData:
    def __init__(self, candle_map: dict[tuple[str, str, int], list[Candle]]) -> None:
        self._candle_map = candle_map
        self.calls: list[tuple[str, str, int]] = []

    def get_ohlcv(self, symbol: str, interval: str, count: int) -> list[Candle]:
        self.calls.append((symbol, interval, count))
        return self._candle_map[(symbol, interval, count)]


def _candles(count: int, *, hours: int = 1, last_offset_hours: int = 0) -> list[Candle]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index in range(count):
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=index * hours + last_offset_hours),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.5 + index,
                volume=10.0 + index,
            )
        )
    return candles


def test_interval_timedelta_handles_minute_and_day() -> None:
    assert interval_timedelta("minute240") == timedelta(minutes=240)
    assert interval_timedelta("day") == timedelta(days=1)
    assert interval_timedelta("week") is None


def test_trim_open_candle_drops_incomplete_latest_bar() -> None:
    now = datetime(2025, 1, 2, 12, tzinfo=UTC)
    candles = _candles(3, hours=4)
    candles[-1] = Candle(
        timestamp=now - timedelta(hours=1),
        open=103.0,
        high=104.0,
        low=102.0,
        close=103.5,
        volume=13.0,
    )

    trimmed = trim_open_candle(candles, "minute240", now=now)

    assert len(trimmed) == 2
    assert trimmed[-1].timestamp == candles[-2].timestamp


def test_runtime_candle_cache_reuses_cached_fetch() -> None:
    market_data = _RecordingMarketData(
        {("KRW-ONT", "minute60", 10): _candles(10)}
    )
    cache = RuntimeCandleCache(market_data)

    first = cache.get("KRW-ONT", "minute60", 10)
    second = cache.get("KRW-ONT", "minute60", 10)

    assert first == second
    assert market_data.calls == [("KRW-ONT", "minute60", 10)]


def test_wallet_candles_for_uses_override_and_trim() -> None:
    now = datetime(2025, 1, 2, 12, tzinfo=UTC)
    default_candles = _candles(5)
    override_candles = _candles(3, hours=4)
    override_candles[-1] = Candle(
        timestamp=now - timedelta(hours=1),
        open=103.0,
        high=104.0,
        low=102.0,
        close=103.5,
        volume=13.0,
    )
    market_data = _RecordingMarketData(
        {
            ("KRW-ONT", "minute240", 3): override_candles,
        }
    )
    cache = RuntimeCandleCache(market_data)
    wallet = SimpleNamespace(
        market_data_spec=lambda _default_interval, _default_count: ("minute240", 3, True)
    )

    candles = wallet_candles_for(
        cache,
        wallet,
        "KRW-ONT",
        default_interval="minute60",
        default_count=5,
        default_candles=default_candles,
        now=now,
    )

    assert len(candles) == 2
    assert market_data.calls == [("KRW-ONT", "minute240", 3)]
