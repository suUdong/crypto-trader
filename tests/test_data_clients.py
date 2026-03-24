from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from crypto_trader.data.binance_client import BinancePriceClient
from crypto_trader.data.fx_client import FXRateClient


def _mock_urlopen(data: dict) -> MagicMock:
    response = MagicMock()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    response.read.return_value = json.dumps(data).encode("utf-8")
    return response


class TestBinancePriceClient(unittest.TestCase):
    def test_binance_returns_price(self):
        mock_resp = _mock_urlopen({"price": "65000.50"})
        with patch("crypto_trader.data.binance_client.request.urlopen", return_value=mock_resp):
            client = BinancePriceClient()
            result = client.get_btc_usdt_price()
        self.assertEqual(result, 65000.5)

    def test_binance_returns_none_on_error(self):
        with patch(
            "crypto_trader.data.binance_client.request.urlopen",
            side_effect=Exception("network error"),
        ):
            client = BinancePriceClient()
            result = client.get_btc_usdt_price()
        self.assertIsNone(result)

    def test_binance_parses_string_price(self):
        mock_resp = _mock_urlopen({"price": "12345.67"})
        with patch("crypto_trader.data.binance_client.request.urlopen", return_value=mock_resp):
            client = BinancePriceClient()
            result = client.get_btc_usdt_price()
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 12345.67)


class TestFXRateClient(unittest.TestCase):
    def test_fx_returns_rate(self):
        mock_resp = _mock_urlopen({"rates": {"KRW": 1350.0}})
        with patch("crypto_trader.data.fx_client.request.urlopen", return_value=mock_resp):
            client = FXRateClient()
            result = client.get_usd_krw_rate()
        self.assertEqual(result, 1350.0)

    def test_fx_returns_none_on_error(self):
        with patch(
            "crypto_trader.data.fx_client.request.urlopen",
            side_effect=Exception("timeout"),
        ):
            client = FXRateClient()
            result = client.get_usd_krw_rate()
        self.assertIsNone(result)

    def test_fx_parses_nested_json(self):
        mock_resp = _mock_urlopen({"rates": {"KRW": 1280.5, "EUR": 0.92}})
        with patch("crypto_trader.data.fx_client.request.urlopen", return_value=mock_resp):
            client = FXRateClient()
            result = client.get_usd_krw_rate()
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 1280.5)


if __name__ == "__main__":
    unittest.main()
