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
from crypto_trader.models import Candle, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy
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

    def test_create_strategy_composite_explicit(self) -> None:
        strategy = create_strategy("composite", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, CompositeStrategy)

    def test_create_strategy_unknown_defaults_to_composite(self) -> None:
        strategy = create_strategy("unknown_type", self.strategy_config, self.regime_config)
        self.assertIsInstance(strategy, CompositeStrategy)


class TestStrategyWalletRunOnce(unittest.TestCase):
    def _make_wallet(self, strategy_type: str = "momentum") -> StrategyWallet:
        strategy_config = _make_strategy_config()
        regime_config = _make_regime_config()
        strategy = create_strategy(strategy_type, strategy_config, regime_config)
        broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
        risk_config = RiskConfig(
            risk_per_trade_pct=0.01,
            stop_loss_pct=0.03,
            take_profit_pct=0.06,
            max_daily_loss_pct=0.05,
            max_concurrent_positions=5,
            min_entry_confidence=0.0,
        )
        risk_manager = RiskManager(risk_config)
        wallet_config = WalletConfig(
            name="test_wallet", strategy=strategy_type, initial_capital=1_000_000.0
        )
        return StrategyWallet(wallet_config, strategy, broker, risk_manager)

    def test_wallet_run_once_buy(self) -> None:
        # Rising prices trigger a momentum BUY when thresholds are loose
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
        candles = _make_candles(closes)
        wallet = self._make_wallet("momentum")

        result = wallet.run_once("KRW-BTC", candles)

        self.assertIsNone(result.error)
        self.assertEqual(result.signal.action, SignalAction.BUY)
        self.assertIsNotNone(result.order)

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


if __name__ == "__main__":
    unittest.main()
