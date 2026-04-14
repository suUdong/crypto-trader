from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from crypto_trader.operator.runtime_symbol_routing import (
    apply_config_symbol_reload,
    build_active_symbols,
    sync_alpha_watchlist,
)


def _wallet(name: str, allowed: set[str], positions: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        allowed_symbols=set(allowed),
        broker=SimpleNamespace(positions={symbol: object() for symbol in positions or []}),
    )


def test_build_active_symbols_merges_config_wallets_and_positions() -> None:
    wallets = [
        _wallet("accumulation_wallet", {"KRW-RED"}),
        _wallet("momentum_wallet", {"KRW-MON"}, positions=["KRW-OLD"]),
    ]

    active = build_active_symbols(
        ["KRW-BTC", "KRW-RED"],
        wallets,
        fallback_symbol="KRW-FALLBACK",
    )

    assert active == ["KRW-BTC", "KRW-RED", "KRW-MON", "KRW-OLD"]


def test_apply_config_symbol_reload_updates_wallets_and_active_symbols() -> None:
    wallets = [_wallet("momentum_wallet", {"KRW-BTC"}, positions=["KRW-OLD"])]

    result = apply_config_symbol_reload(
        wallets,
        {"momentum_wallet": {"KRW-MON"}},
        preferred_symbols=["KRW-BTC"],
        fallback_symbol=None,
    )

    assert wallets[0].allowed_symbols == {"KRW-MON"}
    assert result.active_symbols == ["KRW-BTC", "KRW-MON", "KRW-OLD"]
    assert result.changes == ["momentum_wallet: ['KRW-BTC'] -> ['KRW-MON']"]


def test_sync_alpha_watchlist_updates_mtime_and_symbols(tmp_path: Path) -> None:
    wallets = [_wallet("accumulation_dood_wallet", {"KRW-OLD"})]
    watchlist_path = tmp_path / "alpha-watchlist.json"
    watchlist_path.write_text(
        json.dumps(
            {
                "rotation_candidates": [
                    {"symbol": "KRW-RED", "alpha": 0.82, "rs": 0.91},
                ],
                "rotation_source": "stealth",
            }
        ),
        encoding="utf-8",
    )

    with patch(
        "crypto_trader.strategy.alpha_calibrator.load_calibration",
        return_value=SimpleNamespace(threshold=1.0, is_usable=True),
    ):
        result = sync_alpha_watchlist(
            watchlist_path,
            previous_mtime=0.0,
            wallets=wallets,
            base_symbols=["KRW-OLD"],
            fallback_symbol=None,
        )

    assert result is not None
    assert wallets[0].allowed_symbols == {"KRW-RED"}
    assert result.alpha_watchlist_mtime > 0.0
    assert result.active_symbols == ["KRW-OLD", "KRW-RED"]
    assert result.changes == [
        "Alpha watchlist: accumulation_dood_wallet symbol {'KRW-OLD'} → KRW-RED (source=stealth)"
    ]
