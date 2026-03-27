"""Walk-forward validation to detect overfitting.

Splits candle data into rolling train/test windows and runs backtests on each.
Only strategies that perform consistently on out-of-sample (OOS) data pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from crypto_trader.config import BacktestConfig, RiskConfig
from crypto_trader.models import BacktestResult, Candle, Position, Signal
from crypto_trader.risk.manager import RiskManager


class _StrategyFactory(Protocol):
    """Creates a fresh strategy instance for each fold."""

    def __call__(self) -> _StrategyProtocol: ...


class _StrategyProtocol(Protocol):
    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal: ...


@dataclass(slots=True)
class WalkForwardFold:
    fold_index: int
    train_bars: int
    test_bars: int
    train_result: BacktestResult
    test_result: BacktestResult

    @property
    def train_return_pct(self) -> float:
        return self.train_result.total_return_pct * 100

    @property
    def test_return_pct(self) -> float:
        return self.test_result.total_return_pct * 100

    @property
    def efficiency_ratio(self) -> float:
        """OOS return / IS return. Values > 0.5 suggest low overfitting."""
        if self.train_result.total_return_pct == 0:
            return 0.0
        return self.test_result.total_return_pct / self.train_result.total_return_pct


@dataclass(slots=True)
class WalkForwardReport:
    strategy_name: str
    symbol: str
    total_folds: int
    folds: list[WalkForwardFold] = field(default_factory=list)

    @property
    def avg_train_return_pct(self) -> float:
        if not self.folds:
            return 0.0
        return sum(f.train_return_pct for f in self.folds) / len(self.folds)

    @property
    def avg_test_return_pct(self) -> float:
        if not self.folds:
            return 0.0
        return sum(f.test_return_pct for f in self.folds) / len(self.folds)

    @property
    def avg_efficiency_ratio(self) -> float:
        ratios = [f.efficiency_ratio for f in self.folds if f.train_return_pct != 0]
        if not ratios:
            return 0.0
        return sum(ratios) / len(ratios)

    @property
    def oos_profitable_folds(self) -> int:
        return sum(1 for f in self.folds if f.test_return_pct > 0)

    @property
    def oos_win_rate(self) -> float:
        if not self.folds:
            return 0.0
        return self.oos_profitable_folds / len(self.folds)

    @property
    def avg_oos_profit_factor(self) -> float:
        """Average OOS profit factor across folds."""
        pfs = [f.test_result.profit_factor for f in self.folds if f.test_result.trade_log]
        if not pfs:
            return 0.0
        # Cap inf values at 10.0 for averaging
        capped = [min(pf, 10.0) for pf in pfs]
        return sum(capped) / len(capped)

    @property
    def avg_oos_sharpe(self) -> float:
        """Average OOS Sharpe ratio across folds."""
        sharpes = [f.test_result.sharpe_ratio for f in self.folds if f.test_result.trade_log]
        if not sharpes:
            return 0.0
        return sum(sharpes) / len(sharpes)

    @property
    def passed(self) -> bool:
        """Strategy passes walk-forward if:
        - OOS avg return > 0
        - At least 50% of folds are OOS-profitable
        - Efficiency ratio > 0.3 (not heavily overfit)
        """
        return (
            self.avg_test_return_pct > 0
            and self.oos_win_rate >= 0.5
            and self.avg_efficiency_ratio > 0.3
        )

    def summary(self) -> dict[str, object]:
        return {
            "strategy": self.strategy_name,
            "symbol": self.symbol,
            "total_folds": self.total_folds,
            "avg_train_return_pct": round(self.avg_train_return_pct, 3),
            "avg_test_return_pct": round(self.avg_test_return_pct, 3),
            "avg_efficiency_ratio": round(self.avg_efficiency_ratio, 3),
            "avg_oos_profit_factor": round(self.avg_oos_profit_factor, 3),
            "avg_oos_sharpe": round(self.avg_oos_sharpe, 3),
            "oos_win_rate": round(self.oos_win_rate, 3),
            "passed": self.passed,
        }


class WalkForwardValidator:
    """Rolling-window walk-forward validation.

    Splits candles into `n_folds` sequential train/test windows:
      [train_0|test_0] [train_1|test_1] ... [train_n|test_n]

    Each fold's train window starts where the previous fold's test ended,
    creating an anchored expanding or rolling window.
    """

    def __init__(
        self,
        backtest_config: BacktestConfig,
        risk_config: RiskConfig,
        n_folds: int = 3,
        train_pct: float = 0.7,
    ) -> None:
        self._backtest_config = backtest_config
        self._risk_config = risk_config
        self._n_folds = max(2, n_folds)
        self._train_pct = min(0.9, max(0.5, train_pct))

    def validate(
        self,
        strategy_factory: _StrategyFactory,
        candles: list[Candle],
        symbol: str,
        strategy_name: str = "unknown",
    ) -> WalkForwardReport:
        from crypto_trader.backtest.engine import BacktestEngine

        total = len(candles)
        fold_size = total // self._n_folds
        train_size = max(30, int(fold_size * self._train_pct))
        test_size = max(10, fold_size - train_size)

        if total < (train_size + test_size):
            return WalkForwardReport(
                strategy_name=strategy_name,
                symbol=symbol,
                total_folds=0,
            )

        folds: list[WalkForwardFold] = []

        for i in range(self._n_folds):
            start = i * fold_size
            train_end = start + train_size
            test_end = min(train_end + test_size, total)

            if train_end >= total or test_end <= train_end:
                break

            train_candles = candles[start:train_end]
            test_candles = candles[train_end:test_end]

            if len(train_candles) < 30 or len(test_candles) < 10:
                break

            # Train fold
            train_strategy = strategy_factory()
            train_rm = RiskManager(
                self._risk_config,
                trailing_stop_pct=self._risk_config.trailing_stop_pct,
                atr_stop_multiplier=self._risk_config.atr_stop_multiplier,
            )
            train_engine = BacktestEngine(
                strategy=train_strategy,
                risk_manager=train_rm,
                config=self._backtest_config,
                symbol=symbol,
            )
            train_result = train_engine.run(train_candles)

            # Test fold (OOS)
            test_strategy = strategy_factory()
            test_rm = RiskManager(
                self._risk_config,
                trailing_stop_pct=self._risk_config.trailing_stop_pct,
                atr_stop_multiplier=self._risk_config.atr_stop_multiplier,
            )
            test_engine = BacktestEngine(
                strategy=test_strategy,
                risk_manager=test_rm,
                config=self._backtest_config,
                symbol=symbol,
            )
            test_result = test_engine.run(test_candles)

            folds.append(
                WalkForwardFold(
                    fold_index=i,
                    train_bars=len(train_candles),
                    test_bars=len(test_candles),
                    train_result=train_result,
                    test_result=test_result,
                )
            )

        return WalkForwardReport(
            strategy_name=strategy_name,
            symbol=symbol,
            total_folds=len(folds),
            folds=folds,
        )
