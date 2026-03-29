from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str, json_format: bool = False) -> None:
    fmt: logging.Formatter
    if json_format:
        fmt = JSONFormatter()
    else:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handler = logging.StreamHandler()
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)


def setup_file_logging(
    path: str,
    level: str = "INFO",
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
) -> None:
    """Add a RotatingFileHandler to the root logger."""
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler.setFormatter(JSONFormatter())
    logging.getLogger().addHandler(handler)
