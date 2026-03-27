"""Tests for time-of-day edge multiplier."""

from crypto_trader.risk.edge_schedule import EdgeSchedule


class TestEdgeSchedule:
    def test_peak_hours_return_peak_multiplier(self) -> None:
        sched = EdgeSchedule()
        for h in (22, 23, 7, 8):
            assert sched.hour_multiplier(h) == 1.5, f"hour {h}"

    def test_good_hours_return_good_multiplier(self) -> None:
        sched = EdgeSchedule()
        for h in (1, 2, 19):
            assert sched.hour_multiplier(h) == 1.2, f"hour {h}"

    def test_dead_hours_return_dead_multiplier(self) -> None:
        sched = EdgeSchedule()
        for h in (6, 10, 12, 14):
            assert sched.hour_multiplier(h) == 0.5, f"hour {h}"

    def test_default_hours_return_one(self) -> None:
        sched = EdgeSchedule()
        for h in (3, 4, 5, 9, 11, 13, 15, 16, 17, 18, 20, 21, 0):
            assert sched.hour_multiplier(h) == 1.0, f"hour {h}"

    def test_wraps_around_24(self) -> None:
        sched = EdgeSchedule()
        assert sched.hour_multiplier(22) == sched.hour_multiplier(22 + 24)

    def test_custom_multipliers(self) -> None:
        sched = EdgeSchedule(peak_mult=2.0, good_mult=1.5, dead_mult=0.3, default_mult=0.8)
        assert sched.hour_multiplier(22) == 2.0
        assert sched.hour_multiplier(1) == 1.5
        assert sched.hour_multiplier(6) == 0.3
        assert sched.hour_multiplier(3) == 0.8


class TestEdgeScheduleIntegration:
    """Integration: RiskManager.size_position applies edge multiplier."""

    def test_peak_hour_sizes_larger_than_dead_hour(self) -> None:
        from crypto_trader.config import RiskConfig
        from crypto_trader.risk.manager import RiskManager

        cfg = RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.03, max_position_pct=0.50)
        rm = RiskManager(cfg)
        equity, price = 1_000_000.0, 100.0

        peak = rm.size_position(equity, price, utc_hour=22)   # 1.5x
        dead = rm.size_position(equity, price, utc_hour=10)   # 0.5x
        default = rm.size_position(equity, price, utc_hour=3)  # 1.0x

        assert peak > default > dead
        assert peak / default == 1.5 / 1.0
        assert default / dead == 1.0 / 0.5

    def test_edge_mult_capped_by_max_position_pct(self) -> None:
        from crypto_trader.config import RiskConfig
        from crypto_trader.risk.manager import RiskManager

        cfg = RiskConfig(
            risk_per_trade_pct=0.20,  # very aggressive
            stop_loss_pct=0.03,
            max_position_pct=0.10,  # tight cap
        )
        rm = RiskManager(cfg)
        equity, price = 1_000_000.0, 100.0

        peak = rm.size_position(equity, price, utc_hour=22)
        max_qty = (equity * 0.10) / price
        assert peak <= max_qty + 1e-9  # never exceeds cap
