from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_trader.config import load_config
from crypto_trader.wallet import build_wallets
from scripts.auto_tune import (
    DEFAULT_STRATEGIES,
    TuneResult,
    _run_single_backtest,
    tune_strategy,
    write_optimized_toml,
    write_results_json,
)
from tests.test_grid_search import _build_candles, _trending_down


class TestAutoTuneOutputs(unittest.TestCase):
    def test_default_strategies_cover_all_supported_strategies(self) -> None:
        self.assertEqual(
            DEFAULT_STRATEGIES,
            [
                "momentum",
                "momentum_pullback",
                "bollinger_rsi",
                "mean_reversion",
                "composite",
                "kimchi_premium",
                "funding_rate",
                "volume_spike",
                "obi",
                "vpin",
                "volatility_breakout",
            ],
        )

    def test_write_optimized_toml_uses_best_sharpe_result(self) -> None:
        results = [
            TuneResult(
                strategy="momentum",
                params={"momentum_lookback": 20},
                risk_params={"stop_loss_pct": 0.03, "take_profit_pct": 0.06},
                avg_return_pct=5.0,
                avg_sharpe=1.2,
                avg_mdd_pct=8.0,
                avg_win_rate=55.0,
                avg_profit_factor=1.4,
                total_trades=12,
                best_score=1.0,
                candidate_rank=1,
                top_candidates=[],
                per_symbol={},
            ),
            TuneResult(
                strategy="mean_reversion",
                params={"bollinger_window": 15, "rsi_period": 10},
                risk_params={"stop_loss_pct": 0.02, "take_profit_pct": 0.08},
                avg_return_pct=7.0,
                avg_sharpe=1.8,
                avg_mdd_pct=6.0,
                avg_win_rate=58.0,
                avg_profit_factor=1.6,
                total_trades=18,
                best_score=1.5,
                candidate_rank=2,
                top_candidates=[],
                per_symbol={},
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "optimized.toml"
            write_optimized_toml(results, str(path))
            text = path.read_text(encoding="utf-8")

        self.assertIn("bollinger_window = 15", text)
        self.assertIn("rsi_period = 10", text)
        self.assertIn("stop_loss_pct = 0.02", text)
        self.assertIn("take_profit_pct = 0.08", text)
        self.assertIn("[wallets.strategy_overrides]", text)
        self.assertIn("[wallets.risk_overrides]", text)
        self.assertIn('strategy = "mean_reversion"', text)

    def test_write_results_json_persists_baseline_and_optimized_results(self) -> None:
        tune_results = [
            TuneResult(
                strategy="momentum",
                params={"momentum_lookback": 20},
                risk_params={"stop_loss_pct": 0.03, "take_profit_pct": 0.06},
                avg_return_pct=5.0,
                avg_sharpe=1.2,
                avg_mdd_pct=8.0,
                avg_win_rate=55.0,
                avg_profit_factor=1.4,
                total_trades=12,
                best_score=1.0,
                candidate_rank=1,
                top_candidates=[{"rank": 1, "params": {"momentum_lookback": 20}}],
                per_symbol={"KRW-BTC": {"return_pct": 4.0}},
            ),
        ]
        baseline_results = [
            {"strategy": "momentum", "symbol": "KRW-BTC", "return_pct": 2.0},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.json"
            write_results_json(baseline_results, tune_results, str(path), 90)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["days"], 90)
        self.assertEqual(payload["baseline_results"][0]["symbol"], "KRW-BTC")
        self.assertEqual(payload["optimized_results"][0]["strategy"], "momentum")
        self.assertEqual(
            payload["optimized_results"][0]["top_candidates"][0]["params"]["momentum_lookback"],
            20,
        )

    def test_written_config_round_trips_runtime_parameters(self) -> None:
        result = TuneResult(
            strategy="volatility_breakout",
            params={
                "k_base": 0.7,
                "noise_lookback": 15,
                "ma_filter_period": 15,
                "max_holding_bars": 24,
            },
            risk_params={
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.04,
                "risk_per_trade_pct": 0.015,
                "trailing_stop_pct": 0.04,
                "atr_stop_multiplier": 3.0,
            },
            avg_return_pct=1.0,
            avg_sharpe=1.5,
            avg_mdd_pct=2.0,
            avg_win_rate=50.0,
            avg_profit_factor=1.2,
            total_trades=10,
            best_score=1.0,
            candidate_rank=1,
            top_candidates=[],
            per_symbol={},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "optimized.toml"
            write_optimized_toml([result], str(path))
            config = load_config(path, {})
            wallet = build_wallets(config)[0]

        self.assertEqual(config.strategy.k_base, 0.7)
        self.assertEqual(config.strategy.noise_lookback, 15)
        self.assertEqual(config.strategy.ma_filter_period, 15)
        self.assertEqual(config.risk.trailing_stop_pct, 0.04)
        self.assertEqual(config.risk.atr_stop_multiplier, 3.0)
        self.assertEqual(config.wallets[0].strategy_overrides["k_base"], 0.7)
        self.assertEqual(config.wallets[0].risk_overrides["atr_stop_multiplier"], 3.0)
        self.assertEqual(wallet.strategy._k_base, 0.7)
        self.assertEqual(wallet.risk_manager._trailing_stop_pct, 0.04)
        self.assertEqual(wallet.risk_manager._atr_stop_multiplier, 3.0)

    def test_write_optimized_toml_emits_all_wallets_with_overrides(self) -> None:
        results = [
            TuneResult(
                strategy="momentum",
                params={"momentum_lookback": 15, "momentum_entry_threshold": 0.003},
                risk_params={"stop_loss_pct": 0.03, "take_profit_pct": 0.04},
                avg_return_pct=5.0,
                avg_sharpe=1.3,
                avg_mdd_pct=7.0,
                avg_win_rate=40.0,
                avg_profit_factor=1.2,
                total_trades=100,
                best_score=1.0,
                candidate_rank=1,
                top_candidates=[],
                per_symbol={},
            ),
            TuneResult(
                strategy="kimchi_premium",
                params={"rsi_period": 14, "min_trade_interval_bars": 6, "min_confidence": 0.4},
                risk_params={"stop_loss_pct": 0.02, "take_profit_pct": 0.04},
                avg_return_pct=5.2,
                avg_sharpe=1.2,
                avg_mdd_pct=6.0,
                avg_win_rate=51.0,
                avg_profit_factor=1.4,
                total_trades=160,
                best_score=1.1,
                candidate_rank=1,
                top_candidates=[],
                per_symbol={},
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "optimized.toml"
            write_optimized_toml(results, str(path))
            config = load_config(path, {})

        self.assertEqual(
            [wallet.strategy for wallet in config.wallets],
            ["momentum", "kimchi_premium"],
        )
        kimchi_wallet = config.wallets[1]
        self.assertEqual(kimchi_wallet.strategy_overrides["min_trade_interval_bars"], 6)
        self.assertEqual(kimchi_wallet.strategy_overrides["min_confidence"], 0.4)

    def test_tune_strategy_selects_best_candidate_by_optimized_score(self) -> None:
        class Candidate:
            def __init__(self, params: dict[str, int], score: float) -> None:
                self.params = params
                self.score = score

        candles_by_symbol = {"KRW-BTC": []}
        candidates = [
            Candidate({"x": 1}, 0.5),
            Candidate({"x": 2}, 0.6),
        ]

        def fake_optimize(strategy_type, strategy_params, candles):
            if strategy_params["x"] == 1:
                return {"stop_loss_pct": 0.02}, 0.8
            return {"stop_loss_pct": 0.03}, 1.2

        def fake_evaluate(strategy_type, strategy_params, risk_params, candles):
            if strategy_params["x"] == 1:
                return {
                    "avg_return_pct": 1.0,
                    "avg_sharpe": 0.9,
                    "avg_mdd_pct": 2.0,
                    "avg_win_rate": 50.0,
                    "avg_profit_factor": 1.1,
                    "total_trades": 4,
                    "per_symbol": {"KRW-BTC": {"return_pct": 1.0}},
                }
            return {
                "avg_return_pct": 2.0,
                "avg_sharpe": 1.1,
                "avg_mdd_pct": 3.0,
                "avg_win_rate": 55.0,
                "avg_profit_factor": 1.2,
                "total_trades": 5,
                "per_symbol": {"KRW-BTC": {"return_pct": 2.0}},
            }

        with (
            patch("scripts.auto_tune.run_grid_for_strategy", return_value=["grid"]),
            patch("scripts.auto_tune.top_param_sets", return_value=candidates),
            patch("scripts.auto_tune.optimize_risk_for_strategy", side_effect=fake_optimize),
            patch("scripts.auto_tune.evaluate_strategy_params", side_effect=fake_evaluate),
        ):
            result = tune_strategy("momentum", candles_by_symbol, top_n=2, verbose=False)

        assert result is not None
        self.assertEqual(result.candidate_rank, 2)
        self.assertEqual(result.params, {"x": 2})
        self.assertEqual(result.risk_params, {"stop_loss_pct": 0.03})
        self.assertEqual(len(result.top_candidates), 2)

    def test_run_single_backtest_supports_kimchi_specific_params(self) -> None:
        candles = _build_candles(_trending_down(200))

        result = _run_single_backtest(
            "kimchi_premium",
            {
                "rsi_period": 14,
                "max_holding_bars": 24,
                "min_trade_interval_bars": 0,
                "min_confidence": 0.0,
            },
            {
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.06,
                "risk_per_trade_pct": 0.01,
            },
            candles,
            "KRW-BTC",
        )

        self.assertIsInstance(result["return_pct"], float)
        self.assertGreaterEqual(result["trade_count"], 0)
        self.assertIn("win_rate", result)


if __name__ == "__main__":
    unittest.main()
