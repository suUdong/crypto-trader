from __future__ import annotations

import unittest
from datetime import datetime, timedelta

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
)
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import Candle, OrderType, Position, Signal, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.bollinger_rsi import BollingerRsiStrategy
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.funding_rate import FundingRateStrategy
from crypto_trader.strategy.kimchi_premium import KimchiPremiumStrategy
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy
from crypto_trader.strategy.momentum import MomentumStrategy
from crypto_trader.strategy.momentum_pullback import MomentumPullbackStrategy
from crypto_trader.wallet import StrategyWallet, build_wallets, create_strategy


def _make_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1, 0, 0, 0)
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


def _make_strategy_config(**kwargs: object) -> StrategyConfig:
    defaults: dict[str, object] = dict(
        momentum_lookback=3,
        momentum_entry_threshold=-0.5,
        momentum_exit_threshold=-0.9,
        bollinger_window=5,
        bollinger_stddev=1.5,
        rsi_period=5,
        rsi_oversold_floor=0.0,
        rsi_recovery_ceiling=100.0,
        rsi_overbought=100.0,
        max_holding_bars=48,
    )
    defaults.update(kwargs)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


def _make_regime_config() -> RegimeConfig:
    return RegimeConfig(
        short_lookback=3,
        long_lookback=5,
        bull_threshold_pct=0.03,
        bear_threshold_pct=-0.03,
    )


def _make_minimal_app_config(wallets: list[WalletConfig]) -> AppConfig:
    return AppConfig(
        trading=TradingConfig(
            exchange="upbit",
            symbol="KRW-BTC",
            symbols=["KRW-BTC"],
            interval="minute60",
            candle_count=200,
            paper_trading=True,
        ),
        strategy=StrategyConfig(),
        regime=RegimeConfig(),
        drift=DriftConfig(),
        risk=RiskConfig(),
        backtest=BacktestConfig(),
        telegram=TelegramConfig(),
        runtime=RuntimeConfig(),
        credentials=CredentialsConfig(),
        wallets=wallets,
    )


class TestCreateStrategy(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy_config = _make_strategy_config()
        self.regime_config = _make_regime_config()

    def test_create_strategy_momentum(self) -> None:
        strategy = create_strategy("momentum", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, MomentumStrategy)

    def test_create_strategy_mean_reversion(self) -> None:
        strategy = create_strategy("mean_reversion", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, MeanReversionStrategy)

    def test_create_strategy_momentum_pullback(self) -> None:
        strategy = create_strategy("momentum_pullback", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, MomentumPullbackStrategy)

    def test_create_strategy_bollinger_rsi(self) -> None:
        strategy = create_strategy("bollinger_rsi", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, BollingerRsiStrategy)

    def test_create_strategy_composite_explicit(self) -> None:
        strategy = create_strategy("composite", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, CompositeStrategy)

    def test_create_strategy_funding_rate(self) -> None:
        strategy = create_strategy("funding_rate", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, FundingRateStrategy)

    def test_create_strategy_unknown_defaults_to_composite(self) -> None:
        strategy = create_strategy("unknown_type", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, CompositeStrategy)


class TestStrategyWalletRunOnce(unittest.TestCase):
    def _make_wallet(
        self,
        strategy_type: str = "momentum",
        *,
        strategy_overrides: dict[str, object] | None = None,
        risk_config: RiskConfig | None = None,
        broker: PaperBroker | None = None,
    ) -> StrategyWallet:
        strategy_config = _make_strategy_config()
        regime_config = _make_regime_config()
        strategy = create_strategy(strategy_type, strategy_config, regime_config)
        wallet_broker = broker or PaperBroker(
            starting_cash=1_000_000.0,
            fee_rate=0.0005,
            slippage_pct=0.0005,
        )
        wallet_risk_config = risk_config or RiskConfig(
            risk_per_trade_pct=0.01,
            stop_loss_pct=0.03,
            take_profit_pct=0.06,
            max_daily_loss_pct=0.05,
            max_concurrent_positions=5,
            min_entry_confidence=0.0,
        )
        risk_manager = RiskManager(wallet_risk_config)
        wallet_config = WalletConfig(
            name="test_wallet",
            strategy=strategy_type,
            initial_capital=1_000_000.0,
            strategy_overrides=strategy_overrides or {},
        )
        return StrategyWallet(wallet_config, strategy, wallet_broker, risk_manager)

    def test_wallet_run_once_buy(self) -> None:
        # Rising prices trigger a momentum BUY when thresholds are loose
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
        candles = _make_candles(closes)
        wallet = self._make_wallet("momentum")

        result = wallet.run_once("KRW-BTC", candles)

        self.assertIsNone(result.error)
        self.assertEqual(result.signal.action, SignalAction.BUY)
        self.assertIsNotNone(result.order)
        self.assertEqual(result.order.order_type, OrderType.MARKET)

    def test_mean_reversion_prefers_limit_entry_when_liquidity_is_sufficient(self) -> None:
        class StaticBuyStrategy:
            def evaluate(
                self,
                candles: list[Candle],
                position: Position | None = None,
                *,
                symbol: str = "",
            ) -> Signal:
                return Signal(
                    action=SignalAction.BUY,
                    reason="mean_reversion_entry",
                    confidence=0.64,
                )

        wallet = StrategyWallet(
            WalletConfig(
                name="test_wallet",
                strategy="mean_reversion",
                initial_capital=1_000_000.0,
                strategy_overrides={"execution_cost_multiplier": 1.0},
            ),
            StaticBuyStrategy(),
            PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005),
            RiskManager(
                RiskConfig(
                    take_profit_pct=0.04,
                    stop_loss_pct=0.02,
                    min_entry_confidence=0.5,
                    max_concurrent_positions=5,
                )
            ),
        )

        result = wallet.run_once("KRW-BTC", _make_candles([100.0 + i for i in range(24)]))

        self.assertIsNotNone(result.order)
        self.assertEqual(result.order.order_type, OrderType.LIMIT)

    def test_wallet_uses_market_order_when_limit_confidence_cap_is_tight(self) -> None:
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
        candles = _make_candles(closes)
        wallet = self._make_wallet(
            "momentum",
            strategy_overrides={"limit_confidence_cap": 0.5},
        )

        result = wallet.run_once("KRW-BTC", candles)

        self.assertIsNotNone(result.order)
        self.assertEqual(result.order.order_type, OrderType.MARKET)

    def test_wallet_run_once_error_handling(self) -> None:
        # Empty candle list causes an IndexError inside run_once; must be caught
        wallet = self._make_wallet("momentum")

        result = wallet.run_once("KRW-BTC", [])

        self.assertIsNotNone(result.error)
        self.assertEqual(result.signal.action, SignalAction.HOLD)
        self.assertIsNone(result.order)

    def test_wallet_run_once_updates_atr_history(self) -> None:
        class AtrRecordingRiskManager(RiskManager):
            def __init__(self, config: RiskConfig) -> None:
                super().__init__(config, atr_stop_multiplier=2.0)
                self.atr_updates = 0

            def update_atr_from_candles(self, candles: list[Candle], period: int = 14) -> None:
                self.atr_updates += 1
                super().update_atr_from_candles(candles, period)

        strategy = create_strategy("momentum", _make_strategy_config(), _make_regime_config())
        broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
        risk_manager = AtrRecordingRiskManager(RiskConfig())
        wallet = StrategyWallet(
            WalletConfig(name="test_wallet", strategy="momentum", initial_capital=1_000_000.0),
            strategy,
            broker,
            risk_manager,
        )

        wallet.run_once("KRW-BTC", _make_candles([100.0 + i for i in range(20)]))

        self.assertEqual(risk_manager.atr_updates, 1)

    def test_wallet_blocks_new_entries_after_three_consecutive_losses(self) -> None:
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
        candles = _make_candles(closes)
        wallet = self._make_wallet("momentum")
        for _ in range(3):
            wallet.risk_manager.record_trade(-0.02)

        result = wallet.run_once("KRW-BTC", candles)

        self.assertEqual(result.signal.action, SignalAction.BUY)
        self.assertIsNone(result.order)

    def test_wallet_passes_marked_equity_to_can_open(self) -> None:
        class EquityRecordingRiskManager(RiskManager):
            def __init__(self, config: RiskConfig) -> None:
                super().__init__(config)
                self.current_equities: list[float | None] = []

            def can_open(
                self,
                active_positions: int,
                realized_pnl: float,
                starting_equity: float,
                current_equity: float | None = None,
            ) -> bool:
                self.current_equities.append(current_equity)
                return True

        strategy = create_strategy("momentum", _make_strategy_config(), _make_regime_config())
        broker = PaperBroker(starting_cash=800_000.0, fee_rate=0.0005, slippage_pct=0.0005)
        risk_manager = EquityRecordingRiskManager(
            RiskConfig(
                max_daily_loss_pct=0.05,
                max_concurrent_positions=5,
                min_entry_confidence=0.0,
            )
        )
        wallet = StrategyWallet(
            WalletConfig(name="test_wallet", strategy="momentum", initial_capital=1_000_000.0),
            strategy,
            broker,
            risk_manager,
        )
        broker.positions["KRW-ETH"] = Position(
            symbol="KRW-ETH",
            quantity=1.0,
            entry_price=150_000.0,
            entry_time=datetime(2025, 1, 1, 0, 0, 0),
        )

        wallet.run_once("KRW-BTC", _make_candles([100.0, 101.0, 102.0, 103.0, 104.0, 105.0]))

        self.assertEqual(risk_manager.current_equities, [950_000.0])

    def test_wallet_does_not_open_short_positions_for_funding_rate_sell_signal(self) -> None:
        closes = [100.0] * 20 + [100.0 + i * 2.5 for i in range(12)]
        candles = _make_candles(closes)
        wallet = self._make_wallet("funding_rate")
        assert isinstance(wallet.strategy, FundingRateStrategy)
        wallet.strategy.set_funding_rate(0.0007)

        result = wallet.run_once("KRW-BTC", candles)

        self.assertEqual(result.signal.action, SignalAction.SELL)
        self.assertIsNone(result.order)
        self.assertEqual(wallet.broker.positions, {})

    def test_wallet_blocks_entry_when_execution_costs_dominate_edge(self) -> None:
        class StaticBuyStrategy:
            def evaluate(
                self,
                candles: list[Candle],
                position: Position | None = None,
                *,
                symbol: str = "",
            ) -> Signal:
                return Signal(
                    action=SignalAction.BUY,
                    reason="weak_edge",
                    confidence=0.61,
                )

        broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.001, slippage_pct=0.001)
        risk_manager = RiskManager(
            RiskConfig(
                take_profit_pct=0.02,
                stop_loss_pct=0.02,
                min_entry_confidence=0.6,
                max_concurrent_positions=5,
            )
        )
        wallet = StrategyWallet(
            WalletConfig(name="test_wallet", strategy="momentum", initial_capital=1_000_000.0),
            StaticBuyStrategy(),
            broker,
            risk_manager,
        )

        result = wallet.run_once("KRW-BTC", _make_candles([100.0 + i for i in range(20)]))

        self.assertIsNone(result.order)
        self.assertEqual(result.signal.reason, "execution_edge_below_cost_threshold")

    def test_wallet_force_exit_uses_market_order(self) -> None:
        class ExitRiskManager(RiskManager):
            def should_force_exit(
                self,
                realized_pnl: float,
                starting_equity: float,
                current_equity: float | None = None,
            ) -> bool:
                return True

        strategy = create_strategy("momentum", _make_strategy_config(), _make_regime_config())
        broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
        broker.positions["KRW-BTC"] = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1, 0, 0, 0),
        )
        wallet = StrategyWallet(
            WalletConfig(name="test_wallet", strategy="momentum", initial_capital=1_000_000.0),
            strategy,
            broker,
            ExitRiskManager(RiskConfig(min_entry_confidence=0.0)),
        )

        result = wallet.run_once("KRW-BTC", _make_candles([100.0 + i for i in range(20)]))

        self.assertIsNotNone(result.order)
        self.assertEqual(result.order.order_type, OrderType.MARKET)


class TestBuildWallets(unittest.TestCase):
    def test_build_wallets_count(self) -> None:
        wallet_configs = [
            WalletConfig(name="w1", strategy="momentum", initial_capital=500_000.0),
            WalletConfig(name="w2", strategy="mean_reversion", initial_capital=500_000.0),
            WalletConfig(name="w3", strategy="composite", initial_capital=500_000.0),
        ]
        config = _make_minimal_app_config(wallet_configs)
        wallets = build_wallets(config)

        self.assertEqual(len(wallets), 3)
        self.assertTrue(all(isinstance(w, StrategyWallet) for w in wallets))

    def test_build_wallets_applies_wallet_specific_strategy_and_risk_overrides(self) -> None:
        wallet_configs = [
            WalletConfig(
                name="kimchi_wallet",
                strategy="kimchi_premium",
                initial_capital=500_000.0,
                strategy_overrides={
                    "rsi_period": 10,
                    "max_holding_bars": 24,
                    "min_trade_interval_bars": 6,
                    "min_confidence": 0.4,
                },
                risk_overrides={
                    "stop_loss_pct": 0.02,
                    "take_profit_pct": 0.04,
                    "trailing_stop_pct": 0.03,
                    "atr_stop_multiplier": 2.0,
                },
            ),
        ]
        config = _make_minimal_app_config(wallet_configs)

        wallets = build_wallets(config)

        self.assertEqual(len(wallets), 1)
        wallet = wallets[0]
        self.assertIsInstance(wallet.strategy, KimchiPremiumStrategy)
        self.assertEqual(wallet.strategy._config.rsi_period, 10)
        self.assertEqual(wallet.strategy._config.max_holding_bars, 24)
        self.assertEqual(wallet.strategy._min_trade_interval_bars, 6)
        self.assertEqual(wallet.strategy._min_confidence, 0.4)
        self.assertEqual(wallet.risk_manager._config.stop_loss_pct, 0.02)
        self.assertEqual(wallet.risk_manager._config.take_profit_pct, 0.04)
        self.assertEqual(wallet.risk_manager._trailing_stop_pct, 0.03)
        self.assertEqual(wallet.risk_manager._atr_stop_multiplier, 2.0)

    def test_build_wallets_clamps_runtime_position_cap_to_safer_limit(self) -> None:
        wallet_configs = [
            WalletConfig(
                name="momentum_wallet",
                strategy="momentum",
                initial_capital=500_000.0,
                risk_overrides={"max_position_pct": 0.25},
            ),
        ]
        config = _make_minimal_app_config(wallet_configs)
        config.risk.max_position_pct = 0.25

        wallets = build_wallets(config)

        self.assertEqual(wallets[0].risk_manager._config.max_position_pct, 0.10)


if __name__ == "__main__":
    unittest.main()
