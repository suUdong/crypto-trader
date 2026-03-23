from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.models import BacktestResult, DriftReport, DriftStatus, StrategyRunRecord


class DriftReportGenerator:
    def generate(
        self,
        *,
        symbol: str,
        backtest_result: BacktestResult,
        recent_runs: list[StrategyRunRecord],
    ) -> DriftReport:
        if not recent_runs:
            return DriftReport(
                generated_at=datetime.now(UTC).isoformat(),
                symbol=symbol,
                status=DriftStatus.INSUFFICIENT_DATA,
                reasons=["no paper runs recorded yet"],
                backtest_total_return_pct=backtest_result.total_return_pct,
                backtest_win_rate=backtest_result.win_rate,
                backtest_max_drawdown=backtest_result.max_drawdown,
                backtest_trade_count=len(backtest_result.trade_log),
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

        if paper_error_rate >= 0.2:
            reasons.append("paper runtime error rate is elevated")

        if _different_direction(backtest_result.total_return_pct, paper_realized_pnl_pct):
            reasons.append("paper pnl direction diverges from backtest expectation")

        if abs(backtest_result.total_return_pct - paper_realized_pnl_pct) >= 0.1:
            reasons.append("paper performance is materially offset from backtest return")

        if not reasons:
            status = DriftStatus.ON_TRACK
            reasons.append("paper behavior is directionally aligned with backtest")
        elif paper_error_rate >= 0.2 or len(reasons) >= 2:
            status = DriftStatus.OUT_OF_SYNC
        else:
            status = DriftStatus.CAUTION

        return DriftReport(
            generated_at=datetime.now(UTC).isoformat(),
            symbol=symbol,
            status=status,
            reasons=reasons,
            backtest_total_return_pct=backtest_result.total_return_pct,
            backtest_win_rate=backtest_result.win_rate,
            backtest_max_drawdown=backtest_result.max_drawdown,
            backtest_trade_count=len(backtest_result.trade_log),
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


def _different_direction(backtest_return_pct: float, paper_realized_pnl_pct: float) -> bool:
    if backtest_return_pct == 0 or paper_realized_pnl_pct == 0:
        return False
    return (backtest_return_pct > 0) != (paper_realized_pnl_pct > 0)
