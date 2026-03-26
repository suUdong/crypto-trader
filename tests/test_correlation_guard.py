import unittest

from crypto_trader.risk.correlation_guard import CorrelationGuard, ExposureCheck


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
        result = self.guard.check_entry("KRW-DOGE", "doge_wallet", {"major_crypto": ["a", "b", "c"]})
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


if __name__ == "__main__":
    unittest.main()
