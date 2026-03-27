"""Tests for volume-adaptive slippage in PaperBroker."""

from datetime import UTC, datetime

import pytest

from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import OrderRequest, OrderSide


class TestAdaptiveSlippage:
    def _broker(self) -> PaperBroker:
        return PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.001)

    def test_default_slippage_unchanged(self) -> None:
        b = self._broker()
        buy_price = b._apply_slippage(OrderSide.BUY, 100.0)
        sell_price = b._apply_slippage(OrderSide.SELL, 100.0)
        assert buy_price == pytest.approx(100.1)
        assert sell_price == pytest.approx(99.9)

    def test_high_volume_reduces_slippage(self) -> None:
        b = self._broker()
        buy_normal = b._apply_slippage(OrderSide.BUY, 100.0, volume_ratio=1.0)
        buy_high = b._apply_slippage(OrderSide.BUY, 100.0, volume_ratio=3.0)
        # High volume should give better (lower) buy fill
        assert buy_high < buy_normal

    def test_low_volume_increases_slippage(self) -> None:
        b = self._broker()
        buy_normal = b._apply_slippage(OrderSide.BUY, 100.0, volume_ratio=1.0)
        buy_low = b._apply_slippage(OrderSide.BUY, 100.0, volume_ratio=0.3)
        # Low volume should give worse (higher) buy fill
        assert buy_low > buy_normal

    def test_high_volume_slippage_is_60pct_of_base(self) -> None:
        b = self._broker()
        # base slippage = 0.001, high volume = 0.0006
        buy = b._apply_slippage(OrderSide.BUY, 100.0, volume_ratio=2.5)
        assert buy == pytest.approx(100.0 * (1 + 0.001 * 0.6))

    def test_low_volume_slippage_is_150pct_of_base(self) -> None:
        b = self._broker()
        sell = b._apply_slippage(OrderSide.SELL, 100.0, volume_ratio=0.2)
        assert sell == pytest.approx(100.0 * (1 - 0.001 * 1.5))

    def test_submit_order_accepts_volume_ratio(self) -> None:
        """Smoke test: volume_ratio flows through submit_order."""
        b = self._broker()
        result = b.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=0.001,
                requested_at=datetime.now(UTC),
                reason="test",
            ),
            market_price=100_000_000.0,
            volume_ratio=3.0,
        )
        assert result.status == "filled"
        # High volume → reduced slippage → lower fill price than default
        default_fill = 100_000_000.0 * (1 + 0.001)
        assert result.fill_price < default_fill
