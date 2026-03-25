from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from crypto_trader.config import (
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
    WalletConfig,
)
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import OrderRequest, OrderSide
from crypto_trader.operator.strategy_report import StrategyComparisonReport
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import StrategyWallet, create_strategy


def _make_wallet(
    name: str,
    strategy_type: str = "momentum",
    cash: float = 1_000_000.0,
) -> StrategyWallet:
    wc = WalletConfig(name=name, strategy=strategy_type, initial_capital=cash)
    strategy = create_strategy(strategy_type, StrategyConfig(), RegimeConfig())
    broker = PaperBroker(starting_cash=cash, fee_rate=0.0, slippage_pct=0.0)
    risk_manager = RiskManager(RiskConfig())
    return StrategyWallet(wc, strategy, broker, risk_manager)


class StrategyComparisonReportTests(unittest.TestCase):
    def test_generate_with_no_wallets(self) -> None:
        report = StrategyComparisonReport().generate(
            wallets=[], symbols=["KRW-BTC"], latest_prices={"KRW-BTC": 100_000_000}
        )
        self.assertIn("# Strategy Comparison Report", report)
        self.assertIn("Wallets: 0", report)

    def test_generate_single_wallet_no_trades(self) -> None:
        wallet = _make_wallet("w1")
        report = StrategyComparisonReport().generate(
            wallets=[wallet],
            symbols=["KRW-BTC"],
            latest_prices={"KRW-BTC": 100_000_000},
        )
        self.assertIn("w1", report)
        self.assertIn("momentum", report)
        self.assertIn("0.0%", report)

    def test_generate_wallet_with_closed_trades(self) -> None:
        wallet = _make_wallet("w1")
        wallet.broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=0.01,
                requested_at=datetime(2026, 1, 1),
                reason="entry",
            ),
            market_price=100_000_000,
        )
        wallet.broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.SELL,
                quantity=0.01,
                requested_at=datetime(2026, 1, 1, 1),
                reason="exit",
            ),
            market_price=110_000_000,
        )
        report = StrategyComparisonReport().generate(
            wallets=[wallet],
            symbols=["KRW-BTC"],
            latest_prices={"KRW-BTC": 110_000_000},
        )
        self.assertIn("100.0%", report)  # win rate
        self.assertIn("1", report)  # trade count

    def test_generate_wallet_with_open_position(self) -> None:
        wallet = _make_wallet("w1")
        wallet.broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=0.01,
                requested_at=datetime(2026, 1, 1),
                reason="entry",
            ),
            market_price=100_000_000,
        )
        report = StrategyComparisonReport().generate(
            wallets=[wallet],
            symbols=["KRW-BTC"],
            latest_prices={"KRW-BTC": 110_000_000},
        )
        self.assertIn("Per-Symbol Positions", report)
        self.assertIn("KRW-BTC", report)

    def test_generate_multiple_wallets_rankings(self) -> None:
        w1 = _make_wallet("momentum_w", "momentum")
        w2 = _make_wallet("meanrev_w", "mean_reversion")
        # Give w1 a trade
        w1.broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                quantity=0.01,
                requested_at=datetime(2026, 1, 1),
                reason="entry",
            ),
            market_price=100_000_000,
        )
        w1.broker.submit_order(
            OrderRequest(
                symbol="KRW-BTC",
                side=OrderSide.SELL,
                quantity=0.01,
                requested_at=datetime(2026, 1, 1, 1),
                reason="exit",
            ),
            market_price=110_000_000,
        )
        report = StrategyComparisonReport().generate(
            wallets=[w1, w2],
            symbols=["KRW-BTC"],
            latest_prices={"KRW-BTC": 110_000_000},
        )
        self.assertIn("Performance Rankings", report)
        self.assertIn("By Return %", report)
        self.assertIn("By Trade Count", report)

    def test_generate_no_positions_skips_position_section(self) -> None:
        wallet = _make_wallet("w1")
        report = StrategyComparisonReport().generate(
            wallets=[wallet],
            symbols=["KRW-BTC"],
            latest_prices={"KRW-BTC": 100_000_000},
        )
        self.assertNotIn("Entry Price", report)

    def test_save_writes_report_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sub" / "report.md"
            StrategyComparisonReport().save("# report", path)
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "# report")

    def test_generate_multiple_symbols(self) -> None:
        wallet = _make_wallet("w1")
        report = StrategyComparisonReport().generate(
            wallets=[wallet],
            symbols=["KRW-BTC", "KRW-ETH", "KRW-XRP"],
            latest_prices={"KRW-BTC": 100_000_000},
        )
        self.assertIn("KRW-BTC, KRW-ETH, KRW-XRP", report)
