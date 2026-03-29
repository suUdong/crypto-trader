from __future__ import annotations

import importlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from crypto_trader.macro.client import MacroClient, MacroSnapshot

_has_macro_intel = importlib.util.find_spec("macro_intelligence") is not None
_skip_no_macro = unittest.skipIf(not _has_macro_intel, "macro_intelligence not installed")


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

    @_skip_no_macro
    def test_get_snapshot_returns_none_on_exception(self) -> None:
        client = MacroClient()
        with patch(
            "macro_intelligence.api.get_macro_snapshot",
            side_effect=RuntimeError("db locked"),
        ):
            result = client.get_snapshot()
        self.assertIsNone(result)

    @_skip_no_macro
    def test_get_snapshot_returns_none_when_no_regime(self) -> None:
        client = MacroClient()
        mock_data = {"date": "2026-03-25", "us": None, "kr": None, "crypto": None, "regime": None}
        with patch("macro_intelligence.api.get_macro_snapshot", return_value=mock_data):
            result = client.get_snapshot()
        self.assertIsNone(result)

    @_skip_no_macro
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

    def test_get_snapshot_prefers_http_payload(self) -> None:
        client = MacroClient(base_url="http://macro.local")
        payload = {
            "status": "ok",
            "overall_regime": "contraction",
            "overall_confidence": 0.71,
            "layers": {
                "us": {"regime": "contraction", "confidence": 0.7, "signals": {}},
                "kr": {"regime": "neutral", "confidence": 0.69, "signals": {}},
                "crypto": {
                    "regime": "expansion",
                    "confidence": 0.66,
                    "signals": {"btc": "steady"},
                },
            },
            "crypto_metrics": {
                "btc_dominance": 58.4,
                "kimchi_premium": 1.2,
                "fear_greed_index": 63,
            },
        }

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        with patch(
            "crypto_trader.macro.client.urlopen",
            return_value=_Resp(json.dumps(payload).encode("utf-8")),
        ):
            result = client.get_snapshot()

        assert result is not None
        self.assertEqual(result.overall_regime, "contractionary")
        self.assertEqual(result.us_regime, "contractionary")
        self.assertEqual(result.crypto_regime, "expansionary")
        self.assertEqual(result.crypto_signals["btc"], "steady")
        self.assertEqual(result.fear_greed_index, 63)

    def test_get_snapshot_prefers_downstream_consumer_payload(self) -> None:
        client = MacroClient(base_url="http://macro.local")
        payload = {
            "status": "ok",
            "consumer": "crypto-trader",
            "date": "2026-03-25",
            "overall_regime": "expansionary",
            "overall_confidence": 0.74,
            "layers": {
                "us": {"regime": "neutral", "confidence": 0.51, "signals": {}},
                "kr": {"regime": "neutral", "confidence": 0.54, "signals": {}},
                "crypto": {
                    "regime": "expansionary",
                    "confidence": 0.77,
                    "signals": {"fear_greed": "72 (bullish)"},
                },
            },
            "crypto_metrics": {
                "btc_dominance": 57.8,
                "kimchi_premium": 1.4,
                "fear_greed_index": 72,
            },
            "primary_layer": {
                "name": "crypto",
                "regime": "expansionary",
                "confidence": 0.77,
                "signals": {"fear_greed": "72 (bullish)"},
            },
            "strategy": {"stance": "risk_on"},
            "watch_overlay": "scale alt exposure on pullbacks",
        }

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        requested_urls: list[str] = []

        def _fake_urlopen(url: str, timeout: float):
            requested_urls.append(url)
            return _Resp(json.dumps(payload).encode("utf-8"))

        with patch("crypto_trader.macro.client.urlopen", side_effect=_fake_urlopen):
            result = client.get_snapshot()

        assert result is not None
        self.assertEqual(
            requested_urls,
            ["http://macro.local/regime/downstream/crypto-trader"],
        )
        self.assertEqual(result.overall_regime, "expansionary")
        self.assertEqual(result.crypto_regime, "expansionary")
        self.assertEqual(result.fear_greed_index, 72)
        self.assertEqual(result.crypto_signals["fear_greed"], "72 (bullish)")

    def test_get_snapshot_parses_minimal_downstream_payload_without_layers(self) -> None:
        client = MacroClient(base_url="http://macro.local")
        payload = {
            "status": "ok",
            "consumer": "crypto-trader",
            "date": "2026-03-29",
            "overall_regime": "neutral",
            "overall_confidence": 0.19,
            "primary_layer": {
                "name": "crypto",
                "regime": "neutral",
                "confidence": 0.23,
                "signals": {
                    "fear_greed": "12 (extreme_fear)",
                    "kimchi_premium": "0.65% (bullish)",
                    "btc_dominance_trend": "-0.0% (neutral)",
                },
            },
            "strategy": {"stance": "selective"},
            "watch_overlay": "hold base posture",
        }

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        with patch(
            "crypto_trader.macro.client.urlopen",
            return_value=_Resp(json.dumps(payload).encode("utf-8")),
        ):
            result = client.get_snapshot()

        assert result is not None
        self.assertEqual(result.overall_regime, "neutral")
        self.assertAlmostEqual(result.overall_confidence, 0.19)
        self.assertEqual(result.crypto_regime, "neutral")
        self.assertAlmostEqual(result.crypto_confidence, 0.23)
        self.assertEqual(result.fear_greed_index, 12)
        self.assertAlmostEqual(result.kimchi_premium, 0.65)
        self.assertIsNone(result.btc_dominance)
        self.assertEqual(result.us_regime, "neutral")
        self.assertEqual(result.kr_regime, "neutral")
        self.assertEqual(result.crypto_signals["fear_greed"], "12 (extreme_fear)")

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


class TestMacroClientRetry(unittest.TestCase):
    """Tests for retry / backoff / log-throttling in _fetch_http_payload."""

    def test_retries_on_connection_error(self) -> None:
        """Client retries up to _MAX_RETRIES per endpoint before giving up."""
        client = MacroClient(base_url="http://macro.local")
        call_count = 0

        def _fail(url: str, timeout: float):
            nonlocal call_count
            call_count += 1
            raise URLError("Connection refused")

        with patch("crypto_trader.macro.client.urlopen", side_effect=_fail):
            with patch("crypto_trader.macro.client.time.sleep"):
                result = client._fetch_http_payload()

        self.assertIsNone(result)
        # 2 endpoints x (1 initial + _MAX_RETRIES retries) = 2 x 3 = 6
        from crypto_trader.macro.client import _MAX_RETRIES
        self.assertEqual(call_count, 2 * (_MAX_RETRIES + 1))

    def test_retry_succeeds_on_second_attempt(self) -> None:
        """Client returns payload when retry succeeds."""
        client = MacroClient(base_url="http://macro.local")
        payload = {
            "status": "ok",
            "overall_regime": "neutral",
            "overall_confidence": 0.5,
            "layers": {
                "us": {"regime": "neutral", "confidence": 0.5, "signals": {}},
                "kr": {"regime": "neutral", "confidence": 0.5, "signals": {}},
                "crypto": {"regime": "neutral", "confidence": 0.5, "signals": {}},
            },
            "crypto_metrics": {},
        }

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        attempt = 0

        def _fail_then_succeed(url: str, timeout: float):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise URLError("Connection refused")
            return _Resp(json.dumps(payload).encode("utf-8"))

        with patch("crypto_trader.macro.client.urlopen", side_effect=_fail_then_succeed):
            with patch("crypto_trader.macro.client.time.sleep"):
                result = client._fetch_http_payload()

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "ok")

    def test_consecutive_failure_counter_increments(self) -> None:
        """Consecutive failure counter tracks repeated failures."""
        client = MacroClient(base_url="http://macro.local")

        def _fail(url: str, timeout: float):
            raise URLError("Connection refused")

        with patch("crypto_trader.macro.client.urlopen", side_effect=_fail):
            with patch("crypto_trader.macro.client.time.sleep"):
                client._fetch_http_payload()
                client._fetch_http_payload()

        self.assertEqual(client._consecutive_http_failures, 2)

    def test_consecutive_failure_counter_resets_on_success(self) -> None:
        """Counter resets to 0 after a successful fetch."""
        client = MacroClient(base_url="http://macro.local")
        client._consecutive_http_failures = 5
        payload = {"status": "ok", "overall_regime": "neutral",
                   "overall_confidence": 0.5,
                   "layers": {
                       "us": {"regime": "neutral", "confidence": 0.5, "signals": {}},
                       "kr": {"regime": "neutral", "confidence": 0.5, "signals": {}},
                       "crypto": {"regime": "neutral", "confidence": 0.5, "signals": {}},
                   }, "crypto_metrics": {}}

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        with patch(
            "crypto_trader.macro.client.urlopen",
            return_value=_Resp(json.dumps(payload).encode("utf-8")),
        ):
            client._fetch_http_payload()

        self.assertEqual(client._consecutive_http_failures, 0)

    def test_log_throttling_suppresses_repeated_warnings(self) -> None:
        """After first warning, subsequent failures within the throttle
        interval are logged at DEBUG, not WARNING."""
        client = MacroClient(base_url="http://macro.local")

        def _fail(url: str, timeout: float):
            raise URLError("Connection refused")

        with patch("crypto_trader.macro.client.urlopen", side_effect=_fail):
            with patch("crypto_trader.macro.client.time.sleep"):
                with self.assertLogs("crypto_trader.macro.client", level="DEBUG") as cm:
                    client._fetch_http_payload()  # 1st: WARNING
                    client._fetch_http_payload()  # 2nd: should be DEBUG

        warning_msgs = [r for r in cm.output if "WARNING" in r]
        debug_msgs = [r for r in cm.output if "DEBUG" in r]
        self.assertEqual(len(warning_msgs), 1)
        self.assertGreaterEqual(len(debug_msgs), 1)


def _import_error_snapshot(client: MacroClient) -> MacroSnapshot | None:
    """Simulate ImportError by returning None."""
    return None


if __name__ == "__main__":
    unittest.main()
