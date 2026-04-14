from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

STEALTH_WATCHLIST_PATH = Path("artifacts/stealth-watchlist.json")
STEALTH_WATCHLIST_MAX_AGE_HOURS = 3.0


def read_stealth_watchlist_bool(
    key: str,
    *,
    path: Path = STEALTH_WATCHLIST_PATH,
    max_age_hours: float = STEALTH_WATCHLIST_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> bool | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        current_time = now or datetime.now(UTC)
        age_hours = (current_time - updated_at).total_seconds() / 3600
        if age_hours > max_age_hours:
            return None
        return bool(payload.get(key, True))
    except Exception:
        return None
