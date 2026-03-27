"""Tests for RiskManager.effective_min_confidence adaptive threshold."""

from __future__ import annotations

import pytest

from crypto_trader.config import RiskConfig
from crypto_trader.risk.manager import RiskManager


def make_risk_manager(min_entry_confidence: float = 0.6) -> RiskManager:
    config = RiskConfig(min_entry_confidence=min_entry_confidence)
    return RiskManager(config)


def test_fewer_than_5_trades_returns_base():
    rm = make_risk_manager(min_entry_confidence=0.6)
    for _ in range(4):
        rm.record_trade(0.01)
    assert rm.effective_min_confidence == pytest.approx(0.6)


def test_zero_trades_returns_base():
    rm = make_risk_manager(min_entry_confidence=0.55)
    assert rm.effective_min_confidence == pytest.approx(0.55)


def test_high_win_rate_lowers_confidence():
    rm = make_risk_manager(min_entry_confidence=0.6)
    # 7 wins, 3 losses in 10 trades = 70% win rate -> base - 0.1
    for _ in range(7):
        rm.record_trade(0.02)
    for _ in range(3):
        rm.record_trade(-0.01)
    assert rm.effective_min_confidence == pytest.approx(0.5)


def test_low_win_rate_raises_confidence():
    rm = make_risk_manager(min_entry_confidence=0.6)
    # 3 wins, 7 losses in 10 trades = 30% win rate -> base + 0.1
    for _ in range(3):
        rm.record_trade(0.02)
    for _ in range(7):
        rm.record_trade(-0.01)
    assert rm.effective_min_confidence == pytest.approx(0.7)


def test_normal_win_rate_returns_base():
    rm = make_risk_manager(min_entry_confidence=0.6)
    # 5 wins, 5 losses in 10 trades = 50% win rate -> base unchanged
    for _ in range(5):
        rm.record_trade(0.02)
    for _ in range(5):
        rm.record_trade(-0.01)
    assert rm.effective_min_confidence == pytest.approx(0.6)


def test_clamp_lower_bound():
    # base=0.35, high win rate would give 0.25, clamped to 0.3
    rm = make_risk_manager(min_entry_confidence=0.35)
    for _ in range(7):
        rm.record_trade(0.02)
    for _ in range(3):
        rm.record_trade(-0.01)
    assert rm.effective_min_confidence == pytest.approx(0.3)


def test_clamp_upper_bound():
    # base=0.85, low win rate would give 0.95, clamped to 0.9
    rm = make_risk_manager(min_entry_confidence=0.85)
    for _ in range(3):
        rm.record_trade(0.02)
    for _ in range(7):
        rm.record_trade(-0.01)
    assert rm.effective_min_confidence == pytest.approx(0.9)


def test_uses_last_20_trades():
    rm = make_risk_manager(min_entry_confidence=0.6)
    # Record 25 trades: first 15 are losses (ignored beyond window), last 10 all wins
    for _ in range(15):
        rm.record_trade(-0.05)
    # The last 20 = 5 losses + 10 wins + 5 more wins = need to be careful
    # Let's use exactly: 5 losses then 15 wins (total 20 in window = last 20)
    for _ in range(5):
        rm.record_trade(-0.05)
    for _ in range(5):
        rm.record_trade(0.05)
    # _trade_history has 25 trades; last 20 = 5 losses + 5 from first batch? No:
    # indices 0-14: losses (15), 15-19: losses (5), 20-24: wins (5)
    # last 20 = indices 5-24 = 10 losses + 5 losses + 5 wins = 5 wins / 20 = 25% win rate -> raise
    assert rm.effective_min_confidence == pytest.approx(0.7)
