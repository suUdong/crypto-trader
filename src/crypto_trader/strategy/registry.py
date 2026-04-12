"""Strategy plugin registry.

New strategies self-register via @register decorator at import time.
This replaces the need to edit wallet.py / config.py for each new strategy.

Usage in a strategy file::

    from crypto_trader.strategy.registry import register

    @register("my_strategy", override_fields=frozenset({"param_a", "param_b"}))
    def _factory(strategy_config, regime_config, params):
        return MyStrategy(strategy_config, param_a=float(params.get("param_a", 1.0)))
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Signal


class StrategyProtocol(Protocol):
    def evaluate(
        self, candles: list[Candle], *args: Any, **kwargs: Any
    ) -> Signal: ...


StrategyFactory = Callable[
    [StrategyConfig, RegimeConfig, Mapping[str, Any]],
    StrategyProtocol,
]


@dataclass(frozen=True)
class StrategySpec:
    name: str
    factory: StrategyFactory
    override_fields: frozenset[str]


_REGISTRY: dict[str, StrategySpec] = {}


def register(
    name: str,
    *,
    override_fields: frozenset[str] = frozenset(),
) -> Callable[[StrategyFactory], StrategyFactory]:
    """Decorator that registers a strategy factory function."""

    def _decorator(factory: StrategyFactory) -> StrategyFactory:
        if name in _REGISTRY:
            raise ValueError(f"strategy '{name}' already registered")
        _REGISTRY[name] = StrategySpec(
            name=name, factory=factory, override_fields=override_fields,
        )
        return factory

    return _decorator


def get_spec(name: str) -> StrategySpec | None:
    """Return the StrategySpec for *name*, or None if not registered."""
    return _REGISTRY.get(name)


def known_names() -> frozenset[str]:
    """Return all registered strategy names."""
    return frozenset(_REGISTRY)


def known_override_fields(name: str) -> frozenset[str]:
    """Return override fields for *name*, or empty frozenset if unknown."""
    spec = _REGISTRY.get(name)
    return spec.override_fields if spec is not None else frozenset()
