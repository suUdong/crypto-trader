from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from crypto_trader.backtest.candle_cache import (
    DEFAULT_CACHE_MAX_AGE_HOURS,
    fetch_upbit_candles,
    load_candle_cache,
    save_candle_cache,
)
from crypto_trader.models import Candle


class TestCandleCache(unittest.TestCase):
    def test_save_and_load_round_trip(self) -> None:
        candles = [
            Candle(
                timestamp=datetime(2025, 1, 1) + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.5 + index,
                volume=1000.0 + index,
            )
            for index in range(24)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            save_candle_cache(tmpdir, "KRW-BTC", "minute60", 1, candles)
            loaded = load_candle_cache(tmpdir, "KRW-BTC", "minute60", 1)

        assert loaded is not None
        self.assertEqual(len(loaded), 24)
        self.assertEqual(loaded[0].timestamp, candles[0].timestamp)
        self.assertEqual(loaded[-1].close, candles[-1].close)

    def test_incomplete_cache_is_ignored_and_not_overwritten_by_partial_fetch(self) -> None:
        candles = [
            Candle(
                timestamp=datetime(2025, 1, 1),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000.0,
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            save_candle_cache(tmpdir, "KRW-BTC", "minute60", 90, candles)
            cache_path = Path(tmpdir) / "KRW_BTC-minute60-90d.json"

            fake_pyupbit = type(
                "FakePyUpbit",
                (),
                {"get_ohlcv": staticmethod(lambda *args, **kwargs: None)},
            )
            with patch(
                "crypto_trader.backtest.candle_cache.import_module",
                return_value=fake_pyupbit,
            ):
                fetched = fetch_upbit_candles("KRW-BTC", 90, cache_dir=tmpdir)

            self.assertEqual(fetched, [])
            payload = cache_path.read_text(encoding="utf-8")
            self.assertEqual(len(load_candle_cache(tmpdir, "KRW-BTC", "minute60", 90) or []), 0)
            self.assertIn("2025-01-01T00:00:00", payload)

    def test_expired_cache_is_ignored(self) -> None:
        candles = [
            Candle(
                timestamp=datetime(2025, 1, 1) + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.5 + index,
                volume=1000.0 + index,
            )
            for index in range(24 * 90)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            save_candle_cache(tmpdir, "KRW-BTC", "minute60", 90, candles)
            cache_path = Path(tmpdir) / "KRW_BTC-minute60-90d.json"
            stale_seconds = int((DEFAULT_CACHE_MAX_AGE_HOURS + 1) * 3600)
            stale_mtime = cache_path.stat().st_mtime - stale_seconds
            os.utime(cache_path, (stale_mtime, stale_mtime))

            loaded = load_candle_cache(tmpdir, "KRW-BTC", "minute60", 90)

        self.assertIsNone(loaded)

    def test_load_normalizes_out_of_order_cache_with_duplicate_timestamps(self) -> None:
        candles = [
            Candle(
                timestamp=datetime(2025, 1, 1) + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.5 + index,
                volume=1000.0 + index,
            )
            for index in range(24)
        ]
        malformed = []
        for candle in candles[:12]:
            malformed.append(
                {
                    "timestamp": candle.timestamp.isoformat(),
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
            )
        for candle in candles[10:]:
            malformed.append(
                {
                    "timestamp": candle.timestamp.isoformat(),
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "KRW_BTC-minute60-1d.json"
            cache_path.write_text(
                json.dumps(malformed, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            loaded = load_candle_cache(tmpdir, "KRW-BTC", "minute60", 1)
            repaired = json.loads(cache_path.read_text(encoding="utf-8"))

        assert loaded is not None
        self.assertEqual(len(loaded), 24)
        self.assertEqual(loaded[0].timestamp, candles[0].timestamp)
        self.assertEqual(loaded[-1].timestamp, candles[-1].timestamp)
        self.assertEqual(len(repaired), 24)
        self.assertEqual(repaired[0]["timestamp"], candles[0].timestamp.isoformat())
        self.assertEqual(repaired[-1]["timestamp"], candles[-1].timestamp.isoformat())

    def test_fetch_uses_nine_hour_pagination_offset_to_avoid_batch_overlap(self) -> None:
        candles = [
            Candle(
                timestamp=datetime(2025, 1, 1) + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.5 + index,
                volume=1000.0 + index,
            )
            for index in range(24 * 9)
        ]
        latest_batch = candles[-200:]
        oldest_batch = candles[:-200]
        expected_to = latest_batch[0].timestamp - timedelta(hours=9, seconds=1)

        class FakeFrame:
            def __init__(self, rows: list[Candle]) -> None:
                self._rows = rows
                self.empty = not rows

            def iterrows(self):
                for candle in self._rows:
                    yield candle.timestamp, {
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                        "volume": candle.volume,
                    }

        class FakePyUpbit:
            def __init__(self) -> None:
                self.calls: list[datetime | None] = []

            def get_ohlcv(self, symbol, interval="minute60", count=200, to=None):
                self.calls.append(to)
                if to is None:
                    return FakeFrame(latest_batch)
                if to == expected_to:
                    return FakeFrame(oldest_batch)
                return FakeFrame([])

        fake_pyupbit = FakePyUpbit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "crypto_trader.backtest.candle_cache.import_module",
                return_value=fake_pyupbit,
            ):
                fetched = fetch_upbit_candles("KRW-BTC", 9, cache_dir=tmpdir)
            loaded = load_candle_cache(tmpdir, "KRW-BTC", "minute60", 9)

        self.assertEqual(len(fetched), 24 * 9)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(len(loaded), 24 * 9)
        self.assertEqual(fake_pyupbit.calls, [None, expected_to])


if __name__ == "__main__":
    unittest.main()
