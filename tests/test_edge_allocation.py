"""Tests for edge-weighted capital allocation."""

from crypto_trader.capital_allocator import CapitalAllocator, StrategyPerformance


def _perf(name: str, sharpe: float, trades: int = 10) -> StrategyPerformance:
    return StrategyPerformance(
        strategy=name,
        return_pct=1.0,
        sharpe=sharpe,
        mdd_pct=5.0,
        trade_count=trades,
        win_rate=0.5,
        equity=1_000_000.0,
        initial_capital=1_000_000.0,
    )


class TestEdgeWeightedAllocation:
    def test_no_edge_scores_unchanged(self) -> None:
        """Without edge_scores, allocation is identical to base."""
        allocator = CapitalAllocator(min_weight=0.05, max_weight=0.40)
        perfs = [_perf("A", 2.0), _perf("B", 1.0)]
        base = allocator.allocate(perfs, 1_000_000.0)
        with_none = allocator.allocate(perfs, 1_000_000.0, edge_scores=None)
        for a, b in zip(base.allocations, with_none.allocations, strict=True):
            assert abs(a.weight - b.weight) < 1e-9

    def test_edge_scores_shift_allocation(self) -> None:
        """Higher edge score for B should shift capital toward B."""
        allocator = CapitalAllocator(min_weight=0.05, max_weight=0.60)
        perfs = [_perf("A", 2.0), _perf("B", 1.0)]

        base = allocator.allocate(perfs, 1_000_000.0)
        boosted = allocator.allocate(perfs, 1_000_000.0, edge_scores={"B": 3.0})

        # Find B's weight in each
        base_b = next(a for a in base.allocations if a.strategy == "B")
        boost_b = next(a for a in boosted.allocations if a.strategy == "B")
        assert boost_b.weight > base_b.weight

    def test_edge_score_one_is_neutral(self) -> None:
        """Edge score of 1.0 should not change allocation."""
        allocator = CapitalAllocator()
        perfs = [_perf("A", 2.0), _perf("B", 1.0)]
        base = allocator.allocate(perfs, 1_000_000.0)
        neutral = allocator.allocate(perfs, 1_000_000.0, edge_scores={"A": 1.0, "B": 1.0})
        for a, b in zip(base.allocations, neutral.allocations, strict=True):
            assert abs(a.weight - b.weight) < 1e-9

    def test_edge_score_zero_gets_minimum(self) -> None:
        """Edge score of 0 should push strategy to minimum weight."""
        allocator = CapitalAllocator(min_weight=0.05, max_weight=0.60)
        perfs = [_perf("A", 2.0), _perf("B", 2.0)]
        result = allocator.allocate(perfs, 1_000_000.0, edge_scores={"B": 0.0})
        b_alloc = next(a for a in result.allocations if a.strategy == "B")
        # B should get minimum weight since its score is zeroed
        assert b_alloc.weight <= 0.10  # close to min_weight

    def test_missing_edge_key_defaults_to_one(self) -> None:
        """Strategies not in edge_scores dict get multiplier 1.0."""
        allocator = CapitalAllocator()
        perfs = [_perf("A", 2.0), _perf("B", 1.0)]
        partial = allocator.allocate(perfs, 1_000_000.0, edge_scores={"A": 2.0})
        # A should get boosted, B stays the same
        a_alloc = next(a for a in partial.allocations if a.strategy == "A")
        b_alloc = next(a for a in partial.allocations if a.strategy == "B")
        assert a_alloc.weight > b_alloc.weight
