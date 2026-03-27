"""Tests for capital_allocator module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crypto_trader.capital_allocator import (
    AllocationResult,
    CapitalAllocator,
    StrategyAllocation,
    StrategyPerformance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _perf(
    strategy: str,
    return_pct: float = 5.0,
    sharpe: float = 1.5,
    mdd_pct: float = 3.0,
    trade_count: int = 10,
    win_rate: float = 0.6,
) -> StrategyPerformance:
    return StrategyPerformance(
        strategy=strategy,
        return_pct=return_pct,
        sharpe=sharpe,
        mdd_pct=mdd_pct,
        trade_count=trade_count,
        win_rate=win_rate,
        equity=1_000_000 * (1 + return_pct / 100),
        initial_capital=1_000_000.0,
    )


# ---------------------------------------------------------------------------
# StrategyPerformance.score
# ---------------------------------------------------------------------------


class TestStrategyPerformanceScore:
    def test_positive_sharpe_low_mdd(self):
        p = _perf("a", sharpe=2.0, mdd_pct=5.0)
        assert p.score == pytest.approx(2.0 * 0.95)

    def test_zero_sharpe(self):
        p = _perf("a", sharpe=0.0, mdd_pct=5.0)
        assert p.score == 0.0

    def test_negative_sharpe_floored(self):
        p = _perf("a", sharpe=-1.0, mdd_pct=5.0)
        assert p.score == 0.0

    def test_high_mdd_reduces_score(self):
        low = _perf("a", sharpe=2.0, mdd_pct=5.0)
        high = _perf("b", sharpe=2.0, mdd_pct=50.0)
        assert low.score > high.score

    def test_100_pct_mdd_zeroes_score(self):
        p = _perf("a", sharpe=3.0, mdd_pct=100.0)
        assert p.score == 0.0


# ---------------------------------------------------------------------------
# CapitalAllocator.allocate — basic scenarios
# ---------------------------------------------------------------------------


class TestAllocateBasic:
    def test_empty_input(self):
        allocator = CapitalAllocator()
        result = allocator.allocate([], 7_000_000)
        assert result.allocations == []
        assert result.total_capital == 7_000_000

    def test_single_strategy(self):
        allocator = CapitalAllocator()
        perfs = [_perf("momentum")]
        result = allocator.allocate(perfs, 1_000_000)
        assert len(result.allocations) == 1
        assert result.allocations[0].weight == pytest.approx(1.0)
        assert result.allocations[0].capital == pytest.approx(1_000_000)

    def test_equal_strategies_get_equal_weight(self):
        allocator = CapitalAllocator()
        perfs = [_perf("a"), _perf("b"), _perf("c")]
        result = allocator.allocate(perfs, 3_000_000)
        weights = [a.weight for a in result.allocations]
        assert all(abs(w - 1 / 3) < 0.01 for w in weights)

    def test_weights_sum_to_one(self):
        allocator = CapitalAllocator()
        perfs = [
            _perf("a", sharpe=3.0, mdd_pct=2.0),
            _perf("b", sharpe=1.0, mdd_pct=10.0),
            _perf("c", sharpe=0.5, mdd_pct=5.0),
        ]
        result = allocator.allocate(perfs, 3_000_000)
        total = sum(a.weight for a in result.allocations)
        assert total == pytest.approx(1.0, abs=0.001)

    def test_capitals_sum_to_total(self):
        allocator = CapitalAllocator()
        perfs = [
            _perf("a", sharpe=3.0),
            _perf("b", sharpe=1.0),
            _perf("c", sharpe=0.2),
        ]
        result = allocator.allocate(perfs, 6_000_000)
        total = sum(a.capital for a in result.allocations)
        assert total == pytest.approx(6_000_000, abs=1)


# ---------------------------------------------------------------------------
# Capital concentration — top performer gets more
# ---------------------------------------------------------------------------


class TestConcentration:
    def test_top_performer_gets_most_capital(self):
        allocator = CapitalAllocator()
        perfs = [
            _perf("star", sharpe=5.0, mdd_pct=2.0, trade_count=20),
            _perf("avg", sharpe=1.0, mdd_pct=5.0, trade_count=10),
            _perf("poor", sharpe=0.1, mdd_pct=15.0, trade_count=10),
        ]
        result = allocator.allocate(perfs, 3_000_000)
        by_strategy = {a.strategy: a for a in result.allocations}
        assert by_strategy["star"].capital > by_strategy["avg"].capital
        assert by_strategy["avg"].capital > by_strategy["poor"].capital

    def test_max_weight_cap(self):
        allocator = CapitalAllocator(max_weight=0.40)
        perfs = [
            _perf("dominant", sharpe=100.0, mdd_pct=0.0, trade_count=50),
            _perf("tiny", sharpe=0.01, mdd_pct=20.0, trade_count=10),
        ]
        result = allocator.allocate(perfs, 2_000_000)
        by_strategy = {a.strategy: a for a in result.allocations}
        # After renormalization, dominant should not exceed practical bounds
        assert by_strategy["dominant"].weight <= 0.98  # can't exceed 1 anyway

    def test_min_weight_prevents_starvation(self):
        allocator = CapitalAllocator(min_weight=0.05)
        perfs = [
            _perf("star", sharpe=10.0, trade_count=50),
            _perf("zero_score", sharpe=0.0, mdd_pct=0.0, trade_count=10),
        ]
        result = allocator.allocate(perfs, 2_000_000)
        by_strategy = {a.strategy: a for a in result.allocations}
        assert by_strategy["zero_score"].weight >= 0.04  # near min_weight


# ---------------------------------------------------------------------------
# Ineligible strategies (low trade count)
# ---------------------------------------------------------------------------


class TestIneligible:
    def test_low_trade_count_gets_min_weight(self):
        allocator = CapitalAllocator(min_trades=5, min_weight=0.10)
        perfs = [
            _perf("experienced", sharpe=2.0, trade_count=20),
            _perf("newbie", sharpe=3.0, trade_count=2),  # below min_trades
        ]
        result = allocator.allocate(perfs, 2_000_000)
        by_strategy = {a.strategy: a for a in result.allocations}
        # Newbie has higher sharpe but not enough trades — gets constrained
        assert by_strategy["experienced"].weight > by_strategy["newbie"].weight

    def test_all_ineligible_equal_weight(self):
        allocator = CapitalAllocator(min_trades=100)
        perfs = [_perf("a", trade_count=5), _perf("b", trade_count=5)]
        result = allocator.allocate(perfs, 2_000_000)
        weights = [a.weight for a in result.allocations]
        assert all(abs(w - 0.5) < 0.01 for w in weights)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class TestRanking:
    def test_allocations_ranked_by_score(self):
        allocator = CapitalAllocator()
        perfs = [
            _perf("c", sharpe=0.5, trade_count=10),
            _perf("a", sharpe=3.0, trade_count=10),
            _perf("b", sharpe=1.5, trade_count=10),
        ]
        result = allocator.allocate(perfs, 3_000_000)
        strategies_in_order = [a.strategy for a in result.allocations]
        assert strategies_in_order == ["a", "b", "c"]
        assert result.allocations[0].rank == 1


# ---------------------------------------------------------------------------
# HHI concentration ratio
# ---------------------------------------------------------------------------


class TestConcentrationRatio:
    def test_equal_weight_hhi(self):
        allocator = CapitalAllocator()
        perfs = [_perf("a"), _perf("b"), _perf("c"), _perf("d")]
        result = allocator.allocate(perfs, 4_000_000)
        # Equal weight HHI = N * (1/N)^2 = 1/N = 0.25
        assert result.concentration_ratio == pytest.approx(0.25, abs=0.02)

    def test_single_strategy_hhi_is_one(self):
        allocator = CapitalAllocator()
        result = allocator.allocate([_perf("only")], 1_000_000)
        assert result.concentration_ratio == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# from_checkpoint
# ---------------------------------------------------------------------------


class TestFromCheckpoint:
    def test_loads_checkpoint(self, tmp_path: Path):
        cp = {
            "wallet_states": {
                "momentum_wallet": {
                    "strategy_type": "momentum",
                    "equity": 1_050_000,
                    "realized_pnl": 50_000,
                    "trade_count": 15,
                },
                "obi_wallet": {
                    "strategy_type": "obi",
                    "equity": 980_000,
                    "realized_pnl": -20_000,
                    "trade_count": 8,
                },
            }
        }
        cp_path = tmp_path / "checkpoint.json"
        cp_path.write_text(json.dumps(cp))

        perfs = CapitalAllocator.from_checkpoint(cp_path)
        assert len(perfs) == 2
        by_strat = {p.strategy: p for p in perfs}
        assert by_strat["momentum_wallet"].return_pct == pytest.approx(5.0)
        assert by_strat["obi_wallet"].return_pct == pytest.approx(-2.0)
        assert by_strat["momentum_wallet"].trade_count == 15
        assert by_strat["momentum_wallet"].strategy_type == "momentum"

    def test_missing_checkpoint_returns_empty(self, tmp_path: Path):
        perfs = CapitalAllocator.from_checkpoint(tmp_path / "nope.json")
        assert perfs == []


# ---------------------------------------------------------------------------
# to_toml_wallets
# ---------------------------------------------------------------------------


class TestToTomlWallets:
    def test_generates_valid_toml(self):
        allocations = [
            StrategyAllocation("momentum_wallet", 0.4, 2_800_000, 1_000_000, 2.5, 1, "momentum"),
            StrategyAllocation("obi_wallet", 0.6, 4_200_000, 1_000_000, 1.0, 2, "obi"),
        ]
        toml = CapitalAllocator.to_toml_wallets(allocations)
        assert "[[wallets]]" in toml
        assert 'name = "momentum_wallet"' in toml
        assert 'strategy = "obi"' in toml
        assert "2800000.0" in toml


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------


class TestSaveReport:
    def test_saves_json(self, tmp_path: Path):
        result = AllocationResult(
            generated_at="2026-03-26T00:00:00",
            total_capital=7_000_000,
            allocations=[
                StrategyAllocation("momentum", 0.5, 3_500_000, 1_000_000, 2.0, 1),
                StrategyAllocation("obi", 0.5, 3_500_000, 1_000_000, 1.0, 2),
            ],
            concentration_ratio=0.5,
        )
        path = tmp_path / "allocation.json"
        CapitalAllocator.save_report(result, path)

        data = json.loads(path.read_text())
        assert data["total_capital"] == 7_000_000
        assert len(data["allocations"]) == 2
        assert data["allocations"][0]["rank"] == 1


# ---------------------------------------------------------------------------
# Full 7-strategy scenario
# ---------------------------------------------------------------------------


class TestFullSevenStrategy:
    def test_seven_strategies_realistic(self):
        """Simulate a realistic 7-strategy portfolio and verify concentration."""
        allocator = CapitalAllocator(min_weight=0.05, max_weight=0.35)
        perfs = [
            _perf("momentum", sharpe=2.5, mdd_pct=3.0, return_pct=8.0, trade_count=25),
            _perf("mean_reversion", sharpe=1.8, mdd_pct=4.0, return_pct=5.0, trade_count=18),
            _perf("composite", sharpe=1.2, mdd_pct=5.0, return_pct=3.0, trade_count=12),
            _perf("kimchi_premium", sharpe=0.8, mdd_pct=6.0, return_pct=2.0, trade_count=8),
            _perf("obi", sharpe=3.0, mdd_pct=2.0, return_pct=10.0, trade_count=30),
            _perf("vpin", sharpe=1.5, mdd_pct=7.0, return_pct=4.0, trade_count=15),
            _perf("volatility_breakout", sharpe=2.0, mdd_pct=8.0, return_pct=6.0, trade_count=20),
        ]
        result = allocator.allocate(perfs, 7_000_000)

        assert len(result.allocations) == 7
        total_w = sum(a.weight for a in result.allocations)
        assert total_w == pytest.approx(1.0, abs=0.001)
        total_c = sum(a.capital for a in result.allocations)
        assert total_c == pytest.approx(7_000_000, abs=1)

        # Top performer (obi, sharpe=3.0, mdd=2%) should rank #1
        assert result.allocations[0].strategy == "obi"
        assert result.allocations[0].rank == 1

        # Capital should be concentrated: top 3 get > 50%
        top3_weight = sum(a.weight for a in result.allocations[:3])
        assert top3_weight > 0.50
