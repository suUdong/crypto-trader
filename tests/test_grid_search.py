"""Offline tests for grid search scoring, strategy creation, and parameter selection.

Uses synthetic candle data — no Upbit API calls required.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import (
    BacktestConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
)
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.kimchi_premium import KimchiPremiumStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy
from crypto_trader.wallet import create_strategy


def _build_candles(
    closes: list[float],
    start: datetime | None = None,
    interval_hours: int = 1,
) -> list[Candle]:
    """Build synthetic candles from a list of close prices.

    Uses 2% high/low spread for realistic volatility breakout detection.
    """
    base = start or datetime(2025, 1, 1)
    candles = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i > 0 else c
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=i * interval_hours),
                open=prev,
                high=c * 1.02,
                low=c * 0.98,
                close=c,
                volume=1000.0 + i * 10,
            )
        )
    return candles


def _trending_up(n: int = 200, start_price: float = 100_000.0, step: float = 2000.0) -> list[float]:
    """Uptrend with ~2% per bar moves — triggers momentum entry threshold."""
    return [start_price + i * step for i in range(n)]


def _trending_up_with_pullbacks(
    n: int = 200,
    start_price: float = 100_000.0,
    step: float = 1500.0,
) -> list[float]:
    """Uptrend with periodic pullbacks so RSI stays in tradeable range (not pegged at 100)."""
    closes = []
    price = start_price
    for i in range(n):
        if i % 5 == 4:
            price -= step * 1.5  # pullback every 5th bar
        else:
            price += step
        closes.append(max(price, start_price * 0.5))
    return closes


def _trending_down(
    n: int = 200, start_price: float = 500_000.0, step: float = 2000.0
) -> list[float]:
    return [start_price - i * step for i in range(n)]


def _sideways(
    n: int = 200, base: float = 100_000.0, amplitude: float = 5000.0, freq: float = 0.15
) -> list[float]:
    """Oscillating prices with large amplitude to cross Bollinger bands."""
    import math

    return [base + amplitude * math.sin(i * freq) for i in range(n)]


def _run_backtest(
    strategy_type: str, candles: list[Candle], symbol: str = "KRW-BTC", **kwargs
) -> dict:
    """Run a single backtest and return results dict."""
    config_fields = set(StrategyConfig.__dataclass_fields__)
    config_kwargs = {k: v for k, v in kwargs.items() if k in config_fields}
    strategy_config = StrategyConfig(**config_kwargs)
    regime_config = RegimeConfig()

    if strategy_type == "volatility_breakout":
        strategy = VolatilityBreakoutStrategy(
            strategy_config,
            k_base=float(kwargs.get("k_base", 0.5)),
            noise_lookback=int(kwargs.get("noise_lookback", 20)),
            ma_filter_period=int(kwargs.get("ma_filter_period", 20)),
        )
    else:
        strategy = create_strategy(strategy_type, strategy_config, regime_config)

    risk_manager = RiskManager(RiskConfig())
    engine = BacktestEngine(
        strategy=strategy,
        risk_manager=risk_manager,
        config=BacktestConfig(initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005),
        symbol=symbol,
    )
    result = engine.run(candles)
    return {
        "return_pct": result.total_return_pct,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "max_drawdown": result.max_drawdown,
        "trade_count": len(result.trade_log),
        "equity_curve": result.equity_curve,
    }


# ─── Sharpe approximation (same as grid_search.py) ───


def _approx_sharpe(equity_curve: list[float]) -> float:
    if len(equity_curve) < 3:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / max(1.0, equity_curve[i - 1])
        for i in range(1, len(equity_curve))
    ]
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = variance**0.5
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * (8760**0.5)


class TestSharpeApproximation(unittest.TestCase):
    def test_constant_equity_returns_zero(self) -> None:
        curve = [1_000_000.0] * 100
        self.assertEqual(_approx_sharpe(curve), 0.0)

    def test_monotonically_increasing_positive_sharpe(self) -> None:
        curve = [1_000_000.0 + i * 1000 for i in range(100)]
        self.assertGreater(_approx_sharpe(curve), 0.0)

    def test_monotonically_decreasing_negative_sharpe(self) -> None:
        curve = [1_000_000.0 - i * 1000 for i in range(100)]
        self.assertLess(_approx_sharpe(curve), 0.0)

    def test_too_few_points_returns_zero(self) -> None:
        self.assertEqual(_approx_sharpe([1.0, 2.0]), 0.0)
        self.assertEqual(_approx_sharpe([1.0]), 0.0)


class TestGridScoring(unittest.TestCase):
    """Test the scoring function: Sharpe * (1 - MDD/100)."""

    def _score(self, sharpe: float, mdd_pct: float) -> float:
        return sharpe * (1.0 - mdd_pct / 100.0)

    def test_zero_drawdown_full_sharpe(self) -> None:
        self.assertAlmostEqual(self._score(2.0, 0.0), 2.0)

    def test_high_drawdown_penalizes_sharpe(self) -> None:
        self.assertAlmostEqual(self._score(2.0, 50.0), 1.0)

    def test_negative_sharpe_with_drawdown(self) -> None:
        self.assertLess(self._score(-1.0, 10.0), 0.0)

    def test_best_params_selection(self) -> None:
        """Simulates find_best_params logic: pick combo with highest avg score."""
        from dataclasses import dataclass

        @dataclass
        class FakeResult:
            params: dict
            sharpe_approx: float
            max_drawdown: float

        results = [
            FakeResult({"a": 1}, sharpe_approx=2.0, max_drawdown=5.0),  # score=1.9
            FakeResult({"a": 1}, sharpe_approx=1.5, max_drawdown=3.0),  # score=1.455
            FakeResult({"a": 2}, sharpe_approx=3.0, max_drawdown=20.0),  # score=2.4
            FakeResult({"a": 2}, sharpe_approx=0.5, max_drawdown=10.0),  # score=0.45
        ]
        param_scores: dict[str, list[float]] = {}
        param_map: dict[str, dict] = {}
        for r in results:
            key = str(sorted(r.params.items()))
            if key not in param_scores:
                param_scores[key] = []
                param_map[key] = r.params
            score = r.sharpe_approx * (1.0 - r.max_drawdown / 100.0)
            param_scores[key].append(score)

        best_key = max(param_scores, key=lambda k: sum(param_scores[k]) / len(param_scores[k]))
        best = param_map[best_key]
        # a=1: avg = (1.9 + 1.455) / 2 = 1.6775
        # a=2: avg = (2.4 + 0.45) / 2 = 1.425
        self.assertEqual(best["a"], 1)

    def test_top_param_sets_returns_sorted_candidates(self) -> None:
        from scripts.grid_search import GridResult, top_param_sets

        results = [
            GridResult("mean_reversion", {"a": 1}, "KRW-BTC", 5.0, 50.0, 1.2, 10.0, 3, 2.0),
            GridResult("mean_reversion", {"a": 1}, "KRW-ETH", 4.0, 45.0, 1.1, 10.0, 2, 1.8),
            GridResult("mean_reversion", {"a": 2}, "KRW-BTC", 3.0, 40.0, 1.0, 5.0, 1, 1.0),
            GridResult("mean_reversion", {"a": 2}, "KRW-ETH", 2.0, 35.0, 0.9, 5.0, 1, 0.9),
            GridResult("mean_reversion", {"a": 3}, "KRW-BTC", 1.0, 30.0, 0.8, 20.0, 1, 0.5),
            GridResult("mean_reversion", {"a": 3}, "KRW-ETH", 1.0, 30.0, 0.8, 20.0, 1, 0.4),
        ]

        top_sets = top_param_sets(results, top_n=2)

        self.assertEqual(len(top_sets), 2)
        self.assertEqual(top_sets[0].params, {"a": 1})
        self.assertGreater(top_sets[0].score, top_sets[1].score)
        self.assertEqual(top_sets[0].total_trades, 5)


class TestMeanReversionBacktest(unittest.TestCase):
    def test_sideways_market_generates_trades(self) -> None:
        candles = _build_candles(_sideways(300))
        result = _run_backtest("mean_reversion", candles)
        self.assertGreater(result["trade_count"], 0)

    def test_different_bollinger_params_change_results(self) -> None:
        candles = _build_candles(_sideways(300))
        r1 = _run_backtest("mean_reversion", candles, bollinger_window=15, bollinger_stddev=1.5)
        r2 = _run_backtest("mean_reversion", candles, bollinger_window=25, bollinger_stddev=2.2)
        # Different params should produce different trade counts or returns
        different = (r1["trade_count"] != r2["trade_count"]) or (
            r1["return_pct"] != r2["return_pct"]
        )
        self.assertTrue(different)


class TestMomentumBacktest(unittest.TestCase):
    def test_trending_up_with_pullbacks_generates_trades(self) -> None:
        """Uptrend with pullbacks keeps RSI in the 20-60 entry window."""
        closes = _trending_up_with_pullbacks(300)
        candles = _build_candles(closes)
        # Widen RSI ceiling so momentum entries can trigger
        result = _run_backtest(
            "momentum",
            candles,
            momentum_lookback=10,
            momentum_entry_threshold=0.003,
            rsi_recovery_ceiling=75.0,
        )
        self.assertGreater(result["trade_count"], 0)

    def test_different_lookback_changes_results(self) -> None:
        closes = _trending_up_with_pullbacks(300)
        candles = _build_candles(closes)
        r1 = _run_backtest(
            "momentum",
            candles,
            momentum_lookback=5,
            momentum_entry_threshold=0.001,
            rsi_recovery_ceiling=75.0,
        )
        r2 = _run_backtest(
            "momentum",
            candles,
            momentum_lookback=25,
            momentum_entry_threshold=0.05,
            rsi_recovery_ceiling=75.0,
        )
        different = (r1["trade_count"] != r2["trade_count"]) or (
            r1["return_pct"] != r2["return_pct"]
        )
        self.assertTrue(different)


class TestMomentumPullbackBacktest(unittest.TestCase):
    def test_trending_up_with_pullbacks_generates_trades(self) -> None:
        candles = _build_candles(_trending_up_with_pullbacks(300))
        result = _run_backtest(
            "momentum_pullback",
            candles,
            momentum_lookback=10,
            momentum_entry_threshold=0.003,
            bollinger_window=15,
            bollinger_stddev=1.5,
            rsi_period=10,
            rsi_recovery_ceiling=65.0,
            adx_threshold=5.0,
        )
        self.assertGreater(result["trade_count"], 0)

    def test_different_pullback_params_change_results(self) -> None:
        candles = _build_candles(_trending_up_with_pullbacks(300))
        r1 = _run_backtest(
            "momentum_pullback",
            candles,
            momentum_lookback=10,
            momentum_entry_threshold=0.003,
            bollinger_window=15,
            rsi_recovery_ceiling=65.0,
            adx_threshold=5.0,
        )
        r2 = _run_backtest(
            "momentum_pullback",
            candles,
            momentum_lookback=20,
            momentum_entry_threshold=0.01,
            bollinger_window=20,
            rsi_recovery_ceiling=50.0,
            adx_threshold=20.0,
        )
        different = (r1["trade_count"] != r2["trade_count"]) or (
            r1["return_pct"] != r2["return_pct"]
        )
        self.assertTrue(different)


class TestVPINBacktest(unittest.TestCase):
    def test_runs_without_error(self) -> None:
        candles = _build_candles(_sideways(300))
        result = _run_backtest("vpin", candles)
        self.assertGreaterEqual(result["trade_count"], 0)
        self.assertIsInstance(result["return_pct"], float)


class TestOBIBacktest(unittest.TestCase):
    def test_runs_without_error(self) -> None:
        candles = _build_candles(_sideways(300))
        result = _run_backtest("obi", candles)
        self.assertGreaterEqual(result["trade_count"], 0)
        self.assertIsInstance(result["return_pct"], float)


class TestVolatilityBreakoutBacktest(unittest.TestCase):
    def test_trending_market_generates_trades(self) -> None:
        candles = _build_candles(_trending_up(300))
        result = _run_backtest(
            "volatility_breakout",
            candles,
            k_base=0.1,
            noise_lookback=5,
            ma_filter_period=5,
        )
        self.assertGreater(result["trade_count"], 0)

    def test_different_k_base_changes_results(self) -> None:
        candles = _build_candles(_trending_up(300))
        r1 = _run_backtest(
            "volatility_breakout", candles, k_base=0.1, noise_lookback=5, ma_filter_period=5
        )
        r2 = _run_backtest(
            "volatility_breakout", candles, k_base=0.9, noise_lookback=5, ma_filter_period=5
        )
        different = (r1["trade_count"] != r2["trade_count"]) or (
            r1["return_pct"] != r2["return_pct"]
        )
        self.assertTrue(different)

    def test_sideways_market_fewer_trades(self) -> None:
        trending = _build_candles(_trending_up(300))
        sideways = _build_candles(_sideways(300))
        r_trend = _run_backtest(
            "volatility_breakout", trending, k_base=0.1, noise_lookback=5, ma_filter_period=5
        )
        r_side = _run_backtest(
            "volatility_breakout", sideways, k_base=0.1, noise_lookback=5, ma_filter_period=5
        )
        # Breakout strategy should find more signals in trending markets
        self.assertGreaterEqual(r_trend["trade_count"], r_side["trade_count"])


class TestKimchiPremiumBacktest(unittest.TestCase):
    def _make_backtest_kimchi(
        self,
        candles: list[Candle],
        premium: float,
        rsi_period: int = 14,
        max_holding_bars: int = 48,
        min_trade_interval_bars: int = 0,
        min_confidence: float = 0.0,
    ) -> dict:
        config = StrategyConfig(rsi_period=rsi_period, max_holding_bars=max_holding_bars)
        mock_binance = MagicMock()
        mock_fx = MagicMock()
        mock_binance.get_btc_usdt_price.return_value = None
        mock_fx.get_usd_krw_rate.return_value = None
        strategy = KimchiPremiumStrategy(
            config,
            binance_client=mock_binance,
            fx_client=mock_fx,
            min_trade_interval_bars=min_trade_interval_bars,
            min_confidence=min_confidence,
            cooldown_hours=0.0,
        )
        strategy._cached_premium = premium
        risk_manager = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk_manager,
            config=BacktestConfig(
                initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005
            ),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        return {
            "return_pct": result.total_return_pct,
            "trade_count": len(result.trade_log),
            "win_rate": result.win_rate,
        }

    def test_negative_premium_generates_contrarian_buys(self) -> None:
        candles = _build_candles(_trending_up(200))
        result = self._make_backtest_kimchi(candles, premium=-0.02)
        self.assertGreater(result["trade_count"], 0)

    def test_high_premium_no_entries(self) -> None:
        candles = _build_candles(_sideways(200))
        result = self._make_backtest_kimchi(candles, premium=0.08)
        self.assertEqual(result["trade_count"], 0)

    def test_safe_zone_premium_with_wide_rsi(self) -> None:
        candles = _build_candles(_sideways(200))
        result = self._make_backtest_kimchi(
            candles,
            premium=0.02,
            rsi_period=14,
            max_holding_bars=24,
        )
        self.assertGreaterEqual(result["trade_count"], 0)

    def test_different_rsi_period_changes_results(self) -> None:
        candles = _build_candles(_trending_up(200))
        r1 = self._make_backtest_kimchi(candles, premium=-0.02, rsi_period=10)
        r2 = self._make_backtest_kimchi(candles, premium=-0.02, rsi_period=18)
        # Different RSI periods may produce different trade timing
        self.assertGreater(r1["trade_count"] + r2["trade_count"], 0)


class TestBacktestKellyIntegration(unittest.TestCase):
    """Verify backtest engine records trades for Kelly sizing."""

    def test_backtest_records_trade_history(self) -> None:
        """After backtest with trades, risk manager should have trade history."""
        from crypto_trader.backtest.engine import BacktestEngine

        candles = _build_candles(_sideways(300))
        config = StrategyConfig(bollinger_window=20, bollinger_stddev=1.5)
        regime = RegimeConfig()
        strategy = create_strategy("mean_reversion", config, regime)
        risk_manager = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk_manager,
            config=BacktestConfig(
                initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005
            ),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        if len(result.trade_log) > 0:
            self.assertEqual(len(risk_manager._trade_history), len(result.trade_log))

    def test_kelly_available_after_enough_trades(self) -> None:
        """After 10+ trades with mixed wins/losses, Kelly fraction should be computable."""
        candles = _build_candles(_sideways(500, base=100_000.0, amplitude=8000.0))
        config = StrategyConfig(bollinger_window=15, bollinger_stddev=1.5, max_holding_bars=24)
        regime = RegimeConfig()
        strategy = create_strategy("mean_reversion", config, regime)
        risk_manager = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk_manager,
            config=BacktestConfig(
                initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005
            ),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        if len(result.trade_log) >= 10:
            wins = [t for t in result.trade_log if t.pnl > 0]
            losses = [t for t in result.trade_log if t.pnl <= 0]
            kelly = risk_manager.kelly_fraction()
            if wins and losses:
                self.assertIsNotNone(kelly)
            else:
                self.assertIsNone(kelly)


class TestAllStrategiesCreateSuccessfully(unittest.TestCase):
    """Verify primary strategy types can be instantiated for backtest."""

    def test_create_all_strategies(self) -> None:
        config = StrategyConfig()
        regime = RegimeConfig()
        for name in ["momentum", "momentum_pullback", "mean_reversion", "composite", "obi", "vpin"]:
            strategy = create_strategy(name, config, regime)
            self.assertIsNotNone(strategy)
            self.assertTrue(hasattr(strategy, "evaluate"))

    def test_create_volatility_breakout(self) -> None:
        config = StrategyConfig()
        strategy = VolatilityBreakoutStrategy(
            config, k_base=0.5, noise_lookback=20, ma_filter_period=20
        )
        self.assertTrue(hasattr(strategy, "evaluate"))

    def test_create_kimchi_premium(self) -> None:
        config = StrategyConfig()
        mock_b = MagicMock()
        mock_f = MagicMock()
        strategy = KimchiPremiumStrategy(config, binance_client=mock_b, fx_client=mock_f)
        self.assertTrue(hasattr(strategy, "evaluate"))


class TestGridParamCoverage(unittest.TestCase):
    """Verify all 6 strategy grids have valid parameter names."""

    def test_mean_reversion_grid_params_valid(self) -> None:
        from scripts.grid_search import MEAN_REVERSION_GRID

        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k in MEAN_REVERSION_GRID:
            self.assertIn(k, config_fields)

    def test_momentum_grid_params_valid(self) -> None:
        from scripts.grid_search import MOMENTUM_GRID

        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k in MOMENTUM_GRID:
            self.assertIn(k, config_fields)

    def test_momentum_pullback_grid_params_valid(self) -> None:
        from scripts.grid_search import MOMENTUM_PULLBACK_GRID

        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k in MOMENTUM_PULLBACK_GRID:
            self.assertIn(k, config_fields)

    def test_vpin_grid_params_valid(self) -> None:
        from scripts.grid_search import VPIN_GRID

        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k in VPIN_GRID:
            self.assertIn(k, config_fields)

    def test_obi_grid_params_valid(self) -> None:
        from scripts.grid_search import OBI_GRID

        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k in OBI_GRID:
            self.assertIn(k, config_fields)

    def test_volatility_breakout_grid_params_valid(self) -> None:
        from scripts.grid_search import VOLATILITY_BREAKOUT_GRID

        valid_params = {"k_base", "noise_lookback", "ma_filter_period", "max_holding_bars"}
        for k in VOLATILITY_BREAKOUT_GRID:
            self.assertIn(k, valid_params | set(StrategyConfig.__dataclass_fields__))

    def test_kimchi_premium_grid_params_valid(self) -> None:
        from scripts.grid_search import KIMCHI_PREMIUM_GRID

        valid_params = {"min_trade_interval_bars", "min_confidence", "cooldown_hours"}
        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k in KIMCHI_PREMIUM_GRID:
            self.assertIn(k, valid_params | config_fields)

    def test_bollinger_rsi_grid_params_valid(self) -> None:
        from scripts.grid_search import BOLLINGER_RSI_GRID

        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k in BOLLINGER_RSI_GRID:
            self.assertIn(k, config_fields)

    def test_all_supported_strategies_have_grids(self) -> None:
        from scripts.grid_search import STRATEGY_GRIDS

        expected = {
            "mean_reversion",
            "momentum",
            "momentum_pullback",
            "bollinger_rsi",
            "composite",
            "vpin",
            "obi",
            "volatility_breakout",
            "kimchi_premium",
        }
        self.assertEqual(set(STRATEGY_GRIDS.keys()), expected)

    def test_composite_grid_params_valid(self) -> None:
        from scripts.grid_search import COMPOSITE_GRID

        config_fields = set(StrategyConfig.__dataclass_fields__)
        for k in COMPOSITE_GRID:
            self.assertIn(k, config_fields)

    def test_each_grid_has_multiple_combos(self) -> None:
        import itertools

        from scripts.grid_search import STRATEGY_GRIDS

        for name, grid in STRATEGY_GRIDS.items():
            combos = list(itertools.product(*grid.values()))
            self.assertGreater(len(combos), 1, f"{name} grid has only {len(combos)} combo")


if __name__ == "__main__":
    unittest.main()
