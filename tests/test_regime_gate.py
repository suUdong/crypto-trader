"""Tests for regime-aware wallet active_regimes gate."""
from __future__ import annotations

from crypto_trader.config import _strategy_override_names


def test_active_regimes_allowed_for_all_strategies() -> None:
    """active_regimes must pass config validation for every strategy type."""
    strategy_types = [
        "momentum",
        "vpin",
        "accumulation_breakout",
        "volume_spike",
        "stealth_3gate",
        "mean_reversion",
        "funding_rate",
        "consensus",
        "kimchi_premium",
        "truth_seeker",
        "truth_seeker_v2",
        "etf_flow_admission",
    ]
    for strategy in strategy_types:
        allowed = _strategy_override_names(strategy)
        assert "active_regimes" in allowed, (
            f"active_regimes not allowed for strategy '{strategy}'"
        )
