from __future__ import annotations

import json
import logging
from urllib import request

logger = logging.getLogger(__name__)


class BinancePriceClient:
    """Fetches crypto/USDT prices from Binance public API (no auth needed)."""

    BASE_URL = "https://api.binance.com/api/v3/ticker/price"

    # Map Upbit KRW-XXX symbols to Binance XXXUSDT symbols
    _SYMBOL_MAP: dict[str, str] = {
        "KRW-BTC": "BTCUSDT",
        "KRW-ETH": "ETHUSDT",
        "KRW-XRP": "XRPUSDT",
        "KRW-SOL": "SOLUSDT",
    }

    def get_btc_usdt_price(self) -> float | None:
        return self.get_usdt_price("KRW-BTC")

    def get_usdt_price(self, upbit_symbol: str = "KRW-BTC") -> float | None:
        """Fetch USDT price for any supported symbol."""
        binance_symbol = self._SYMBOL_MAP.get(upbit_symbol)
        if binance_symbol is None:
            # Fallback: strip KRW- prefix and append USDT
            base = upbit_symbol.replace("KRW-", "")
            binance_symbol = f"{base}USDT"
        try:
            url = f"{self.BASE_URL}?symbol={binance_symbol}"
            req = request.Request(url, headers={"Accept": "application/json"})
            with request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return float(data["price"])
        except Exception:
            logger.warning("Failed to fetch Binance %s price", binance_symbol, exc_info=True)
            return None
