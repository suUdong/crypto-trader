import unittest
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from crypto_trader.data.pyupbit_client import PyUpbitMarketDataClient, _to_datetime
from crypto_trader.models import Candle


def _make_df():
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [95.0, 96.0, 97.0],
            "close": [103.0, 104.0, 105.0],
            "volume": [1000.0, 1100.0, 1200.0],
        },
        index=pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
    )


class TestPyUpbitMarketDataClient(unittest.TestCase):
    def test_get_ohlcv_returns_candles(self):
        mock_module = MagicMock()
        mock_module.get_ohlcv.return_value = _make_df()
        client = PyUpbitMarketDataClient(module=mock_module)

        result = client.get_ohlcv("KRW-BTC", "day", 3)

        mock_module.get_ohlcv.assert_called_once_with("KRW-BTC", interval="day", count=3)
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], Candle)

        self.assertEqual(result[0].open, 100.0)
        self.assertEqual(result[0].high, 105.0)
        self.assertEqual(result[0].low, 95.0)
        self.assertEqual(result[0].close, 103.0)
        self.assertEqual(result[0].volume, 1000.0)

        self.assertEqual(result[1].open, 101.0)
        self.assertEqual(result[2].close, 105.0)

    def test_get_ohlcv_raises_on_none(self):
        mock_module = MagicMock()
        mock_module.get_ohlcv.return_value = None
        client = PyUpbitMarketDataClient(module=mock_module)

        with self.assertRaises(RuntimeError):
            client.get_ohlcv("KRW-BTC", "day", 3)

    def test_to_datetime_with_datetime_input(self):
        dt = datetime(2025, 1, 1)
        result = _to_datetime(dt)
        self.assertEqual(result, datetime(2025, 1, 1))
        self.assertIsInstance(result, datetime)

    def test_to_datetime_with_string_input(self):
        result = _to_datetime("2025-01-01T00:00:00")
        self.assertEqual(result, datetime(2025, 1, 1, 0, 0, 0))
        self.assertIsInstance(result, datetime)


if __name__ == "__main__":
    unittest.main()
