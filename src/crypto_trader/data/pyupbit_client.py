from __future__ import annotations

from datetime import datetime
from importlib import import_module
from typing import Any

from crypto_trader.models import Candle


class PyUpbitMarketDataClient:
    def __init__(self, module: Any | None = None) -> None:
        self._module = module

    def get_ohlcv(self, symbol: str, interval: str, count: int) -> list[Candle]:
        module = self._module or _load_pyupbit()
        frame = module.get_ohlcv(symbol, interval=interval, count=count)
        if frame is None:
            raise RuntimeError(f"No OHLCV data returned for {symbol}")

        candles: list[Candle] = []
        for index, row in frame.iterrows():
            candles.append(
                Candle(
                    timestamp=_to_datetime(index),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        return candles


def _load_pyupbit() -> Any:
    try:
        return import_module("pyupbit")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "pyupbit is required for live Upbit market data. Install with `pip install .[live]`."
        ) from exc


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
