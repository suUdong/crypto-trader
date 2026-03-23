from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from crypto_trader.models import RuntimeCheckpoint


class RuntimeCheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> RuntimeCheckpoint | None:
        if not self._path.exists():
            return None
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return RuntimeCheckpoint(**payload)

    def save(self, checkpoint: RuntimeCheckpoint) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(checkpoint), indent=2), encoding="utf-8")
