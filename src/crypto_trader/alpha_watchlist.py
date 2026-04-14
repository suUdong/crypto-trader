from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

EXCLUDED_ALPHA_ROTATION_SYMBOLS = frozenset(
    {
        "KRW-USD1",
    }
)
_HISTORICAL_MONTHLY_240M_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "historical" / "monthly" / "240m"
)
MIN_ACCUMULATION_HISTORY_MONTHS = 12


def filter_rotation_candidates(
    candidates: list[dict[str, Any]],
    *,
    excluded_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = EXCLUDED_ALPHA_ROTATION_SYMBOLS if excluded_symbols is None else excluded_symbols
    return [candidate for candidate in candidates if candidate.get("symbol") not in excluded]


def parse_alpha_watchlist(
    scan_data: str,
    *,
    threshold: float,
    max_symbols: int = 5,
    excluded_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    top_symbols: list[dict[str, Any]] = []
    excluded = EXCLUDED_ALPHA_ROTATION_SYMBOLS if excluded_symbols is None else excluded_symbols
    for line in scan_data.splitlines()[1:]:
        parts = line.split()
        if not parts:
            continue
        try:
            symbol = parts[0]
            alpha_val = float(parts[1])
        except (IndexError, ValueError):
            continue
        if symbol in excluded:
            continue
        if alpha_val < threshold:
            continue
        top_symbols.append({"symbol": symbol, "alpha": alpha_val})
        if len(top_symbols) >= max_symbols:
            break
    return top_symbols


def select_accumulation_candidates(
    rows: list[dict[str, Any]],
    *,
    threshold: float,
    max_symbols: int = 5,
    excluded_symbols: set[str] | None = None,
    min_history_months: int = MIN_ACCUMULATION_HISTORY_MONTHS,
) -> list[dict[str, Any]]:
    excluded = EXCLUDED_ALPHA_ROTATION_SYMBOLS if excluded_symbols is None else excluded_symbols
    scored: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("Symbol", row.get("symbol", "")))
        if not symbol or symbol in excluded:
            continue
        try:
            alpha = float(row.get("Alpha", row.get("alpha", 0.0)))
            rs = float(row.get("RS", row.get("rs", 0.0)))
            acc = float(row.get("Acc", row.get("acc", 0.0)))
            cvd = float(row.get("CVD", row.get("cvd", 0.0)))
        except (TypeError, ValueError):
            continue
        if alpha < threshold:
            continue
        history_months = _historical_month_count(symbol)
        if min_history_months > 0 and history_months < min_history_months:
            continue
        if not (0.5 <= rs < 1.0):
            continue
        if acc < 1.0 or cvd <= 0:
            continue

        rs_center_score = max(0.0, 1.0 - abs(rs - 0.75) / 0.25)
        acc_score = min(1.0, max(0.0, (acc - 1.0) / 0.5))
        cvd_score = min(1.0, cvd / 5.0)
        fitness = round(
            alpha * 0.6
            + rs_center_score * 0.15
            + acc_score * 0.15
            + cvd_score * 0.10,
            4,
        )
        scored.append(
            {
                "symbol": symbol,
                "alpha": round(alpha, 4),
                "rs": round(rs, 4),
                "acc": round(acc, 4),
                "cvd": round(cvd, 4),
                "history_months": history_months,
                "accumulation_fitness": fitness,
            }
        )

    scored.sort(
        key=lambda row: (
            float(row["accumulation_fitness"]),
            float(row["alpha"]),
            float(row["cvd"]),
        ),
        reverse=True,
    )
    return scored[:max_symbols]


@lru_cache(maxsize=512)
def _historical_month_count(symbol: str) -> int:
    if not symbol or not _HISTORICAL_MONTHLY_240M_DIR.exists():
        return 0
    count = 0
    pattern = f"{symbol}_candle-240m_*.zip"
    for year_dir in _HISTORICAL_MONTHLY_240M_DIR.iterdir():
        if not year_dir.is_dir():
            continue
        count += sum(1 for _ in year_dir.glob(pattern))
    return count


def advance_symbol_streaks(
    previous: dict[str, int],
    current_symbols: list[str],
) -> dict[str, int]:
    current_set = set(current_symbols)
    return {
        symbol: previous.get(symbol, 0) + 1
        for symbol in current_symbols
        if symbol in current_set
    }


def load_rotation_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "alpha_streaks": {},
            "stealth_streaks": {},
            "alpha_last_bar": "",
            "stealth_last_bar": "",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "alpha_streaks": {},
            "stealth_streaks": {},
            "alpha_last_bar": "",
            "stealth_last_bar": "",
        }
    alpha = payload.get("alpha_streaks", {})
    stealth = payload.get("stealth_streaks", {})
    return {
        "alpha_streaks": {
            str(symbol): int(count)
            for symbol, count in alpha.items()
            if isinstance(count, int | float)
        },
        "stealth_streaks": {
            str(symbol): int(count)
            for symbol, count in stealth.items()
            if isinstance(count, int | float)
        },
        "alpha_last_bar": str(payload.get("alpha_last_bar", "")),
        "stealth_last_bar": str(payload.get("stealth_last_bar", "")),
    }


def save_rotation_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def update_rotation_state(
    previous_state: dict[str, Any],
    *,
    alpha_symbols: list[str],
    stealth_symbols: list[str],
    bar_id: str = "",
) -> dict[str, Any]:
    alpha_last_bar = str(previous_state.get("alpha_last_bar", ""))
    stealth_last_bar = str(previous_state.get("stealth_last_bar", ""))

    alpha_streaks = previous_state.get("alpha_streaks", {})
    if not bar_id or alpha_last_bar != bar_id:
        alpha_streaks = advance_symbol_streaks(alpha_streaks, alpha_symbols)
        alpha_last_bar = bar_id

    stealth_streaks = previous_state.get("stealth_streaks", {})
    if not bar_id or stealth_last_bar != bar_id:
        stealth_streaks = advance_symbol_streaks(stealth_streaks, stealth_symbols)
        stealth_last_bar = bar_id

    return {
        "alpha_streaks": alpha_streaks,
        "stealth_streaks": stealth_streaks,
        "alpha_last_bar": alpha_last_bar,
        "stealth_last_bar": stealth_last_bar,
    }


def select_persistent_candidates(
    candidates: list[dict[str, Any]],
    *,
    streaks: dict[str, int],
    min_streak: int,
    max_symbols: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        symbol = str(candidate.get("symbol", ""))
        if streaks.get(symbol, 0) < min_streak:
            continue
        selected.append(candidate)
        if len(selected) >= max_symbols:
            break
    return selected


def _normalize_rotation_rows(
    rows: list[dict[str, Any]],
    *,
    excluded_symbols: set[str] | None = None,
    min_alpha_threshold: float | None = None,
) -> list[dict[str, Any]]:
    excluded = EXCLUDED_ALPHA_ROTATION_SYMBOLS if excluded_symbols is None else excluded_symbols
    normalized: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol", "")).strip()
        if not symbol or symbol in excluded:
            continue
        if min_alpha_threshold is not None:
            try:
                alpha = float(row.get("alpha", 0.0))
            except (TypeError, ValueError):
                continue
            if alpha < min_alpha_threshold:
                continue
        normalized_row = dict(row)
        normalized_row["symbol"] = symbol
        normalized.append(normalized_row)
    return normalized


def extract_rotation_candidates(
    payload: Mapping[str, Any],
    *,
    threshold: float,
    excluded_symbols: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return the approved rotation pool from an alpha-watchlist payload.

    New payloads expose `rotation_candidates`, which already passed the
    persistence gate in `market_scan_loop.py`. Those rows should be trusted
    as-is, even when they came from the stealth fallback path and their alpha
    score is below the calibrated threshold.

    Legacy payloads did not include `rotation_candidates`, so we fall back to
    filtering `accumulation_candidates` / `top_symbols` by the current alpha
    threshold to preserve old behavior.
    """

    if "rotation_candidates" in payload:
        source = payload.get("rotation_source")
        rows = payload.get("rotation_candidates") or []
        return (
            _normalize_rotation_rows(rows, excluded_symbols=excluded_symbols),
            str(source) if source else None,
        )

    for key, source in (
        ("alpha_rotation_candidates", "alpha"),
        ("stealth_rotation_candidates", "stealth"),
    ):
        if key in payload:
            rows = payload.get(key) or []
            return (
                _normalize_rotation_rows(rows, excluded_symbols=excluded_symbols),
                source,
            )

    for key in ("accumulation_candidates", "top_symbols"):
        if key in payload:
            rows = payload.get(key) or []
            return (
                _normalize_rotation_rows(
                    rows,
                    excluded_symbols=excluded_symbols,
                    min_alpha_threshold=threshold,
                ),
                "alpha",
            )

    return [], None
