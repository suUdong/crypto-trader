"""Tests for entry-time blackout window (item 2 from CT paper audit 2026-05-11)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RiskConfig, WalletConfig
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import Candle, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import StrategyWallet, create_strategy
from tests.test_wallet import (
    _benign_macro_snapshot,
    _make_regime_config,
    _make_strategy_config,
)


def _candles_at_hour(start_hour_utc: int, closes: list[float]) -> list[Candle]:
    """Build candles whose latest timestamp falls on `start_hour_utc + len(closes) - 1` UTC."""
    start = datetime(2025, 1, 1, start_hour_utc, 0, 0)
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


def _build_wallet(blackout: tuple[int, ...]) -> StrategyWallet:
    strategy_config = _make_strategy_config()
    regime_config = _make_regime_config()
    strategy = create_strategy("momentum", strategy_config, regime_config)
    broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
    risk_cfg = RiskConfig(
        risk_per_trade_pct=0.01,
        stop_loss_pct=0.03,
        take_profit_pct=0.06,
        max_daily_loss_pct=0.05,
        max_concurrent_positions=5,
        min_entry_confidence=0.0,
        entry_blackout_utc_hours=blackout,
    )
    risk_manager = RiskManager(risk_cfg)
    wallet_config = WalletConfig(
        name="blackout_test_wallet",
        strategy="momentum",
        initial_capital=1_000_000.0,
    )
    wallet = StrategyWallet(wallet_config, strategy, broker, risk_manager)
    wallet._macro_snapshot = _benign_macro_snapshot()
    return wallet


class EntryBlackoutTests(unittest.TestCase):
    """A BUY signal at a UTC hour inside the blackout window must be downgraded
    to HOLD; outside the window it must still fire."""

    rising_closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]

    def test_buy_inside_blackout_is_blocked(self) -> None:
        # start_hour=15 + len(10)-1 = hour 24 (rolls to next day hour 0)
        candles = _candles_at_hour(15, self.rising_closes)
        self.assertEqual(candles[-1].timestamp.hour, 0)
        wallet = _build_wallet(blackout=(23, 0, 1, 2))

        result = wallet.run_once("KRW-BTC", candles)

        self.assertIsNone(result.error)
        self.assertEqual(result.signal.action, SignalAction.HOLD)
        self.assertIn("blackout", (result.signal.reason or "").lower())
        self.assertIsNone(result.order)

    def test_buy_outside_blackout_still_fires(self) -> None:
        # latest candle hour = 9 UTC -> outside (23,0,1,2)
        candles = _candles_at_hour(0, self.rising_closes)
        self.assertEqual(candles[-1].timestamp.hour, 9)
        wallet = _build_wallet(blackout=(23, 0, 1, 2))

        result = wallet.run_once("KRW-BTC", candles)

        self.assertIsNone(result.error)
        self.assertEqual(result.signal.action, SignalAction.BUY)
        self.assertIsNotNone(result.order)

    def test_empty_blackout_is_a_noop(self) -> None:
        # latest candle hour = 0 UTC, but blackout is empty -> BUY allowed
        candles = _candles_at_hour(15, self.rising_closes)
        wallet = _build_wallet(blackout=())

        result = wallet.run_once("KRW-BTC", candles)

        self.assertIsNone(result.error)
        self.assertEqual(result.signal.action, SignalAction.BUY)


if __name__ == "__main__":
    unittest.main()
