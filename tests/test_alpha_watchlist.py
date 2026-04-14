from __future__ import annotations

from pathlib import Path

from crypto_trader.alpha_watchlist import (
    MIN_ACCUMULATION_HISTORY_MONTHS,
    advance_symbol_streaks,
    extract_rotation_candidates,
    load_rotation_state,
    parse_alpha_watchlist,
    save_rotation_state,
    select_accumulation_candidates,
    select_persistent_candidates,
    update_rotation_state,
)


def test_parse_alpha_watchlist_filters_excluded_and_threshold() -> None:
    scan_data = """Symbol Alpha RS Acc CVD
KRW-MMT 1.33 0.80 1.10 0.50
KRW-USD1 1.20 0.95 1.20 0.40
KRW-MON 0.40 0.70 1.05 0.30
KRW-SAFE 1.05 0.82 1.22 0.60
"""

    rows = parse_alpha_watchlist(scan_data, threshold=1.0)

    assert rows == [
        {"symbol": "KRW-MMT", "alpha": 1.33},
        {"symbol": "KRW-SAFE", "alpha": 1.05},
    ]


def test_advance_symbol_streaks_resets_absent_symbols() -> None:
    streaks = advance_symbol_streaks({"KRW-MMT": 2, "KRW-MON": 1}, ["KRW-MMT", "KRW-SAFE"])

    assert streaks == {"KRW-MMT": 3, "KRW-SAFE": 1}


def test_update_rotation_state_tracks_alpha_and_stealth_independently() -> None:
    state = update_rotation_state(
        {
            "alpha_streaks": {"KRW-MMT": 1},
            "stealth_streaks": {"KRW-SAFE": 2},
            "alpha_last_bar": "2026-04-10T00:00:00+00:00",
            "stealth_last_bar": "2026-04-10T00:00:00+00:00",
        },
        alpha_symbols=["KRW-MMT", "KRW-MON"],
        stealth_symbols=["KRW-SAFE"],
        bar_id="2026-04-10T04:00:00+00:00",
    )

    assert state["alpha_streaks"] == {"KRW-MMT": 2, "KRW-MON": 1}
    assert state["stealth_streaks"] == {"KRW-SAFE": 3}
    assert state["alpha_last_bar"] == "2026-04-10T04:00:00+00:00"
    assert state["stealth_last_bar"] == "2026-04-10T04:00:00+00:00"


def test_update_rotation_state_does_not_increment_twice_for_same_bar() -> None:
    state = update_rotation_state(
        {
            "alpha_streaks": {"KRW-MMT": 2},
            "stealth_streaks": {"KRW-SAFE": 3},
            "alpha_last_bar": "2026-04-10T04:00:00+00:00",
            "stealth_last_bar": "2026-04-10T04:00:00+00:00",
        },
        alpha_symbols=["KRW-MMT", "KRW-MON"],
        stealth_symbols=["KRW-SAFE", "KRW-NEW"],
        bar_id="2026-04-10T04:00:00+00:00",
    )

    assert state["alpha_streaks"] == {"KRW-MMT": 2}
    assert state["stealth_streaks"] == {"KRW-SAFE": 3}


def test_select_persistent_candidates_preserves_rank_order() -> None:
    candidates = [
        {"symbol": "KRW-MMT", "alpha": 1.3},
        {"symbol": "KRW-MON", "alpha": 1.2},
        {"symbol": "KRW-SAFE", "alpha": 1.1},
    ]

    rows = select_persistent_candidates(
        candidates,
        streaks={"KRW-MMT": 2, "KRW-MON": 1, "KRW-SAFE": 3},
        min_streak=2,
        max_symbols=2,
    )

    assert rows == [
        {"symbol": "KRW-MMT", "alpha": 1.3},
        {"symbol": "KRW-SAFE", "alpha": 1.1},
    ]


def test_rotation_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "alpha-rotation-state.json"
    save_rotation_state(
        path,
        {
            "alpha_streaks": {"KRW-MMT": 2},
            "stealth_streaks": {"KRW-SAFE": 3},
            "alpha_last_bar": "2026-04-10T04:00:00+00:00",
            "stealth_last_bar": "2026-04-10T04:00:00+00:00",
        },
    )

    loaded = load_rotation_state(path)

    assert loaded == {
        "alpha_streaks": {"KRW-MMT": 2},
        "stealth_streaks": {"KRW-SAFE": 3},
        "alpha_last_bar": "2026-04-10T04:00:00+00:00",
        "stealth_last_bar": "2026-04-10T04:00:00+00:00",
    }


def test_select_accumulation_candidates_prefers_alignment_with_strategy_filters(
    monkeypatch,
) -> None:
    rows = [
        {"Symbol": "KRW-USD1", "Alpha": 1.5, "RS": 0.8, "Acc": 1.2, "CVD": 0.6},
        {"Symbol": "KRW-MMT", "Alpha": 1.3, "RS": 0.74, "Acc": 1.3, "CVD": 1.2},
        {"Symbol": "KRW-MON", "Alpha": 1.4, "RS": 1.1, "Acc": 1.4, "CVD": 1.3},
        {"Symbol": "KRW-SAFE", "Alpha": 1.1, "RS": 0.78, "Acc": 1.1, "CVD": 0.7},
    ]
    monkeypatch.setattr(
        "crypto_trader.alpha_watchlist._historical_month_count",
        lambda symbol: {"KRW-MMT": 24, "KRW-SAFE": 24}.get(symbol, 0),
    )

    selected = select_accumulation_candidates(rows, threshold=1.0, max_symbols=3)

    assert [row["symbol"] for row in selected] == ["KRW-MMT", "KRW-SAFE"]
    assert selected[0]["accumulation_fitness"] > selected[1]["accumulation_fitness"]


def test_select_accumulation_candidates_excludes_red_like_short_history_cluster(
    monkeypatch,
) -> None:
    rows = [
        {"Symbol": "KRW-ONT", "Alpha": 1.3, "RS": 0.74, "Acc": 1.3, "CVD": 1.2},
        {"Symbol": "KRW-RED", "Alpha": 1.4, "RS": 0.72, "Acc": 1.4, "CVD": 1.1},
        {"Symbol": "KRW-RAY", "Alpha": 1.2, "RS": 0.78, "Acc": 1.1, "CVD": 0.8},
    ]
    month_counts = {"KRW-ONT": 24, "KRW-RED": 7, "KRW-RAY": 10}
    monkeypatch.setattr(
        "crypto_trader.alpha_watchlist._historical_month_count",
        lambda symbol: month_counts.get(symbol, 0),
    )

    selected = select_accumulation_candidates(rows, threshold=1.0, max_symbols=5)

    assert [row["symbol"] for row in selected] == ["KRW-ONT"]
    assert selected[0]["history_months"] >= MIN_ACCUMULATION_HISTORY_MONTHS


def test_extract_rotation_candidates_respects_empty_persistent_gate() -> None:
    payload = {
        "rotation_candidates": [],
        "rotation_source": "alpha",
        "accumulation_candidates": [
            {"symbol": "KRW-MMT", "alpha": 1.3},
            {"symbol": "KRW-SAFE", "alpha": 1.1},
        ],
    }

    selected, source = extract_rotation_candidates(payload, threshold=1.0)

    assert selected == []
    assert source == "alpha"


def test_extract_rotation_candidates_keeps_approved_stealth_rows_without_alpha_gate() -> None:
    payload = {
        "rotation_candidates": [
            {"symbol": "KRW-RED", "alpha": 0.82, "rs": 0.91, "acc": 1.22},
        ],
        "rotation_source": "stealth",
    }

    selected, source = extract_rotation_candidates(payload, threshold=1.0)

    assert selected == [
        {"symbol": "KRW-RED", "alpha": 0.82, "rs": 0.91, "acc": 1.22},
    ]
    assert source == "stealth"
