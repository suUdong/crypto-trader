from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path

from crypto_trader.models import Candle

DEFAULT_CACHE_MAX_AGE_HOURS = 6
UPBIT_PAGINATION_HOURS = 9


def _normalize_candles(candles: list[Candle], expected_count: int | None = None) -> list[Candle]:
    """Sort candles and collapse duplicate timestamps.

    Upbit batch pagination can overlap at batch boundaries. Keeping the latest
    candle per timestamp gives a stable, cacheable series for later reuse.
    """
    deduped: dict[datetime, Candle] = {}
    for candle in candles:
        deduped[candle.timestamp] = candle

    normalized = [deduped[timestamp] for timestamp in sorted(deduped)]
    if expected_count is not None and len(normalized) > expected_count:
        normalized = normalized[-expected_count:]
    return normalized


def _cache_path(cache_dir: str | None, symbol: str, interval: str, days: int) -> Path | None:
    if not cache_dir:
        return None
    safe_symbol = symbol.replace("-", "_")
    return Path(cache_dir) / f"{safe_symbol}-{interval}-{days}d.json"


def load_candle_cache(
    cache_dir: str | None,
    symbol: str,
    interval: str,
    days: int,
) -> list[Candle] | None:
    path = _cache_path(cache_dir, symbol, interval, days)
    if path is None or not path.exists():
        return None

    age_hours = (
        datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    ).total_seconds() / 3600.0
    if age_hours > DEFAULT_CACHE_MAX_AGE_HOURS:
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_count = days * 24
    if len(payload) < expected_count:
        return None

    candles = [
        Candle(
            timestamp=datetime.fromisoformat(item["timestamp"]),
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            volume=float(item["volume"]),
        )
        for item in payload
    ]
    candles = _normalize_candles(candles, expected_count=expected_count)
    if len(candles) < expected_count:
        return None
    serialized = [
        {
            "timestamp": candle.timestamp.isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        for candle in candles
    ]
    if payload != serialized:
        path.write_text(json.dumps(serialized, indent=2, ensure_ascii=False), encoding="utf-8")
    return candles


def _load_pyupbit():
    try:
        return import_module("pyupbit")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "pyupbit is required to fetch live candle data; "
            "install the 'live' extra or reuse cache."
        ) from exc


def save_candle_cache(
    cache_dir: str | None,
    symbol: str,
    interval: str,
    days: int,
    candles: list[Candle],
) -> None:
    path = _cache_path(cache_dir, symbol, interval, days)
    if path is None:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "timestamp": candle.timestamp.isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        for candle in candles
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_upbit_candles(
    symbol: str,
    days: int,
    interval: str = "minute60",
    cache_dir: str | None = None,
) -> list[Candle]:
    cached = load_candle_cache(cache_dir, symbol, interval, days)
    if cached is not None:
        return cached

    total_needed = days * 24
    pyupbit = _load_pyupbit()
    all_candles: list[Candle] = []
    to_dt: datetime | None = None

    while len(all_candles) < total_needed:
        remaining = total_needed - len(all_candles)
        batch_size = min(200, remaining)
        df = pyupbit.get_ohlcv(symbol, interval=interval, count=batch_size, to=to_dt)
        if df is None or df.empty:
            break

        batch: list[Candle] = []
        for idx, row in df.iterrows():
            ts = idx if isinstance(idx, datetime) else datetime.fromisoformat(str(idx))
            batch.append(
                Candle(
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )

        if not batch:
            break

        # pyupbit interprets naive `to` values on a UTC boundary while the
        # returned candle timestamps are effectively KST-aligned. Without the
        # 9-hour offset, each batch overlaps and the final cache misses data.
        to_dt = batch[0].timestamp - timedelta(hours=UPBIT_PAGINATION_HOURS, seconds=1)
        all_candles = batch + all_candles
        if len(batch) < batch_size:
            break
        time.sleep(0.15)

    normalized = _normalize_candles(all_candles, expected_count=total_needed)
    if len(normalized) >= total_needed:
        save_candle_cache(cache_dir, symbol, interval, days, normalized)
    return normalized
