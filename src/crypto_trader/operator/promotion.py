from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.models import (
    BacktestBaseline,
    DriftReport,
    DriftStatus,
    PromotionGateDecision,
    PromotionStatus,
    StrategyRunRecord,
)


class MicroLiveCriteria:
    """Criteria for paper-to-micro-live transition."""

    MINIMUM_PAPER_DAYS: int = 7
    MINIMUM_TRADES: int = 10
    MINIMUM_WIN_RATE: float = 0.45
    MAXIMUM_DRAWDOWN: float = 0.10
    MINIMUM_PROFIT_FACTOR: float = 1.2
    MINIMUM_POSITIVE_STRATEGIES: int = 2

    @classmethod
    def evaluate(
        cls,
        paper_days: int,
        total_trades: int,
        win_rate: float,
        max_drawdown: float,
        profit_factor: float,
        positive_strategies: int,
    ) -> tuple[bool, list[str]]:
        """Return (ready, reasons) for micro-live transition."""
        reasons: list[str] = []
        ready = True

        if paper_days < cls.MINIMUM_PAPER_DAYS:
            reasons.append(f"Need {cls.MINIMUM_PAPER_DAYS}d paper trading (have {paper_days}d)")
            ready = False
        if total_trades < cls.MINIMUM_TRADES:
            reasons.append(f"Need {cls.MINIMUM_TRADES}+ trades (have {total_trades})")
            ready = False
        if win_rate < cls.MINIMUM_WIN_RATE:
            reasons.append(f"Win rate {win_rate:.0%} below {cls.MINIMUM_WIN_RATE:.0%} minimum")
            ready = False
        if max_drawdown > cls.MAXIMUM_DRAWDOWN:
            reasons.append(f"MDD {max_drawdown:.1%} exceeds {cls.MAXIMUM_DRAWDOWN:.0%} limit")
            ready = False
        if profit_factor < cls.MINIMUM_PROFIT_FACTOR:
            reasons.append(f"Profit factor {profit_factor:.2f} below {cls.MINIMUM_PROFIT_FACTOR:.1f}")
            ready = False
        if positive_strategies < cls.MINIMUM_POSITIVE_STRATEGIES:
            reasons.append(
                f"Need {cls.MINIMUM_POSITIVE_STRATEGIES}+ profitable strategies "
                f"(have {positive_strategies})"
            )
            ready = False

        if ready:
            reasons.append("All micro-live criteria met. Ready for transition.")

        return ready, reasons

    @classmethod
    def evaluate_from_artifacts(
        cls,
        checkpoint_path: str | Path,
        journal_path: str | Path | None = None,
    ) -> tuple[bool, list[str], dict]:
        """Evaluate micro-live readiness from runtime artifacts.

        Returns (ready, reasons, metrics_dict).
        """
        cp_path = Path(checkpoint_path)
        if not cp_path.exists():
            return False, ["Checkpoint file not found"], {}

        try:
            checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, [f"Failed to read checkpoint: {exc}"], {}

        wallet_states = checkpoint.get("wallet_states", {})
        generated_at_str = checkpoint.get("generated_at", "")

        # Load journal trades
        trades: list[dict] = []
        jp_path = Path(journal_path) if journal_path is not None else None
        if jp_path is not None and jp_path.exists():
            for line in jp_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except Exception:
                        pass

        # paper_days: days from first trade timestamp to now, or checkpoint generated_at to now
        now = datetime.now(UTC)
        if trades:
            first_ts_str = trades[0].get("timestamp", "")
            try:
                first_dt = datetime.fromisoformat(first_ts_str)
                paper_days = max(0, (now - first_dt).days)
            except Exception:
                paper_days = 0
        else:
            try:
                generated_at = datetime.fromisoformat(generated_at_str)
                paper_days = max(0, (now - generated_at).days)
            except Exception:
                paper_days = 0

        # total_trades: sum of trade_count across wallets
        total_trades = sum(
            w.get("trade_count", 0) for w in wallet_states.values()
        )

        # win_rate from journal pnl
        if trades:
            winning = sum(1 for t in trades if t.get("pnl", 0) > 0)
            win_rate = winning / len(trades)
        else:
            win_rate = 0.0

        # max_drawdown: per-wallet (initial - min_equity) / initial, take worst
        initial_capital = 1_000_000.0
        max_drawdown = 0.0
        for w in wallet_states.values():
            equity = w.get("equity", initial_capital)
            drawdown = (initial_capital - equity) / initial_capital
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        max_drawdown = max(0.0, max_drawdown)

        # profit_factor from journal
        gross_profit = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0))
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        # positive_strategies: wallets where equity > initial_capital
        positive_strategies = sum(
            1 for w in wallet_states.values() if w.get("equity", 0) > initial_capital
        )

        ready, reasons = cls.evaluate(
            paper_days=paper_days,
            total_trades=total_trades,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            positive_strategies=positive_strategies,
        )

        metrics: dict = {
            "paper_days": paper_days,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "max_drawdown": max_drawdown,
            "profit_factor": profit_factor,
            "positive_strategies": positive_strategies,
        }

        return ready, reasons, metrics


class PromotionGate:
    def __init__(self, minimum_paper_runs_required: int = 5) -> None:
        self._minimum_paper_runs_required = minimum_paper_runs_required

    def evaluate(
        self,
        *,
        symbol: str,
        backtest_baseline: BacktestBaseline,
        drift_report: DriftReport,
        latest_run: StrategyRunRecord | None,
    ) -> PromotionGateDecision:
        reasons: list[str] = []

        if backtest_baseline.total_return_pct <= 0:
            reasons.append("backtest return is not positive")
        if backtest_baseline.max_drawdown > 0.2:
            reasons.append("backtest drawdown is above 20%")
        if drift_report.paper_run_count < self._minimum_paper_runs_required:
            reasons.append("not enough paper runs have been recorded yet")
        if drift_report.status is DriftStatus.OUT_OF_SYNC:
            reasons.append("paper behavior is out of sync with the backtest")
        if drift_report.status is DriftStatus.CAUTION:
            reasons.append("paper behavior still needs more observation")
        if drift_report.paper_realized_pnl_pct <= 0:
            reasons.append("paper pnl is not yet positive")
        if (
            latest_run is not None
            and latest_run.verdict_status in {"pause_strategy", "reduce_risk"}
        ):
            reasons.append("latest strategy verdict does not support promotion")

        if (
            "backtest return is not positive" in reasons
            or "backtest drawdown is above 20%" in reasons
        ):
            status = PromotionStatus.DO_NOT_PROMOTE
        elif reasons:
            status = PromotionStatus.STAY_IN_PAPER
        else:
            status = PromotionStatus.CANDIDATE_FOR_PROMOTION
            reasons.append("paper evidence and drift checks support a promotion review")

        return PromotionGateDecision(
            generated_at=datetime.now(UTC).isoformat(),
            symbol=symbol,
            status=status,
            reasons=reasons,
            minimum_paper_runs_required=self._minimum_paper_runs_required,
            observed_paper_runs=drift_report.paper_run_count,
            backtest_total_return_pct=backtest_baseline.total_return_pct,
            paper_realized_pnl_pct=drift_report.paper_realized_pnl_pct,
            drift_status=drift_report.status,
        )

    def save(self, decision: PromotionGateDecision, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(decision)
        payload["status"] = decision.status.value
        payload["drift_status"] = decision.drift_status.value
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
