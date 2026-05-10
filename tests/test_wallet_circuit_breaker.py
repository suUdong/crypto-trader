"""Integration tests for StrategyWallet ↔ SymbolCircuitBreaker wiring."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from crypto_trader.config import RiskConfig, WalletConfig
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.macro.client import MacroSnapshot
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.risk.symbol_circuit_breaker import (
    SymbolCircuitBreaker,
    SymbolCircuitConfig,
)
from crypto_trader.wallet import StrategyWallet


def _benign_macro() -> MacroSnapshot:
    return MacroSnapshot(
        overall_regime="expansionary",
        overall_confidence=0.6,
        us_regime="expansionary",
        us_confidence=0.6,
        kr_regime="expansionary",
        kr_confidence=0.6,
        crypto_regime="expansionary",
        crypto_confidence=0.6,
        crypto_signals={},
        btc_dominance=55.0,
        kimchi_premium=2.0,
        fear_greed_index=50,
    )


def _candles(closes: list[float]) -> list[Candle]:
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1_000.0 + i,
        )
        for i, c in enumerate(closes)
    ]


class _StaticBuyStrategy:
    def __init__(self, action: SignalAction = SignalAction.BUY) -> None:
        self._action = action

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        return Signal(action=self._action, reason="static_buy", confidence=0.9)


def _make_wallet(
    circuit_breaker: SymbolCircuitBreaker | None,
    strategy: _StaticBuyStrategy | None = None,
) -> StrategyWallet:
    strat = strategy or _StaticBuyStrategy()
    broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
    risk = RiskManager(
        RiskConfig(
            risk_per_trade_pct=0.01,
            stop_loss_pct=0.03,
            take_profit_pct=0.06,
            min_entry_confidence=0.0,
            max_concurrent_positions=5,
            max_position_pct=0.5,
        )
    )
    wallet = StrategyWallet(
        WalletConfig(name="test_wallet", strategy="momentum", initial_capital=1_000_000.0),
        strat,
        broker,
        risk,
        circuit_breaker=circuit_breaker,
    )
    wallet._macro_snapshot = _benign_macro()
    return wallet


class WalletCircuitBreakerTests(unittest.TestCase):
    def test_buy_succeeds_when_breaker_clear(self) -> None:
        cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
        wallet = _make_wallet(cb)
        candles = _candles([100 + i for i in range(10)])
        result = wallet.run_once("KRW-BTC", candles)
        self.assertEqual(result.signal.action, SignalAction.BUY)
        self.assertIsNotNone(result.order)

    def test_disabled_symbol_blocks_buy(self) -> None:
        cb = SymbolCircuitBreaker(
            SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=24)
        )
        # Pre-trip the breaker
        now = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        for i in range(3):
            cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=now + timedelta(hours=i))
        self.assertTrue(cb.is_disabled("KRW-BTC", now + timedelta(hours=3)))

        wallet = _make_wallet(cb)
        # Candles end at hour 9 (well inside the cooldown window)
        candles = _candles([100 + i for i in range(10)])
        result = wallet.run_once("KRW-BTC", candles)
        self.assertEqual(result.signal.action, SignalAction.HOLD)
        self.assertIn("symbol_circuit_breaker", result.signal.reason)
        self.assertIsNone(result.order)

    def test_other_symbols_unaffected_by_disabled_symbol(self) -> None:
        cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
        now = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        for i in range(3):
            cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=now + timedelta(hours=i))
        wallet = _make_wallet(cb)
        # ETH not affected
        result = wallet.run_once("KRW-ETH", _candles([100 + i for i in range(10)]))
        self.assertEqual(result.signal.action, SignalAction.BUY)

    def test_loss_close_is_recorded_to_breaker(self) -> None:
        cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=2, window_hours=48))
        wallet = _make_wallet(cb)
        candles = _candles([100 + i for i in range(10)])
        # Open
        wallet.run_once("KRW-BTC", candles)
        self.assertIn("KRW-BTC", wallet.broker.positions)
        # Force a losing close by injecting a SELL signal
        wallet.strategy = _StaticBuyStrategy(SignalAction.SELL)
        # New candles with a downward move so the realized pnl_pct is negative
        candles_down = _candles([110.0] * 9 + [95.0])
        # Re-attach position into the candle window's last bar so sell processes
        wallet.run_once("KRW-BTC", candles_down)
        self.assertNotIn("KRW-BTC", wallet.broker.positions)
        # The breaker should now hold one losing trade for KRW-BTC
        # (verified by triggering with one more loss to cross threshold=2).
        cb.record_trade(
            "KRW-BTC",
            pnl_pct=-0.05,
            closed_at=datetime(2026, 5, 2, tzinfo=UTC),
        )
        self.assertTrue(cb.is_disabled("KRW-BTC", datetime(2026, 5, 2, tzinfo=UTC)))

    def test_wallet_without_breaker_is_unchanged(self) -> None:
        wallet = _make_wallet(circuit_breaker=None)
        candles = _candles([100 + i for i in range(10)])
        result = wallet.run_once("KRW-BTC", candles)
        self.assertEqual(result.signal.action, SignalAction.BUY)
        self.assertIsNotNone(result.order)


if __name__ == "__main__":
    unittest.main()
