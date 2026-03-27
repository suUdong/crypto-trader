"""Strategy signal correlation — detect redundant wallets and find optimal combos."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import cast

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
    vectors = _build_signal_vectors(strategies, candles, names)

    # Compute pairwise correlation
    result: dict[tuple[str, str], float] = {}
    for i, name_a in enumerate(names):
        for j, name_b in enumerate(names):
            if i <= j:
                corr = _binary_correlation(vectors[name_a], vectors[name_b])
                result[(name_a, name_b)] = corr
    return result


def diversification_score(
    strategies: Sequence[object],
    candles: list[Candle],
    strategy_names: list[str] | None = None,
) -> float:
    """Compute portfolio diversification score (0.0 = fully correlated, 1.0 = fully independent).

    Based on average pairwise correlation of BUY signals.
    Lower avg correlation = better diversification.
    """
    names = strategy_names or [f"s{i}" for i in range(len(strategies))]
    if len(names) < 2:
        return 1.0

    corr_matrix = signal_correlation(strategies, candles, names)

    # Average off-diagonal correlations
    pair_corrs: list[float] = []
    for i, name_a in enumerate(names):
        for j, name_b in enumerate(names):
            if i < j:
                pair_corrs.append(corr_matrix.get((name_a, name_b), 0.0))

    if not pair_corrs:
        return 1.0

    avg_corr = sum(pair_corrs) / len(pair_corrs)
    # Score: 1 - avg_correlation (higher = more diversified)
    return max(0.0, min(1.0, 1.0 - avg_corr))


def optimal_combo(
    strategies: Sequence[object],
    candles: list[Candle],
    strategy_names: list[str] | None = None,
    min_size: int = 2,
    max_size: int | None = None,
) -> list[tuple[list[str], float]]:
    """Find strategy combinations ranked by diversification score.

    Returns list of (strategy_names, diversification_score) sorted best-first.
    Evaluates all combinations of size min_size to max_size.
    """
    names = strategy_names or [f"s{i}" for i in range(len(strategies))]
    if max_size is None:
        max_size = len(names)
    max_size = min(max_size, len(names))

    vectors = _build_signal_vectors(strategies, candles, names)

    combos: list[tuple[list[str], float]] = []
    for size in range(min_size, max_size + 1):
        for combo in itertools.combinations(range(len(names)), size):
            combo_names = [names[i] for i in combo]
            combo_vectors = {names[i]: vectors[names[i]] for i in combo}

            # Compute avg pairwise correlation for this combo
            pair_corrs: list[float] = []
            for ci, cj in itertools.combinations(combo, 2):
                corr = _binary_correlation(combo_vectors[names[ci]], combo_vectors[names[cj]])
                pair_corrs.append(corr)

            avg_corr = sum(pair_corrs) / len(pair_corrs) if pair_corrs else 0.0
            div_score = max(0.0, min(1.0, 1.0 - avg_corr))
            combos.append((combo_names, div_score))

    # Sort by diversification score descending (best diversification first)
    combos.sort(key=lambda x: x[1], reverse=True)
    return combos


def correlation_matrix_report(
    strategies: Sequence[object],
    candles: list[Candle],
    strategy_names: list[str] | None = None,
) -> str:
    """Generate a human-readable correlation matrix report.

    Returns markdown-formatted report with:
    - Pairwise correlation matrix
    - Diversification score
    - Optimal combination recommendations
    """
    names = strategy_names or [f"s{i}" for i in range(len(strategies))]
    corr_data = signal_correlation(strategies, candles, names)
    div_score = diversification_score(strategies, candles, names)

    lines: list[str] = []
    lines.append("# Strategy Correlation Report")
    lines.append("")

    # Signal activity summary
    vectors = _build_signal_vectors(strategies, candles, names)
    lines.append("## Signal Activity")
    lines.append("")
    total_bars = len(next(iter(vectors.values()))) if vectors else 0
    for name in names:
        buy_count = sum(vectors[name])
        rate = buy_count / total_bars * 100 if total_bars > 0 else 0
        lines.append(f"- **{name}**: {buy_count}/{total_bars} BUY signals ({rate:.1f}%)")
    lines.append("")

    # Correlation matrix
    lines.append("## Pairwise Correlation")
    lines.append("")
    # Header
    header = "| |" + "|".join(f" {n} " for n in names) + "|"
    sep = "|---|" + "|".join("---" for _ in names) + "|"
    lines.append(header)
    lines.append(sep)

    for name_a in names:
        row = f"| **{name_a}** |"
        for name_b in names:
            key = (name_a, name_b) if (name_a, name_b) in corr_data else (name_b, name_a)
            val = corr_data.get(key, 0.0)
            row += f" {val:.3f} |"
        lines.append(row)
    lines.append("")

    # Diversification score
    lines.append(f"## Diversification Score: **{div_score:.3f}**")
    lines.append("")
    if div_score >= 0.7:
        lines.append("Excellent diversification - strategies are largely independent.")
    elif div_score >= 0.4:
        lines.append("Good diversification - moderate strategy overlap.")
    else:
        lines.append(
            "Poor diversification - strategies are highly correlated. "
            "Consider replacing redundant ones."
        )
    lines.append("")

    # Optimal combos (top 5)
    if len(names) >= 3:
        combos = optimal_combo(strategies, candles, names, min_size=2, max_size=min(4, len(names)))
        lines.append("## Top Strategy Combinations")
        lines.append("")
        for combo_names, score in combos[:5]:
            lines.append(f"- {' + '.join(combo_names)}: div_score={score:.3f}")
        lines.append("")

    # High-correlation warnings
    lines.append("## Warnings")
    lines.append("")
    warnings_found = False
    for i, name_a in enumerate(names):
        for j, name_b in enumerate(names):
            if i < j:
                corr = corr_data.get((name_a, name_b), 0.0)
                if corr > 0.7:
                    lines.append(
                        f"- **HIGH CORRELATION** ({corr:.3f}): {name_a} <-> {name_b}"
                        " — consider dropping one"
                    )
                    warnings_found = True
    if not warnings_found:
        lines.append("No high-correlation pairs detected.")
    lines.append("")

    return "\n".join(lines)


def average_pairwise_correlation(
    strategy_names: Sequence[str],
    corr_matrix: dict[tuple[str, str], float],
) -> float:
    pair_corrs: list[float] = []
    names = list(strategy_names)
    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            key = (name_a, name_b) if (name_a, name_b) in corr_matrix else (name_b, name_a)
            pair_corrs.append(corr_matrix.get(key, 0.0))
    if not pair_corrs:
        return 0.0
    return sum(pair_corrs) / len(pair_corrs)


def diversification_multipliers(
    strategy_names: Sequence[str],
    corr_matrix: dict[tuple[str, str], float],
) -> dict[str, float]:
    """Translate average positive overlap into a portfolio penalty multiplier."""
    names = list(strategy_names)
    multipliers: dict[str, float] = {}
    for name in names:
        peer_corrs = []
        for peer in names:
            if peer == name:
                continue
            key = (name, peer) if (name, peer) in corr_matrix else (peer, name)
            peer_corrs.append(max(0.0, corr_matrix.get(key, 0.0)))
        avg_peer_corr = sum(peer_corrs) / len(peer_corrs) if peer_corrs else 0.0
        multipliers[name] = max(0.35, 1.0 - avg_peer_corr)
    return multipliers


def rank_portfolios(
    corr_matrix: dict[tuple[str, str], float],
    performance_by_strategy: dict[str, dict[str, float]],
    *,
    min_size: int = 2,
    max_size: int | None = None,
) -> list[dict[str, float | list[str]]]:
    """Rank combos by diversification and positive performance."""
    strategy_names = sorted(performance_by_strategy)
    if max_size is None:
        max_size = len(strategy_names)
    max_size = min(max_size, len(strategy_names))
    ranked: list[dict[str, float | list[str]]] = []

    for size in range(min_size, max_size + 1):
        for combo in itertools.combinations(strategy_names, size):
            avg_corr = average_pairwise_correlation(combo, corr_matrix)
            diversification = max(0.0, min(1.0, 1.0 - avg_corr))
            avg_sharpe = sum(
                max(0.0, performance_by_strategy[name].get("sharpe", 0.0)) for name in combo
            ) / size
            avg_return = (
                sum(performance_by_strategy[name].get("return_pct", 0.0) for name in combo) / size
            )
            avg_profit_factor = (
                sum(
                    performance_by_strategy[name].get("profit_factor", 0.0) for name in combo
                )
                / size
            )
            effective_profit_factor = (
                3.0 if avg_profit_factor == float("inf") else avg_profit_factor
            )
            portfolio_score = (
                diversification * (1.0 + avg_sharpe) * max(0.25, effective_profit_factor)
            )
            ranked.append(
                {
                    "strategies": list(combo),
                    "avg_correlation": avg_corr,
                    "diversification_score": diversification,
                    "avg_sharpe": avg_sharpe,
                    "avg_return_pct": avg_return,
                    "avg_profit_factor": avg_profit_factor,
                    "portfolio_score": portfolio_score,
                }
            )

    ranked.sort(
        key=lambda row: (
            cast(float, row["portfolio_score"]),
            cast(float, row["diversification_score"]),
            cast(float, row["avg_sharpe"]),
        ),
        reverse=True,
    )
    return ranked


def _build_signal_vectors(
    strategies: Sequence[object],
    candles: list[Candle],
    names: list[str],
) -> dict[str, list[int]]:
    """Generate binary signal vectors (1=BUY, 0=not BUY) for each strategy."""
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
    return vectors


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
