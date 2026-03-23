from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from crypto_trader.models import StrategyRunRecord


class StrategyRunJournal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def append(self, record: StrategyRunRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=True))
            handle.write("\n")

    def load_recent(self, limit: int = 20) -> list[StrategyRunRecord]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        recent = lines[-limit:]
        records: list[StrategyRunRecord] = []
        for line in recent:
            payload = json.loads(line)
            records.append(StrategyRunRecord(**payload))
        return records
