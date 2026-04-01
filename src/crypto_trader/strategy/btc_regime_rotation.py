"""BTC Regime Rotation Strategy

Entry condition:
  - BTC bull regime (stealth-watchlist.json btc_bull_regime=True)
  - Symbol is in top alpha watchlist (alpha-watchlist.json)
Exit condition:
  - BTC regime turns bear, OR symbol drops off alpha watchlist
  - Normal stop-loss / take-profit handled by RiskManager
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction

_logger = logging.getLogger(__name__)

_STEALTH_PATH = Path("artifacts/stealth-watchlist.json")
_ALPHA_PATH = Path("artifacts/alpha-watchlist.json")
_STALE_HOURS = 3.0


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _age_hours(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 999.0


class BtcRegimeRotationStrategy:
    """Altcoin rotation gated on BTC bull regime + alpha watchlist membership."""

    def __init__(self, config: StrategyConfig, min_alpha: float = 1.0) -> None:
        self._config = config
        self._min_alpha = min_alpha

    # ── public interface ────────────────────────────────────────────────────────

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
        **_kwargs,
    ) -> Signal:
        btc_bull, regime_age = self._read_btc_regime()
        alpha_score, watchlist_age = self._read_alpha(symbol)
        in_watchlist = alpha_score is not None and alpha_score >= self._min_alpha

        # ── exit logic (position already open) ─────────────────────────────────
        if position is not None:
            if btc_bull is False:
                return Signal(
                    action=SignalAction.SELL,
                    reason="btc_bear_exit",
                    confidence=0.9,
                    indicators={"btc_bull": False, "alpha": alpha_score or 0.0},
                )
            if not in_watchlist:
                return Signal(
                    action=SignalAction.SELL,
                    reason="watchlist_exit",
                    confidence=0.8,
                    indicators={"btc_bull": btc_bull, "alpha": alpha_score or 0.0},
                )
            return Signal(
                action=SignalAction.HOLD,
                reason="hold_in_watchlist",
                confidence=0.5,
                indicators={"btc_bull": btc_bull, "alpha": alpha_score or 0.0},
            )

        # ── entry logic ─────────────────────────────────────────────────────────
        if btc_bull is None:
            return Signal(
                action=SignalAction.HOLD,
                reason="btc_regime_unknown",
                confidence=0.0,
                indicators={"regime_age_h": regime_age},
            )
        if not btc_bull:
            return Signal(
                action=SignalAction.HOLD,
                reason="btc_bear_gate",
                confidence=0.0,
                indicators={"btc_bull": False},
            )
        if not in_watchlist:
            return Signal(
                action=SignalAction.HOLD,
                reason="not_in_alpha_watchlist",
                confidence=0.0,
                indicators={"alpha": alpha_score or 0.0, "min_alpha": self._min_alpha},
            )

        # BTC bull + symbol in watchlist → BUY
        # Confidence: 0.6 base + alpha contribution, capped at 0.92
        confidence = min(0.92, 0.6 + (alpha_score or 1.0) * 0.05)
        _logger.info(
            "[btc_rotation] BUY %s  alpha=%.3f  confidence=%.2f  regime_age=%.1fh",
            symbol, alpha_score, confidence, regime_age,
        )
        return Signal(
            action=SignalAction.BUY,
            reason="btc_bull_rotation",
            confidence=confidence,
            indicators={
                "btc_bull": True,
                "alpha": alpha_score,
                "regime_age_h": regime_age,
                "watchlist_age_h": watchlist_age,
            },
        )

    # ── helpers ─────────────────────────────────────────────────────────────────

    def _read_btc_regime(self) -> tuple[bool | None, float]:
        """Returns (btc_bull | None, age_hours). None = stale or missing."""
        data = _load_json(_STEALTH_PATH)
        if not data:
            return None, 999.0
        age = _age_hours(data.get("updated_at", ""))
        if age > _STALE_HOURS:
            return None, age
        return bool(data.get("btc_bull_regime", True)), age

    def _read_alpha(self, symbol: str) -> tuple[float | None, float]:
        """Returns (alpha_score | None, watchlist_age_hours)."""
        data = _load_json(_ALPHA_PATH)
        if not data:
            return None, 999.0
        age = _age_hours(data.get("updated_at", ""))
        for entry in data.get("top_symbols", []):
            if entry.get("symbol") == symbol:
                return float(entry["alpha"]), age
        return None, age
