"""Tests for symbol-level circuit breaker (CT P1 audit item 4).

Auto-disables a symbol after configurable loss bursts inside a rolling
window; re-enables after a cooldown. State is persisted to disk so the
behaviour survives daemon restarts.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crypto_trader.risk.symbol_circuit_breaker import (
    SymbolCircuitBreaker,
    SymbolCircuitConfig,
)


def _ts(hours: float, base: datetime | None = None) -> datetime:
    base = base or datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    return base + timedelta(hours=hours)


def test_no_losses_means_symbol_is_enabled() -> None:
    cb = SymbolCircuitBreaker(SymbolCircuitConfig())
    assert cb.is_disabled("KRW-BTC", _ts(0)) is False
    assert cb.disable_reason("KRW-BTC") == ""


def test_single_loss_does_not_disable() -> None:
    cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(0))
    assert cb.is_disabled("KRW-BTC", _ts(1)) is False


def test_two_losses_does_not_disable_with_threshold_three() -> None:
    cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(0))
    cb.record_trade("KRW-BTC", pnl_pct=-0.02, closed_at=_ts(1))
    assert cb.is_disabled("KRW-BTC", _ts(2)) is False


def test_three_losses_inside_window_disables() -> None:
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=24)
    )
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(0))
    cb.record_trade("KRW-BTC", pnl_pct=-0.02, closed_at=_ts(1))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(2))
    assert cb.is_disabled("KRW-BTC", _ts(3)) is True
    reason = cb.disable_reason("KRW-BTC")
    assert "loss_burst" in reason


def test_disable_clears_after_cooldown_hours() -> None:
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=24)
    )
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(0))
    cb.record_trade("KRW-BTC", pnl_pct=-0.02, closed_at=_ts(1))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(2))
    assert cb.is_disabled("KRW-BTC", _ts(2)) is True
    # 23h after the 3rd loss → still cooling
    assert cb.is_disabled("KRW-BTC", _ts(2 + 23)) is True
    # 24h after the 3rd loss → re-enabled
    assert cb.is_disabled("KRW-BTC", _ts(2 + 24 + 0.01)) is False


def test_old_losses_outside_window_do_not_count() -> None:
    cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(0))
    # 49h gap → first loss falls out of the rolling window
    cb.record_trade("KRW-BTC", pnl_pct=-0.02, closed_at=_ts(49))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(50))
    assert cb.is_disabled("KRW-BTC", _ts(50)) is False


def test_wins_do_not_count_toward_loss_burst() -> None:
    cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(0))
    cb.record_trade("KRW-BTC", pnl_pct=+0.05, closed_at=_ts(1))  # winner
    cb.record_trade("KRW-BTC", pnl_pct=-0.02, closed_at=_ts(2))
    cb.record_trade("KRW-BTC", pnl_pct=+0.04, closed_at=_ts(3))  # winner
    assert cb.is_disabled("KRW-BTC", _ts(4)) is False


def test_expectancy_threshold_disables_after_min_trades() -> None:
    # expectancy_threshold_pct=-0.005, min 5 trades; expectancy = mean(pnl_pct)
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(
            loss_threshold=99,
            window_hours=48,
            cooldown_hours=24,
            expectancy_threshold_pct=-0.005,
            min_trades_for_expectancy=5,
        )
    )
    # Mean pnl_pct = -0.01 over 5 trades → below -0.005 floor
    for i in range(5):
        cb.record_trade("KRW-XRP", pnl_pct=-0.01, closed_at=_ts(i))
    assert cb.is_disabled("KRW-XRP", _ts(5)) is True
    assert "expectancy" in cb.disable_reason("KRW-XRP")


def test_expectancy_does_not_fire_below_min_trades() -> None:
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(
            loss_threshold=99,
            window_hours=48,
            cooldown_hours=24,
            expectancy_threshold_pct=-0.005,
            min_trades_for_expectancy=5,
        )
    )
    for i in range(4):
        cb.record_trade("KRW-XRP", pnl_pct=-0.02, closed_at=_ts(i))
    assert cb.is_disabled("KRW-XRP", _ts(5)) is False


def test_symbols_are_independent() -> None:
    cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
    for i in range(3):
        cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(i))
    cb.record_trade("KRW-ETH", pnl_pct=-0.01, closed_at=_ts(0))
    assert cb.is_disabled("KRW-BTC", _ts(3)) is True
    assert cb.is_disabled("KRW-ETH", _ts(3)) is False


def test_alert_callback_fires_only_on_state_transition() -> None:
    events: list[tuple[str, str, str]] = []  # (symbol, transition, reason)

    def on_change(symbol: str, transition: str, reason: str) -> None:
        events.append((symbol, transition, reason))

    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=1),
        on_state_change=on_change,
    )
    # 3 losses → one disable event
    for i in range(3):
        cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(i))
    assert cb.is_disabled("KRW-BTC", _ts(3)) is True
    disable_events = [e for e in events if e[1] == "disabled"]
    assert len(disable_events) == 1
    assert disable_events[0][0] == "KRW-BTC"

    # Cooldown elapses → re-enable event must fire exactly once
    cb.is_disabled("KRW-BTC", _ts(3 + 1.01))
    enable_events = [e for e in events if e[1] == "re_enabled"]
    assert len(enable_events) == 1


def test_alert_callback_not_called_on_non_loss() -> None:
    events: list[tuple[str, str, str]] = []
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48),
        on_state_change=lambda s, t, r: events.append((s, t, r)),
    )
    cb.record_trade("KRW-BTC", pnl_pct=+0.04, closed_at=_ts(0))
    cb.record_trade("KRW-BTC", pnl_pct=+0.05, closed_at=_ts(1))
    assert events == []


def test_state_persists_across_save_load(tmp_path: Path) -> None:
    state_path = tmp_path / "symbol-circuit.json"
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=24)
    )
    for i in range(3):
        cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(i))
    assert cb.is_disabled("KRW-BTC", _ts(3)) is True
    cb.save(state_path)
    assert state_path.exists()

    # Reload into a fresh instance — disabled state must survive
    cb2 = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=24)
    )
    cb2.load(state_path)
    assert cb2.is_disabled("KRW-BTC", _ts(3)) is True

    # And the cooldown clock continues from the persisted disable timestamp
    assert cb2.is_disabled("KRW-BTC", _ts(2 + 24 + 0.01)) is False


def test_load_missing_file_is_noop(tmp_path: Path) -> None:
    cb = SymbolCircuitBreaker(SymbolCircuitConfig())
    cb.load(tmp_path / "does-not-exist.json")
    assert cb.is_disabled("KRW-BTC", _ts(0)) is False


def test_save_writes_jsonl_event_on_disable(tmp_path: Path) -> None:
    events_path = tmp_path / "circuit-breaker-events.jsonl"
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=24),
        events_path=events_path,
    )
    for i in range(3):
        cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(i))
    assert cb.is_disabled("KRW-BTC", _ts(3)) is True
    assert events_path.exists()
    lines = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["symbol"] == "KRW-BTC"
    assert lines[0]["transition"] == "disabled"
    assert "category" in lines[0]
    assert lines[0]["category"] == "circuit_breaker"


def test_jsonl_events_for_disable_and_reenable(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=1),
        events_path=events_path,
    )
    for i in range(3):
        cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(i))
    cb.is_disabled("KRW-BTC", _ts(2 + 1.01))  # triggers re-enable
    lines = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    transitions = [line["transition"] for line in lines]
    assert transitions == ["disabled", "re_enabled"]


def test_reenable_after_cooldown_restarts_with_clean_window() -> None:
    """After re-enable, the loss window starts fresh — old losses don't double-disable."""
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=1)
    )
    for i in range(3):
        cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(i))
    assert cb.is_disabled("KRW-BTC", _ts(2)) is True
    # Cooldown clears
    assert cb.is_disabled("KRW-BTC", _ts(2 + 1.01)) is False
    # One more loss right after re-enable — must NOT instantly re-disable
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(2 + 1.5))
    assert cb.is_disabled("KRW-BTC", _ts(2 + 1.6)) is False


def test_zero_pnl_is_treated_as_neither_win_nor_loss() -> None:
    cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(0))
    cb.record_trade("KRW-BTC", pnl_pct=0.0, closed_at=_ts(1))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(2))
    cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(3))
    assert cb.is_disabled("KRW-BTC", _ts(4)) is True


def test_disabled_returns_remaining_cooldown_seconds() -> None:
    cb = SymbolCircuitBreaker(
        SymbolCircuitConfig(loss_threshold=3, window_hours=48, cooldown_hours=24)
    )
    for i in range(3):
        cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=_ts(i))
    remaining = cb.cooldown_seconds_remaining("KRW-BTC", _ts(2 + 1))
    # 24h cooldown, 1h elapsed → ~23h
    assert remaining == pytest.approx(23 * 3600, rel=0.01)


def test_record_trade_with_naive_datetime_is_normalized_to_utc() -> None:
    """Daemon may pass tz-naive timestamps; breaker should normalize."""
    cb = SymbolCircuitBreaker(SymbolCircuitConfig(loss_threshold=3, window_hours=48))
    naive_base = datetime(2026, 5, 1, 0, 0)
    for i in range(3):
        cb.record_trade("KRW-BTC", pnl_pct=-0.01, closed_at=naive_base + timedelta(hours=i))
    assert cb.is_disabled("KRW-BTC", _ts(3)) is True
