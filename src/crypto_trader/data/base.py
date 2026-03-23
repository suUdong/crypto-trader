from __future__ import annotations

from typing import Protocol

from crypto_trader.models import Candle


class MarketDataClient(Protocol):
    def get_ohlcv(self, symbol: str, interval: str, count: int) -> list[Candle]:
        """Return candles ordered from oldest to newest."""
