from __future__ import annotations

import json
import logging
from urllib import request

logger = logging.getLogger(__name__)


class FXRateClient:
    """Fetches USD/KRW exchange rate from a public API."""

    def get_usd_krw_rate(self) -> float | None:
        try:
            url = "https://open.er-api.com/v6/latest/USD"
            req = request.Request(url, headers={"Accept": "application/json"})
            with request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return float(data["rates"]["KRW"])
        except Exception:
            logger.warning("Failed to fetch USD/KRW rate", exc_info=True)
            return None
