"""Tests for kill switch integration with MultiSymbolRuntime."""
from __future__ import annotations

import unittest

from crypto_trader.risk.kill_switch import KillSwitch, KillSwitchConfig


class TestKillSwitchPortfolioDrawdown(unittest.TestCase):
    def test_triggers_on_drawdown(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_portfolio_drawdown_pct=0.05))
        # Set peak at 1M
        ks.check(1_000_000, 1_000_000, 0.0)
        self.assertFalse(ks.is_triggered)
        # Drop to 940K = 6% drawdown > 5% limit
        state = ks.check(940_000, 1_000_000, -60_000)
        self.assertTrue(state.triggered)
        self.assertIn("drawdown", state.trigger_reason.lower())

    def test_no_trigger_within_limit(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_portfolio_drawdown_pct=0.10, max_daily_loss_pct=0.10))
        ks.check(1_000_000, 1_000_000, 0.0)
        state = ks.check(950_000, 1_000_000, -50_000)
        self.assertFalse(state.triggered)


class TestKillSwitchDailyLoss(unittest.TestCase):
    def test_triggers_on_daily_loss(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_daily_loss_pct=0.03, max_portfolio_drawdown_pct=1.0))
        ks.check(1_000_000, 1_000_000, 0.0)
        # 4% daily loss > 3% limit
        state = ks.check(960_000, 1_000_000, -40_000)
        self.assertTrue(state.triggered)
        self.assertIn("daily loss", state.trigger_reason.lower())


class TestKillSwitchConsecutiveLosses(unittest.TestCase):
    def test_triggers_on_consecutive_losses(self) -> None:
        ks = KillSwitch(KillSwitchConfig(
            max_consecutive_losses=3,
            max_portfolio_drawdown_pct=1.0,
            max_daily_loss_pct=1.0,
        ))
        ks.check(1_000_000, 1_000_000, 0.0, trade_won=False)
        ks.check(1_000_000, 1_000_000, 0.0, trade_won=False)
        state = ks.check(1_000_000, 1_000_000, 0.0, trade_won=False)
        self.assertTrue(state.triggered)
        self.assertIn("consecutive", state.trigger_reason.lower())

    def test_win_resets_counter(self) -> None:
        ks = KillSwitch(KillSwitchConfig(
            max_consecutive_losses=3,
            max_portfolio_drawdown_pct=1.0,
            max_daily_loss_pct=1.0,
        ))
        ks.check(1_000_000, 1_000_000, 0.0, trade_won=False)
        ks.check(1_000_000, 1_000_000, 0.0, trade_won=False)
        ks.check(1_000_000, 1_000_000, 0.0, trade_won=True)  # reset
        state = ks.check(1_000_000, 1_000_000, 0.0, trade_won=False)
        self.assertFalse(state.triggered)
        self.assertEqual(state.consecutive_losses, 1)


class TestKillSwitchReset(unittest.TestCase):
    def test_manual_reset_clears_trigger(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_portfolio_drawdown_pct=0.01))
        ks.check(1_000_000, 1_000_000, 0.0)
        ks.check(900_000, 1_000_000, -100_000)
        self.assertTrue(ks.is_triggered)
        ks.reset()
        self.assertFalse(ks.is_triggered)
        self.assertEqual(ks.state.trigger_reason, "")


class TestKillSwitchSaveLoad(unittest.TestCase):
    def test_save_and_load_state(self) -> None:
        import tempfile
        ks1 = KillSwitch(KillSwitchConfig(max_consecutive_losses=2, max_portfolio_drawdown_pct=1.0, max_daily_loss_pct=1.0))
        ks1.check(1_000_000, 1_000_000, 0.0, trade_won=False)
        ks1.check(1_000_000, 1_000_000, 0.0, trade_won=False)
        self.assertTrue(ks1.is_triggered)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        ks1.save(path)

        ks2 = KillSwitch()
        ks2.load(path)
        self.assertTrue(ks2.is_triggered)
        self.assertEqual(ks2.state.consecutive_losses, 2)

    def test_load_nonexistent_file_is_safe(self) -> None:
        ks = KillSwitch()
        ks.load("/tmp/nonexistent_kill_switch_test.json")
        self.assertFalse(ks.is_triggered)


class TestKillSwitchStaysTriggered(unittest.TestCase):
    def test_once_triggered_stays_triggered(self) -> None:
        ks = KillSwitch(KillSwitchConfig(max_portfolio_drawdown_pct=0.05))
        ks.check(1_000_000, 1_000_000, 0.0)
        ks.check(940_000, 1_000_000, -60_000)
        self.assertTrue(ks.is_triggered)
        # Even if equity recovers, stays triggered
        state = ks.check(1_100_000, 1_000_000, 100_000)
        self.assertTrue(state.triggered)


class TestRiskGridOptimization(unittest.TestCase):
    """Test that risk parameter combinations are valid."""

    def test_take_profit_must_exceed_stop_loss(self) -> None:
        import itertools

        from scripts.auto_tune import RISK_GRID
        risk_combos = list(itertools.product(*RISK_GRID.values()))
        valid_count = 0
        for combo in risk_combos:
            params = dict(zip(RISK_GRID.keys(), combo))
            if params["take_profit_pct"] > params["stop_loss_pct"]:
                valid_count += 1
        # At least some combos should be valid
        self.assertGreater(valid_count, 0)
        # Not all should be valid (some TP <= SL)
        self.assertLess(valid_count, len(risk_combos))

    def test_risk_grid_has_expected_params(self) -> None:
        from scripts.auto_tune import RISK_GRID
        self.assertIn("stop_loss_pct", RISK_GRID)
        self.assertIn("take_profit_pct", RISK_GRID)
        self.assertIn("risk_per_trade_pct", RISK_GRID)


class TestAutoTuneBacktestRunner(unittest.TestCase):
    """Test the single backtest runner from auto_tune."""

    def test_run_single_backtest_returns_metrics(self) -> None:
        from scripts.auto_tune import _run_single_backtest
        from tests.test_grid_search import _build_candles, _sideways

        candles = _build_candles(_sideways(200))
        result = _run_single_backtest(
            "mean_reversion",
            {"bollinger_window": 20, "bollinger_stddev": 1.8, "rsi_period": 14},
            {"stop_loss_pct": 0.03, "take_profit_pct": 0.06, "risk_per_trade_pct": 0.01},
            candles,
            "KRW-BTC",
        )
        self.assertIn("return_pct", result)
        self.assertIn("sharpe", result)
        self.assertIn("mdd_pct", result)
        self.assertIn("win_rate", result)
        self.assertIn("profit_factor", result)
        self.assertIn("trade_count", result)

    def test_volatility_breakout_with_risk_params(self) -> None:
        from scripts.auto_tune import _run_single_backtest
        from tests.test_grid_search import _build_candles, _trending_up

        candles = _build_candles(_trending_up(200))
        result = _run_single_backtest(
            "volatility_breakout",
            {"k_base": 0.1, "noise_lookback": 5, "ma_filter_period": 5},
            {"stop_loss_pct": 0.02, "take_profit_pct": 0.08, "risk_per_trade_pct": 0.01},
            candles,
            "KRW-BTC",
        )
        self.assertIsInstance(result["return_pct"], float)
        self.assertGreaterEqual(result["trade_count"], 0)


if __name__ == "__main__":
    unittest.main()
