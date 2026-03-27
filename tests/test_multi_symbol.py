from __future__ import annotations

import json
import signal
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.config import (
    AppConfig,
    BacktestConfig,
    CredentialsConfig,
    DriftConfig,
    RegimeConfig,
    RiskConfig,
    RuntimeConfig,
    StrategyConfig,
    TelegramConfig,
    TradingConfig,
    WalletConfig,
    load_config,
)
from crypto_trader.data.base import MarketDataClient
from crypto_trader.models import Candle, SignalAction
from crypto_trader.multi_runtime import MultiSymbolRuntime
from crypto_trader.operator.strategy_report import StrategyComparisonReport
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy
from crypto_trader.strategy.momentum import MomentumStrategy
from crypto_trader.wallet import build_wallets, create_strategy


def _build_candles(closes: list[float], symbol: str = "KRW-BTC") -> list[Candle]:
    start = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1.0 + i,
        )
        for i, c in enumerate(closes)
    ]


def _make_config(
    symbols: list[str] | None = None,
    wallets: list[WalletConfig] | None = None,
    daemon_mode: bool = False,
    max_iterations: int = 2,
    poll_interval_seconds: int = 0,
) -> AppConfig:
    artifacts_dir = tempfile.mkdtemp(prefix="crypto-trader-test-artifacts-")
    return AppConfig(
        trading=TradingConfig(
            symbols=symbols or ["KRW-BTC", "KRW-ETH"],
            symbol=(symbols or ["KRW-BTC"])[0],
            candle_count=200,
        ),
        strategy=StrategyConfig(
            momentum_lookback=3,
            momentum_entry_threshold=-0.5,
            bollinger_window=5,
            bollinger_stddev=1.5,
            rsi_period=3,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
        ),
        regime=RegimeConfig(),
        drift=DriftConfig(),
        risk=RiskConfig(max_concurrent_positions=5),
        backtest=BacktestConfig(initial_capital=1_000_000.0),
        telegram=TelegramConfig(),
        runtime=RuntimeConfig(
            poll_interval_seconds=poll_interval_seconds,
            max_iterations=max_iterations,
            daemon_mode=daemon_mode,
            kill_switch_path=f"{artifacts_dir}/kill-switch.json",
            healthcheck_path=f"{artifacts_dir}/health.json",
            runtime_checkpoint_path=f"{artifacts_dir}/runtime-checkpoint.json",
            strategy_run_journal_path=f"{artifacts_dir}/strategy-runs.jsonl",
            paper_trade_journal_path=f"{artifacts_dir}/paper-trades.jsonl",
            position_snapshot_path=f"{artifacts_dir}/positions.json",
            daily_performance_path=f"{artifacts_dir}/daily-performance.json",
            promotion_gate_path=f"{artifacts_dir}/promotion-gate.json",
        ),
        credentials=CredentialsConfig(),
        wallets=wallets
        or [
            WalletConfig("momentum_wallet", "momentum", 1_000_000.0),
            WalletConfig("mean_reversion_wallet", "mean_reversion", 1_000_000.0),
            WalletConfig("composite_wallet", "composite", 1_000_000.0),
        ],
    )


class FakeMarketData(MarketDataClient):
    def __init__(self, candle_map: dict[str, list[Candle]]) -> None:
        self._candle_map = candle_map

    def get_ohlcv(self, symbol: str, interval: str = "minute60", count: int = 200) -> list[Candle]:
        return self._candle_map.get(symbol, [])


class TestMultiSymbolConfig(unittest.TestCase):
    def test_symbols_list_parsed_from_toml(self) -> None:
        import os
        import tempfile

        toml_content = """
[trading]
symbol = "KRW-BTC"
symbols = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
interval = "minute60"
candle_count = 200
paper_trading = true

[strategy]
[regime]
[drift]
[risk]
[backtest]
[telegram]
[runtime]
[credentials]
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name)
                self.assertEqual(config.trading.symbols, ["KRW-BTC", "KRW-ETH", "KRW-XRP"])
                self.assertEqual(config.trading.symbol, "KRW-BTC")
            finally:
                os.unlink(f.name)

    def test_single_symbol_backward_compat(self) -> None:
        import os
        import tempfile

        toml_content = """
[trading]
symbol = "KRW-ETH"
interval = "minute60"
candle_count = 200
paper_trading = true

[strategy]
[regime]
[drift]
[risk]
[backtest]
[telegram]
[runtime]
[credentials]
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name)
                self.assertEqual(config.trading.symbols, ["KRW-ETH"])
            finally:
                os.unlink(f.name)

    def test_wallets_parsed_from_toml(self) -> None:
        import os
        import tempfile

        toml_content = """
[trading]
symbol = "KRW-BTC"
symbols = ["KRW-BTC"]
paper_trading = true

[strategy]
[regime]
[drift]
[risk]
[backtest]
[telegram]
[runtime]
[credentials]

[[wallets]]
name = "my_wallet"
strategy = "momentum"
initial_capital = 500000.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name)
                self.assertEqual(len(config.wallets), 1)
                self.assertEqual(config.wallets[0].name, "my_wallet")
                self.assertEqual(config.wallets[0].strategy, "momentum")
                self.assertAlmostEqual(config.wallets[0].initial_capital, 500_000.0)
            finally:
                os.unlink(f.name)

    def test_daemon_mode_default_true(self) -> None:
        import os
        import tempfile

        toml_content = """
[trading]
symbol = "KRW-BTC"
paper_trading = true
[strategy]
[regime]
[drift]
[risk]
[backtest]
[telegram]
[runtime]
[credentials]
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            try:
                config = load_config(f.name)
                self.assertTrue(config.runtime.daemon_mode)
            finally:
                os.unlink(f.name)


class TestIndividualStrategies(unittest.TestCase):
    def test_momentum_strategy_produces_signal(self) -> None:
        closes = [100.0] * 20 + [90.0, 89.0]
        candles = _build_candles(closes)
        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertIn(signal.action, list(SignalAction))
        self.assertEqual(signal.context.get("strategy"), "momentum")

    def test_mean_reversion_strategy_produces_signal(self) -> None:
        closes = [100.0] * 20 + [90.0, 89.0]
        candles = _build_candles(closes)
        strategy = MeanReversionStrategy(
            StrategyConfig(
                bollinger_window=5,
                bollinger_stddev=1.5,
                rsi_period=3,
                rsi_recovery_ceiling=100.0,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertIn(signal.action, list(SignalAction))
        self.assertEqual(signal.context.get("strategy"), "mean_reversion")

    def test_create_strategy_factory(self) -> None:
        sc = StrategyConfig()
        rc = RegimeConfig()
        self.assertIsInstance(create_strategy("momentum", sc, rc), MomentumStrategy)
        self.assertIsInstance(create_strategy("mean_reversion", sc, rc), MeanReversionStrategy)
        from crypto_trader.strategy.composite import CompositeStrategy

        self.assertIsInstance(create_strategy("composite", sc, rc), CompositeStrategy)


class TestStrategyWallet(unittest.TestCase):
    def test_two_wallets_produce_independent_pnl(self) -> None:
        config = _make_config()
        wallets = build_wallets(config)
        self.assertEqual(len(wallets), 3)
        for w in wallets:
            self.assertAlmostEqual(w.broker.cash, 1_000_000.0)
            self.assertEqual(len(w.broker.positions), 0)
            self.assertAlmostEqual(w.broker.realized_pnl, 0.0)

        closes = [100.0] * 20 + [90.0, 89.0]
        candles = _build_candles(closes)
        for w in wallets:
            w.run_once("KRW-BTC", candles)

        self.assertEqual(len(set(w.name for w in wallets)), 3)

    def test_wallet_handles_error_gracefully(self) -> None:
        config = _make_config()
        wallets = build_wallets(config)
        result = wallets[0].run_once("KRW-BTC", [])
        self.assertIsNotNone(result.error)


class TestMultiSymbolRuntime(unittest.TestCase):
    def test_runtime_processes_all_symbol_wallet_pairs(self) -> None:
        btc_candles = _build_candles([100.0] * 25)
        eth_candles = _build_candles([50.0] * 25)
        market_data = FakeMarketData(
            {
                "KRW-BTC": btc_candles,
                "KRW-ETH": eth_candles,
            }
        )
        config = _make_config(
            symbols=["KRW-BTC", "KRW-ETH"],
            max_iterations=2,
            daemon_mode=False,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=market_data,
            config=config,
        )
        runtime.run()
        self.assertEqual(runtime._iteration, 2)

    def test_daemon_mode_shutdown_flag(self) -> None:
        btc_candles = _build_candles([100.0] * 25)
        market_data = FakeMarketData({"KRW-BTC": btc_candles})
        config = _make_config(
            symbols=["KRW-BTC"],
            daemon_mode=True,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=market_data,
            config=config,
        )
        runtime._shutdown_requested = True
        runtime.run()
        self.assertEqual(runtime._iteration, 0)

    def test_signal_handler_sets_shutdown_flag(self) -> None:
        btc_candles = _build_candles([100.0] * 25)
        market_data = FakeMarketData({"KRW-BTC": btc_candles})
        config = _make_config(symbols=["KRW-BTC"], daemon_mode=True, poll_interval_seconds=0)
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(wallets=wallets, market_data=market_data, config=config)
        runtime._handle_signal(signal.SIGINT, None)
        self.assertTrue(runtime._shutdown_requested)

    def test_restore_from_checkpoint_normalizes_future_entry_time(self) -> None:
        btc_candles = _build_candles([100.0] * 25)
        market_data = FakeMarketData({"KRW-BTC": btc_candles})
        config = _make_config(symbols=["KRW-BTC"], daemon_mode=False, poll_interval_seconds=0)
        future_wrong = (datetime.now(UTC) + timedelta(hours=9)).replace(microsecond=0)
        checkpoint = {
            "generated_at": datetime.now(UTC).isoformat(),
            "iteration": 1,
            "symbols": ["KRW-BTC"],
            "session_id": "stale-session",
            "wallet_states": {
                "momentum_wallet": {
                    "strategy_type": "momentum",
                    "cash": 900000.0,
                    "realized_pnl": 0.0,
                    "open_positions": 1,
                    "equity": 1000000.0,
                    "trade_count": 0,
                    "positions": {
                        "KRW-BTC": {
                            "symbol": "KRW-BTC",
                            "quantity": 1.0,
                            "entry_price": 100.0,
                            "entry_time": future_wrong.isoformat(),
                            "entry_index": 10,
                            "entry_fee_paid": 0.0,
                            "high_watermark": 100.0,
                            "partial_tp_taken": False,
                        }
                    },
                }
            },
        }
        with open(config.runtime.runtime_checkpoint_path, "w", encoding="utf-8") as handle:
            json.dump(checkpoint, handle)

        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(wallets=wallets, market_data=market_data, config=config)
        runtime._restore_from_checkpoint()

        position = wallets[0].broker.positions["KRW-BTC"]
        self.assertLessEqual(
            position.entry_time,
            datetime.now(UTC) + MultiSymbolRuntime._FUTURE_ENTRY_GRACE,
        )


class TestStrategyComparisonReport(unittest.TestCase):
    def test_report_contains_all_wallets(self) -> None:
        config = _make_config()
        wallets = build_wallets(config)
        report = StrategyComparisonReport().generate(
            wallets=wallets,
            symbols=["KRW-BTC", "KRW-ETH"],
            latest_prices={"KRW-BTC": 100_000.0, "KRW-ETH": 5_000.0},
        )
        self.assertIn("Strategy Comparison Report", report)
        self.assertIn("momentum_wallet", report)
        self.assertIn("mean_reversion_wallet", report)
        self.assertIn("composite_wallet", report)
        self.assertIn("Performance Rankings", report)

    def test_report_save_writes_file(self) -> None:
        import os
        import tempfile

        config = _make_config()
        wallets = build_wallets(config)
        report = StrategyComparisonReport().generate(
            wallets=wallets,
            symbols=["KRW-BTC"],
            latest_prices={"KRW-BTC": 100_000.0},
        )
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            path = f.name
        try:
            StrategyComparisonReport().save(report, path)
            with open(path) as f:
                content = f.read()
            self.assertIn("Strategy Comparison Report", content)
        finally:
            os.unlink(path)


class TestIntegrationMultiSymbolPaperTrading(unittest.TestCase):
    def test_end_to_end_multi_symbol_multi_wallet(self) -> None:
        btc_closes = [100.0] * 20 + [90.0, 89.0, 88.0, 95.0, 100.0]
        eth_closes = [50.0] * 20 + [45.0, 44.0, 43.0, 48.0, 50.0]
        btc_candles = _build_candles(btc_closes)
        eth_candles = _build_candles(eth_closes)
        market_data = FakeMarketData(
            {
                "KRW-BTC": btc_candles,
                "KRW-ETH": eth_candles,
            }
        )
        config = _make_config(
            symbols=["KRW-BTC", "KRW-ETH"],
            max_iterations=3,
            daemon_mode=False,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=market_data,
            config=config,
        )
        runtime.run()
        self.assertEqual(runtime._iteration, 3)

        for wallet in wallets:
            self.assertIsNotNone(wallet.broker.cash)
            self.assertGreater(wallet.broker.cash, 0)

        report = StrategyComparisonReport().generate(
            wallets=wallets,
            symbols=["KRW-BTC", "KRW-ETH"],
            latest_prices={"KRW-BTC": btc_closes[-1], "KRW-ETH": eth_closes[-1]},
        )
        self.assertIn("momentum_wallet", report)
        self.assertIn("mean_reversion_wallet", report)
        self.assertIn("composite_wallet", report)
        self.assertIn("KRW-BTC", report)
        self.assertIn("KRW-ETH", report)


class TestMultiRuntimeArtifacts(unittest.TestCase):
    def test_first_iteration_refreshes_portfolio_gate_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            config = _make_config(
                symbols=["KRW-BTC"],
                wallets=[WalletConfig("momentum_btc_wallet", "momentum", 1_000_000.0)],
                daemon_mode=False,
                max_iterations=1,
                poll_interval_seconds=0,
            )
            config.runtime.runtime_checkpoint_path = str(artifacts_dir / "runtime-checkpoint.json")
            config.runtime.position_snapshot_path = str(artifacts_dir / "positions.json")
            config.runtime.healthcheck_path = str(artifacts_dir / "health.json")
            config.runtime.daily_performance_path = str(artifacts_dir / "daily-performance.json")
            config.runtime.promotion_gate_path = str(artifacts_dir / "promotion-gate.json")
            config.runtime.paper_trade_journal_path = str(artifacts_dir / "paper-trades.jsonl")
            config.runtime.strategy_run_journal_path = str(artifacts_dir / "strategy-runs.jsonl")
            config.source_config_path = "config/test.toml"

            wallets = build_wallets(config)
            runtime = MultiSymbolRuntime(
                wallets=wallets,
                market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 240)}),
                config=config,
            )

            runtime.run()

            self.assertTrue((artifacts_dir / "promotion-gate.json").exists())


if __name__ == "__main__":
    unittest.main()
