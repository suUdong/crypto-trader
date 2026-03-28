from __future__ import annotations

import json
import signal
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from crypto_trader.macro.client import MacroSnapshot
from crypto_trader.models import (
    Candle,
    OrderRequest,
    OrderSide,
    PipelineResult,
    Position,
    Signal,
    SignalAction,
)
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


def _make_macro_snapshot(**overrides: object) -> MacroSnapshot:
    defaults = dict(
        overall_regime="neutral",
        overall_confidence=0.6,
        us_regime="neutral",
        us_confidence=0.6,
        kr_regime="neutral",
        kr_confidence=0.6,
        crypto_regime="neutral",
        crypto_confidence=0.6,
        crypto_signals={},
        btc_dominance=55.0,
        kimchi_premium=2.0,
        fear_greed_index=50,
    )
    defaults.update(overrides)
    return MacroSnapshot(**defaults)  # type: ignore[arg-type]


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


class _RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, message: str) -> None:
        self.messages.append(message)


class FlakyMarketData(MarketDataClient):
    def __init__(self, failures_before_success: int, candles: list[Candle]) -> None:
        self._failures_before_success = failures_before_success
        self._candles = candles
        self._calls = 0

    def get_ohlcv(self, symbol: str, interval: str = "minute60", count: int = 200) -> list[Candle]:
        self._calls += 1
        if self._calls <= self._failures_before_success:
            raise TimeoutError("API timeout")
        return self._candles


class SequenceMacroClient:
    def __init__(self, snapshots: list[MacroSnapshot | None]) -> None:
        self._snapshots = list(snapshots)
        self._last = snapshots[-1] if snapshots else None

    def get_snapshot(self) -> MacroSnapshot | None:
        if self._snapshots:
            self._last = self._snapshots.pop(0)
        return self._last


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
    def test_refresh_macro_propagates_snapshot_to_mean_reversion_strategy(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[WalletConfig("mean_rev_wallet", "mean_reversion", 1_000_000.0)],
        )
        config.macro.enabled = True
        config.macro.base_url = "http://macro.local"
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 40)}),
            config=config,
        )
        runtime._macro_client = SequenceMacroClient([_make_macro_snapshot(fear_greed_index=12)])

        runtime._refresh_macro()

        strategy = wallets[0].strategy
        self.assertEqual(strategy._macro_snapshot.fear_greed_index, 12)

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

    def test_runtime_marks_health_degraded_on_transient_fetch_failure(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        market_data = MagicMock()
        market_data.get_ohlcv.side_effect = RuntimeError("network error")
        runtime = MultiSymbolRuntime(wallets=wallets, market_data=market_data, config=config)

        runtime.run()

        health = json.loads(Path(config.runtime.healthcheck_path).read_text(encoding="utf-8"))
        self.assertFalse(health["success"])
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["failure_streak"], 1)
        self.assertTrue(health["recoverable_error"])
        self.assertEqual(health["recovery_delay_seconds"], 15)
        self.assertIn("network error", health["last_error"])

    def test_runtime_emits_degraded_daemon_alert_on_transient_fetch_failure(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        market_data = MagicMock()
        market_data.get_ohlcv.side_effect = RuntimeError("network error")
        runtime = MultiSymbolRuntime(wallets=wallets, market_data=market_data, config=config)

        with patch.object(runtime._alert_manager, "alert_daemon_status") as alert_daemon_status:
            runtime.run()

        alert_daemon_status.assert_called_once()
        self.assertEqual(alert_daemon_status.call_args.kwargs["status"], "degraded")
        self.assertIn("network error", alert_daemon_status.call_args.kwargs["error_message"])

    def test_runtime_recovers_health_after_transient_fetch_failure(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            daemon_mode=False,
            max_iterations=2,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        market_data = FlakyMarketData(
            failures_before_success=2,
            candles=_build_candles([100.0] * 240),
        )
        runtime = MultiSymbolRuntime(wallets=wallets, market_data=market_data, config=config)

        with patch("crypto_trader.multi_runtime.time.sleep"):
            runtime.run()

        health = json.loads(Path(config.runtime.healthcheck_path).read_text(encoding="utf-8"))
        self.assertTrue(health["success"])
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["failure_streak"], 0)
        self.assertIsNotNone(health["last_failure_at"])
        self.assertIsNotNone(health["last_success_at"])

    def test_runtime_re_raises_non_recoverable_fetch_errors(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        market_data = MagicMock()
        market_data.get_ohlcv.side_effect = ValueError("bad parser state")
        runtime = MultiSymbolRuntime(wallets=wallets, market_data=market_data, config=config)

        with self.assertRaisesRegex(ValueError, "bad parser state"):
            runtime.run()

    def test_portfolio_risk_state_reduces_capacity_during_drawdown(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )
        runtime._portfolio_peak_equity = runtime._total_starting_equity
        wallets[0].broker.cash = 600_000.0

        state = runtime._compute_portfolio_risk_state({"KRW-BTC": 100.0})

        self.assertLess(state["entry_size_penalty"], 1.0)
        self.assertLess(state["allowed_new_positions"], state["base_position_limit"])

    def test_drawdown_warning_alerts_on_stage_transition_only(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.kill_switch.max_portfolio_drawdown_pct = 0.10
        config.kill_switch.max_daily_loss_pct = 1.0
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )
        notifier = _RecordingNotifier()
        runtime._alert_manager = runtime._alert_manager.__class__([notifier])

        runtime._check_kill_switch_after_tick([])
        runtime._kill_switch._daily_start_equity = 900_000
        wallets[0].broker.cash = 940_000.0
        runtime._check_kill_switch_after_tick([])
        runtime._check_kill_switch_after_tick([])
        wallets[0].broker.cash = 920_000.0
        runtime._check_kill_switch_after_tick([])

        self.assertEqual(len(notifier.messages), 2)
        self.assertIn("RISK WARNING", notifier.messages[0])
        self.assertIn("RISK REDUCE", notifier.messages[1])

    def test_kill_switch_liquidates_all_positions_on_hard_daily_loss(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.backtest.fee_rate = 0.0
        config.backtest.slippage_pct = 0.0
        config.kill_switch.max_portfolio_drawdown_pct = 1.0
        config.kill_switch.max_daily_loss_pct = 0.20
        wallets = build_wallets(config)
        wallet = wallets[0]
        wallet.broker.cash = 0.0
        wallet.broker.positions["KRW-BTC"] = Position(
            symbol="KRW-BTC",
            quantity=10_000.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1, tzinfo=UTC),
        )
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30 + [94.0])}),
            config=config,
        )

        runtime._check_kill_switch_after_tick(
            [
                PipelineResult(
                    symbol="KRW-BTC",
                    signal=Signal(action=SignalAction.HOLD, reason="baseline", confidence=0.0),
                    order=None,
                    message="baseline",
                    latest_price=100.0,
                )
            ]
        )
        self.assertFalse(runtime._kill_switch.is_triggered)

        runtime._check_kill_switch_after_tick(
            [
                PipelineResult(
                    symbol="KRW-BTC",
                    signal=Signal(action=SignalAction.HOLD, reason="drawdown", confidence=0.0),
                    order=None,
                    message="drawdown",
                    latest_price=94.0,
                )
            ]
        )

        self.assertTrue(runtime._kill_switch.is_triggered)
        self.assertNotIn("KRW-BTC", wallet.broker.positions)
        self.assertGreater(wallet.broker.cash, 0.0)

    def test_daily_loss_warning_uses_hard_cap_even_when_config_is_looser(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.kill_switch.max_portfolio_drawdown_pct = 1.0
        config.kill_switch.max_daily_loss_pct = 0.20
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )
        notifier = _RecordingNotifier()
        runtime._alert_manager = runtime._alert_manager.__class__([notifier])

        runtime._check_kill_switch_after_tick([])
        runtime._kill_switch._daily_start_equity = 1_000_000.0
        wallets[0].broker.cash = 970_000.0
        runtime._check_kill_switch_after_tick([])

        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("RISK WARNING", notifier.messages[0])
        self.assertIn("daily_loss", notifier.messages[0])

    def test_rebalance_idle_wallet_cash_moves_capital_and_updates_summary(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[
                WalletConfig("leader_wallet", "momentum", 1_000_000.0),
                WalletConfig("laggard_wallet", "mean_reversion", 1_000_000.0),
            ],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        wallets[0].broker.cash = 1_500_000.0
        wallets[0].broker.realized_pnl = 200_000.0
        wallets[1].broker.cash = 500_000.0
        wallets[1].broker.realized_pnl = -150_000.0
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )

        runtime._rebalance_idle_wallet_cash({"KRW-BTC": 100.0})

        self.assertGreater(runtime._last_capital_reallocation["transfer_count"], 0)
        self.assertLess(wallets[0].broker.cash, 1_500_000.0)
        self.assertGreater(wallets[1].broker.cash, 500_000.0)
        self.assertEqual(
            wallets[0].broker.cash + wallets[1].broker.cash,
            2_000_000.0,
        )

    def test_drawdown_reduce_stage_trims_open_positions_once(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.backtest.fee_rate = 0.0
        config.backtest.slippage_pct = 0.0
        config.kill_switch.max_portfolio_drawdown_pct = 0.10
        wallets = build_wallets(config)
        wallet = wallets[0]
        wallet.broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=5_000.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="seed_position",
            ),
            market_price=100.0,
        )
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30 + [84.0])}),
            config=config,
        )
        runtime._portfolio_peak_equity = runtime._total_starting_equity

        state = runtime._compute_portfolio_risk_state({"KRW-BTC": 84.0})
        applied = runtime._maybe_reduce_positions_for_drawdown(
            {"KRW-BTC": _build_candles([100.0] * 30 + [84.0])},
            {"KRW-BTC": 84.0},
        )

        self.assertEqual(state["stage"], "reduce")
        self.assertTrue(applied)
        self.assertAlmostEqual(wallet.broker.positions["KRW-BTC"].quantity, 2_500.0)
        self.assertEqual(runtime._last_position_reduction["status"], "executed")

        applied_again = runtime._maybe_reduce_positions_for_drawdown(
            {"KRW-BTC": _build_candles([100.0] * 30 + [84.0])},
            {"KRW-BTC": 84.0},
        )

        self.assertFalse(applied_again)
        self.assertAlmostEqual(wallet.broker.positions["KRW-BTC"].quantity, 2_500.0)
        self.assertEqual(runtime._last_position_reduction["status"], "already_reduced")

    def test_daily_rebalance_runs_once_per_kst_day(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[
                WalletConfig("leader_wallet", "momentum", 1_000_000.0),
                WalletConfig("laggard_wallet", "mean_reversion", 1_000_000.0),
            ],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        wallets = build_wallets(config)
        wallets[0].broker.cash = 1_500_000.0
        wallets[0].broker.realized_pnl = 200_000.0
        wallets[1].broker.cash = 500_000.0
        wallets[1].broker.realized_pnl = -150_000.0
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )

        runtime._maybe_rebalance_idle_wallet_cash(
            {"KRW-BTC": 100.0},
            now=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        )
        first_cash = [wallet.broker.cash for wallet in wallets]
        self.assertEqual(runtime._last_capital_reallocation["rebalance_date"], "2025-01-01")

        runtime._maybe_rebalance_idle_wallet_cash(
            {"KRW-BTC": 100.0},
            now=datetime(2025, 1, 1, 1, 0, tzinfo=UTC),
        )

        self.assertEqual(
            runtime._last_capital_reallocation["status"],
            "skipped_already_rebalanced_today",
        )
        self.assertEqual(first_cash, [wallet.broker.cash for wallet in wallets])

        wallets[0].broker.cash += 100_000.0
        wallets[1].broker.cash -= 100_000.0
        runtime._maybe_rebalance_idle_wallet_cash(
            {"KRW-BTC": 100.0},
            now=datetime(2025, 1, 1, 15, 30, tzinfo=UTC),
        )

        self.assertEqual(runtime._last_capital_reallocation["rebalance_date"], "2025-01-02")
        self.assertNotEqual(
            runtime._last_capital_reallocation["status"],
            "skipped_already_rebalanced_today",
        )

    def test_daily_rebalance_waits_for_idle_wallets_before_consuming_day(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[
                WalletConfig("leader_wallet", "momentum", 1_000_000.0),
                WalletConfig("laggard_wallet", "mean_reversion", 1_000_000.0),
            ],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.backtest.fee_rate = 0.0
        config.backtest.slippage_pct = 0.0
        wallets = build_wallets(config)
        wallets[0].broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=1_000.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="seed_position",
            ),
            market_price=100.0,
        )
        wallets[1].broker.cash = 500_000.0
        wallets[1].broker.realized_pnl = -150_000.0
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )

        runtime._maybe_rebalance_idle_wallet_cash(
            {"KRW-BTC": 100.0},
            now=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        )

        self.assertEqual(
            runtime._last_capital_reallocation["status"],
            "skipped_not_enough_idle_wallets",
        )
        self.assertIsNone(runtime._last_rebalance_date)

        wallets[0].broker.positions.clear()
        runtime._maybe_rebalance_idle_wallet_cash(
            {"KRW-BTC": 100.0},
            now=datetime(2025, 1, 1, 1, 0, tzinfo=UTC),
        )

        self.assertEqual(runtime._last_rebalance_date, "2025-01-01")
        self.assertNotEqual(
            runtime._last_capital_reallocation["status"],
            "skipped_not_enough_idle_wallets",
        )

    def test_daily_rebalance_with_macro_and_no_trade_history_preserves_seed_weights(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[
                WalletConfig("wallet_a", "momentum", 350_000.0),
                WalletConfig("wallet_b", "momentum", 250_000.0),
                WalletConfig("wallet_c", "momentum", 200_000.0),
                WalletConfig("wallet_d", "momentum", 200_000.0),
            ],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.macro.enabled = True
        config.macro.base_url = "http://macro.local"
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )
        runtime._macro_allocation_edge_scores = {
            "wallet_a": 0.6,
            "wallet_b": 0.6,
            "wallet_c": 0.6,
            "wallet_d": 0.6,
        }

        runtime._maybe_rebalance_idle_wallet_cash(
            {"KRW-BTC": 100.0},
            now=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        )

        self.assertEqual(runtime._last_capital_reallocation["status"], "no_transfer_needed")
        self.assertEqual(runtime._last_capital_reallocation["transfer_count"], 0)
        self.assertEqual(
            runtime._last_capital_reallocation["target_capital"],
            {
                "wallet_a": 350000.0,
                "wallet_b": 250000.0,
                "wallet_c": 200000.0,
                "wallet_d": 200000.0,
            },
        )

    def test_macro_regime_change_triggers_rebalance_and_updates_macro_state(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[
                WalletConfig("momentum_wallet", "momentum", 1_000_000.0),
                WalletConfig("mean_reversion_wallet", "mean_reversion", 1_000_000.0),
            ],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.macro.enabled = True
        config.macro.base_url = "http://macro.local"
        config.backtest.fee_rate = 0.0
        config.backtest.slippage_pct = 0.0
        wallets = build_wallets(config)
        wallets[0].broker.cash = 1_500_000.0
        wallets[1].broker.cash = 500_000.0
        wallets[0].broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=2_000.0,
                requested_at=datetime(2025, 1, 1, 0, 0, 0),
                reason="seed_position",
            ),
            market_price=100.0,
        )
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )
        runtime._macro_client = MagicMock()
        runtime._macro_client.get_snapshot.side_effect = [
            _make_macro_snapshot(overall_regime="neutral"),
            _make_macro_snapshot(overall_regime="contraction"),
        ]

        runtime._refresh_macro()
        self.assertIsNone(runtime._pending_macro_rebalance)

        runtime._refresh_macro()
        runtime._maybe_rebalance_for_macro_regime_change(
            {"KRW-BTC": _build_candles([100.0] * 30)},
            {"KRW-BTC": 100.0},
        )

        self.assertEqual(runtime._last_macro_state["overall_regime"], "contractionary")
        self.assertTrue(runtime._last_macro_state["changed"])
        self.assertAlmostEqual(wallets[0].broker.positions["KRW-BTC"].quantity, 1_000.0)
        self.assertEqual(
            runtime._last_macro_state["last_transition"]["position_adjustment_status"],
            "executed",
        )
        self.assertAlmostEqual(
            runtime._last_macro_state["last_transition"]["keep_fraction"],
            0.5,
        )
        self.assertEqual(runtime._last_capital_reallocation["reason"], "macro_regime_change")
        self.assertEqual(
            runtime._last_capital_reallocation["macro_transition"]["previous_regime"],
            "neutral",
        )
        self.assertEqual(
            runtime._last_capital_reallocation["macro_transition"]["current_regime"],
            "contractionary",
        )
        self.assertIn(
            runtime._last_capital_reallocation["status"],
            {"rebalanced", "no_transfer_needed", "skipped_not_enough_idle_wallets"},
        )


class TestMacroRegimeRuntime(unittest.TestCase):
    def test_macro_regime_change_rebalances_idle_wallets_with_strategy_tilts(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[
                WalletConfig("momentum_wallet", "momentum", 1_000_000.0),
                WalletConfig("mean_reversion_wallet", "mean_reversion", 1_000_000.0),
            ],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.macro.enabled = True
        config.macro.base_url = "http://macro.local"
        config.risk.max_concurrent_positions = 0
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData(
                {"KRW-BTC": _build_candles([100.0] * 20 + [102.0, 104.0, 106.0, 108.0])}
            ),
            config=config,
        )
        runtime._current_market_regime = "bull"
        runtime._macro_client = SequenceMacroClient(
            [
                _make_macro_snapshot(overall_regime="neutral"),
                _make_macro_snapshot(overall_regime="expansionary"),
            ]
        )

        runtime._refresh_macro()
        runtime._refresh_macro()
        runtime._maybe_rebalance_for_macro_regime_change(
            {"KRW-BTC": _build_candles([100.0] * 20 + [102.0, 104.0, 106.0, 108.0])},
            {"KRW-BTC": 108.0},
        )

        self.assertEqual(runtime._last_capital_reallocation["reason"], "macro_regime_change")
        self.assertEqual(
            runtime._last_capital_reallocation["macro_transition"]["previous_regime"],
            "neutral",
        )
        self.assertEqual(
            runtime._last_capital_reallocation["macro_transition"]["current_regime"],
            "expansionary",
        )
        self.assertGreater(runtime._last_capital_reallocation["transfer_count"], 0)
        self.assertGreater(wallets[0].broker.cash, wallets[1].broker.cash)
        self.assertEqual(runtime._last_macro_state["overall_regime"], "expansionary")
        self.assertGreater(
            runtime._last_capital_reallocation["strategy_edge_scores"]["momentum_wallet"],
            runtime._last_capital_reallocation["strategy_edge_scores"]["mean_reversion_wallet"],
        )

    def test_macro_regime_change_does_not_repeat_without_new_transition(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[
                WalletConfig("momentum_wallet", "momentum", 1_000_000.0),
                WalletConfig("mean_reversion_wallet", "mean_reversion", 1_000_000.0),
            ],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.macro.enabled = True
        config.macro.base_url = "http://macro.local"
        config.risk.max_concurrent_positions = 0
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=FakeMarketData(
                {"KRW-BTC": _build_candles([100.0] * 20 + [102.0, 104.0, 106.0, 108.0])}
            ),
            config=config,
        )
        runtime._current_market_regime = "bear"
        runtime._macro_client = SequenceMacroClient(
            [
                _make_macro_snapshot(overall_regime="neutral"),
                _make_macro_snapshot(overall_regime="contractionary"),
                _make_macro_snapshot(overall_regime="contractionary"),
            ]
        )

        runtime._refresh_macro()
        runtime._refresh_macro()
        runtime._maybe_rebalance_for_macro_regime_change(
            {"KRW-BTC": _build_candles([100.0] * 20 + [102.0, 104.0, 106.0, 108.0])},
            {"KRW-BTC": 108.0},
        )
        cash_after_transition = [wallet.broker.cash for wallet in wallets]
        last_transition = dict(runtime._last_capital_reallocation["macro_transition"])

        runtime._refresh_macro()
        runtime._maybe_rebalance_for_macro_regime_change(
            {"KRW-BTC": _build_candles([100.0] * 20 + [102.0, 104.0, 106.0, 108.0])},
            {"KRW-BTC": 108.0},
        )

        self.assertEqual(cash_after_transition, [wallet.broker.cash for wallet in wallets])
        self.assertEqual(runtime._last_capital_reallocation["macro_transition"], last_transition)
        self.assertEqual(runtime._last_macro_state["overall_regime"], "contractionary")

    def test_macro_refresh_failure_marks_macro_state_unavailable(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.macro.enabled = True
        config.macro.base_url = "http://macro.local"
        runtime = MultiSymbolRuntime(
            wallets=build_wallets(config),
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )
        runtime._current_market_regime = "bull"
        runtime._macro_client = MagicMock()
        runtime._macro_client.get_snapshot.side_effect = TimeoutError("macro timeout")
        runtime._last_macro_regime = "expansionary"

        runtime._refresh_macro()

        self.assertEqual(runtime._last_macro_state["status"], "unavailable")
        self.assertEqual(runtime._last_macro_state["overall_regime"], "unavailable")
        self.assertEqual(runtime._last_macro_state["previous_regime"], "expansionary")
        self.assertEqual(runtime._last_macro_state["strategy_edge_scores"], {})

    def test_macro_unavailable_does_not_create_synthetic_transition(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.macro.enabled = True
        config.macro.base_url = "http://macro.local"
        runtime = MultiSymbolRuntime(
            wallets=build_wallets(config),
            market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
            config=config,
        )
        runtime._macro_client = SequenceMacroClient(
            [
                _make_macro_snapshot(overall_regime="expansionary"),
                None,
                _make_macro_snapshot(overall_regime="expansionary"),
            ]
        )

        runtime._refresh_macro()
        runtime._refresh_macro()
        self.assertEqual(runtime._last_macro_state["status"], "unavailable")
        self.assertIsNone(runtime._pending_macro_rebalance)

        runtime._refresh_macro()

        self.assertEqual(runtime._last_macro_state["overall_regime"], "expansionary")
        self.assertFalse(runtime._last_macro_state["changed"])
        self.assertIsNone(runtime._pending_macro_rebalance)

    def test_macro_rebalance_is_not_overwritten_by_daily_schedule_on_same_day(self) -> None:
        config = _make_config(
            symbols=["KRW-BTC"],
            wallets=[
                WalletConfig("momentum_wallet", "momentum", 1_000_000.0),
                WalletConfig("mean_reversion_wallet", "mean_reversion", 1_000_000.0),
            ],
            daemon_mode=False,
            max_iterations=1,
            poll_interval_seconds=0,
        )
        config.macro.enabled = True
        config.macro.base_url = "http://macro.local"
        runtime = MultiSymbolRuntime(
            wallets=build_wallets(config),
            market_data=FakeMarketData(
                {
                    "KRW-BTC": _build_candles(
                        [100.0] * 30 + [102.0, 104.0, 106.0, 108.0]
                    )
                }
            ),
            config=config,
        )
        runtime._current_market_regime = "bull"
        runtime._macro_client = SequenceMacroClient(
            [
                _make_macro_snapshot(overall_regime="neutral"),
                _make_macro_snapshot(overall_regime="expansionary"),
            ]
        )

        runtime._refresh_macro()
        runtime._refresh_macro()
        runtime._maybe_rebalance_for_macro_regime_change(
            {"KRW-BTC": _build_candles([100.0] * 30 + [102.0, 104.0, 106.0, 108.0])},
            {"KRW-BTC": 108.0},
        )
        preserved_transition = dict(runtime._last_capital_reallocation["macro_transition"])

        runtime._maybe_rebalance_idle_wallet_cash(
            {"KRW-BTC": 108.0},
            now=datetime.now(UTC),
        )

        self.assertEqual(runtime._last_capital_reallocation["reason"], "macro_regime_change")
        self.assertEqual(
            runtime._last_capital_reallocation["macro_transition"],
            preserved_transition,
        )

    def test_restored_unavailable_macro_state_reuses_previous_regime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            config = _make_config(
                symbols=["KRW-BTC"],
                wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
                daemon_mode=False,
                max_iterations=1,
                poll_interval_seconds=0,
            )
            config.macro.enabled = True
            config.macro.base_url = "http://macro.local"
            config.runtime.runtime_checkpoint_path = str(artifacts_dir / "runtime-checkpoint.json")

            runtime = MultiSymbolRuntime(
                wallets=build_wallets(config),
                market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
                config=config,
            )
            runtime._macro_client = SequenceMacroClient([None])
            runtime._last_macro_regime = "expansionary"

            runtime._refresh_macro()
            runtime._save_checkpoint([])

            restored_runtime = MultiSymbolRuntime(
                wallets=build_wallets(config),
                market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30)}),
                config=config,
            )
            restored_runtime._restore_from_checkpoint()
            self.assertEqual(restored_runtime._last_macro_regime, "expansionary")

            restored_runtime._macro_client = SequenceMacroClient(
                [_make_macro_snapshot(overall_regime="expansionary")]
            )
            restored_runtime._refresh_macro()

            self.assertIsNone(restored_runtime._pending_macro_rebalance)
            self.assertFalse(restored_runtime._last_macro_state["changed"])


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
    def test_position_snapshot_and_checkpoint_include_live_pnl_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            config = _make_config(
                symbols=["KRW-BTC"],
                wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
                daemon_mode=False,
                max_iterations=1,
                poll_interval_seconds=0,
            )
            config.backtest.fee_rate = 0.0
            config.backtest.slippage_pct = 0.0
            config.runtime.runtime_checkpoint_path = str(artifacts_dir / "runtime-checkpoint.json")
            config.runtime.position_snapshot_path = str(artifacts_dir / "positions.json")
            config.runtime.healthcheck_path = str(artifacts_dir / "health.json")
            config.runtime.daily_performance_path = str(artifacts_dir / "daily-performance.json")
            config.runtime.promotion_gate_path = str(artifacts_dir / "promotion-gate.json")
            config.runtime.paper_trade_journal_path = str(artifacts_dir / "paper-trades.jsonl")
            config.runtime.strategy_run_journal_path = str(artifacts_dir / "strategy-runs.jsonl")

            wallets = build_wallets(config)
            wallets[0].broker.submit_order(
                OrderRequest(
                    symbol="KRW-BTC",
                    side=OrderSide.BUY,
                    quantity=1_000.0,
                    requested_at=datetime(2025, 1, 1, 0, 0, 0),
                    reason="seed_position",
                ),
                market_price=100.0,
            )
            runtime = MultiSymbolRuntime(
                wallets=wallets,
                market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30 + [110.0])}),
                config=config,
            )
            runtime._latest_prices = {"KRW-BTC": 110.0}

            runtime._refresh_position_snapshot()
            runtime._save_checkpoint([])

            positions = json.loads((artifacts_dir / "positions.json").read_text())
            checkpoint = json.loads((artifacts_dir / "runtime-checkpoint.json").read_text())

            self.assertEqual(positions["open_position_count"], 1)
            self.assertIn("market_price", positions["positions"][0])
            self.assertIn("unrealized_pnl", positions["positions"][0])
            self.assertIn("unrealized_pnl_pct", positions["positions"][0])
            self.assertIn("marked_value", positions["positions"][0])
            position_state = checkpoint["wallet_states"]["momentum_wallet"]["positions"]["KRW-BTC"]
            self.assertEqual(position_state["market_price"], 110.0)
            self.assertEqual(position_state["unrealized_pnl"], 10_000.0)
            self.assertAlmostEqual(position_state["unrealized_pnl_pct"], 0.1)

    def test_restore_checkpoint_recovers_latest_prices_and_rebalance_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            config = _make_config(
                symbols=["KRW-BTC"],
                wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
                daemon_mode=False,
                max_iterations=1,
                poll_interval_seconds=0,
            )
            config.backtest.fee_rate = 0.0
            config.backtest.slippage_pct = 0.0
            config.runtime.runtime_checkpoint_path = str(artifacts_dir / "runtime-checkpoint.json")
            config.runtime.position_snapshot_path = str(artifacts_dir / "positions.json")
            config.runtime.healthcheck_path = str(artifacts_dir / "health.json")
            config.runtime.daily_performance_path = str(artifacts_dir / "daily-performance.json")
            config.runtime.promotion_gate_path = str(artifacts_dir / "promotion-gate.json")
            config.runtime.paper_trade_journal_path = str(artifacts_dir / "paper-trades.jsonl")
            config.runtime.strategy_run_journal_path = str(artifacts_dir / "strategy-runs.jsonl")

            original_wallets = build_wallets(config)
            original_wallets[0].broker.submit_order(
                OrderRequest(
                    symbol="KRW-BTC",
                    side=OrderSide.BUY,
                    quantity=1_000.0,
                    requested_at=datetime(2025, 1, 1, 0, 0, 0),
                    reason="seed_position",
                ),
                market_price=100.0,
            )
            original_runtime = MultiSymbolRuntime(
                wallets=original_wallets,
                market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30 + [110.0])}),
                config=config,
            )
            original_runtime._latest_prices = {"KRW-BTC": 110.0}
            original_runtime._last_rebalance_date = "2025-01-01"
            original_runtime._last_capital_reallocation = {
                "status": "rebalanced",
                "reason": "macro_regime_change",
                "rebalance_date": "2025-01-01",
                "transfer_count": 0,
                "transfers": [],
                "target_capital": {"momentum_wallet": 1_000_000.0},
                "macro_regime": "expansionary",
                "macro_transition": {
                    "previous_regime": "neutral",
                    "current_regime": "expansionary",
                },
                "strategy_edge_scores": {"momentum_wallet": 1.4},
            }
            original_runtime._last_macro_state = {
                "status": "active",
                "overall_regime": "expansionary",
                "market_regime": "bull",
                "position_size_multiplier": 1.5,
                "risk_per_trade_multiplier": 1.25,
                "weekend": False,
                "changed": True,
                "previous_regime": "neutral",
                "confidence": 0.8,
                "reasons": ["macro regime=expansionary"],
                "strategy_edge_scores": {"momentum_wallet": 1.4},
                "wallet_multipliers": {"momentum_wallet": 2.1},
            }
            original_runtime._save_checkpoint([])

            restored_wallets = build_wallets(config)
            restored_runtime = MultiSymbolRuntime(
                wallets=restored_wallets,
                market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 30 + [110.0])}),
                config=config,
            )
            restored_runtime._restore_from_checkpoint()

            self.assertEqual(restored_runtime._latest_prices["KRW-BTC"], 110.0)
            self.assertEqual(restored_runtime._last_rebalance_date, "2025-01-01")
            self.assertEqual(restored_runtime._last_macro_regime, "expansionary")
            self.assertEqual(restored_runtime._last_macro_state["overall_regime"], "expansionary")
            self.assertIn("KRW-BTC", restored_wallets[0].broker.positions)

    def test_runtime_refreshes_daily_and_weekly_report_artifacts(self) -> None:
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

            runtime = MultiSymbolRuntime(
                wallets=build_wallets(config),
                market_data=FakeMarketData({"KRW-BTC": _build_candles([100.0] * 240)}),
                config=config,
            )

            runtime.run()

            self.assertTrue((artifacts_dir / "daily-report.md").exists())
            self.assertTrue((artifacts_dir / "daily-report.json").exists())
            self.assertTrue((artifacts_dir / "weekly-report.md").exists())
            self.assertTrue((artifacts_dir / "weekly-report.json").exists())

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

    def test_checkpoint_and_heartbeat_include_portfolio_monitoring_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            config = _make_config(
                symbols=["KRW-BTC", "KRW-ETH"],
                wallets=[WalletConfig("momentum_wallet", "momentum", 1_000_000.0)],
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

            runtime = MultiSymbolRuntime(
                wallets=build_wallets(config),
                market_data=FakeMarketData(
                    {
                        "KRW-BTC": _build_candles([100.0, 101.0, 102.0, 103.0, 104.0, 105.0]),
                        "KRW-ETH": _build_candles([50.0, 50.5, 51.0, 51.5, 52.0, 52.5]),
                    }
                ),
                config=config,
            )

            runtime.run()

            checkpoint = json.loads((artifacts_dir / "runtime-checkpoint.json").read_text())
            heartbeat = json.loads((artifacts_dir / "daemon-heartbeat.json").read_text())
            health = json.loads((artifacts_dir / "health.json").read_text())

            self.assertIn("correlation", checkpoint)
            self.assertIn("portfolio_risk", checkpoint)
            self.assertIn("capital_reallocation", checkpoint)
            self.assertIn("macro_state", checkpoint)
            self.assertIn("correlation", heartbeat)
            self.assertIn("portfolio_risk", heartbeat)
            self.assertIn("capital_reallocation", heartbeat)
            self.assertIn("macro_state", heartbeat)
            self.assertIn("macro_state", health)


if __name__ == "__main__":
    unittest.main()
