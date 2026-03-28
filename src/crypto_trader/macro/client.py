"""Client for reading macro-intelligence regime data."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

_REGIME_ALIASES: dict[str, str] = {
    "expansion": "expansionary",
    "expansionary": "expansionary",
    "neutral": "neutral",
    "contraction": "contractionary",
    "contractionary": "contractionary",
}


@dataclass(slots=True)
class MacroSnapshot:
    """Lightweight snapshot of macro regime state for crypto-trader consumption."""

    overall_regime: str  # "expansionary" | "neutral" | "contractionary"
    overall_confidence: float
    us_regime: str
    us_confidence: float
    kr_regime: str
    kr_confidence: float
    crypto_regime: str
    crypto_confidence: float
    crypto_signals: dict[str, str]
    btc_dominance: float | None = None
    kimchi_premium: float | None = None
    fear_greed_index: int | None = None


class MacroClient:
    """Reads macro regime data from the macro-intelligence service or local package."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._db_path = Path(db_path) if db_path else None
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _normalize_regime(value: Any) -> str:
        text = str(value or "neutral").strip().lower()
        return _REGIME_ALIASES.get(text, text or "neutral")

    def _fetch_http_payload(self) -> dict[str, Any] | None:
        """Fetch the latest regime payload from the macro HTTP API."""
        if not self._base_url:
            return None

        last_error: Exception | None = None
        for path in ("/regime/downstream/crypto-trader", "/regime/current"):
            url = f"{self._base_url}{path}"
            try:
                with urlopen(url, timeout=self._timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                continue

            if not isinstance(payload, dict):
                logger.info("Macro HTTP payload is not an object (url=%s)", url)
                continue
            if payload.get("status") != "ok":
                logger.info(
                    "Macro HTTP payload unavailable (url=%s status=%s)",
                    url,
                    payload.get("status"),
                )
                continue
            return payload

        if last_error is not None:
            logger.warning("Failed to fetch macro regime over HTTP", exc_info=last_error)
        return None

    @staticmethod
    def _snapshot_from_payload(data: dict[str, Any]) -> MacroSnapshot | None:
        """Normalize HTTP or local payload into MacroSnapshot."""
        if "regime" in data:
            regime = data.get("regime")
            crypto = data.get("crypto")
            if regime is None:
                return None
            return MacroSnapshot(
                overall_regime=MacroClient._normalize_regime(regime["overall"]),
                overall_confidence=regime["overall_confidence"],
                us_regime=MacroClient._normalize_regime(regime["us"]["regime"]),
                us_confidence=regime["us"]["confidence"],
                kr_regime=MacroClient._normalize_regime(regime["kr"]["regime"]),
                kr_confidence=regime["kr"]["confidence"],
                crypto_regime=MacroClient._normalize_regime(regime["crypto"]["regime"]),
                crypto_confidence=regime["crypto"]["confidence"],
                crypto_signals=regime["crypto"].get("signals", {}),
                btc_dominance=crypto.get("btc_dominance") if crypto else None,
                kimchi_premium=crypto.get("kimchi_premium") if crypto else None,
                fear_greed_index=crypto.get("fear_greed_index") if crypto else None,
            )

        layers = data.get("layers")
        if not layers:
            return None

        crypto_metrics = data.get("crypto_metrics", {})
        return MacroSnapshot(
            overall_regime=MacroClient._normalize_regime(data["overall_regime"]),
            overall_confidence=data["overall_confidence"],
            us_regime=MacroClient._normalize_regime(layers["us"]["regime"]),
            us_confidence=layers["us"]["confidence"],
            kr_regime=MacroClient._normalize_regime(layers["kr"]["regime"]),
            kr_confidence=layers["kr"]["confidence"],
            crypto_regime=MacroClient._normalize_regime(layers["crypto"]["regime"]),
            crypto_confidence=layers["crypto"]["confidence"],
            crypto_signals=layers["crypto"].get("signals", {}),
            btc_dominance=crypto_metrics.get("btc_dominance"),
            kimchi_premium=crypto_metrics.get("kimchi_premium"),
            fear_greed_index=crypto_metrics.get("fear_greed_index"),
        )

    def get_snapshot(self) -> MacroSnapshot | None:
        """Fetch the latest macro regime snapshot. Returns None on any failure."""
        http_payload = self._fetch_http_payload()
        if http_payload is not None:
            return self._snapshot_from_payload(http_payload)

        try:
            from macro_intelligence.api import get_macro_snapshot
            from macro_intelligence.config import Config

            config = Config()
            if self._db_path:
                config.db_path = self._db_path

            data = get_macro_snapshot(config=config)
            snapshot = self._snapshot_from_payload(data)
            if snapshot is None:
                logger.info("Macro regime data not available (insufficient data)")
            return snapshot
        except ImportError:
            logger.warning("macro_intelligence package not installed, skipping macro layer")
            return None
        except Exception:
            logger.exception("Failed to read macro regime data")
            return None

    def get_memo_summary(self) -> dict[str, Any] | None:
        """Return a dict suitable for embedding in the daily memo."""
        snapshot = self.get_snapshot()
        if snapshot is None:
            return None
        return {
            "overall_regime": snapshot.overall_regime,
            "overall_confidence": snapshot.overall_confidence,
            "layers": {
                "US": {"regime": snapshot.us_regime, "confidence": snapshot.us_confidence},
                "Korea": {"regime": snapshot.kr_regime, "confidence": snapshot.kr_confidence},
                "Crypto": {
                    "regime": snapshot.crypto_regime,
                    "confidence": snapshot.crypto_confidence,
                },
            },
            "crypto_signals": {
                "btc_dominance": snapshot.btc_dominance,
                "kimchi_premium": snapshot.kimchi_premium,
                "fear_greed_index": snapshot.fear_greed_index,
            },
        }
