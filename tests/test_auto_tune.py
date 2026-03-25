from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.config import load_config
from crypto_trader.wallet import build_wallets
from scripts.auto_tune import TuneResult, write_optimized_toml, write_results_json


class TestAutoTuneOutputs(unittest.TestCase):
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

        self.assertIn('bollinger_window = 15', text)
        self.assertIn('rsi_period = 10', text)
        self.assertIn('stop_loss_pct = 0.02', text)
        self.assertIn('take_profit_pct = 0.08', text)

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
        self.assertEqual(wallet.strategy._k_base, 0.7)
        self.assertEqual(wallet.risk_manager._trailing_stop_pct, 0.04)
        self.assertEqual(wallet.risk_manager._atr_stop_multiplier, 3.0)


if __name__ == "__main__":
    unittest.main()
