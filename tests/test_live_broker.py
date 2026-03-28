"""Tests for LiveBroker with mocked pyupbit."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

# Ensure pyupbit module is available even if not installed
_mock_pyupbit = MagicMock()
sys.modules.setdefault("pyupbit", _mock_pyupbit)

from crypto_trader.execution.live import LiveBroker  # noqa: E402
from crypto_trader.models import OrderRequest, OrderSide, OrderType  # noqa: E402


@pytest.fixture
def mock_upbit():
    instance = MagicMock()
    with patch("crypto_trader.execution.live.pyupbit") as mock_mod:
        mock_mod.Upbit.return_value = instance
        # Ensure pyupbit is not None so __init__ doesn't raise ImportError
        yield instance


@pytest.fixture
def broker(mock_upbit):
    return LiveBroker(
        access_key="test-key",
        secret_key="test-secret",
        starting_cash=1_000_000.0,
        fee_rate=0.0005,
    )


def test_live_broker_requires_credentials():
    with pytest.raises(ValueError, match="credentials required"):
        LiveBroker(access_key="", secret_key="test", starting_cash=100_000.0)


def test_buy_market_order(broker, mock_upbit):
    mock_upbit.buy_market_order.return_value = {"uuid": "order-123"}
    mock_upbit.get_order.return_value = {
        "state": "done",
        "trades": [{"price": "50000000", "volume": "0.001"}],
        "paid_fee": "25.0",
    }

    request = OrderRequest(
        symbol="KRW-BTC",
        side=OrderSide.BUY,
        quantity=0.001,
        requested_at=datetime.now(UTC),
        reason="test_buy",
        confidence=0.8,
    )
    result = broker.submit_order(request, market_price=50_000_000.0)

    assert result.status == "filled"
    assert result.order_id == "order-123"
    assert result.quantity == 0.001
    mock_upbit.buy_market_order.assert_called_once()


def test_sell_market_order(broker, mock_upbit):
    # First set up a position
    from crypto_trader.models import Position

    broker.positions["KRW-BTC"] = Position(
        symbol="KRW-BTC",
        quantity=0.001,
        entry_price=50_000_000.0,
        entry_time=datetime.now(UTC),
        entry_fee_paid=25.0,
    )
    broker.cash = 950_000.0

    mock_upbit.sell_market_order.return_value = {"uuid": "sell-456"}
    mock_upbit.get_order.return_value = {
        "state": "done",
        "trades": [{"price": "51000000", "volume": "0.001"}],
        "paid_fee": "25.5",
    }

    request = OrderRequest(
        symbol="KRW-BTC",
        side=OrderSide.SELL,
        quantity=0.001,
        requested_at=datetime.now(UTC),
        reason="test_sell",
    )
    result = broker.submit_order(request, market_price=51_000_000.0)

    assert result.status == "filled"
    assert result.order_id == "sell-456"
    assert len(broker.closed_trades) == 1
    assert "KRW-BTC" not in broker.positions
    mock_upbit.sell_market_order.assert_called_once()


def test_buy_insufficient_cash(broker, mock_upbit):
    request = OrderRequest(
        symbol="KRW-BTC",
        side=OrderSide.BUY,
        quantity=100.0,  # Way more than cash allows
        requested_at=datetime.now(UTC),
        reason="too_expensive",
    )
    result = broker.submit_order(request, market_price=50_000_000.0)

    assert result.status == "rejected"
    assert result.reason == "insufficient_cash"
    mock_upbit.buy_market_order.assert_not_called()


def test_buy_below_minimum(broker, mock_upbit):
    request = OrderRequest(
        symbol="KRW-BTC",
        side=OrderSide.BUY,
        quantity=0.0000001,  # Below 5000 KRW minimum
        requested_at=datetime.now(UTC),
        reason="too_small",
    )
    result = broker.submit_order(request, market_price=50_000_000.0)

    assert result.status == "rejected"
    assert result.reason == "below_minimum_order"


def test_sell_no_position(broker, mock_upbit):
    request = OrderRequest(
        symbol="KRW-BTC",
        side=OrderSide.SELL,
        quantity=0.001,
        requested_at=datetime.now(UTC),
        reason="no_pos",
    )
    result = broker.submit_order(request, market_price=50_000_000.0)

    assert result.status == "rejected"
    assert result.reason == "insufficient_position"


def test_exchange_error_retries(broker, mock_upbit):
    mock_upbit.buy_market_order.side_effect = [
        None,
        None,
        {"uuid": "retry-ok"},
    ]
    mock_upbit.get_order.return_value = {
        "state": "done",
        "trades": [{"price": "50000000", "volume": "0.001"}],
        "paid_fee": "25.0",
    }

    request = OrderRequest(
        symbol="KRW-BTC",
        side=OrderSide.BUY,
        quantity=0.001,
        requested_at=datetime.now(UTC),
        reason="retry_test",
        confidence=0.7,
    )
    with patch("crypto_trader.execution.live.time.sleep"):
        result = broker.submit_order(request, market_price=50_000_000.0)

    assert result.status == "filled"
    assert mock_upbit.buy_market_order.call_count == 3


def test_exchange_error_all_retries_fail(broker, mock_upbit):
    mock_upbit.buy_market_order.return_value = None

    request = OrderRequest(
        symbol="KRW-BTC",
        side=OrderSide.BUY,
        quantity=0.001,
        requested_at=datetime.now(UTC),
        reason="fail_test",
    )
    with patch("crypto_trader.execution.live.time.sleep"):
        result = broker.submit_order(request, market_price=50_000_000.0)

    assert result.status == "rejected"
    assert result.reason == "exchange_error"


def test_equity(broker, mock_upbit):
    from crypto_trader.models import Position

    broker.cash = 500_000.0
    broker.positions["KRW-BTC"] = Position(
        symbol="KRW-BTC",
        quantity=0.01,
        entry_price=50_000_000.0,
        entry_time=datetime.now(UTC),
    )
    eq = broker.equity({"KRW-BTC": 51_000_000.0})
    assert eq == 500_000.0 + 0.01 * 51_000_000.0


def test_estimate_costs(broker, mock_upbit):
    assert broker.estimate_entry_cost_pct(OrderType.MARKET) == 0.0005
    assert broker.estimate_round_trip_cost_pct(OrderType.MARKET) == 0.001
