from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from crypto_trader.alpha_watchlist import extract_rotation_candidates


class _BrokerLike(Protocol):
    positions: Mapping[str, object]


class WalletRouteTarget(Protocol):
    name: str
    allowed_symbols: set[str]
    broker: _BrokerLike


@dataclass(frozen=True, slots=True)
class SymbolReloadResult:
    active_symbols: list[str]
    changes: list[str]


@dataclass(frozen=True, slots=True)
class AlphaWatchlistSyncResult:
    alpha_watchlist_mtime: float
    active_symbols: list[str]
    changes: list[str]


def build_active_symbols(
    base_symbols: Sequence[str],
    wallets: Sequence[object],
    *,
    excluded_symbols: set[str] | None = None,
    fallback_symbol: str | None = None,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    excluded = excluded_symbols or set()

    def append(symbol: str) -> None:
        if symbol and symbol not in excluded and symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)

    for symbol in base_symbols:
        append(symbol)
    for wallet_obj in wallets:
        wallet = cast(WalletRouteTarget, wallet_obj)
        for symbol in sorted(wallet.allowed_symbols):
            append(symbol)
        for symbol in wallet.broker.positions:
            if symbol and symbol not in seen:
                seen.add(symbol)
                ordered.append(symbol)
    if not ordered and fallback_symbol:
        append(fallback_symbol)
    return ordered


def apply_config_symbol_reload(
    wallets: Sequence[object],
    new_wallet_symbols: Mapping[str, set[str]],
    *,
    excluded_symbols: set[str] | None = None,
    preferred_symbols: Sequence[str],
    fallback_symbol: str | None = None,
) -> SymbolReloadResult:
    changes: list[str] = []
    for wallet_obj in wallets:
        wallet = cast(WalletRouteTarget, wallet_obj)
        new_syms = new_wallet_symbols.get(wallet.name)
        if new_syms is None:
            continue
        if new_syms != wallet.allowed_symbols:
            before = sorted(wallet.allowed_symbols)
            after = sorted(new_syms)
            wallet.allowed_symbols = set(new_syms)
            changes.append(f"{wallet.name}: {before} -> {after}")

    active_symbols = build_active_symbols(
        preferred_symbols,
        wallets,
        excluded_symbols=excluded_symbols,
        fallback_symbol=fallback_symbol,
    )
    return SymbolReloadResult(active_symbols=active_symbols, changes=changes)


def sync_alpha_watchlist(
    path: Path,
    previous_mtime: float,
    wallets: Sequence[object],
    *,
    excluded_symbols: set[str] | None = None,
    base_symbols: Sequence[str],
    fallback_symbol: str | None = None,
) -> AlphaWatchlistSyncResult | None:
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    if mtime <= previous_mtime:
        return None

    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    from crypto_trader.strategy.alpha_calibrator import load_calibration

    calibration = load_calibration()
    threshold = calibration.threshold if calibration.is_usable else 1.0
    candidate_rows, rotation_source = extract_rotation_candidates(data, threshold=threshold)
    new_symbols = [str(row["symbol"]) for row in candidate_rows]

    changes: list[str] = []
    if new_symbols:
        acc_wallets = [
            cast(WalletRouteTarget, wallet_obj)
            for wallet_obj in wallets
            if "accumulation" in cast(WalletRouteTarget, wallet_obj).name
        ]
        for index, wallet in enumerate(acc_wallets):
            symbol = new_symbols[index % len(new_symbols)]
            old = wallet.allowed_symbols.copy()
            wallet.allowed_symbols = {symbol}
            if old != wallet.allowed_symbols:
                changes.append(
                    f"Alpha watchlist: {wallet.name} symbol {old} → {symbol} "
                    f"(source={rotation_source or 'legacy'})"
                )

    active_symbols = build_active_symbols(
        base_symbols,
        wallets,
        excluded_symbols=excluded_symbols,
        fallback_symbol=fallback_symbol,
    )
    return AlphaWatchlistSyncResult(
        alpha_watchlist_mtime=mtime,
        active_symbols=active_symbols,
        changes=changes,
    )
