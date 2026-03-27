import unittest
from datetime import datetime, timedelta

from crypto_trader.models import Candle
from crypto_trader.risk.correlation_guard import CorrelationGuard


def _candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=price,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=1_000.0 + i,
        )
        for i, price in enumerate(closes)
    ]


class TestCorrelationGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = CorrelationGuard(max_cluster_exposure=3)

    def test_allows_entry_when_no_exposure(self) -> None:
        result = self.guard.check_entry("KRW-BTC", "momentum_btc", {})
        self.assertTrue(result.allowed)
        self.assertEqual(result.current_exposure, 0)

    def test_allows_entry_within_limit(self) -> None:
        exposure = {"major_crypto": ["momentum_btc", "vpin_btc"]}
        result = self.guard.check_entry("KRW-ETH", "momentum_eth", exposure)
        self.assertTrue(result.allowed)
        self.assertEqual(result.current_exposure, 2)

    def test_blocks_entry_at_limit(self) -> None:
        exposure = {"major_crypto": ["momentum_btc", "vpin_btc", "kimchi"]}
        result = self.guard.check_entry("KRW-SOL", "vpin_sol", exposure)
        self.assertFalse(result.allowed)
        self.assertIn("exposure_3/3", result.reason)

    def test_allows_unknown_symbol(self) -> None:
        result = self.guard.check_entry(
            "KRW-DOGE",
            "doge_wallet",
            {"major_crypto": ["a", "b", "c"]},
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "symbol_not_in_cluster")

    def test_get_cluster_exposure(self) -> None:
        positions = [
            ("momentum_btc", "KRW-BTC"),
            ("vpin_eth", "KRW-ETH"),
            ("kimchi", "KRW-SOL"),
        ]
        exposure = self.guard.get_cluster_exposure(positions)
        self.assertEqual(len(exposure["major_crypto"]), 3)

    def test_get_cluster_exposure_deduplicates_wallets(self) -> None:
        """One wallet with multiple symbols in same cluster counts as 1."""
        positions = [
            ("kimchi", "KRW-BTC"),
            ("kimchi", "KRW-ETH"),
            ("kimchi", "KRW-SOL"),
            ("kimchi", "KRW-XRP"),
        ]
        exposure = self.guard.get_cluster_exposure(positions)
        self.assertEqual(len(exposure["major_crypto"]), 1)
        self.assertEqual(exposure["major_crypto"], ["kimchi"])

    def test_deduplicated_exposure_allows_entry_below_limit(self) -> None:
        positions = [
            ("kimchi", "KRW-BTC"),
            ("kimchi", "KRW-ETH"),
            ("vpin_eth", "KRW-ETH"),
        ]
        exposure = self.guard.get_cluster_exposure(positions)
        result = self.guard.check_entry("KRW-SOL", "momentum_sol", exposure)
        self.assertTrue(result.allowed)
        self.assertEqual(result.current_exposure, 2)

    def test_deduplicated_exposure_blocks_at_limit(self) -> None:
        positions = [
            ("kimchi", "KRW-BTC"),
            ("kimchi", "KRW-ETH"),
            ("vpin_eth", "KRW-ETH"),
            ("ema_xrp", "KRW-XRP"),
        ]
        exposure = self.guard.get_cluster_exposure(positions)
        result = self.guard.check_entry("KRW-SOL", "momentum_sol", exposure)
        self.assertFalse(result.allowed)
        self.assertEqual(result.current_exposure, 3)
        self.assertIn("exposure_3/3", result.reason)

    def test_custom_clusters(self) -> None:
        guard = CorrelationGuard(
            max_cluster_exposure=1,
            clusters={"layer1": ["KRW-ETH", "KRW-SOL"]},
        )
        exposure = {"layer1": ["vpin_eth"]}
        result = guard.check_entry("KRW-SOL", "vpin_sol", exposure)
        self.assertFalse(result.allowed)

    def test_default_max_exposure_is_six(self) -> None:
        guard = CorrelationGuard()
        self.assertEqual(guard._max_cluster_exposure, 6)

    def test_build_snapshot_tracks_high_correlation_pairs(self) -> None:
        guard = CorrelationGuard(
            max_cluster_exposure=3,
            max_correlation=0.8,
            max_high_correlation_exposure=1,
        )
        snapshot = guard.build_snapshot(
            {
                "KRW-BTC": _candles([100, 102, 101, 104, 103, 106]),
                "KRW-ETH": _candles([50, 51, 50.5, 52, 51.5, 53]),
                "KRW-XRP": _candles([20, 19, 20, 18, 19, 17]),
            },
            [("btc_wallet", "KRW-BTC")],
        )

        self.assertGreater(snapshot.correlation_for("KRW-BTC", "KRW-ETH"), 0.8)
        self.assertIn(("KRW-BTC", "KRW-ETH"), snapshot.high_correlation_pairs)
        self.assertNotIn(("KRW-BTC", "KRW-XRP"), snapshot.high_correlation_pairs)

    def test_blocks_entry_when_highly_correlated_symbol_already_open(self) -> None:
        guard = CorrelationGuard(
            max_cluster_exposure=6,
            max_correlation=0.8,
            max_high_correlation_exposure=1,
        )
        snapshot = guard.build_snapshot(
            {
                "KRW-BTC": _candles([100, 102, 101, 104, 103, 106]),
                "KRW-ETH": _candles([50, 51, 50.5, 52, 51.5, 53]),
            },
            [("btc_wallet", "KRW-BTC")],
        )

        result = guard.check_entry(
            "KRW-ETH",
            "eth_wallet",
            {"major_crypto": ["btc_wallet"]},
            correlation_snapshot=snapshot,
        )

        self.assertFalse(result.allowed)
        self.assertIn("high_correlation", result.reason)
        self.assertEqual(result.current_exposure, 1)
        self.assertIn("KRW-BTC", result.blocking_symbols)


if __name__ == "__main__":
    unittest.main()
