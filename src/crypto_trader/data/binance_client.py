from __future__ import annotations

import json
import logging
from urllib import request

logger = logging.getLogger(__name__)


class BinancePriceClient:
    """Fetches BTC/USDT price from Binance public API (no auth needed)."""

    BASE_URL = "https://api.binance.com/api/v3/ticker/price"

    def get_btc_usdt_price(self) -> float | None:
        try:
            url = f"{self.BASE_URL}?symbol=BTCUSDT"
            req = request.Request(url, headers={"Accept": "application/json"})
            with request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return float(data["price"])
        except Exception:
            logger.warning("Failed to fetch Binance BTC/USDT price", exc_info=True)
            return None
