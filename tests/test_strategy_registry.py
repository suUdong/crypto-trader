"""Tests for strategy plugin registry."""
from __future__ import annotations

import pytest


def test_register_and_retrieve() -> None:
    """A decorated factory is retrievable by name."""
    from crypto_trader.strategy.registry import StrategySpec, _REGISTRY, register

    name = "__test_register_and_retrieve__"

    @register(name, override_fields=frozenset({"alpha"}))
    def _factory(strategy_config, regime_config, params):  # type: ignore[no-untyped-def]
        return object()

    spec = _REGISTRY.get(name)
    assert spec is not None
    assert spec.name == name
    assert "alpha" in spec.override_fields
    del _REGISTRY[name]


def test_duplicate_registration_raises() -> None:
    """Registering the same name twice raises ValueError."""
    from crypto_trader.strategy.registry import _REGISTRY, register

    name = "__test_duplicate__"

    @register(name)
    def _factory1(sc, rc, p):  # type: ignore[no-untyped-def]
        return object()

    with pytest.raises(ValueError, match="already registered"):

        @register(name)
        def _factory2(sc, rc, p):  # type: ignore[no-untyped-def]
            return object()

    del _REGISTRY[name]


def test_known_names_includes_registered() -> None:
    """known_names() returns all registered strategy names."""
    from crypto_trader.strategy.registry import _REGISTRY, known_names, register

    name = "__test_known_names__"

    @register(name)
    def _factory(sc, rc, p):  # type: ignore[no-untyped-def]
        return object()

    assert name in known_names()
    del _REGISTRY[name]


def test_known_override_fields() -> None:
    """known_override_fields() returns fields for a registered strategy."""
    from crypto_trader.strategy.registry import (
        _REGISTRY,
        known_override_fields,
        register,
    )

    name = "__test_override_fields__"

    @register(name, override_fields=frozenset({"x", "y"}))
    def _factory(sc, rc, p):  # type: ignore[no-untyped-def]
        return object()

    assert known_override_fields(name) == frozenset({"x", "y"})
    assert known_override_fields("nonexistent") == frozenset()
    del _REGISTRY[name]


def test_get_spec_returns_none_for_unknown() -> None:
    """get_spec() returns None for unregistered names."""
    from crypto_trader.strategy.registry import get_spec

    assert get_spec("__never_registered__") is None


def test_create_strategy_via_registry() -> None:
    """create_strategy finds registry-based strategies."""
    from crypto_trader.config import RegimeConfig, StrategyConfig
    from crypto_trader.wallet import create_strategy

    for name in ("volume_weighted_momentum", "pdh_pdl_sweep_reclaim"):
        s = create_strategy(name, StrategyConfig(), RegimeConfig())
        assert hasattr(s, "evaluate")
        assert hasattr(s, "set_btc_candles")
