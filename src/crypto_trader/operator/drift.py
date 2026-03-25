from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from crypto_trader.config import DriftConfig
from crypto_trader.models import BacktestBaseline, DriftReport, DriftStatus, StrategyRunRecord


class DriftReportGenerator:
    def __init__(self, config: DriftConfig | None = None) -> None:
        self._config = config or DriftConfig()

    def generate(
        self,
        *,
        symbol: str,
        backtest_baseline: BacktestBaseline,
        recent_runs: list[StrategyRunRecord],
    ) -> DriftReport:
        if not recent_runs:
            return DriftReport(
                generated_at=datetime.now(timezone.utc).isoformat(),
                symbol=symbol,
                status=DriftStatus.INSUFFICIENT_DATA,
                reasons=["no paper runs recorded yet"],
                backtest_total_return_pct=backtest_baseline.total_return_pct,
                backtest_win_rate=backtest_baseline.win_rate,
                backtest_max_drawdown=backtest_baseline.max_drawdown,
                backtest_trade_count=backtest_baseline.trade_count,
                paper_run_count=0,
                paper_error_rate=0.0,
                paper_buy_rate=0.0,
                paper_sell_rate=0.0,
                paper_hold_rate=0.0,
                paper_realized_pnl_pct=0.0,
            )

        paper_run_count = len(recent_runs)
        error_count = sum(1 for run in recent_runs if not run.success)
        buy_count = sum(1 for run in recent_runs if run.signal_action == "buy")
        sell_count = sum(1 for run in recent_runs if run.signal_action == "sell")
        hold_count = sum(1 for run in recent_runs if run.signal_action == "hold")
        latest = recent_runs[-1]
        starting_equity = (
            latest.session_starting_equity if latest.session_starting_equity > 0 else 1.0
        )
        paper_realized_pnl_pct = latest.realized_pnl / starting_equity
        paper_error_rate = error_count / paper_run_count
        reasons: list[str] = []
        return_tolerance = self._return_tolerance_for_regime(latest.market_regime)
        error_rate_threshold = self._error_threshold_for_regime(latest.market_regime)

        if paper_error_rate >= error_rate_threshold:
            reasons.append("paper runtime error rate is elevated")

        if _different_direction(backtest_baseline.total_return_pct, paper_realized_pnl_pct):
            reasons.append("paper pnl direction diverges from backtest expectation")

        return_gap = abs(backtest_baseline.total_return_pct - paper_realized_pnl_pct)
        major_return_gap = return_gap >= return_tolerance
        if major_return_gap:
            reasons.append("paper performance is materially offset from backtest return")
        elif return_gap >= return_tolerance * 0.5:
            reasons.append("paper performance is starting to drift from backtest return")

        if not reasons:
            status = DriftStatus.ON_TRACK
            reasons.append("paper behavior is directionally aligned with backtest")
        elif paper_error_rate >= error_rate_threshold or _different_direction(
            backtest_baseline.total_return_pct,
            paper_realized_pnl_pct,
        ) or major_return_gap:
            status = DriftStatus.OUT_OF_SYNC
        else:
            status = DriftStatus.CAUTION

        return DriftReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            status=status,
            reasons=reasons,
            backtest_total_return_pct=backtest_baseline.total_return_pct,
            backtest_win_rate=backtest_baseline.win_rate,
            backtest_max_drawdown=backtest_baseline.max_drawdown,
            backtest_trade_count=backtest_baseline.trade_count,
            paper_run_count=paper_run_count,
            paper_error_rate=paper_error_rate,
            paper_buy_rate=buy_count / paper_run_count,
            paper_sell_rate=sell_count / paper_run_count,
            paper_hold_rate=hold_count / paper_run_count,
            paper_realized_pnl_pct=paper_realized_pnl_pct,
        )

    def save(self, report: DriftReport, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    def _return_tolerance_for_regime(self, regime: str | None) -> float:
        if regime == "bull":
            return self._config.bull_return_tolerance_pct
        if regime == "bear":
            return self._config.bear_return_tolerance_pct
        return self._config.sideways_return_tolerance_pct

    def _error_threshold_for_regime(self, regime: str | None) -> float:
        if regime == "bull":
            return self._config.bull_error_rate_threshold
        if regime == "bear":
            return self._config.bear_error_rate_threshold
        return self._config.sideways_error_rate_threshold


def _different_direction(backtest_return_pct: float, paper_realized_pnl_pct: float) -> bool:
    if backtest_return_pct == 0 or paper_realized_pnl_pct == 0:
        return False
    return (backtest_return_pct > 0) != (paper_realized_pnl_pct > 0)
