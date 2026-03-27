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
