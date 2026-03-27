from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from crypto_trader.config import StrategyConfig
from crypto_trader.data.funding_rate_client import BinanceFundingRateClient, FundingRatePoint
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.funding_rate import FundingRateStrategy


def build_candles(
    closes: list[float],
    volume: float = 1.0,
    *,
    start: datetime | None = None,
) -> list[Candle]:
    base = start or datetime(2025, 1, 1, 0, 0, 0)
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=index),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=volume + index,
            )
        )
    return candles


def _default_config() -> StrategyConfig:
    return StrategyConfig(rsi_period=14, momentum_lookback=10)


def _make_strategy(funding_rate: float | None = None, **kwargs) -> FundingRateStrategy:
    mock_client = MagicMock(spec=BinanceFundingRateClient)
    mock_client.get_latest_funding_rate.return_value = funding_rate
    mock_client.get_funding_rate_history.return_value = []
    strategy = FundingRateStrategy(_default_config(), funding_client=mock_client, **kwargs)
    return strategy


class TestFundingRateClient(unittest.TestCase):
    def test_symbol_mapping(self) -> None:
        client = BinanceFundingRateClient()
        assert client._to_perp_symbol("KRW-BTC") == "BTCUSDT"
        assert client._to_perp_symbol("KRW-ETH") == "ETHUSDT"
        assert client._to_perp_symbol("KRW-XRP") == "XRPUSDT"
        assert client._to_perp_symbol("KRW-SOL") == "SOLUSDT"
        assert client._to_perp_symbol("KRW-DOGE") == "DOGEUSDT"

    def test_cached_rate_returned_on_failure(self) -> None:
        client = BinanceFundingRateClient()
        client._cached_rate["KRW-BTC"] = 0.0001
        with patch.object(client, "_request_json", side_effect=OSError("offline")):
            result = client.get_latest_funding_rate("KRW-BTC")
        self.assertEqual(result, 0.0001)


class TestFundingRateStrategyEntry(unittest.TestCase):
    def test_hold_on_insufficient_candles(self) -> None:
        strategy = _make_strategy(funding_rate=-0.0005)
        candles = build_candles([100.0] * 10)
        signal = strategy.evaluate(candles)
        assert signal.action is SignalAction.HOLD
        assert signal.reason == "insufficient_data"

    def test_deep_negative_funding_rsi_oversold_buy(self) -> None:
        closes = [100.0] * 20 + [100 - i * 2.0 for i in range(10)]
        strategy = _make_strategy(funding_rate=-0.0005)
        signal = strategy.evaluate(build_candles(closes), symbol="KRW-BTC")
        assert signal.action is SignalAction.BUY
        assert "deep_negative" in signal.reason
        assert signal.confidence >= 0.6

    def test_high_positive_funding_can_open_short(self) -> None:
        closes = [100.0] * 20 + [100 + i * 2.5 for i in range(12)]
        strategy = _make_strategy(funding_rate=0.0007)
        signal = strategy.evaluate(build_candles(closes), symbol="KRW-BTC")
        assert signal.action is SignalAction.SELL
        assert "short_bias" in signal.reason

    def test_no_funding_data_hold_for_non_historical_candles(self) -> None:
        strategy = _make_strategy(funding_rate=None)
        candles = build_candles(
            [100.0] * 20 + [99.0, 98.0, 97.0, 96.0, 95.0, 94.5, 94.0, 93.5, 93.0, 92.5],
            start=datetime.now(tz=UTC).replace(tzinfo=None),
        )
        signal = strategy.evaluate(candles, symbol="KRW-BTC")
        assert signal.action is SignalAction.HOLD
        assert signal.reason == "funding_data_unavailable"

    def test_history_lookup_is_used_for_backtest(self) -> None:
        closes = [100.0] * 20 + [100 + i * 2.0 for i in range(12)]
        candles = build_candles(closes)
        strategy = _make_strategy(funding_rate=None)
        strategy.set_funding_rate_history(
            [
                FundingRatePoint(
                    symbol="KRW-BTC",
                    funding_rate=0.0006,
                    funding_time=candles[-3].timestamp.replace(tzinfo=UTC),
                )
            ]
        )
        signal = strategy.evaluate(candles, symbol="KRW-BTC")
        assert signal.action is SignalAction.SELL
        assert signal.context["funding_source"] == "history"

    def test_prime_backtest_funding_uses_proxy_history_without_network_lookup(self) -> None:
        candles = build_candles([100.0 + i for i in range(40)])
        strategy = _make_strategy(funding_rate=None)

        strategy.prime_backtest_funding("KRW-BTC", candles)

        strategy._funding_client.get_funding_rate_history.assert_not_called()
        self.assertTrue(strategy._funding_history)
        self.assertEqual(strategy._funding_history[0].symbol, "KRW-BTC")


class TestFundingRateStrategyExit(unittest.TestCase):
    def _make_position(
        self,
        *,
        entry_price: float = 100.0,
        entry_index: int = 20,
        side: str = "long",
    ) -> Position:
        return Position(
            symbol="KRW-BTC",
            quantity=0.01,
            entry_price=entry_price,
            entry_time=datetime(2025, 1, 1, 0, 0, 0) + timedelta(hours=entry_index),
            entry_index=entry_index,
            side=side,
        )

    def test_exit_long_on_extreme_funding(self) -> None:
        closes = [100.0] * 30 + [110.0]
        strategy = _make_strategy(funding_rate=0.001)
        signal = strategy.evaluate(
            build_candles(closes),
            self._make_position(entry_index=20, side="long"),
            symbol="KRW-BTC",
        )
        assert signal.action is SignalAction.SELL
        assert "overheated" in signal.reason

    def test_exit_short_on_deep_negative_funding(self) -> None:
        closes = [120.0] * 20 + [118.0, 116.0, 114.0, 111.0, 109.0, 108.0]
        strategy = _make_strategy(funding_rate=-0.0005)
        signal = strategy.evaluate(
            build_candles(closes),
            self._make_position(entry_price=120.0, entry_index=20, side="short"),
            symbol="KRW-BTC",
        )
        assert signal.action is SignalAction.BUY
        assert "cover" in signal.reason

    def test_exit_short_on_max_holding_period(self) -> None:
        closes = [100.0] * 80
        strategy = _make_strategy(funding_rate=0.0002, max_holding_bars=48)
        signal = strategy.evaluate(
            build_candles(closes),
            self._make_position(entry_index=10, side="short"),
            symbol="KRW-BTC",
        )
        assert signal.action is SignalAction.BUY
        assert signal.reason == "max_holding_period"


class TestFundingRateStrategyCooldown(unittest.TestCase):
    def test_cooldown_prevents_immediate_reentry(self) -> None:
        closes = [100.0] * 20 + [100 - i * 2.0 for i in range(10)]
        strategy = _make_strategy(funding_rate=-0.0005, cooldown_bars=6)
        candles = build_candles(closes)
        signal1 = strategy.evaluate(candles, symbol="KRW-BTC")
        signal2 = strategy.evaluate(candles, symbol="KRW-BTC")
        assert signal1.action is SignalAction.BUY
        assert signal2.action is SignalAction.HOLD
        assert signal2.reason == "cooldown_active"


class TestFundingRateStrategyIndicators(unittest.TestCase):
    def test_signal_includes_indicators(self) -> None:
        strategy = _make_strategy(funding_rate=0.0002)
        signal = strategy.evaluate(build_candles([100.0] * 30), symbol="KRW-BTC")
        assert "rsi" in signal.indicators
        assert "momentum" in signal.indicators
        assert "funding_rate" in signal.indicators
        assert "funding_rate_bps" in signal.indicators
        assert signal.context.get("strategy") == "funding_rate"

    def test_confidence_below_threshold_hold(self) -> None:
        closes = [100.0] * 20 + [99.0, 98.5, 98.0, 97.5, 97.0, 97.5, 98.0, 98.5, 99.0, 99.5]
        strategy = _make_strategy(
            funding_rate=-0.00012,
            min_confidence=0.9,
        )
        signal = strategy.evaluate(build_candles(closes), symbol="KRW-BTC")
        assert signal.action is SignalAction.HOLD


class TestFundingRateStrategyBacktestIntegration(unittest.TestCase):
    def test_backtest_engine_can_record_short_trade(self) -> None:
        from crypto_trader.backtest.engine import BacktestEngine
        from crypto_trader.config import BacktestConfig, RiskConfig
        from crypto_trader.risk.manager import RiskManager

        closes = (
            [100.0] * 25
            + [100.0 + i * 2.0 for i in range(15)]
            + [128.0 - i * 3.0 for i in range(16)]
            + [80.0 + i * 0.3 for i in range(20)]
        )
        candles = build_candles(closes)
        strategy = FundingRateStrategy(_default_config())
        strategy.set_funding_rate_history(
            [
                FundingRatePoint(
                    symbol="KRW-BTC",
                    funding_rate=0.0007,
                    funding_time=candles[24].timestamp.replace(tzinfo=UTC),
                ),
                FundingRatePoint(
                    symbol="KRW-BTC",
                    funding_rate=-0.0004,
                    funding_time=candles[44].timestamp.replace(tzinfo=UTC),
                ),
            ]
        )

        risk_manager = RiskManager(
            RiskConfig(
                stop_loss_pct=0.05,
                take_profit_pct=0.10,
                max_concurrent_positions=1,
                min_entry_confidence=0.4,
                cooldown_bars=2,
                max_position_pct=0.25,
            )
        )
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk_manager,
            config=BacktestConfig(
                initial_capital=1_000_000.0,
                fee_rate=0.0005,
                slippage_pct=0.0005,
            ),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertTrue(any(trade.position_side == "short" for trade in result.trade_log))
        self.assertGreater(len(result.equity_curve), len(candles))


class TestFundingRateStrategyCorrelation(unittest.TestCase):
    def test_low_correlation_with_momentum(self) -> None:
        from crypto_trader.backtest.correlation import signal_correlation
        from crypto_trader.strategy.momentum import MomentumStrategy

        config = _default_config()
        momentum_strategy = MomentumStrategy(config)
        funding_strategy = FundingRateStrategy(config)
        funding_strategy.set_funding_rate(-0.0003)

        closes = (
            [100.0] * 30
            + [100 + i * 0.5 for i in range(20)]
            + [110.0 - i * 1.0 for i in range(15)]
            + [95.0 + i * 0.3 for i in range(20)]
            + [101.0] * 15
        )
        corr = signal_correlation(
            [momentum_strategy, funding_strategy],
            build_candles(closes),
            ["momentum", "funding_rate"],
        )
        assert ("momentum", "funding_rate") in corr
        assert corr[("momentum", "funding_rate")] < 0.95


class TestCreateStrategyIntegration(unittest.TestCase):
    def test_create_funding_rate_strategy(self) -> None:
        from crypto_trader.config import RegimeConfig
        from crypto_trader.wallet import create_strategy

        strategy = create_strategy("funding_rate", _default_config(), RegimeConfig())
        assert isinstance(strategy, FundingRateStrategy)

    def test_create_with_extra_params(self) -> None:
        from crypto_trader.config import RegimeConfig
        from crypto_trader.wallet import create_strategy

        strategy = create_strategy(
            "funding_rate",
            _default_config(),
            RegimeConfig(),
            extra_params={
                "high_funding_threshold": 0.0005,
                "cooldown_bars": 10,
            },
        )
        assert isinstance(strategy, FundingRateStrategy)
        assert strategy._high_funding == 0.0005
        assert strategy._cooldown_bars == 10


if __name__ == "__main__":
    unittest.main()
