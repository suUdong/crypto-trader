from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.operator.stealth_watchlist import read_stealth_watchlist_bool


def test_read_stealth_watchlist_bool_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert read_stealth_watchlist_bool("btc_bull_regime", path=tmp_path / "missing.json") is None


def test_read_stealth_watchlist_bool_returns_none_for_stale_file(tmp_path: Path) -> None:
    path = tmp_path / "stealth-watchlist.json"
    path.write_text(
        json.dumps(
            {
                "updated_at": (datetime.now(UTC) - timedelta(hours=4)).isoformat(),
                "btc_bull_regime": True,
            }
        ),
        encoding="utf-8",
    )

    assert read_stealth_watchlist_bool("btc_bull_regime", path=path) is None


def test_read_stealth_watchlist_bool_treats_naive_timestamp_as_utc(tmp_path: Path) -> None:
    now = datetime(2026, 4, 11, 12, tzinfo=UTC)
    path = tmp_path / "stealth-watchlist.json"
    path.write_text(
        json.dumps(
            {
                "updated_at": "2026-04-11T10:00:00",
                "btc_bull_regime": False,
            }
        ),
        encoding="utf-8",
    )

    assert read_stealth_watchlist_bool("btc_bull_regime", path=path, now=now) is False


def test_read_stealth_watchlist_bool_returns_requested_flag(tmp_path: Path) -> None:
    path = tmp_path / "stealth-watchlist.json"
    path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "btc_bull_regime": True,
                "btc_30bar_pos": False,
            }
        ),
        encoding="utf-8",
    )

    assert read_stealth_watchlist_bool("btc_bull_regime", path=path) is True
    assert read_stealth_watchlist_bool("btc_30bar_pos", path=path) is False
