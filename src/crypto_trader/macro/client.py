"""Client for reading macro-intelligence regime data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
    """Reads macro regime data from the macro-intelligence SQLite database."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else None

    def get_snapshot(self) -> MacroSnapshot | None:
        """Fetch the latest macro regime snapshot. Returns None on any failure."""
        try:
            from macro_intelligence.api import get_macro_snapshot
            from macro_intelligence.config import Config

            config = Config()
            if self._db_path:
                config.db_path = self._db_path

            data = get_macro_snapshot(config=config)
            regime = data.get("regime")
            crypto = data.get("crypto")

            if regime is None:
                logger.info("Macro regime data not available (insufficient data)")
                return None

            return MacroSnapshot(
                overall_regime=regime["overall"],
                overall_confidence=regime["overall_confidence"],
                us_regime=regime["us"]["regime"],
                us_confidence=regime["us"]["confidence"],
                kr_regime=regime["kr"]["regime"],
                kr_confidence=regime["kr"]["confidence"],
                crypto_regime=regime["crypto"]["regime"],
                crypto_confidence=regime["crypto"]["confidence"],
                crypto_signals=regime["crypto"].get("signals", {}),
                btc_dominance=crypto.get("btc_dominance") if crypto else None,
                kimchi_premium=crypto.get("kimchi_premium") if crypto else None,
                fear_greed_index=crypto.get("fear_greed_index") if crypto else None,
            )
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
