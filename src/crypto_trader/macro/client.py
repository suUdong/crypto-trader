"""Client for reading macro-intelligence regime data."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# Retry / backoff constants
_MAX_RETRIES = 2  # per endpoint, per call
_INITIAL_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 4.0
_LOG_THROTTLE_INTERVAL = 300  # suppress repeat warnings for 5 minutes

_REGIME_ALIASES: dict[str, str] = {
    "expansion": "expansionary",
    "expansionary": "expansionary",
    "neutral": "neutral",
    "contraction": "contractionary",
    "contractionary": "contractionary",
}

_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


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
        self._consecutive_http_failures: int = 0
        self._last_failure_log_time: float = 0.0

    @staticmethod
    def _normalize_regime(value: Any) -> str:
        text = str(value or "neutral").strip().lower()
        return _REGIME_ALIASES.get(text, text or "neutral")

    def _fetch_http_payload(self) -> dict[str, Any] | None:
        """Fetch the latest regime payload from the macro HTTP API.

        Retries each endpoint up to ``_MAX_RETRIES`` times with exponential
        backoff.  Consecutive failure warnings are throttled to one log line
        per ``_LOG_THROTTLE_INTERVAL`` seconds so a prolonged outage does not
        flood the log file.
        """
        if not self._base_url:
            return None

        last_error: Exception | None = None
        for path in ("/regime/downstream/crypto-trader", "/regime/current"):
            url = f"{self._base_url}{path}"
            backoff = _INITIAL_BACKOFF_SECONDS
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    with urlopen(url, timeout=self._timeout_seconds) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                except (HTTPError, URLError, TimeoutError, OSError,
                        json.JSONDecodeError) as exc:
                    last_error = exc
                    if attempt < _MAX_RETRIES:
                        time.sleep(backoff)
                        backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                    continue

                if not isinstance(payload, dict):
                    logger.info("Macro HTTP payload is not an object (url=%s)", url)
                    break  # move to next endpoint
                if payload.get("status") != "ok":
                    logger.info(
                        "Macro HTTP payload unavailable (url=%s status=%s)",
                        url,
                        payload.get("status"),
                    )
                    break  # move to next endpoint

                # Success — reset failure counter
                if self._consecutive_http_failures > 0:
                    logger.info(
                        "Macro HTTP connection restored after %d consecutive failures",
                        self._consecutive_http_failures,
                    )
                self._consecutive_http_failures = 0
                return payload

        # All endpoints failed
        self._consecutive_http_failures += 1
        now = time.monotonic()
        if now - self._last_failure_log_time >= _LOG_THROTTLE_INTERVAL:
            logger.warning(
                "Failed to fetch macro regime over HTTP "
                "(consecutive_failures=%d)",
                self._consecutive_http_failures,
                exc_info=last_error,
            )
            self._last_failure_log_time = now
        else:
            logger.debug(
                "Macro HTTP fetch failed (consecutive_failures=%d): %s",
                self._consecutive_http_failures,
                last_error,
            )
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
        if layers:
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

        primary_layer = data.get("primary_layer")
        if isinstance(primary_layer, dict) and "overall_regime" in data:
            signals = primary_layer.get("signals", {})
            if not isinstance(signals, dict):
                signals = {}
            crypto_metrics = data.get("crypto_metrics", {})
            overall_regime = MacroClient._normalize_regime(data.get("overall_regime"))
            overall_confidence = float(data.get("overall_confidence", 0.0) or 0.0)
            crypto_regime = MacroClient._normalize_regime(
                primary_layer.get("regime", overall_regime)
            )
            crypto_confidence = float(
                primary_layer.get("confidence", overall_confidence) or overall_confidence
            )
            return MacroSnapshot(
                overall_regime=overall_regime,
                overall_confidence=overall_confidence,
                us_regime="neutral",
                us_confidence=0.0,
                kr_regime="neutral",
                kr_confidence=0.0,
                crypto_regime=crypto_regime,
                crypto_confidence=crypto_confidence,
                crypto_signals={str(key): str(value) for key, value in signals.items()},
                btc_dominance=MacroClient._coerce_optional_float(
                    crypto_metrics.get("btc_dominance")
                ),
                kimchi_premium=MacroClient._coerce_optional_float(
                    crypto_metrics.get("kimchi_premium", signals.get("kimchi_premium"))
                ),
                fear_greed_index=MacroClient._coerce_optional_int(
                    crypto_metrics.get("fear_greed_index", signals.get("fear_greed"))
                ),
            )

        return None

    @staticmethod
    def _coerce_optional_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = _NUMBER_PATTERN.search(str(value))
        return float(match.group(0)) if match else None

    @staticmethod
    def _coerce_optional_int(value: Any) -> int | None:
        coerced = MacroClient._coerce_optional_float(value)
        return int(coerced) if coerced is not None else None

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
