"""Adapts trading parameters based on macro regime."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from crypto_trader.macro.client import MacroSnapshot

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MacroAdjustment:
    """Position sizing and risk adjustments derived from macro regime."""

    position_size_multiplier: float
    risk_per_trade_multiplier: float
    reasons: list[str]


# Base multipliers per overall regime
_REGIME_MULTIPLIERS: dict[str, float] = {
    "expansionary": 1.5,
    "neutral": 1.0,
    "contractionary": 0.5,
}


class MacroRegimeAdapter:
    """Translates macro regime into position sizing adjustments.

    Logic:
    - Expansionary regime  -> 1.5x base position size (aggressive)
    - Neutral regime       -> 1.0x base position size
    - Contractionary regime -> 0.5x base position size (defensive)

    Additional crypto-specific adjustments:
    - Fear & Greed >= 80 (extreme greed) -> reduce by 0.1 (overheated)
    - Fear & Greed <= 20 (extreme fear)  -> reduce by 0.1 (capitulation risk)
    - Kimchi premium > 5%  -> reduce by 0.15 (overheated local market)
    - BTC dominance > 65%  -> reduce by 0.1 for alt-heavy portfolios (risk-off)

    Multiplier is clamped to [0.25, 2.0] range.
    """

    MIN_MULTIPLIER = 0.25
    MAX_MULTIPLIER = 2.0

    # Per-strategy regime weight multipliers
    # Market regime (from RegimeDetector) -> strategy type -> extra multiplier
    STRATEGY_REGIME_WEIGHTS: dict[str, dict[str, float]] = {
        "bull": {
            "momentum": 1.4,
            "momentum_pullback": 1.3,
            "bollinger_rsi": 0.9,
            "mean_reversion": 0.7,
            "obi": 1.0,
            "vpin": 1.0,
            "composite": 1.2,
            "kimchi_premium": 0.8,
            "volatility_breakout": 1.3,
            "consensus": 1.2,
        },
        "sideways": {
            "momentum": 0.6,
            "momentum_pullback": 1.0,
            "bollinger_rsi": 1.4,
            "mean_reversion": 1.5,
            "obi": 1.3,
            "vpin": 1.2,
            "composite": 0.8,
            "kimchi_premium": 0.7,
            "volatility_breakout": 0.5,
            "consensus": 0.8,
        },
        "bear": {
            "momentum": 0.4,
            "momentum_pullback": 0.7,
            "bollinger_rsi": 0.8,
            "mean_reversion": 1.0,
            "obi": 0.8,
            "vpin": 1.1,
            "composite": 0.6,
            "kimchi_premium": 0.5,
            "volatility_breakout": 0.3,
            "consensus": 0.5,
        },
    }

    def strategy_weight(self, strategy_type: str, market_regime: str) -> float:
        """Get regime-aware weight multiplier for a specific strategy type."""
        regime_weights = self.STRATEGY_REGIME_WEIGHTS.get(market_regime, {})
        return regime_weights.get(strategy_type, 1.0)

    def compute(self, snapshot: MacroSnapshot | None) -> MacroAdjustment:
        """Compute position sizing adjustment from macro snapshot."""
        if snapshot is None:
            return MacroAdjustment(
                position_size_multiplier=1.0,
                risk_per_trade_multiplier=1.0,
                reasons=["no macro data available, using defaults"],
            )

        reasons: list[str] = []
        regime = snapshot.overall_regime
        base = _REGIME_MULTIPLIERS.get(regime, 1.0)
        reasons.append(
            f"macro regime={regime} (confidence={snapshot.overall_confidence:.0%}) -> base={base}x"
        )

        adjustment = 0.0

        # Crypto-specific signal adjustments
        if snapshot.fear_greed_index is not None:
            if snapshot.fear_greed_index >= 80:
                adjustment -= 0.1
                reasons.append(f"extreme greed (F&G={snapshot.fear_greed_index}) -> -0.1")
            elif snapshot.fear_greed_index <= 20:
                adjustment -= 0.1
                reasons.append(f"extreme fear (F&G={snapshot.fear_greed_index}) -> -0.1")

        if snapshot.kimchi_premium is not None and snapshot.kimchi_premium > 5.0:
            adjustment -= 0.15
            reasons.append(f"high kimchi premium ({snapshot.kimchi_premium:.1f}%) -> -0.15")

        if snapshot.btc_dominance is not None and snapshot.btc_dominance > 65.0:
            adjustment -= 0.1
            reasons.append(f"high BTC dominance ({snapshot.btc_dominance:.1f}%) -> -0.1 (risk-off)")

        final = max(self.MIN_MULTIPLIER, min(self.MAX_MULTIPLIER, base + adjustment))

        if adjustment != 0.0:
            reasons.append(f"final multiplier={final:.2f}")

        # Risk multiplier follows same direction but dampened
        risk_mult = max(self.MIN_MULTIPLIER, min(self.MAX_MULTIPLIER, 0.5 + final * 0.5))

        return MacroAdjustment(
            position_size_multiplier=final,
            risk_per_trade_multiplier=risk_mult,
            reasons=reasons,
        )
