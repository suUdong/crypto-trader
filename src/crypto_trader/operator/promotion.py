from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from crypto_trader.models import (
    BacktestBaseline,
    DriftReport,
    DriftStatus,
    PortfolioPromotionDecision,
    PromotionGateDecision,
    PromotionStatus,
    StrategyRunRecord,
)

JsonDict = dict[str, Any]


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
            reasons.append(
                f"Profit factor {profit_factor:.2f} below {cls.MINIMUM_PROFIT_FACTOR:.1f}"
            )
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
        strategy_runs_path: str | Path | None = None,
    ) -> tuple[bool, list[str], JsonDict]:
        """Evaluate micro-live readiness from runtime artifacts.

        Returns (ready, reasons, metrics_dict).
        """
        cp_path = Path(checkpoint_path)
        if not cp_path.exists():
            return False, ["Checkpoint file not found"], {}

        try:
            checkpoint = cast(JsonDict, json.loads(cp_path.read_text(encoding="utf-8")))
        except Exception as exc:
            return False, [f"Failed to read checkpoint: {exc}"], {}

        wallet_states = cast(dict[str, JsonDict], checkpoint.get("wallet_states", {}))
        generated_at_str = checkpoint.get("generated_at", "")

        # Load journal trades
        trades: list[JsonDict] = []
        jp_path = Path(journal_path) if journal_path is not None else None
        if jp_path is not None and jp_path.exists():
            for line in jp_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        trades.append(cast(JsonDict, json.loads(line)))
                    except Exception:
                        pass

        # paper_days: use earliest timestamp from journal, checkpoint, or strategy-runs
        now = datetime.now(UTC)
        earliest_dt: datetime | None = None

        # Try checkpoint generated_at
        try:
            candidate = datetime.fromisoformat(generated_at_str)
            if earliest_dt is None or candidate < earliest_dt:
                earliest_dt = candidate
        except Exception:
            pass

        # Try journal first trade entry_time
        if trades:
            for ts_key in ("entry_time", "timestamp", "recorded_at"):
                ts_str = trades[0].get(ts_key, "")
                if ts_str:
                    try:
                        candidate = datetime.fromisoformat(ts_str)
                        if earliest_dt is None or candidate < earliest_dt:
                            earliest_dt = candidate
                        break
                    except Exception:
                        pass

        # Try strategy-runs.jsonl first entry for earliest paper start
        sr_path = Path(strategy_runs_path) if strategy_runs_path is not None else None
        if sr_path is None:
            # Auto-detect from checkpoint path sibling
            sr_candidate = cp_path.parent / "strategy-runs.jsonl"
            if sr_candidate.exists():
                sr_path = sr_candidate
        if sr_path is not None and sr_path.exists():
            try:
                with sr_path.open(encoding="utf-8") as f:
                    first_line = f.readline().strip()
                if first_line:
                    first_run = json.loads(first_line)
                    ts_str = first_run.get("recorded_at", "")
                    if ts_str:
                        candidate = datetime.fromisoformat(ts_str)
                        if earliest_dt is None or candidate < earliest_dt:
                            earliest_dt = candidate
            except Exception:
                pass

        paper_days = max(0, (now - earliest_dt).days) if earliest_dt else 0

        # total_trades: use journal closed trades count, fall back to checkpoint trade_count
        checkpoint_trades = sum(w.get("trade_count", 0) for w in wallet_states.values())
        journal_trades = len(trades)
        total_trades = max(checkpoint_trades, journal_trades)

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

        metrics: JsonDict = {
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
        if latest_run is not None and latest_run.verdict_status in {
            "pause_strategy",
            "reduce_risk",
        }:
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


class PortfolioPromotionGate:
    """Evaluate promotion readiness across the entire multi-wallet portfolio."""

    MINIMUM_PAPER_DAYS = 7
    MINIMUM_TOTAL_TRADES = 10
    MINIMUM_PROFITABLE_WALLETS = 2
    MINIMUM_PORTFOLIO_RETURN_PCT = 0.0  # must be positive

    def evaluate_from_checkpoint(
        self,
        checkpoint_path: str | Path,
        journal_path: str | Path | None = None,
    ) -> PortfolioPromotionDecision:
        """Evaluate portfolio-level promotion from runtime checkpoint."""
        cp_path = Path(checkpoint_path)
        if not cp_path.exists():
            return self._fail("Checkpoint file not found")

        checkpoint = cast(JsonDict, json.loads(cp_path.read_text(encoding="utf-8")))
        wallet_states = cast(dict[str, JsonDict], checkpoint.get("wallet_states", {}))
        generated_at_str = checkpoint.get("generated_at", "")

        # Calculate paper days
        now = datetime.now(UTC)
        try:
            gen_dt = datetime.fromisoformat(generated_at_str)
            paper_days = max(0, (now - gen_dt).days)
        except Exception:
            paper_days = 0

        # Also check journal for first trade timestamp
        if journal_path:
            jp = Path(journal_path)
            if jp.exists():
                first_line = ""
                with jp.open(encoding="utf-8") as f:
                    first_line = f.readline().strip()
                if first_line:
                    try:
                        first_rec = cast(JsonDict, json.loads(first_line))
                        ts = first_rec.get("recorded_at", "")
                        first_dt = datetime.fromisoformat(ts)
                        paper_days = max(paper_days, (now - first_dt).days)
                    except Exception:
                        pass

        initial_capital = 1_000_000.0
        per_wallet: dict[str, JsonDict] = {}
        total_equity = 0.0
        total_realized_pnl = 0.0
        total_trades = 0
        profitable_wallets = 0

        for name, ws in wallet_states.items():
            equity = ws.get("equity", initial_capital)
            pnl = ws.get("realized_pnl", 0.0)
            trades = ws.get("trade_count", 0)
            return_pct = (
                (equity - initial_capital) / initial_capital if initial_capital > 0 else 0.0
            )
            per_wallet[name] = {
                "equity": equity,
                "realized_pnl": pnl,
                "trades": trades,
                "return_pct": return_pct,
            }
            total_equity += equity
            total_realized_pnl += pnl
            total_trades += trades
            if equity > initial_capital:
                profitable_wallets += 1

        wallet_count = len(wallet_states)
        total_initial = initial_capital * wallet_count
        portfolio_return_pct = (
            (total_equity - total_initial) / total_initial if total_initial > 0 else 0.0
        )

        # Evaluate criteria
        reasons: list[str] = []
        if paper_days < self.MINIMUM_PAPER_DAYS:
            reasons.append(f"Need {self.MINIMUM_PAPER_DAYS}d paper trading (have {paper_days}d)")
        if total_trades < self.MINIMUM_TOTAL_TRADES:
            reasons.append(f"Need {self.MINIMUM_TOTAL_TRADES}+ trades (have {total_trades})")
        if profitable_wallets < self.MINIMUM_PROFITABLE_WALLETS:
            reasons.append(
                f"Need {self.MINIMUM_PROFITABLE_WALLETS}+ profitable wallets "
                f"(have {profitable_wallets})"
            )
        if portfolio_return_pct <= self.MINIMUM_PORTFOLIO_RETURN_PCT:
            reasons.append(f"Portfolio return {portfolio_return_pct:.4%} not positive")

        if reasons:
            status = PromotionStatus.STAY_IN_PAPER
        else:
            status = PromotionStatus.CANDIDATE_FOR_PROMOTION
            reasons.append("Portfolio meets all promotion criteria")

        return PortfolioPromotionDecision(
            generated_at=now.isoformat(),
            status=status,
            reasons=reasons,
            wallet_count=wallet_count,
            total_equity=total_equity,
            total_realized_pnl=total_realized_pnl,
            portfolio_return_pct=portfolio_return_pct,
            profitable_wallets=profitable_wallets,
            total_trades=total_trades,
            paper_days=paper_days,
            per_wallet=per_wallet,
        )

    def _fail(self, reason: str) -> PortfolioPromotionDecision:
        return PortfolioPromotionDecision(
            generated_at=datetime.now(UTC).isoformat(),
            status=PromotionStatus.DO_NOT_PROMOTE,
            reasons=[reason],
            wallet_count=0,
            total_equity=0.0,
            total_realized_pnl=0.0,
            portfolio_return_pct=0.0,
            profitable_wallets=0,
            total_trades=0,
            paper_days=0,
            per_wallet={},
        )

    def save(self, decision: PortfolioPromotionDecision, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": decision.generated_at,
            "status": decision.status.value,
            "reasons": decision.reasons,
            "wallet_count": decision.wallet_count,
            "total_equity": decision.total_equity,
            "total_realized_pnl": decision.total_realized_pnl,
            "portfolio_return_pct": decision.portfolio_return_pct,
            "profitable_wallets": decision.profitable_wallets,
            "total_trades": decision.total_trades,
            "paper_days": decision.paper_days,
            "per_wallet": decision.per_wallet,
        }
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
