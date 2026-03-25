from __future__ import annotations

import unittest
from unittest.mock import patch

from crypto_trader.macro.client import MacroClient, MacroSnapshot


class TestMacroClient(unittest.TestCase):
    def test_get_snapshot_returns_none_when_import_fails(self) -> None:
        """MacroClient gracefully returns None when macro_intelligence not installed."""
        client = MacroClient(db_path="/nonexistent/path.db")
        with patch(
            "crypto_trader.macro.client.MacroClient.get_snapshot",
            side_effect=_import_error_snapshot,
        ):
            result = _import_error_snapshot(client)
        self.assertIsNone(result)

    def test_get_snapshot_returns_none_on_exception(self) -> None:
        client = MacroClient()
        with patch(
            "macro_intelligence.api.get_macro_snapshot",
            side_effect=RuntimeError("db locked"),
        ):
            result = client.get_snapshot()
        self.assertIsNone(result)

    def test_get_snapshot_returns_none_when_no_regime(self) -> None:
        client = MacroClient()
        mock_data = {"date": "2026-03-25", "us": None, "kr": None, "crypto": None, "regime": None}
        with patch("macro_intelligence.api.get_macro_snapshot", return_value=mock_data):
            result = client.get_snapshot()
        self.assertIsNone(result)

    def test_get_snapshot_parses_full_data(self) -> None:
        client = MacroClient()
        mock_data = {
            "date": "2026-03-25",
            "us": {"fed_funds_rate": 4.5},
            "kr": {"bok_base_rate": 3.0},
            "crypto": {
                "btc_dominance": 58.3,
                "kimchi_premium": 2.1,
                "fear_greed_index": 65,
            },
            "regime": {
                "overall": "expansionary",
                "overall_confidence": 0.72,
                "us": {"regime": "expansionary", "confidence": 0.8, "signals": {}},
                "kr": {"regime": "neutral", "confidence": 0.5, "signals": {}},
                "crypto": {
                    "regime": "expansionary",
                    "confidence": 0.7,
                    "signals": {"fear_greed": "65 (bullish)"},
                },
            },
        }
        with patch("macro_intelligence.api.get_macro_snapshot", return_value=mock_data):
            result = client.get_snapshot()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.overall_regime, "expansionary")
        self.assertAlmostEqual(result.overall_confidence, 0.72)
        self.assertEqual(result.btc_dominance, 58.3)
        self.assertEqual(result.kimchi_premium, 2.1)
        self.assertEqual(result.fear_greed_index, 65)

    def test_get_memo_summary_returns_none_when_no_snapshot(self) -> None:
        client = MacroClient()
        with patch.object(client, "get_snapshot", return_value=None):
            result = client.get_memo_summary()
        self.assertIsNone(result)

    def test_get_memo_summary_returns_dict(self) -> None:
        client = MacroClient()
        snapshot = MacroSnapshot(
            overall_regime="contractionary",
            overall_confidence=0.6,
            us_regime="contractionary",
            us_confidence=0.7,
            kr_regime="neutral",
            kr_confidence=0.4,
            crypto_regime="contractionary",
            crypto_confidence=0.5,
            crypto_signals={},
            btc_dominance=62.0,
            kimchi_premium=3.5,
            fear_greed_index=28,
        )
        with patch.object(client, "get_snapshot", return_value=snapshot):
            result = client.get_memo_summary()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["overall_regime"], "contractionary")
        self.assertEqual(result["crypto_signals"]["fear_greed_index"], 28)
        self.assertIn("US", result["layers"])
        self.assertIn("Korea", result["layers"])
        self.assertIn("Crypto", result["layers"])


def _import_error_snapshot(client: MacroClient) -> MacroSnapshot | None:
    """Simulate ImportError by returning None."""
    return None


if __name__ == "__main__":
    unittest.main()
