from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "specs" / "trading_system_contract.toml"


class TradingSystemContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = tomllib.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_primary_scope_is_upbit_krw(self) -> None:
        project = self.contract["project"]
        self.assertEqual(project["primary_exchange"], "upbit")
        self.assertEqual(project["market_scope"], "krw-spot")
        self.assertTrue(project["paper_trading_default"])

    def test_strategy_uses_three_factor_confirmation(self) -> None:
        strategy = self.contract["strategy"]
        self.assertEqual(
            strategy["components"],
            ["momentum", "bollinger_bands", "rsi"],
        )
        self.assertTrue(strategy["supports_backtest"])
        self.assertTrue(strategy["entry_requires_all"])
        self.assertGreater(strategy["bollinger_window"], 1)
        self.assertGreater(strategy["momentum_lookback"], 1)

    def test_risk_limits_are_ordered_safely(self) -> None:
        risk = self.contract["risk"]
        self.assertEqual(risk["position_sizing"], "risk_percent")
        self.assertLess(risk["risk_per_trade_pct"], risk["max_daily_loss_pct"])
        self.assertLess(risk["stop_loss_pct"], risk["take_profit_pct"])
        self.assertGreaterEqual(risk["max_concurrent_positions"], 1)

    def test_pipeline_order_preserves_guardrails_before_execution(self) -> None:
        stages = self.contract["pipeline"]["stages"]
        self.assertEqual(
            stages,
            [
                "market_data",
                "feature_calculation",
                "signal_generation",
                "risk_evaluation",
                "order_execution",
                "notifications",
            ],
        )
        self.assertLess(stages.index("risk_evaluation"), stages.index("order_execution"))

    def test_backtest_outputs_cover_core_performance_metrics(self) -> None:
        backtest = self.contract["backtest"]
        self.assertTrue(backtest["requires_ohlcv"])
        self.assertTrue(backtest["includes_fees"])
        self.assertTrue(backtest["includes_slippage"])
        self.assertEqual(
            backtest["outputs"],
            ["equity_curve", "trade_log", "win_rate", "profit_factor", "max_drawdown"],
        )


if __name__ == "__main__":
    unittest.main()
