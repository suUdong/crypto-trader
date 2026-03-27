"""Time-of-day edge multiplier for position sizing.

Based on empirical signal hit-rate analysis (7-day rolling):
- Peak hours have 5-6x higher buy-signal rate than average
- Dead zones produce near-zero actionable signals
- Scaling position size with edge concentrates capital when it matters.
"""

from __future__ import annotations

# UTC hour -> position-size multiplier.
# Derived from strategy-runs.jsonl signal analysis:
#   UTC 22-23 (KST 07-08): 10.3-10.8% buy rate  -> 1.5x (peak)
#   UTC 07-08 (KST 16-17): 3.2-4.7% buy rate     -> 1.5x (peak)
#   UTC 01-02 (KST 10-11): 2.5-3.0% buy rate     -> 1.2x (good)
#   UTC 19    (KST 04):    3.1% buy rate           -> 1.2x (good)
#   UTC 06,10,12,14 (dead): 0% buy rate            -> 0.5x (dead)
#   All other hours: baseline                       -> 1.0x

_PEAK_HOURS: frozenset[int] = frozenset({22, 23, 7, 8})
_GOOD_HOURS: frozenset[int] = frozenset({1, 2, 19})
_DEAD_HOURS: frozenset[int] = frozenset({6, 10, 12, 14})

_PEAK_MULT: float = 1.5
_GOOD_MULT: float = 1.2
_DEAD_MULT: float = 0.5
_DEFAULT_MULT: float = 1.0


class EdgeSchedule:
    """Returns a position-size multiplier based on the hour of day (UTC)."""

    def __init__(
        self,
        peak_mult: float = _PEAK_MULT,
        good_mult: float = _GOOD_MULT,
        dead_mult: float = _DEAD_MULT,
        default_mult: float = _DEFAULT_MULT,
    ) -> None:
        self._peak_mult = peak_mult
        self._good_mult = good_mult
        self._dead_mult = dead_mult
        self._default_mult = default_mult

    def hour_multiplier(self, utc_hour: int) -> float:
        """Return the position-size multiplier for the given UTC hour (0-23)."""
        h = utc_hour % 24
        if h in _PEAK_HOURS:
            return self._peak_mult
        if h in _GOOD_HOURS:
            return self._good_mult
        if h in _DEAD_HOURS:
            return self._dead_mult
        return self._default_mult
