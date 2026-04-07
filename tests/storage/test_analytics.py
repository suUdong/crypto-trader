"""Tests for the DuckDB analytics layer over SqliteStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from crypto_trader.storage import SqliteStore, TradeRow
from crypto_trader.storage.analytics import AnalyticsView


def _trade(
    *,
    wallet: str,
    pnl_pct: float,
    exit_reason: str,
    exit_time: str,
    session_id: str = "s1",
) -> TradeRow:
    return TradeRow(
        wallet=wallet,
        symbol="KRW-DOGE",
        entry_time=exit_time,  # exact time doesn't matter for these tests
        exit_time=exit_time,
        entry_price=140.0,
        exit_price=140.0 * (1 + pnl_pct),
        quantity=100.0,
        pnl=140.0 * pnl_pct * 100.0,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
        session_id=session_id,
    )


@pytest.fixture()
def populated_store(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(tmp_path / "analytics.sqlite")
    rows = [
        _trade(
            wallet="vpin_doge_wallet",
            pnl_pct=-0.0085,
            exit_reason="atr_stop_loss",
            exit_time="2026-04-07T01:00:00+00:00",
            session_id=f"s{i}",
        )
        for i in range(11)
    ]
    rows += [
        _trade(
            wallet="vpin_ondo_wallet",
            pnl_pct=0.012,
            exit_reason="rsi_overbought",
            exit_time="2026-04-07T02:00:00+00:00",
            session_id=f"o{i}",
        )
        for i in range(5)
    ]
    rows += [
        _trade(
            wallet="vpin_ondo_wallet",
            pnl_pct=-0.005,
            exit_reason="atr_stop_loss",
            exit_time="2026-04-07T03:00:00+00:00",
            session_id=f"o{i}_loss",
        )
        for i in range(2)
    ]
    for r in rows:
        store.insert_trade(r)
    return store


class TestWalletStats:
    def test_returns_one_row_per_wallet(self, populated_store: SqliteStore) -> None:
        view = AnalyticsView(populated_store)
        stats = view.wallet_stats()
        wallets = {s.wallet for s in stats}
        assert wallets == {"vpin_doge_wallet", "vpin_ondo_wallet"}

    def test_doge_wallet_has_zero_win_rate(self, populated_store: SqliteStore) -> None:
        view = AnalyticsView(populated_store)
        doge = next(s for s in view.wallet_stats() if s.wallet == "vpin_doge_wallet")
        assert doge.trade_count == 11
        assert doge.win_rate == 0.0
        assert doge.avg_pnl_pct < 0

    def test_ondo_wallet_has_5_of_7_winners(
        self, populated_store: SqliteStore
    ) -> None:
        view = AnalyticsView(populated_store)
        ondo = next(s for s in view.wallet_stats() if s.wallet == "vpin_ondo_wallet")
        assert ondo.trade_count == 7
        assert ondo.win_rate == pytest.approx(5 / 7)
        assert ondo.avg_pnl_pct > 0


class TestExitReasonDistribution:
    def test_doge_atr_stop_loss_dominates(
        self, populated_store: SqliteStore
    ) -> None:
        view = AnalyticsView(populated_store)
        dist = view.exit_reason_distribution(wallet="vpin_doge_wallet")
        assert dist == {"atr_stop_loss": 11}

    def test_ondo_has_two_exit_reasons(
        self, populated_store: SqliteStore
    ) -> None:
        view = AnalyticsView(populated_store)
        dist = view.exit_reason_distribution(wallet="vpin_ondo_wallet")
        assert dist == {"rsi_overbought": 5, "atr_stop_loss": 2}


class TestRecentTrades:
    def test_filters_by_iso_cutoff(self, populated_store: SqliteStore) -> None:
        view = AnalyticsView(populated_store)
        recent = view.recent_trades(since="2026-04-07T02:30:00+00:00")
        # Only the 2 ondo loss rows have exit_time >= cutoff
        assert len(recent) == 2
        assert all(t.wallet == "vpin_ondo_wallet" for t in recent)
