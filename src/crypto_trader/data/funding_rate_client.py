from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib import parse, request

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FundingRatePoint:
    symbol: str
    funding_rate: float
    funding_time: datetime


class UpbitFundingRateClient:
    """Funding-rate client keyed by Upbit spot symbols.

    Upbit spot markets do not expose funding-rate endpoints, so this client maps
    Upbit symbols to corresponding Binance perpetual symbols and fetches official
    futures funding data as the cross-market sentiment proxy.
    """

    FUTURES_BASE_URL = "https://fapi.binance.com"

    _SYMBOL_MAP: dict[str, str] = {
        "KRW-BTC": "BTCUSDT",
        "KRW-ETH": "ETHUSDT",
        "KRW-XRP": "XRPUSDT",
        "KRW-SOL": "SOLUSDT",
    }

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        self._cached_rate: dict[str, float] = {}
        self._cached_history: dict[str, list[FundingRatePoint]] = {}

    def _to_perp_symbol(self, upbit_symbol: str) -> str:
        mapped = self._SYMBOL_MAP.get(upbit_symbol)
        if mapped is not None:
            return mapped
        base = upbit_symbol.replace("KRW-", "")
        return f"{base}USDT"

    def get_funding_rate(self, upbit_symbol: str = "KRW-BTC") -> float | None:
        """Fetch the latest funding rate as a decimal."""
        history = self.get_funding_rate_history(upbit_symbol, limit=1)
        if history:
            rate = history[-1].funding_rate
            self._cached_rate[upbit_symbol] = rate
            return rate
        return self._cached_rate.get(upbit_symbol)

    def get_latest_funding_rate(self, upbit_symbol: str = "KRW-BTC") -> float | None:
        return self.get_funding_rate(upbit_symbol)

    def get_funding_rate_history(
        self,
        upbit_symbol: str = "KRW-BTC",
        limit: int = 100,
    ) -> list[FundingRatePoint]:
        """Fetch recent official funding-rate history."""
        perp_symbol = self._to_perp_symbol(upbit_symbol)
        query = parse.urlencode({"symbol": perp_symbol, "limit": max(1, int(limit))})
        url = f"{self.FUTURES_BASE_URL}/fapi/v1/fundingRate?{query}"
        try:
            payload = self._request_json(url)
            if isinstance(payload, list):
                points = [
                    FundingRatePoint(
                        symbol=upbit_symbol,
                        funding_rate=float(item["fundingRate"]),
                        funding_time=datetime.fromtimestamp(
                            int(item["fundingTime"]) / 1000,
                            tz=UTC,
                        ),
                    )
                    for item in payload
                ]
                self._cached_history[upbit_symbol] = points
                if points:
                    self._cached_rate[upbit_symbol] = points[-1].funding_rate
                return points
        except Exception:
            logger.warning(
                "Failed to fetch funding-rate history for %s",
                perp_symbol,
                exc_info=True,
            )
        return list(self._cached_history.get(upbit_symbol, []))

    def get_premium_index(self, upbit_symbol: str = "KRW-BTC") -> dict[str, float] | None:
        """Fetch current premium index and latest funding snapshot."""
        perp_symbol = self._to_perp_symbol(upbit_symbol)
        query = parse.urlencode({"symbol": perp_symbol})
        url = f"{self.FUTURES_BASE_URL}/fapi/v1/premiumIndex?{query}"
        try:
            payload = self._request_json(url)
            if not isinstance(payload, dict):
                return None
            return {
                "lastFundingRate": float(payload.get("lastFundingRate", 0.0)),
                "nextFundingTime": float(payload.get("nextFundingTime", 0.0)),
                "markPrice": float(payload.get("markPrice", 0.0)),
                "indexPrice": float(payload.get("indexPrice", 0.0)),
            }
        except Exception:
            logger.warning(
                "Failed to fetch premium index for %s",
                perp_symbol,
                exc_info=True,
            )
        return None

    def _request_json(self, url: str) -> object:
        req = request.Request(url, headers={"Accept": "application/json"})
        with request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


BinanceFundingRateClient = UpbitFundingRateClient
