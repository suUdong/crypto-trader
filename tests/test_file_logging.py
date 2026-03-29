"""Tests for setup_file_logging ensuring daemon logs go to file."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from crypto_trader.logging_utils import setup_file_logging, setup_logging


class TestFileLogging(unittest.TestCase):
    def test_setup_file_logging_creates_log_file(self) -> None:
        """setup_file_logging should create and write to the specified log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = str(Path(tmpdir) / "test-daemon.log")
            setup_logging("INFO")
            setup_file_logging(log_path, level="INFO")

            logger = logging.getLogger("test_file_logging_creates")
            logger.info("hello from test")

            # Flush handlers
            for h in logging.getLogger().handlers:
                h.flush()

            content = Path(log_path).read_text(encoding="utf-8")
            self.assertIn("hello from test", content)

        # Cleanup: remove the file handler we added
        root = logging.getLogger()
        root.handlers = [h for h in root.handlers if not hasattr(h, "baseFilename")]

    def test_setup_file_logging_creates_parent_dirs(self) -> None:
        """setup_file_logging should create missing parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = str(Path(tmpdir) / "nested" / "deep" / "daemon.log")
            setup_file_logging(log_path, level="INFO")

            self.assertTrue(Path(log_path).parent.exists())

        root = logging.getLogger()
        root.handlers = [h for h in root.handlers if not hasattr(h, "baseFilename")]

    def test_file_logging_uses_json_format(self) -> None:
        """File handler should write JSON-formatted log entries."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = str(Path(tmpdir) / "json-daemon.log")
            setup_logging("INFO")
            setup_file_logging(log_path, level="INFO")

            logger = logging.getLogger("test_json_format")
            logger.info("json check")

            for h in logging.getLogger().handlers:
                h.flush()

            content = Path(log_path).read_text(encoding="utf-8").strip()
            entry = json.loads(content.splitlines()[-1])
            self.assertIn("message", entry)
            self.assertIn("json check", entry["message"])

        root = logging.getLogger()
        root.handlers = [h for h in root.handlers if not hasattr(h, "baseFilename")]


if __name__ == "__main__":
    unittest.main()
