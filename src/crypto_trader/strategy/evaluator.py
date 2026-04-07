from __future__ import annotations

from inspect import Parameter, signature
from typing import Any, Protocol, cast

from crypto_trader.macro.client import MacroSnapshot
from crypto_trader.models import Candle, Position, Signal


class _LegacyStrategyProtocol(Protocol):
    def evaluate(self, candles: list[Candle], position: Position | None = None) -> Signal: ...


class _SymbolAwareStrategyProtocol(Protocol):
    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal: ...


class _MacroAwareStrategyProtocol(Protocol):
    def evaluate(
        self,
        candles: list[Candle],
        macro: MacroSnapshot | None = None,
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal: ...


def evaluate_strategy(
    strategy: object,
    candles: list[Candle],
    position: Position | None = None,
    *,
    symbol: str = "",
    macro: MacroSnapshot | None = None,
) -> Signal:
    evaluate = cast(Any, strategy).evaluate
    params = _get_parameters(evaluate)

    kwargs: dict[str, Any] = {}
    if "symbol" in params or _has_var_kwargs(params):
        kwargs["symbol"] = symbol
    if "macro" in params or _has_var_kwargs(params):
        kwargs["macro"] = macro

    if kwargs:
        return evaluate(candles, position=position, **kwargs)

    return evaluate(candles, position=position)


def _get_parameters(method: Any) -> dict[str, Parameter]:
    try:
        return dict(signature(method).parameters)
    except (TypeError, ValueError):
        return {}


def _has_var_kwargs(params: dict[str, Parameter]) -> bool:
    return any(param.kind is Parameter.VAR_KEYWORD for param in params.values())
