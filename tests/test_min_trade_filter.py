"""Tests for minimum trade notional filter in StrategyWallet."""

from datetime import UTC, datetime

from crypto_trader.config import RegimeConfig, RiskConfig, StrategyConfig, WalletConfig
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import Candle, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import StrategyWallet, create_strategy


def _make_candles(n: int = 50, price: float = 100.0, volume: float = 1000.0) -> list[Candle]:
    base = datetime(2026, 3, 27, 22, 0, 0, tzinfo=UTC)  # peak hour
    return [
        Candle(
            timestamp=base.replace(hour=(22 + i) % 24),
            open=price,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=volume,
        )
        for i in range(n)
    ]


def _make_wallet(
    cash: float = 1_000_000.0,
    risk_per_trade: float = 0.01,
) -> StrategyWallet:
    sc = StrategyConfig()
    rc = RegimeConfig()
    risk_cfg = RiskConfig(
        risk_per_trade_pct=risk_per_trade,
        min_entry_confidence=0.0,  # disable confidence gate for testing
        stop_loss_pct=0.03,
        max_position_pct=0.25,
    )
    strategy = create_strategy("momentum", sc, rc)
    broker = PaperBroker(starting_cash=cash, fee_rate=0.0005, slippage_pct=0.0005)
    risk_manager = RiskManager(risk_cfg)
    wc = WalletConfig(name="test_wallet", strategy="momentum", symbols=["KRW-TEST"])
    return StrategyWallet(wc, strategy, broker, risk_manager)


class TestMinTradeFilter:
    def test_min_notional_constant_exists(self) -> None:
        assert StrategyWallet._MIN_NOTIONAL == 10_000.0

    def test_tiny_trade_is_filtered(self) -> None:
        """With very low cash, the sized quantity should produce notional < 10K and be skipped."""
        wallet = _make_wallet(cash=100.0, risk_per_trade=0.001)
        candles = _make_candles(price=50_000_000.0)  # BTC-like price
        result = wallet.run_once("KRW-TEST", candles)
        # Should not produce a buy order (too small)
        assert result.order is None

    def test_normal_trade_passes_filter(self) -> None:
        """With adequate cash, trades pass the min notional filter."""
        wallet = _make_wallet(cash=1_000_000.0, risk_per_trade=0.01)
        candles = _make_candles(price=100.0)
        result = wallet.run_once("KRW-TEST", candles)
        # The strategy may or may not signal buy depending on indicators,
        # but if it does, the filter should not block it
        if result.signal.action is SignalAction.BUY:
            # If confidence was sufficient and order was placed, notional should be >= 10K
            if result.order is not None:
                assert result.order.quantity * result.order.fill_price >= 10_000.0


class TestVolumeRatio:
    def test_volume_ratio_normal(self) -> None:
        candles = _make_candles(n=30, volume=1000.0)
        ratio = StrategyWallet._volume_ratio(candles)
        assert 0.9 <= ratio <= 1.1  # all equal volumes → ~1.0

    def test_volume_ratio_spike(self) -> None:
        candles = _make_candles(n=30, volume=1000.0)
        # Last candle has 5x volume
        candles[-1] = Candle(
            timestamp=candles[-1].timestamp,
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=5000.0,
        )
        ratio = StrategyWallet._volume_ratio(candles)
        assert ratio > 4.0

    def test_volume_ratio_thin(self) -> None:
        candles = _make_candles(n=30, volume=1000.0)
        candles[-1] = Candle(
            timestamp=candles[-1].timestamp,
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=100.0,
        )
        ratio = StrategyWallet._volume_ratio(candles)
        assert ratio < 0.2

    def test_single_candle_returns_one(self) -> None:
        candles = _make_candles(n=1)
        assert StrategyWallet._volume_ratio(candles) == 1.0
