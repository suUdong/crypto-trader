"""Base class for all evaluator check plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod

from crypto_trader.evaluator.models import CheckResult, EvalContext


class BaseCheck(ABC):
    """All check plugins must inherit from this class."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique check identifier, e.g. 'backtest_quality'."""

    @property
    def weight(self) -> float:
        """Weight for overall_score calculation. Default 1.0."""
        return 1.0

    @abstractmethod
    def run(self, ctx: EvalContext) -> CheckResult:
        """Execute the check. Return Grade.SKIP if data is insufficient."""
