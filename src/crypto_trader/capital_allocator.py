"""Dynamic capital allocation based on strategy performance.

Ranks strategies by a composite score (Sharpe-weighted, MDD-penalized)
and reallocates capital from underperformers to top performers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class StrategyPerformance:
    strategy: str
    return_pct: float
    sharpe: float
    mdd_pct: float
    trade_count: int
    win_rate: float
    equity: float
    initial_capital: float
    composite_score_override: float | None = None
    strategy_type: str | None = None

    @property
    def score(self) -> float:
        """Composite score: uses override from backtest-all if available,
        otherwise falls back to Sharpe * (1 - MDD_fraction), floored at 0."""
        if self.composite_score_override is not None:
            return max(0.0, self.composite_score_override)
        mdd_frac = min(self.mdd_pct / 100.0, 1.0)
        raw = self.sharpe * (1.0 - mdd_frac)
        return max(0.0, raw)


@dataclass(slots=True)
class AllocationResult:
    generated_at: str
    total_capital: float
    allocations: list[StrategyAllocation]
    concentration_ratio: float  # HHI-like: how concentrated the portfolio is


@dataclass(slots=True, frozen=True)
class CapitalTransfer:
    source: str
    target: str
    amount: float


@dataclass(slots=True)
class StrategyAllocation:
    strategy: str
    weight: float
    capital: float
    previous_capital: float
    score: float
    rank: int
    strategy_type: str | None = None


class CapitalAllocator:
    """Allocates capital across strategies based on performance scores.

    Parameters
    ----------
    min_weight : float
        Minimum allocation per active strategy (prevents total starvation).
    max_weight : float
        Maximum allocation per strategy (prevents over-concentration).
    min_trades : int
        Minimum trade count to be eligible for performance-based allocation.
        Strategies below this get equal-weight allocation.
    """

    def __init__(
        self,
        min_weight: float = 0.05,
        max_weight: float = 0.40,
        min_trades: int = 3,
    ) -> None:
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.min_trades = min_trades

    def allocate(
        self,
        performances: list[StrategyPerformance],
        total_capital: float,
        edge_scores: dict[str, float] | None = None,
    ) -> AllocationResult:
        if not performances:
            return AllocationResult(
                generated_at=datetime.now(UTC).isoformat(),
                total_capital=total_capital,
                allocations=[],
                concentration_ratio=0.0,
            )

        n = len(performances)

        # Separate strategies with enough trades from those without
        eligible = [p for p in performances if p.trade_count >= self.min_trades]
        ineligible = [p for p in performances if p.trade_count < self.min_trades]

        if not eligible:
            # All strategies lack data. Prefer config initial_capital ratios
            # (operator's intended ROI-weighted allocation) over equal weight.
            # Fall back to edge scores, then equal weight.
            config_capitals = {p.strategy: p.initial_capital for p in performances}
            total_config = sum(config_capitals.values())
            if total_config > 0 and any(
                abs(c - total_config / n) > 1.0 for c in config_capitals.values()
            ):
                # Config has intentional non-equal allocation — respect it
                weights = {
                    strategy: capital / total_config
                    for strategy, capital in config_capitals.items()
                }
            else:
                edge = {
                    p.strategy: max(0.0, float((edge_scores or {}).get(p.strategy, 1.0)))
                    for p in performances
                }
                total_edge = sum(edge.values())
                if total_edge > 0:
                    weights = {
                        strategy: score / total_edge for strategy, score in edge.items()
                    }
                else:
                    equal_w = 1.0 / n
                    weights = {p.strategy: equal_w for p in performances}
            allocations = [
                StrategyAllocation(
                    strategy=p.strategy,
                    strategy_type=p.strategy_type,
                    weight=weights[p.strategy],
                    capital=total_capital * weights[p.strategy],
                    previous_capital=p.initial_capital,
                    score=weights[p.strategy],
                    rank=i + 1,
                )
                for i, p in enumerate(performances)
            ]
            return AllocationResult(
                generated_at=datetime.now(UTC).isoformat(),
                total_capital=total_capital,
                allocations=allocations,
                concentration_ratio=sum(w**2 for w in weights.values()),
            )

        # Reserve minimum allocation for ineligible strategies
        ineligible_reserve = len(ineligible) * self.min_weight
        eligible_pool = 1.0 - ineligible_reserve

        # Score-proportional weights for eligible strategies
        # Apply edge multipliers when provided (signal quality, hit rate, etc.)
        _edge = edge_scores or {}
        scores = {
            p.strategy: p.score * _edge.get(p.strategy, 1.0)
            for p in eligible
        }
        total_score = sum(scores.values())

        if total_score > 0:
            raw_weights = {s: (sc / total_score) * eligible_pool for s, sc in scores.items()}
        else:
            equal_w = eligible_pool / len(eligible)
            raw_weights = {p.strategy: equal_w for p in eligible}

        # Apply min/max bounds and renormalize
        weights = self._bound_and_normalize(raw_weights, eligible_pool)

        # Add ineligible strategies at min_weight
        for p in ineligible:
            weights[p.strategy] = self.min_weight

        # Final normalization
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {s: w / total_w for s, w in weights.items()}

        # Build ranked allocations
        ranked = sorted(performances, key=lambda p: scores.get(p.strategy, 0.0), reverse=True)
        allocations = []
        for rank, p in enumerate(ranked, 1):
            w = weights.get(p.strategy, self.min_weight)
            allocations.append(
                StrategyAllocation(
                    strategy=p.strategy,
                    strategy_type=p.strategy_type,
                    weight=w,
                    capital=round(total_capital * w, 0),
                    previous_capital=p.initial_capital,
                    score=scores.get(p.strategy, 0.0),
                    rank=rank,
                )
            )

        # HHI concentration ratio
        hhi = sum(a.weight**2 for a in allocations)

        return AllocationResult(
            generated_at=datetime.now(UTC).isoformat(),
            total_capital=total_capital,
            allocations=allocations,
            concentration_ratio=round(hhi, 4),
        )

    def _bound_and_normalize(
        self,
        raw_weights: dict[str, float],
        pool: float,
    ) -> dict[str, float]:
        """Apply min/max bounds and redistribute excess to unclamped strategies."""
        weights = {s: w / pool if pool > 0 else 0.0 for s, w in raw_weights.items()}

        for _ in range(10):
            clamped: set[str] = set()
            excess = 0.0
            for s, w in weights.items():
                if w > self.max_weight:
                    excess += w - self.max_weight
                    weights[s] = self.max_weight
                    clamped.add(s)
                elif w < self.min_weight:
                    excess -= self.min_weight - w
                    weights[s] = self.min_weight
                    clamped.add(s)

            if not clamped or abs(excess) < 1e-9:
                break

            free = {s for s in weights if s not in clamped}
            if not free:
                break
            free_total = sum(weights[s] for s in free)
            if free_total > 0:
                for s in free:
                    weights[s] += excess * (weights[s] / free_total)

        # Scale back to pool
        return {s: w * pool for s, w in weights.items()}

    @staticmethod
    def from_backtest_all(backtest_all_path: str | Path) -> list[StrategyPerformance]:
        """Load strategy performances from a backtest-all JSON export.

        Uses composite_score, kelly_fraction, and EV from the richer backtest-all output.
        """
        bp = Path(backtest_all_path)
        if not bp.exists():
            return []

        data = json.loads(bp.read_text(encoding="utf-8"))
        results = data.get("results", [])

        performances = []
        for r in results:
            performances.append(
                StrategyPerformance(
                    strategy=r["strategy"],
                    strategy_type=r["strategy"],
                    return_pct=r.get("return_pct", 0.0),
                    sharpe=r.get("sharpe", 0.0),
                    mdd_pct=r.get("max_drawdown_pct", 0.0),
                    trade_count=r.get("trade_count", 0),
                    win_rate=r.get("win_rate_pct", 0.0) / 100.0,
                    equity=0.0,
                    initial_capital=0.0,
                    composite_score_override=r.get("composite_score"),
                )
            )
        return performances

    @staticmethod
    def from_checkpoint(checkpoint_path: str | Path) -> list[StrategyPerformance]:
        """Load strategy performances from a runtime checkpoint."""
        cp = Path(checkpoint_path)
        if not cp.exists():
            return []

        data = json.loads(cp.read_text(encoding="utf-8"))
        wallet_states = data.get("wallet_states", {})

        performances = []
        for wallet_name, state in wallet_states.items():
            equity = state.get("equity", 1_000_000.0)
            initial = 1_000_000.0
            realized = state.get("realized_pnl", 0.0)
            trade_count = state.get("trade_count", 0)
            return_pct = (equity / initial - 1.0) * 100.0
            mdd = max(0.0, -return_pct) if return_pct < 0 else 0.0

            # Approximate Sharpe from total return
            daily_ret = return_pct / max(1, 7)  # assume ~7 day window
            daily_vol = max(abs(daily_ret) * 2, 0.1)
            sharpe = (daily_ret * 365) / (daily_vol * math.sqrt(365)) if daily_vol > 0 else 0.0

            win_rate = 1.0 if realized > 0 and trade_count > 0 else 0.0

            performances.append(
                StrategyPerformance(
                    strategy=wallet_name,
                    strategy_type=state.get("strategy_type", wallet_name),
                    return_pct=return_pct,
                    sharpe=sharpe,
                    mdd_pct=mdd,
                    trade_count=trade_count,
                    win_rate=win_rate,
                    equity=equity,
                    initial_capital=initial,
                )
            )

        return performances

    @staticmethod
    def to_toml_wallets(allocations: list[StrategyAllocation]) -> str:
        """Generate TOML wallet sections from allocation result."""
        lines = []
        for a in allocations:
            wallet_name = a.strategy if a.strategy.endswith("_wallet") else f"{a.strategy}_wallet"
            strategy_type = a.strategy_type or a.strategy.removesuffix("_wallet")
            lines.extend(
                [
                    "[[wallets]]",
                    f'name = "{wallet_name}"',
                    f'strategy = "{strategy_type}"',
                    f"initial_capital = {a.capital:.1f}",
                    "",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def save_report(result: AllocationResult, path: str | Path) -> None:
        """Save allocation report as JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "generated_at": result.generated_at,
            "total_capital": result.total_capital,
            "concentration_ratio": result.concentration_ratio,
            "allocations": [
                {
                    "rank": a.rank,
                    "strategy": a.strategy,
                    "strategy_type": a.strategy_type,
                    "weight": round(a.weight, 4),
                    "capital": a.capital,
                    "previous_capital": a.previous_capital,
                    "score": round(a.score, 4),
                }
                for a in result.allocations
            ],
        }
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def plan_transfers(
        current_capital: dict[str, float],
        target_capital: dict[str, float],
        *,
        locked_strategies: set[str] | None = None,
        min_transfer: float = 50_000.0,
    ) -> list[CapitalTransfer]:
        locked = locked_strategies or set()
        transferable = (set(current_capital) & set(target_capital)) - locked
        donors = {
            strategy: max(0.0, current_capital[strategy] - target_capital[strategy])
            for strategy in transferable
        }
        receivers = {
            strategy: max(0.0, target_capital[strategy] - current_capital[strategy])
            for strategy in transferable
        }
        donor_order = sorted(donors, key=lambda name: (-donors[name], name))
        receiver_order = sorted(receivers, key=lambda name: (-receivers[name], name))

        transfers: list[CapitalTransfer] = []
        for donor in donor_order:
            remaining_surplus = donors[donor]
            if remaining_surplus < min_transfer:
                continue
            for receiver in receiver_order:
                remaining_need = receivers[receiver]
                if donor == receiver or remaining_need < min_transfer:
                    continue
                amount = min(remaining_surplus, remaining_need)
                if amount < min_transfer:
                    continue
                rounded_amount = float(round(amount, 0))
                transfers.append(
                    CapitalTransfer(
                        source=donor,
                        target=receiver,
                        amount=rounded_amount,
                    )
                )
                donors[donor] -= rounded_amount
                receivers[receiver] -= rounded_amount
                remaining_surplus = donors[donor]
                if remaining_surplus < min_transfer:
                    break
        return transfers
