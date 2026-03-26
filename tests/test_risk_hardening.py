"""Tests for risk management hardening: max_position_pct, tiered kill switch, slippage monitor."""
from __future__ import annotations

import pytest
from crypto_trader.config import RiskConfig, KillSwitchCfg
from crypto_trader.risk.manager import RiskManager
from crypto_trader.risk.kill_switch import KillSwitch, KillSwitchConfig, KillSwitchState
from crypto_trader.risk.slippage_monitor import SlippageMonitor, SlippageStats


# ── max_position_pct cap ──────────────────────────────────────────────


class TestMaxPositionPct:
    def test_default_cap_is_25_percent(self):
        cfg = RiskConfig()
        assert cfg.max_position_pct == 0.25

    def test_position_capped_at_max_pct(self):
        cfg = RiskConfig(
            risk_per_trade_pct=0.5,
            stop_loss_pct=0.01,
            max_position_pct=0.10,
        )
        rm = RiskManager(cfg)
        equity = 1_000_000.0
        price = 100.0
        qty = rm.size_position(equity, price)
        position_value = qty * price
        assert position_value <= equity * 0.10 + 1e-6

    def test_position_not_capped_when_small(self):
        cfg = RiskConfig(
            risk_per_trade_pct=0.005,
            stop_loss_pct=0.03,
            max_position_pct=0.25,
        )
        rm = RiskManager(cfg)
        equity = 1_000_000.0
        price = 50_000.0
        qty = rm.size_position(equity, price)
        position_value = qty * price
        assert position_value <= equity * 0.25 + 1e-6
        # With small risk_per_trade, should be well below cap
        assert position_value < equity * 0.20

    def test_cap_with_macro_multiplier(self):
        cfg = RiskConfig(
            risk_per_trade_pct=0.5,
            stop_loss_pct=0.01,
            max_position_pct=0.15,
        )
        rm = RiskManager(cfg)
        equity = 1_000_000.0
        price = 100.0
        qty = rm.size_position(equity, price, macro_multiplier=2.0)
        position_value = qty * price
        assert position_value <= equity * 0.15 + 1e-6

    def test_cap_zero_price(self):
        cfg = RiskConfig(max_position_pct=0.25)
        rm = RiskManager(cfg)
        assert rm.size_position(1_000_000, 0.0) == 0.0

    def test_cap_zero_equity(self):
        cfg = RiskConfig(max_position_pct=0.25)
        rm = RiskManager(cfg)
        assert rm.size_position(0.0, 100.0) == 0.0


# ── Tiered Kill Switch ────────────────────────────────────────────────


class TestTieredKillSwitch:
    def _make_ks(self, **kwargs) -> KillSwitch:
        defaults = dict(
            max_portfolio_drawdown_pct=0.10,
            max_daily_loss_pct=0.10,  # match portfolio DD to isolate tests
            max_consecutive_losses=5,
            warn_threshold_pct=0.5,
            reduce_threshold_pct=0.75,
            reduce_position_factor=0.5,
        )
        defaults.update(kwargs)
        return KillSwitch(config=KillSwitchConfig(**defaults))

    def _ks_with_peak(self, **kwargs) -> KillSwitch:
        """Create kill switch and establish peak equity at 1M."""
        ks = self._make_ks(**kwargs)
        ks.check(1_000_000, 1_000_000, 0.0)  # establish peak
        return ks

    def test_no_warning_below_threshold(self):
        ks = self._ks_with_peak()
        # 2% drawdown = 20% of 10% limit, below 50% warn threshold
        state = ks.check(980_000, 1_000_000, 0.0)
        assert not state.triggered
        assert not state.warning_active
        assert state.position_size_penalty == 1.0

    def test_warning_at_50pct_of_limit(self):
        ks = self._ks_with_peak()
        # 6% drawdown = 60% of 10% limit => warning zone, penalty interpolated
        state = ks.check(940_000, 1_000_000, 0.0)
        assert not state.triggered
        assert state.warning_active
        assert state.position_size_penalty < 1.0
        assert state.position_size_penalty >= 0.5

    def test_reduce_at_75pct_of_limit(self):
        ks = self._ks_with_peak()
        # 7.5% drawdown = 75% of 10% limit => full reduce
        state = ks.check(925_000, 1_000_000, 0.0)
        assert not state.triggered
        assert state.warning_active
        assert state.position_size_penalty == pytest.approx(0.5, abs=1e-6)

    def test_halt_at_100pct_of_limit(self):
        ks = self._ks_with_peak()
        # 10% drawdown = 100% of limit => triggered
        state = ks.check(900_000, 1_000_000, 0.0)
        assert state.triggered

    def test_daily_loss_tiered_response(self):
        ks = self._ks_with_peak(max_daily_loss_pct=0.05)
        # 2.5% daily loss = 50% of 5% limit => warning
        state = ks.check(975_000, 1_000_000, 0.0)
        assert state.warning_active

    def test_penalty_interpolation(self):
        ks = self._ks_with_peak()
        # 6.25% drawdown = 62.5% of 10% limit, between warn(50%) and reduce(75%)
        state = ks.check(937_500, 1_000_000, 0.0)
        assert not state.triggered
        assert state.warning_active
        # Penalty should be between 0.5 and 1.0
        assert 0.5 <= state.position_size_penalty < 1.0

    def test_state_persistence(self, tmp_path):
        ks = self._ks_with_peak()
        ks.check(930_000, 1_000_000, 0.0)  # Should set warning + penalty
        path = tmp_path / "ks.json"
        ks.save(path)

        ks2 = self._make_ks()
        ks2.load(path)
        assert ks2.state.warning_active == ks.state.warning_active
        assert ks2.state.position_size_penalty == ks.state.position_size_penalty

    def test_reset_clears_tiered_state(self):
        ks = self._ks_with_peak()
        ks.check(925_000, 1_000_000, 0.0)
        assert ks.state.warning_active
        ks.reset()
        assert not ks.state.warning_active
        assert ks.state.position_size_penalty == 1.0


# ── Slippage Monitor ─────────────────────────────────────────────────


class TestSlippageMonitor:
    def test_normal_slippage_not_anomaly(self):
        sm = SlippageMonitor(expected_slippage_pct=0.0005)
        record = sm.record_fill("KRW-BTC", "buy", 100_000_000, 100_050_000)
        assert not record.is_anomaly
        assert record.actual_slippage_pct == pytest.approx(0.0005, abs=1e-6)

    def test_anomalous_slippage_detected(self):
        sm = SlippageMonitor(expected_slippage_pct=0.0005, alert_multiplier=3.0)
        # 0.5% slippage vs 0.05% expected (10x) => anomaly
        record = sm.record_fill("KRW-BTC", "buy", 100_000_000, 100_500_000)
        assert record.is_anomaly

    def test_sell_slippage(self):
        sm = SlippageMonitor(expected_slippage_pct=0.0005)
        record = sm.record_fill("KRW-ETH", "sell", 5_000_000, 4_997_500)
        assert record.actual_slippage_pct == pytest.approx(0.0005, abs=1e-6)
        assert not record.is_anomaly

    def test_stats_calculation(self):
        sm = SlippageMonitor(expected_slippage_pct=0.001, alert_multiplier=3.0)
        sm.record_fill("KRW-BTC", "buy", 100_000, 100_050)  # 0.05%
        sm.record_fill("KRW-BTC", "buy", 100_000, 100_100)  # 0.10%
        sm.record_fill("KRW-BTC", "buy", 100_000, 100_500)  # 0.50% anomaly

        stats = sm.get_stats()
        assert stats.total_trades == 3
        assert stats.anomaly_count == 1
        assert stats.max_slippage_pct == pytest.approx(0.005, abs=1e-4)
        assert stats.avg_slippage_pct > 0

    def test_per_symbol_stats(self):
        sm = SlippageMonitor(expected_slippage_pct=0.001)
        sm.record_fill("KRW-BTC", "buy", 100_000, 100_050)
        sm.record_fill("KRW-ETH", "buy", 5_000, 5_003)
        sm.record_fill("KRW-BTC", "buy", 100_000, 100_080)

        btc_stats = sm.get_stats("KRW-BTC")
        assert btc_stats.total_trades == 2

        eth_stats = sm.get_stats("KRW-ETH")
        assert eth_stats.total_trades == 1

    def test_anomaly_rate(self):
        sm = SlippageMonitor(expected_slippage_pct=0.0001, alert_multiplier=2.0)
        # 4 normal, 1 anomaly
        for _ in range(4):
            sm.record_fill("KRW-BTC", "buy", 100_000, 100_005)  # 0.005%
        sm.record_fill("KRW-BTC", "buy", 100_000, 100_500)  # 0.5% anomaly
        assert sm.anomaly_rate == pytest.approx(0.2)

    def test_empty_stats(self):
        sm = SlippageMonitor()
        stats = sm.get_stats()
        assert stats.total_trades == 0
        assert stats.anomaly_count == 0
        assert sm.anomaly_rate == 0.0

    def test_zero_market_price(self):
        sm = SlippageMonitor()
        record = sm.record_fill("KRW-BTC", "buy", 0.0, 100.0)
        assert record.actual_slippage_pct == 0.0
        assert not record.is_anomaly

    def test_window_limit(self):
        sm = SlippageMonitor(window=5)
        for i in range(10):
            sm.record_fill("KRW-BTC", "buy", 100_000, 100_050 + i)
        assert len(sm.recent_records) == 5


# ── Config integration ────────────────────────────────────────────────


class TestConfigIntegration:
    def test_risk_config_has_max_position_pct(self):
        cfg = RiskConfig()
        assert hasattr(cfg, "max_position_pct")
        assert cfg.max_position_pct == 0.25

    def test_kill_switch_cfg_has_tiered_fields(self):
        cfg = KillSwitchCfg()
        assert cfg.warn_threshold_pct == 0.5
        assert cfg.reduce_threshold_pct == 0.75
        assert cfg.reduce_position_factor == 0.5

    def test_kill_switch_state_has_new_fields(self):
        state = KillSwitchState()
        assert state.warning_active is False
        assert state.position_size_penalty == 1.0
