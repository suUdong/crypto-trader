"""Tests for strategy performance analysis report generator."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crypto_trader.models import BacktestResult, TradeRecord
from crypto_trader.operator.strategy_perf_report import (
    StrategyPerformanceAnalyzer,
    _compute_risk_adjusted_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 1, tzinfo=UTC)


def _trade(pnl: float = 100.0) -> TradeRecord:
    return TradeRecord(
        symbol="KRW-BTC",
        entry_time=_T0,
        exit_time=_T1,
        entry_price=50_000.0,
        exit_price=50_000.0 + pnl,
        quantity=1.0,
        pnl=pnl,
        pnl_pct=pnl / 50_000.0 * 100,
        exit_reason="take_profit" if pnl > 0 else "stop_loss",
        wallet="test_wallet",
    )


def _backtest_result(
    *,
    total_return_pct: float = 10.0,
    sharpe: float = 1.5,
    sortino: float = 2.0,
    calmar: float = 1.8,
    max_drawdown: float = 0.05,
    profit_factor: float = 2.0,
    win_rate: float = 0.6,
    trades: list[TradeRecord] | None = None,
    regime_breakdown: dict[str, dict[str, float]] | None = None,
) -> BacktestResult:
    if trades is None:
        trades = [_trade(100), _trade(-50), _trade(200)]
    return BacktestResult(
        initial_capital=1_000_000.0,
        final_equity=1_000_000 * (1 + total_return_pct / 100),
        total_return_pct=total_return_pct,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        trade_log=trades,
        equity_curve=[1_000_000.0, 1_050_000.0],
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        regime_breakdown=regime_breakdown or {},
    )


# ---------------------------------------------------------------------------
# _compute_risk_adjusted_score
# ---------------------------------------------------------------------------


class TestComputeRiskAdjustedScore:
    def test_positive_metrics(self):
        score = _compute_risk_adjusted_score(
            sharpe=2.0, sortino=3.0, profit_factor=3.0, win_rate=0.7,
        )
        # 0.4*2.0 + 0.3*min(3/3,1) + 0.2*min(3/3,1) + 0.1*(0.7-0.5)
        # = 0.8 + 0.3 + 0.2 + 0.02 = 1.32
        assert score == pytest.approx(1.32)

    def test_zero_metrics(self):
        score = _compute_risk_adjusted_score(
            sharpe=0.0, sortino=0.0, profit_factor=0.0, win_rate=0.5,
        )
        assert score == pytest.approx(0.0)

    def test_high_sortino_capped(self):
        score = _compute_risk_adjusted_score(
            sharpe=1.0, sortino=10.0, profit_factor=1.0, win_rate=0.5,
        )
        # sortino_norm capped at 1.0
        # 0.4*1.0 + 0.3*1.0 + 0.2*(1/3) + 0.1*0.0 = 0.4+0.3+0.0667+0 = 0.7667
        assert score == pytest.approx(0.4 + 0.3 + 1.0 / 3 * 0.2, abs=0.001)


# ---------------------------------------------------------------------------
# StrategyPerformanceAnalyzer.generate_from_backtest_results
# ---------------------------------------------------------------------------


class TestGenerateFromBacktestResults:
    def test_empty_input(self):
        analyzer = StrategyPerformanceAnalyzer()
        result = analyzer.generate_from_backtest_results([])
        assert result == []

    def test_single_strategy(self):
        analyzer = StrategyPerformanceAnalyzer()
        br = _backtest_result(sharpe=2.0, sortino=2.5, profit_factor=1.8, win_rate=0.65)
        metrics = analyzer.generate_from_backtest_results([("momentum", br)])
        assert len(metrics) == 1
        assert metrics[0].strategy == "momentum"
        assert metrics[0].sharpe == 2.0
        assert metrics[0].sortino == 2.5
        assert metrics[0].win_rate == 0.65
        assert metrics[0].risk_adjusted_score > 0.0

    def test_multi_strategy_sorted_by_score(self):
        analyzer = StrategyPerformanceAnalyzer()
        strong = _backtest_result(sharpe=3.0, sortino=4.0, profit_factor=2.5, win_rate=0.7)
        weak = _backtest_result(sharpe=0.5, sortino=0.3, profit_factor=0.8, win_rate=0.4)
        metrics = analyzer.generate_from_backtest_results([
            ("weak_strat", weak),
            ("strong_strat", strong),
        ])
        assert metrics[0].strategy == "strong_strat"
        assert metrics[1].strategy == "weak_strat"
        assert metrics[0].risk_adjusted_score > metrics[1].risk_adjusted_score

    def test_trade_count_from_trade_log(self):
        analyzer = StrategyPerformanceAnalyzer()
        trades = [_trade(100), _trade(-50), _trade(200), _trade(150)]
        br = _backtest_result(trades=trades)
        metrics = analyzer.generate_from_backtest_results([("test", br)])
        assert metrics[0].trade_count == 4
        assert metrics[0].avg_trade_pnl == pytest.approx(100.0)

    def test_max_drawdown_converted_to_pct(self):
        analyzer = StrategyPerformanceAnalyzer()
        br = _backtest_result(max_drawdown=0.123)
        metrics = analyzer.generate_from_backtest_results([("test", br)])
        assert metrics[0].max_drawdown_pct == pytest.approx(12.3)

    def test_regime_breakdown_populated(self):
        analyzer = StrategyPerformanceAnalyzer()
        regime = {
            "BULL": {"win_rate": 0.7, "avg_pnl": 200.0, "trade_count": 10.0},
            "BEAR": {"win_rate": 0.3, "avg_pnl": -100.0, "trade_count": 5.0},
        }
        br = _backtest_result(regime_breakdown=regime)
        metrics = analyzer.generate_from_backtest_results([("test", br)])
        assert "BULL" in metrics[0].regime_breakdown
        assert metrics[0].regime_breakdown["BULL"]["win_rate"] == 0.7
        assert "BEAR" in metrics[0].regime_breakdown


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------


class TestToMarkdown:
    def test_empty_produces_no_strategies(self):
        analyzer = StrategyPerformanceAnalyzer()
        md = analyzer.to_markdown([])
        assert "No strategies to rank" in md

    def test_contains_summary_table(self):
        analyzer = StrategyPerformanceAnalyzer()
        br = _backtest_result()
        metrics = analyzer.generate_from_backtest_results([("momentum", br)])
        md = analyzer.to_markdown(metrics)
        assert "## Summary" in md
        assert "| momentum" in md
        assert "## Rankings" in md

    def test_regime_section_present_when_data_exists(self):
        analyzer = StrategyPerformanceAnalyzer()
        regime = {"BULL": {"win_rate": 0.7, "avg_pnl": 200.0, "trade_count": 10.0}}
        br = _backtest_result(regime_breakdown=regime)
        metrics = analyzer.generate_from_backtest_results([("test", br)])
        md = analyzer.to_markdown(metrics)
        assert "## Regime Breakdown" in md
        assert "BULL" in md


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


class TestToJson:
    def test_valid_json_output(self):
        analyzer = StrategyPerformanceAnalyzer()
        br = _backtest_result()
        metrics = analyzer.generate_from_backtest_results([("momentum", br)])
        raw = analyzer.to_json(metrics)
        data = json.loads(raw)
        assert data["strategy_count"] == 1
        assert data["metrics"][0]["strategy"] == "momentum"
        assert "generated_at" in data

    def test_multi_strategy_json(self):
        analyzer = StrategyPerformanceAnalyzer()
        results = [
            ("a", _backtest_result(sharpe=2.0)),
            ("b", _backtest_result(sharpe=1.0)),
        ]
        metrics = analyzer.generate_from_backtest_results(results)
        data = json.loads(analyzer.to_json(metrics))
        assert data["strategy_count"] == 2
        assert data["metrics"][0]["strategy"] == "a"


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


class TestSave:
    def test_writes_files(self, tmp_path: Path):
        analyzer = StrategyPerformanceAnalyzer()
        analyzer.save("# Report", '{"test": 1}', tmp_path / "reports")
        output_dir = tmp_path / "reports"
        md_files = list(output_dir.glob("*.md"))
        json_files = list(output_dir.glob("*.json"))
        assert len(md_files) == 1
        assert len(json_files) == 1
        assert md_files[0].read_text() == "# Report"
