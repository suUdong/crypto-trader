"""Strategy signal correlation — detect redundant wallets."""
from __future__ import annotations

from collections.abc import Sequence

from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.evaluator import evaluate_strategy


def signal_correlation(
    strategies: Sequence[object],
    candles: list[Candle],
    strategy_names: list[str] | None = None,
) -> dict[tuple[str, str], float]:
    """Compute pairwise correlation of BUY signals across strategies.

    Returns dict mapping (name_a, name_b) -> correlation coefficient.
    Correlation of 1.0 means strategies always agree, 0.0 means independent.
    """
    names = strategy_names or [f"s{i}" for i in range(len(strategies))]

    # Generate binary signal vectors (1=BUY, 0=not BUY)
    vectors: dict[str, list[int]] = {}
    for name, strategy in zip(names, strategies, strict=False):
        signals: list[int] = []
        for i in range(30, len(candles)):  # need warmup
            window = candles[: i + 1]
            try:
                sig = evaluate_strategy(strategy, window, None, symbol="")
                signals.append(1 if sig.action is SignalAction.BUY else 0)
            except Exception:
                signals.append(0)
        vectors[name] = signals

    # Compute pairwise correlation
    result: dict[tuple[str, str], float] = {}
    for i, name_a in enumerate(names):
        for j, name_b in enumerate(names):
            if i <= j:
                corr = _binary_correlation(vectors[name_a], vectors[name_b])
                result[(name_a, name_b)] = corr
    return result


def _binary_correlation(a: list[int], b: list[int]) -> float:
    """Phi coefficient for two binary vectors."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0

    n11 = sum(1 for i in range(n) if a[i] == 1 and b[i] == 1)
    n10 = sum(1 for i in range(n) if a[i] == 1 and b[i] == 0)
    n01 = sum(1 for i in range(n) if a[i] == 0 and b[i] == 1)
    n00 = sum(1 for i in range(n) if a[i] == 0 and b[i] == 0)

    denom = ((n11 + n10) * (n11 + n01) * (n00 + n10) * (n00 + n01)) ** 0.5
    if denom == 0:
        return 0.0
    return float((n11 * n00 - n10 * n01) / denom)
