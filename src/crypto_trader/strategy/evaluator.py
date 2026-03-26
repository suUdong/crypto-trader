from __future__ import annotations

from inspect import Parameter, signature
from typing import Any, Protocol, cast

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


def evaluate_strategy(
    strategy: object,
    candles: list[Candle],
    position: Position | None = None,
    *,
    symbol: str = "",
) -> Signal:
    evaluate = cast(Any, strategy).evaluate
    if _supports_symbol_kwarg(evaluate):
        return cast(_SymbolAwareStrategyProtocol, strategy).evaluate(
            candles,
            position,
            symbol=symbol,
        )
    return cast(_LegacyStrategyProtocol, strategy).evaluate(candles, position)


def _supports_symbol_kwarg(method: Any) -> bool:
    try:
        params = signature(method).parameters
    except (TypeError, ValueError):
        return False
    return "symbol" in params or any(
        param.kind is Parameter.VAR_KEYWORD for param in params.values()
    )
