# ruff: noqa: E501

from __future__ import annotations

import argparse
from pathlib import Path

from crypto_trader.backtest.baseline import BacktestBaselineStore, build_baseline
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.capital_allocator import CapitalAllocator
from crypto_trader.config import load_config
from crypto_trader.daemon_supervisor import DaemonSupervisor
from crypto_trader.data.pyupbit_client import PyUpbitMarketDataClient
from crypto_trader.execution.live import LiveBroker
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.logging_utils import setup_file_logging, setup_logging
from crypto_trader.monitoring import HealthMonitor
from crypto_trader.multi_runtime import MultiSymbolRuntime
from crypto_trader.notifications.alert_manager import TradeAlertManager
from crypto_trader.notifications.telegram import NullNotifier, SlackNotifier, TelegramNotifier
from crypto_trader.operator.artifact_health import summarize_artifact_health
from crypto_trader.operator.automated_reporting import (
    AutomatedReportGenerator,
    build_legacy_daily_performance_summary,
)
from crypto_trader.operator.calibration import DriftCalibrationToolkit
from crypto_trader.operator.drift import DriftReportGenerator
from crypto_trader.operator.execution_quality import (
    generate_execution_quality_report,
    save_execution_quality_report,
)
from crypto_trader.operator.execution_quality import (
    to_markdown as execution_quality_to_markdown,
)
from crypto_trader.operator.gate_progress import generate_gate_progress_report
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.paper_trading import PaperTradingOperations
from crypto_trader.operator.performance_report import generate_performance_report
from crypto_trader.operator.pnl_report import PnLReportGenerator
from crypto_trader.operator.promotion import (
    MicroLiveCriteria,
    PortfolioPromotionGate,
    PromotionGate,
)
from crypto_trader.operator.regime_report import RegimeReportGenerator
from crypto_trader.operator.report import OperatorReportBuilder
from crypto_trader.operator.runtime_state import RuntimeCheckpointStore
from crypto_trader.operator.services import generate_operator_artifacts
from crypto_trader.operator.strategy_report import StrategyComparisonReport
from crypto_trader.operator.verdicts import StrategyVerdictEngine
from crypto_trader.operator.wallet_performance import WalletPerformanceReportGenerator
from crypto_trader.pipeline import TradingPipeline
from crypto_trader.risk.manager import RiskManager
from crypto_trader.runtime import TradingRuntime
from crypto_trader.wallet import build_wallets, create_strategy


def _build_risk_manager(config) -> RiskManager:
    return RiskManager(
        config.risk,
        trailing_stop_pct=config.risk.trailing_stop_pct,
        atr_stop_multiplier=config.risk.atr_stop_multiplier,
    )


def _build_alert_manager(config) -> TradeAlertManager:
    notifiers = [TelegramNotifier(config.telegram) if config.telegram.enabled else NullNotifier()]
    if config.slack.enabled:
        notifiers.append(SlackNotifier(config.slack))
    return TradeAlertManager(notifiers)


def _prime_strategy_for_backtest(strategy, strategy_type: str, symbol: str, candles) -> None:
    if strategy_type == "kimchi_premium":
        from unittest.mock import MagicMock

        if len(candles) >= 50:
            closes = [c.close for c in candles]
            ma50 = sum(closes[-50:]) / 50.0
            if ma50 > 0 and hasattr(strategy, "_cached_premium"):
                strategy._cached_premium = (closes[-1] - ma50) / ma50
        if hasattr(strategy, "_binance"):
            strategy._binance = MagicMock()
            strategy._binance.get_btc_usdt_price.return_value = None
        if hasattr(strategy, "_fx"):
            strategy._fx = MagicMock()
            strategy._fx.get_usd_krw_rate.return_value = None
        return

    if strategy_type == "funding_rate" and hasattr(strategy, "prime_backtest_funding"):
        strategy.prime_backtest_funding(symbol, candles)


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto trader control plane")
    parser.add_argument(
        "command",
        choices=[
            "run-once",
            "run-loop",
            "run-multi",
            "backtest",
            "regime-report",
            "calibrate-drift",
            "operator-report",
            "drift-report",
            "promotion-gate",
            "daily-memo",
            "strategy-report",
            "pnl-report",
            "pnl-history",
            "performance-report",
            "execution-quality-report",
            "wallet-performance",
            "micro-live-check",
            "rebalance-capital",
            "walk-forward",
            "grid-wf",
            "snapshot",
            "correlation",
            "apply-params",
            "backtest-all",
            "grid-wf-all",
            "strategy-dashboard",
            "signal-summary",
            "refresh-artifacts",
            "sync-artifacts",
            "portfolio-gate",
            "gate-progress",
        ],
    )
    parser.add_argument("--config", default=None)
    parser.add_argument(
        "--strategy",
        choices=[
            "momentum",
            "momentum_pullback",
            "mean_reversion",
            "composite",
            "kimchi_premium",
            "funding_rate",
            "obi",
            "vpin",
            "volatility_breakout",
            "ema_crossover",
            "consensus",
        ],
        default="composite",
        help="Strategy type for backtest (default: composite)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=0,
        help="Time window in hours for PnL report filtering (e.g. 72 for 3-day report)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days for walk-forward validation (default: 90)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        dest="top_n",
        help="Number of top grid search candidates to validate (default: 5)",
    )
    parser.add_argument("--wallet", default=None, help="Target wallet name for apply-params")
    parser.add_argument(
        "--regime",
        choices=["bull", "bear", "sideways"],
        default=None,
        help="Filter candles by market regime for grid-wf",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        dest="output_dir",
        help="Output directory for snapshot artifacts",
    )
    args = parser.parse_args()

    read_only_artifact_commands = {
        "execution-quality-report",
        "performance-report",
        "wallet-performance",
        "pnl-report",
        "pnl-history",
        "gate-progress",
        "micro-live-check",
    }
    config = load_config(
        args.config,
        allow_missing_live_credentials=args.command in read_only_artifact_commands,
    )
    setup_logging(config.runtime.log_level)
    if config.runtime.log_file_path:
        setup_file_logging(config.runtime.log_file_path, level=config.runtime.log_level)
    strategy = create_strategy(args.strategy, config.strategy, config.regime)
    risk_manager = _build_risk_manager(config)
    market_data = PyUpbitMarketDataClient()

    if args.command == "backtest":
        backtest_strategy = create_strategy(args.strategy, config.strategy, config.regime)
        candles = market_data.get_ohlcv(
            config.trading.symbol,
            interval=config.trading.interval,
            count=config.trading.candle_count,
        )
        _prime_strategy_for_backtest(
            backtest_strategy,
            args.strategy,
            config.trading.symbol,
            candles,
        )
        engine = BacktestEngine(
            strategy=backtest_strategy,
            risk_manager=risk_manager,
            config=config.backtest,
            symbol=config.trading.symbol,
        )
        backtest_result = engine.run(candles)
        baseline = build_baseline(config=config, result=backtest_result)
        BacktestBaselineStore(config.runtime.backtest_baseline_path).save(baseline)
        print(
            f"final_equity={backtest_result.final_equity:.2f} "
            f"return={backtest_result.total_return_pct:.2%} "
            f"win_rate={backtest_result.win_rate:.2%} "
            f"max_drawdown={backtest_result.max_drawdown:.2%}"
        )
        # Export equity curve
        import json

        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        curve_data = {
            "strategy": args.strategy,
            "symbol": config.trading.symbol,
            "initial_capital": config.backtest.initial_capital,
            "final_equity": backtest_result.final_equity,
            "total_return_pct": backtest_result.total_return_pct,
            "equity_curve": backtest_result.equity_curve,
        }
        curve_path = artifacts_dir / f"equity-curve-{args.strategy}.json"
        curve_path.write_text(json.dumps(curve_data, indent=2), encoding="utf-8")
        print(f"equity_curve saved to {curve_path} ({len(backtest_result.equity_curve)} points)")
        return

    if args.command == "regime-report":
        candles = market_data.get_ohlcv(
            config.trading.symbol,
            interval=config.trading.interval,
            count=config.trading.candle_count,
        )
        report = RegimeReportGenerator(config.regime).generate(
            symbol=config.trading.symbol,
            strategy=config.strategy,
            candles=candles,
        )
        RegimeReportGenerator(config.regime).save(report, config.runtime.regime_report_path)
        print(
            f"market_regime={report.market_regime} "
            f"short_return={report.short_return_pct:.2%} "
            f"long_return={report.long_return_pct:.2%}"
        )
        return

    if args.command == "calibrate-drift":
        loaded_baseline = BacktestBaselineStore(config.runtime.backtest_baseline_path).load()
        if loaded_baseline is None:
            raise RuntimeError("No backtest baseline found. Run `backtest` first.")
        recent_runs = StrategyRunJournal(config.runtime.strategy_run_journal_path).load_recent(200)
        calibration_report = DriftCalibrationToolkit().generate(
            symbol=config.trading.symbol,
            backtest_baseline=loaded_baseline,
            recent_runs=recent_runs,
        )
        DriftCalibrationToolkit().save(
            calibration_report,
            config.runtime.drift_calibration_path,
        )
        print(
            f"calibration_entries={len(calibration_report.entries)} "
            f"path={config.runtime.drift_calibration_path}"
        )
        return

    if args.command == "operator-report":
        candles = market_data.get_ohlcv(
            config.trading.symbol,
            interval=config.trading.interval,
            count=config.trading.candle_count,
        )
        regime_report = RegimeReportGenerator(config.regime).generate(
            symbol=config.trading.symbol,
            strategy=config.strategy,
            candles=candles,
        )
        RegimeReportGenerator(config.regime).save(regime_report, config.runtime.regime_report_path)
        artifacts = generate_operator_artifacts(
            config=config,
            market_data=market_data,
            strategy=strategy,
            risk_manager=risk_manager,
        )
        calibration = DriftCalibrationToolkit().generate(
            symbol=config.trading.symbol,
            backtest_baseline=artifacts.backtest_baseline,
            recent_runs=StrategyRunJournal(config.runtime.strategy_run_journal_path).load_recent(
                200
            ),
        )
        DriftCalibrationToolkit().save(calibration, config.runtime.drift_calibration_path)
        operator_report = OperatorReportBuilder().build(
            baseline=artifacts.backtest_baseline,
            regime_report=regime_report,
            drift_report=artifacts.drift_report,
            promotion_decision=artifacts.promotion_decision,
            memo=artifacts.daily_memo,
            calibration_report=calibration,
        )
        OperatorReportBuilder().save(operator_report, config.runtime.operator_report_path)
        print(config.runtime.operator_report_path)
        return

    if args.command == "drift-report":
        artifacts = generate_operator_artifacts(
            config=config,
            market_data=market_data,
            strategy=strategy,
            risk_manager=risk_manager,
        )
        print(
            f"drift_status={artifacts.drift_report.status.value} "
            f"paper_pnl={artifacts.drift_report.paper_realized_pnl_pct:.2%} "
            f"backtest_return={artifacts.drift_report.backtest_total_return_pct:.2%}"
        )
        return

    if args.command == "promotion-gate":
        artifacts = generate_operator_artifacts(
            config=config,
            market_data=market_data,
            strategy=strategy,
            risk_manager=risk_manager,
        )
        d = artifacts.promotion_decision
        print(f"=== Promotion Gate: {d.symbol} ===")
        print(f"Status : {d.status.value}")
        print(f"Drift  : {d.drift_status.value}")
        print(f"Runs   : {d.observed_paper_runs}/{d.minimum_paper_runs_required} required")
        print(
            f"Return : backtest={d.backtest_total_return_pct:.2%}  "
            f"paper_pnl={d.paper_realized_pnl_pct:.2%}"
        )
        print()
        for reason in d.reasons:
            is_pass = d.status.value == "candidate_for_promotion"
            tag = "PASS" if is_pass else "FAIL"
            print(f"  [{tag}] {reason}")
        return

    if args.command == "daily-memo":
        notifier = TelegramNotifier(config.telegram) if config.telegram.enabled else NullNotifier()
        generate_operator_artifacts(
            config=config,
            market_data=market_data,
            strategy=strategy,
            risk_manager=risk_manager,
            notifier=notifier,
            send_daily_memo=True,
        )
        print(config.runtime.daily_memo_path)
        return

    if args.command == "pnl-report":
        generator = PnLReportGenerator()
        period = f"{args.hours}h" if args.hours > 0 else "daily"
        report = generator.generate_from_checkpoint(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            trade_journal_path=config.runtime.paper_trade_journal_path,
            period=period,
            hours=args.hours,
        )
        output_path = "artifacts/pnl-report.md"
        generator.save(report, output_path)
        print(generator.to_markdown(report))
        return

    if args.command == "pnl-history":
        from crypto_trader.operator.pnl_report import PnLSnapshotStore

        snapshot_path = Path(config.runtime.runtime_checkpoint_path).parent / "pnl-snapshots.jsonl"
        store = PnLSnapshotStore(snapshot_path)
        history = store.load_history()
        if not history:
            print("No PnL snapshots found. Run pnl-report first to accumulate history.")
            return
        print(f"\n{'=' * 80}")
        print("  PnL HISTORY — Trending Performance")
        print(f"{'=' * 80}\n")
        print(
            f"  {'Date':<22} {'Equity':>14} {'Return%':>9} {'Realized':>12} "
            f"{'Delta':>10} {'Trades':>7}"
        )
        print(f"  {'-' * 76}")
        prev_equity = None
        for entry in history:
            ts = entry.get("timestamp", "?")[:19]
            equity = entry.get("total_equity", 0)
            ret = entry.get("portfolio_return_pct", 0)
            realized = entry.get("total_realized_pnl", 0)
            trades = entry.get("total_trades", 0)
            delta = equity - prev_equity if prev_equity is not None else 0
            delta_str = f"{delta:+,.0f}" if prev_equity is not None else "-"
            print(
                f"  {ts:<22} {equity:>13,.0f} {ret:>+8.3f}% "
                f"{realized:>+11,.0f} {delta_str:>10} {trades:>7}"
            )
            prev_equity = equity
        print(f"\n  Snapshots: {len(history)}")
        print(f"{'=' * 80}\n")
        return

    if args.command == "snapshot":
        import sys

        from crypto_trader.operator.pnl_report import PnLSnapshotStore

        generator = PnLReportGenerator()
        period = f"{args.hours}h" if args.hours > 0 else "daily"
        output_dir = Path(getattr(args, "output_dir", None) or "artifacts")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            report = generator.generate_from_checkpoint(
                checkpoint_path=config.runtime.runtime_checkpoint_path,
                trade_journal_path=config.runtime.paper_trade_journal_path,
                period=period,
                hours=args.hours,
            )
            # Save markdown report to output_dir
            output_path = output_dir / "pnl-report.md"
            generator.save(report, output_path)
            # Append to snapshot history
            snapshot_path = (
                Path(config.runtime.runtime_checkpoint_path).parent / "pnl-snapshots.jsonl"
            )
            store = PnLSnapshotStore(snapshot_path)
            store.append(report)
            # JSON summary on stdout for cron consumption
            summary = {
                "status": "ok",
                "equity": report.total_equity,
                "return_pct": round(report.portfolio_return_pct, 4),
                "sharpe": round(report.portfolio_sharpe, 2),
                "trades": report.total_trades,
                "win_rate": round(report.portfolio_win_rate, 4),
                "realized_pnl": round(report.total_realized_pnl, 0),
                "source_session_id": report.source_session_id,
                "artifact_consistency_status": report.artifact_consistency_status,
                "artifact_freshness_status": summarize_artifact_health(report)["freshness_status"],
                "report_path": str(output_path),
                "snapshot_path": str(snapshot_path),
            }
            print(json.dumps(summary))
        except Exception as exc:
            print(json.dumps({"status": "error", "error": str(exc)}))
            sys.exit(1)
        return

    if args.command == "performance-report":
        output_path = config.runtime.performance_report_path
        content = generate_performance_report(
            Path(config.runtime.runtime_checkpoint_path),
            Path(config.runtime.paper_trade_journal_path),
        )
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(content, encoding="utf-8")
        print(content)
        return

    if args.command == "execution-quality-report":
        artifacts_dir = Path(config.runtime.runtime_checkpoint_path).parent
        output_path = artifacts_dir / "execution-quality-report.md"
        report = generate_execution_quality_report(
            Path(config.runtime.strategy_run_journal_path),
            artifacts_dir / "logs" / "events.jsonl",
        )
        save_execution_quality_report(report, output_path)
        print(execution_quality_to_markdown(report))
        return

    if args.command == "wallet-performance":
        generator = WalletPerformanceReportGenerator()
        report = generator.generate(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            strategy_run_journal_path=config.runtime.strategy_run_journal_path,
            trade_journal_path=config.runtime.paper_trade_journal_path,
            lookback_hours=168,
        )
        output_path = generator.default_output_path()
        generator.save(report, output_path)
        print(generator.to_markdown(report))
        return

    if args.command == "gate-progress":
        output_path = Path("docs/gate-progress.md")
        content = generate_gate_progress_report(
            runtime_checkpoint_path=Path(config.runtime.runtime_checkpoint_path),
            backtest_baseline_path=Path(config.runtime.backtest_baseline_path),
            drift_report_path=Path(config.runtime.drift_report_path),
            promotion_gate_path=Path(config.runtime.promotion_gate_path),
            strategy_run_journal_path=Path(config.runtime.strategy_run_journal_path),
            walk_forward_summary_path=Path("artifacts/walk-forward-90d/grid-wf-summary.json"),
            output_path=output_path,
        )
        print(content)
        return

    if args.command == "micro-live-check":
        ready, reasons, metrics = MicroLiveCriteria.evaluate_from_artifacts(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            journal_path=config.runtime.paper_trade_journal_path,
        )
        print("=== Micro-Live Readiness Check ===")
        if metrics:
            criteria_checks = [
                (
                    "Paper days",
                    metrics.get("paper_days", 0) >= MicroLiveCriteria.MINIMUM_PAPER_DAYS,
                    f"{metrics.get('paper_days', 0)}d / "
                    f"{MicroLiveCriteria.MINIMUM_PAPER_DAYS}d required",
                ),
                (
                    "Trade count",
                    metrics.get("total_trades", 0) >= MicroLiveCriteria.MINIMUM_TRADES,
                    f"{metrics.get('total_trades', 0)} / "
                    f"{MicroLiveCriteria.MINIMUM_TRADES} required",
                ),
                (
                    "Win rate",
                    metrics.get("win_rate", 0.0) >= MicroLiveCriteria.MINIMUM_WIN_RATE,
                    f"{metrics.get('win_rate', 0.0):.1%} / "
                    f"{MicroLiveCriteria.MINIMUM_WIN_RATE:.0%} required",
                ),
                (
                    "Max drawdown",
                    metrics.get("max_drawdown", 1.0) <= MicroLiveCriteria.MAXIMUM_DRAWDOWN,
                    f"{metrics.get('max_drawdown', 0.0):.1%} / "
                    f"{MicroLiveCriteria.MAXIMUM_DRAWDOWN:.0%} limit",
                ),
                (
                    "Profit factor",
                    metrics.get("profit_factor", 0.0) >= MicroLiveCriteria.MINIMUM_PROFIT_FACTOR,
                    f"{metrics.get('profit_factor', 0.0):.2f} / "
                    f"{MicroLiveCriteria.MINIMUM_PROFIT_FACTOR:.1f} required",
                ),
                (
                    "Positive strategies",
                    metrics.get("positive_strategies", 0)
                    >= MicroLiveCriteria.MINIMUM_POSITIVE_STRATEGIES,
                    f"{metrics.get('positive_strategies', 0)} / "
                    f"{MicroLiveCriteria.MINIMUM_POSITIVE_STRATEGIES} required",
                ),
            ]
            for label, passed, detail in criteria_checks:
                tag = "PASS" if passed else "FAIL"
                print(f"  [{tag}] {label}: {detail}")
        else:
            for reason in reasons:
                print(f"  [FAIL] {reason}")
        print()
        print("READY" if ready else "NOT READY")
        return

    if args.command == "rebalance-capital":
        allocator = CapitalAllocator()
        performances = allocator.from_checkpoint(config.runtime.runtime_checkpoint_path)
        if not performances:
            print("No checkpoint data found. Run the daemon first to collect performance data.")
            return
        total_capital = sum(p.initial_capital for p in performances)
        result = allocator.allocate(performances, total_capital)
        report_path = "artifacts/capital-allocation.json"
        allocator.save_report(result, report_path)
        print(f"\n{'=' * 60}")
        print("  CAPITAL REBALANCE — Concentrate on Top Performers")
        print(f"{'=' * 60}")
        print(f"\n  {'Rank':<5} {'Strategy':<22} {'Score':>7} {'Weight':>8} {'Capital':>14}")
        print(f"  {'-' * 58}")
        for a in result.allocations:
            print(
                f"  #{a.rank:<4} {a.strategy:<22} {a.score:>6.3f} "
                f"{a.weight:>7.1%} {a.capital:>13,.0f}"
            )
        print(f"\n  Concentration (HHI): {result.concentration_ratio:.4f}")
        print("  TOML wallets:\n")
        print(allocator.to_toml_wallets(result.allocations))
        print(f"\n  Report saved to {report_path}")
        return

    if args.command == "walk-forward":
        from crypto_trader.backtest.walk_forward import WalkForwardValidator

        strategy_type = args.strategy
        days = args.days
        symbols = config.trading.symbols

        # Fetch candles
        candles_map: dict[str, list] = {}
        for sym in symbols:
            try:
                c = market_data.get_ohlcv(sym, interval=config.trading.interval, count=days * 24)
                if c and len(c) >= 100:
                    candles_map[sym] = c
            except Exception as e:
                print(f"  Skipping {sym}: {e}")

        if not candles_map:
            print("No candle data available for walk-forward validation.")
            return

        validator = WalkForwardValidator(
            backtest_config=config.backtest,
            risk_config=config.risk,
            n_folds=3,
            train_pct=0.7,
        )

        print(f"\n{'=' * 60}")
        print(f"  WALK-FORWARD VALIDATION — {strategy_type} ({days}d)")
        print(f"{'=' * 60}")

        all_passed = True
        for sym, candles in candles_map.items():

            def _factory(s=sym, cs=candles):
                strat = create_strategy(strategy_type, config.strategy, config.regime)
                _prime_strategy_for_backtest(strat, strategy_type, s, cs)
                return strat

            report = validator.validate(
                strategy_factory=_factory,
                candles=candles,
                symbol=sym,
                strategy_name=strategy_type,
            )

            summary = report.summary()
            status = "PASS" if report.passed else "FAIL"
            all_passed = all_passed and report.passed

            print(f"\n  {sym}:")
            print(f"    Folds: {summary['total_folds']}")
            print(f"    Avg Train Return: {summary['avg_train_return_pct']:+.3f}%")
            print(f"    Avg Test Return:  {summary['avg_test_return_pct']:+.3f}%")
            print(f"    Efficiency Ratio: {summary['avg_efficiency_ratio']:.3f}")
            print(f"    OOS Win Rate:     {summary['oos_win_rate']:.1%}")
            print(f"    Status:           [{status}]")

        print(f"\n{'=' * 60}")
        overall = "PASS" if all_passed else "FAIL"
        print(f"  Overall: [{overall}]")
        print(f"{'=' * 60}\n")
        return

    if args.command == "grid-wf":
        from crypto_trader.backtest.grid_wf import run_grid_wf

        strategy_type = args.strategy
        days = args.days
        top_n = args.top_n
        symbols = config.trading.symbols

        # Fetch candles
        candles_map: dict[str, list] = {}
        for sym in symbols:
            try:
                c = market_data.get_ohlcv(sym, interval=config.trading.interval, count=days * 24)
                if c and len(c) >= 100:
                    candles_map[sym] = c
            except Exception as e:
                print(f"  Skipping {sym}: {e}")

        if not candles_map:
            print("No candle data available for grid-wf.")
            return

        print(f"\n{'=' * 60}")
        print(f"  GRID-WF: {strategy_type} ({days}d, top-{top_n})")
        print(f"{'=' * 60}")

        summary = run_grid_wf(
            strategy_type=strategy_type,
            candles_by_symbol=candles_map,
            top_n=top_n,
            backtest_config=config.backtest,
            risk_config=config.risk,
            regime_filter=args.regime,
        )

        print(f"\n  Candidates tested: {summary.candidates_tested}")
        print(f"  Candidates validated (WF pass): {summary.candidates_validated}")

        print(
            f"\n  {'Rank':<5} {'Sharpe':>8} {'Sortino':>8} {'Return%':>9} "
            f"{'Trades':>7} {'WF':>6} {'EffR':>7} {'OOS WR':>7}"
        )
        print(f"  {'-' * 58}")
        for i, r in enumerate(summary.results, 1):
            wf_status = "PASS" if r.validated else "FAIL"
            eff_r = r.wf_report.avg_efficiency_ratio
            oos_wr = r.wf_report.oos_win_rate
            sortino_val = (
                r.candidate.avg_sortino if r.candidate.avg_sortino != float("inf") else 999.0
            )
            print(
                f"  #{i:<4} {r.candidate.avg_sharpe:>7.2f} "
                f"{sortino_val:>7.2f} "
                f"{r.candidate.avg_return_pct:>+8.2f}% "
                f"{r.candidate.total_trades:>7} "
                f"[{wf_status}] "
                f"{eff_r:>6.3f} "
                f"{oos_wr:>6.1%}"
            )
            print(f"         params: {r.candidate.params}")

        best = summary.best_validated
        if best:
            print(
                f"\n  BEST VALIDATED: Sharpe={best.candidate.avg_sharpe:.2f} "
                f"Return={best.candidate.avg_return_pct:+.2f}%"
            )
            print(f"  Params: {best.candidate.params}")
        else:
            print("\n  No candidates passed walk-forward validation.")

        print(f"\n{'=' * 60}\n")

        # Save results to JSON
        import json
        from datetime import date

        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        export_path = artifacts_dir / f"grid-wf-{strategy_type}-{date.today().isoformat()}.json"
        export_path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
        print(f"  Results saved to {export_path}")
        return

    if args.command == "correlation":
        from crypto_trader.backtest.correlation import signal_correlation

        strategy_types = ["momentum", "mean_reversion", "vpin", "volatility_breakout"]
        strategy_types.insert(1, "momentum_pullback")
        strategies = [create_strategy(s, config.strategy, config.regime) for s in strategy_types]

        # Fetch candles for primary symbol
        candles = market_data.get_ohlcv(
            config.trading.symbol,
            interval=config.trading.interval,
            count=config.trading.candle_count,
        )

        if not candles or len(candles) < 50:
            print("Not enough candle data for correlation analysis.")
            return

        corr = signal_correlation(strategies, candles, strategy_types)

        print(f"\n{'=' * 60}")
        print("  STRATEGY SIGNAL CORRELATION MATRIX")
        print(f"{'=' * 60}\n")

        # Print header
        header = f"  {'':>20}" + "".join(f"{s:>14}" for s in strategy_types)
        print(header)
        print(f"  {'-' * (20 + 14 * len(strategy_types))}")

        for sa in strategy_types:
            row = f"  {sa:>20}"
            for sb in strategy_types:
                key = (sa, sb) if (sa, sb) in corr else (sb, sa)
                val = corr.get(key, 0.0)
                row += f"{val:>13.3f} "
            print(row)

        print("\n  Correlation > 0.7 = highly redundant (consider removing one)")
        print("  Correlation < 0.3 = good diversification")
        print(f"{'=' * 60}\n")
        return

    if args.command == "apply-params":
        import glob as globmod
        import json

        # Find latest grid-wf JSON
        strategy_type = args.strategy
        pattern = f"artifacts/grid-wf-{strategy_type}-*.json"
        files = sorted(globmod.glob(pattern))
        if not files:
            print(f"No grid-wf results found for {strategy_type}. Run grid-wf first.")
            return

        latest = files[-1]
        data = json.loads(Path(latest).read_text(encoding="utf-8"))

        best = data.get("best_validated")
        if not best:
            print(f"No validated candidate in {latest}.")
            return

        best_params = best["params"]
        wallet_name = args.wallet

        if not wallet_name:
            # Auto-detect: find wallet matching strategy type
            matching = [w for w in config.wallets if w.strategy == strategy_type]
            if not matching:
                print(f"No wallet with strategy={strategy_type}. Use --wallet to specify.")
                return
            wallet_name = matching[0].name

        # Read daemon.toml and update
        config_path = Path(args.config or "config/daemon.toml")
        if not config_path.exists():
            print(f"Config file not found: {config_path}")
            return

        config_path.read_text(encoding="utf-8")

        # Find the wallet section and show diff
        print(f"\n{'=' * 60}")
        print(f"  APPLY PARAMS: {strategy_type} -> {wallet_name}")
        print(f"  Source: {latest}")
        print(f"{'=' * 60}\n")

        # Show what will change
        target_wallet = None
        for w in config.wallets:
            if w.name == wallet_name:
                target_wallet = w
                break

        if not target_wallet:
            print(f"Wallet '{wallet_name}' not found in config.")
            return

        from crypto_trader.config import _STRATEGY_FIELD_NAMES

        strategy_params = {k: v for k, v in best_params.items() if k in _STRATEGY_FIELD_NAMES}

        print("  Parameter changes:")
        for key, new_val in sorted(strategy_params.items()):
            old_val = target_wallet.strategy_overrides.get(key, "(default)")
            marker = " *" if str(old_val) != str(new_val) else ""
            print(f"    {key}: {old_val} -> {new_val}{marker}")

        # Write updated params as JSON sidecar (safer than modifying TOML directly)
        output = {
            "wallet": wallet_name,
            "strategy": strategy_type,
            "source": latest,
            "params": strategy_params,
            "best_sharpe": best["avg_sharpe"],
        }
        sidecar_path = Path("artifacts") / f"apply-params-{wallet_name}.json"
        sidecar_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

        print(f"\n  Params saved to {sidecar_path}")
        print(f"  To apply: manually update [wallets.strategy_overrides] in {config_path}")
        print(f"{'=' * 60}\n")
        return

    if args.command == "backtest-all":
        import json
        from datetime import date

        from crypto_trader.backtest.grid_wf import (
            _approx_calmar,
            _approx_sharpe,
            _approx_sortino,
            bootstrap_return_ci,
            kelly_fraction,
        )
        from crypto_trader.strategy.regime import RegimeDetector

        all_strategies = [
            "momentum",
            "momentum_pullback",
            "mean_reversion",
            "vpin",
            "volatility_breakout",
            "kimchi_premium",
            "funding_rate",
            "obi",
            "ema_crossover",
            "consensus",
        ]
        symbols = config.trading.symbols
        results_list: list[dict] = []

        # Fetch candles for all symbols
        candles_map: dict[str, list] = {}
        for sym in symbols:
            try:
                c = market_data.get_ohlcv(
                    sym, interval=config.trading.interval, count=config.trading.candle_count
                )
                if c and len(c) >= 50:
                    candles_map[sym] = c
            except Exception as e:
                print(f"  Skipping {sym}: {e}")

        if not candles_map:
            print("No candle data available for backtest-all.")
            return

        print(f"\n{'=' * 90}")
        print(f"  BACKTEST-ALL: {len(all_strategies)} strategies x {len(candles_map)} symbols")
        print(f"{'=' * 90}")
        print(
            f"\n  {'Strategy':<22} {'Return%':>9} {'Sharpe':>8} {'Sortino':>8} "
            f"{'Calmar':>8} {'PF':>6} {'MDD%':>7} {'WinR%':>7} {'Trades':>7} "
            f"{'MCL':>4}"
        )
        print(f"  {'-' * 88}")

        for strat_name in all_strategies:
            try:
                sym_returns: list[float] = []
                sym_sharpes: list[float] = []
                sym_sortinos: list[float] = []
                sym_calmars: list[float] = []
                sym_pfs: list[float] = []
                sym_mdds: list[float] = []
                sym_wrs: list[float] = []
                sym_payoffs: list[float] = []
                sym_evs: list[float] = []
                sym_recoveries: list[float] = []
                sym_tails: list[float] = []
                sym_durations: list[float] = []
                all_trade_returns: list[float] = []
                total_trades = 0
                max_mcl = 0
                max_mcw = 0
                max_dur = 0
                regime_wins: dict[str, int] = {"bull": 0, "sideways": 0, "bear": 0}
                regime_totals: dict[str, int] = {"bull": 0, "sideways": 0, "bear": 0}
                regime_profit: dict[str, float] = {"bull": 0.0, "sideways": 0.0, "bear": 0.0}
                regime_loss: dict[str, float] = {"bull": 0.0, "sideways": 0.0, "bear": 0.0}

                for sym, candles in candles_map.items():
                    bt_strategy = create_strategy(strat_name, config.strategy, config.regime)
                    _prime_strategy_for_backtest(bt_strategy, strat_name, sym, candles)
                    bt_risk = _build_risk_manager(config)
                    engine = BacktestEngine(
                        strategy=bt_strategy,
                        risk_manager=bt_risk,
                        config=config.backtest,
                        symbol=sym,
                    )
                    bt_result = engine.run(candles)
                    sharpe = _approx_sharpe(bt_result.equity_curve)
                    sortino = _approx_sortino(bt_result.equity_curve)
                    calmar = _approx_calmar(bt_result.equity_curve)

                    sym_returns.append(bt_result.total_return_pct * 100)
                    sym_sharpes.append(sharpe)
                    sym_sortinos.append(sortino if sortino != float("inf") else 0.0)
                    sym_calmars.append(calmar if calmar != float("inf") else 0.0)
                    pf = bt_result.profit_factor if bt_result.profit_factor != float("inf") else 0.0
                    sym_pfs.append(pf)
                    sym_mdds.append(bt_result.max_drawdown * 100)
                    sym_wrs.append(bt_result.win_rate * 100)
                    sym_payoffs.append(bt_result.payoff_ratio)
                    sym_evs.append(bt_result.expected_value_per_trade)
                    sym_recoveries.append(bt_result.recovery_factor)
                    sym_tails.append(bt_result.tail_ratio)
                    sym_durations.append(bt_result.avg_trade_duration_bars)
                    all_trade_returns.extend(t.pnl_pct for t in bt_result.trade_log)
                    total_trades += len(bt_result.trade_log)
                    max_mcl = max(max_mcl, bt_result.max_consecutive_losses)
                    max_mcw = max(max_mcw, bt_result.max_consecutive_wins)
                    max_dur = max(max_dur, bt_result.max_trade_duration_bars)

                    # Regime breakdown per trade
                    regime_det = RegimeDetector(config.regime)
                    for trade in bt_result.trade_log:
                        # Find entry index in candle list
                        entry_idx = None
                        for ci, c in enumerate(candles):
                            if c.timestamp >= trade.entry_time:
                                entry_idx = ci
                                break
                        if entry_idx is not None and entry_idx >= 31:
                            r = regime_det.detect(candles[: entry_idx + 1])
                            rkey = r.value
                            regime_totals[rkey] = regime_totals.get(rkey, 0) + 1
                            if trade.pnl > 0:
                                regime_wins[rkey] = regime_wins.get(rkey, 0) + 1
                                regime_profit[rkey] = regime_profit.get(rkey, 0.0) + trade.pnl
                            else:
                                regime_loss[rkey] = regime_loss.get(rkey, 0.0) + abs(trade.pnl)

                n = len(sym_returns)
                if n == 0:
                    print(f"  {strat_name:<22} {'(no valid results)':>40}")
                    continue

                avg_sharpe = round(sum(sym_sharpes) / n, 3)
                avg_sortino = round(sum(sym_sortinos) / n, 3)
                avg_calmar = round(sum(sym_calmars) / n, 3)
                avg_pf = round(sum(sym_pfs) / n, 3)
                # Composite score: Sharpe 30% + Sortino 25% + Calmar 15% + PF 20% + WinRate 10%
                composite = (
                    avg_sharpe * 0.30
                    + avg_sortino * 0.25
                    + avg_calmar * 0.15
                    + avg_pf * 0.20
                    + (sum(sym_wrs) / n / 100) * 0.10
                )
                row = {
                    "strategy": strat_name,
                    "symbols_tested": n,
                    "return_pct": round(sum(sym_returns) / n, 3),
                    "sharpe": avg_sharpe,
                    "sortino": avg_sortino,
                    "calmar": avg_calmar,
                    "profit_factor": avg_pf,
                    "max_drawdown_pct": round(max(sym_mdds), 3),
                    "win_rate_pct": round(sum(sym_wrs) / n, 1),
                    "trade_count": total_trades,
                    "max_consecutive_losses": max_mcl,
                    "max_consecutive_wins": max_mcw,
                    "avg_trade_duration_bars": round(sum(sym_durations) / n, 1)
                    if sym_durations
                    else 0.0,
                    "max_trade_duration_bars": max_dur,
                    "payoff_ratio": round(sum(sym_payoffs) / n, 3) if sym_payoffs else 0.0,
                    "expected_value_per_trade": round(sum(sym_evs) / n, 2) if sym_evs else 0.0,
                    "recovery_factor": round(sum(sym_recoveries) / n, 3) if sym_recoveries else 0.0,
                    "tail_ratio": round(sum(sym_tails) / n, 3) if sym_tails else 0.0,
                    "regime_bull_wr": round(
                        regime_wins.get("bull", 0) / max(1, regime_totals.get("bull", 0)) * 100, 1
                    ),
                    "regime_sideways_wr": round(
                        regime_wins.get("sideways", 0)
                        / max(1, regime_totals.get("sideways", 0))
                        * 100,
                        1,
                    ),
                    "regime_bear_wr": round(
                        regime_wins.get("bear", 0) / max(1, regime_totals.get("bear", 0)) * 100, 1
                    ),
                    "regime_bull_n": regime_totals.get("bull", 0),
                    "regime_sideways_n": regime_totals.get("sideways", 0),
                    "regime_bear_n": regime_totals.get("bear", 0),
                    "regime_bull_pf": round(
                        regime_profit.get("bull", 0) / max(0.01, regime_loss.get("bull", 0.01)), 2
                    ),
                    "regime_sideways_pf": round(
                        regime_profit.get("sideways", 0)
                        / max(0.01, regime_loss.get("sideways", 0.01)),
                        2,
                    ),
                    "regime_bear_pf": round(
                        regime_profit.get("bear", 0) / max(0.01, regime_loss.get("bear", 0.01)), 2
                    ),
                    "return_ci_5": round(
                        bootstrap_return_ci(all_trade_returns, n_samples=500)[0] * 100, 3
                    )
                    if all_trade_returns
                    else 0.0,
                    "return_ci_95": round(
                        bootstrap_return_ci(all_trade_returns, n_samples=500)[1] * 100, 3
                    )
                    if all_trade_returns
                    else 0.0,
                    "kelly_fraction": round(
                        kelly_fraction(
                            sum(sym_wrs) / n / 100, sum(sym_payoffs) / n if sym_payoffs else 0.0
                        ),
                        4,
                    ),
                    "composite_score": round(composite, 3),
                }
                results_list.append(row)
                print(
                    f"  {strat_name:<22} {row['return_pct']:>+8.2f}% "
                    f"{row['sharpe']:>7.2f} "
                    f"{row['sortino']:>7.2f} "
                    f"{row['calmar']:>7.2f} "
                    f"{row['profit_factor']:>5.2f} "
                    f"{row['max_drawdown_pct']:>6.2f}% "
                    f"{row['win_rate_pct']:>6.1f}% "
                    f"{row['trade_count']:>7} "
                    f"{row['max_consecutive_losses']:>4}"
                )
            except Exception as exc:
                print(f"  {strat_name:<22} ERROR: {exc}")

        # Strategy recommendations based on composite score
        if results_list:
            ranked = sorted(results_list, key=lambda r: r.get("composite_score", 0), reverse=True)
            print(f"\n{'=' * 90}")
            print("  STRATEGY RANKING (by composite score)")
            print(f"{'=' * 90}")
            print(f"\n  {'Rank':<6} {'Strategy':<22} {'Score':>7} {'Kelly%':>7} {'Action':<20}")
            print(f"  {'-' * 62}")
            for i, r in enumerate(ranked, 1):
                score = r.get("composite_score", 0)
                kf = r.get("kelly_fraction", 0) * 100
                if score > 1.0 and r["return_pct"] > 0:
                    action = "DEPLOY candidate"
                elif score > 0.5 and r["return_pct"] > 0:
                    action = "RESEARCH hold"
                elif r["return_pct"] > 0:
                    action = "WATCHLIST"
                else:
                    action = "DROP"
                print(f"  #{i:<5} {r['strategy']:<22} {score:>6.3f} {kf:>6.1f}% {action}")

        # Correlation guard: warn about highly correlated strategy pairs
        if len(results_list) >= 2:
            equity_curves: dict[str, list[float]] = {}
            for strat_name2 in all_strategies:
                try:
                    curves: list[list[float]] = []
                    for sym, candle_list in candles_map.items():
                        bt_s = create_strategy(strat_name2, config.strategy, config.regime)
                        _prime_strategy_for_backtest(bt_s, strat_name2, sym, candle_list)
                        bt_r = _build_risk_manager(config)
                        eng = BacktestEngine(
                            strategy=bt_s,
                            risk_manager=bt_r,
                            config=config.backtest,
                            symbol=sym,
                        )
                        res = eng.run(candle_list)
                        curves.append(res.equity_curve)
                    if curves:
                        # Use the first symbol's equity curve as representative
                        equity_curves[strat_name2] = curves[0]
                except Exception:
                    pass

            corr_warnings: list[str] = []
            strat_names = list(equity_curves.keys())
            for i in range(len(strat_names)):
                for j in range(i + 1, len(strat_names)):
                    a = equity_curves[strat_names[i]]
                    b = equity_curves[strat_names[j]]
                    min_len = min(len(a), len(b))
                    if min_len >= 20:
                        from crypto_trader.strategy.indicators import rolling_correlation

                        corr = rolling_correlation(a[:min_len], b[:min_len], min_len)
                        if corr > 0.8:
                            corr_warnings.append(
                                f"  {strat_names[i]} <-> {strat_names[j]}: r={corr:.3f}"
                            )

            if corr_warnings:
                print(f"\n{'=' * 90}")
                print("  CORRELATION WARNINGS (r > 0.8 — avoid deploying both)")
                print(f"{'=' * 90}")
                for w in corr_warnings:
                    print(w)

        print(f"\n{'=' * 90}\n")

        # Save results
        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        export = {
            "date": date.today().isoformat(),
            "symbols": list(candles_map.keys()),
            "candle_count": config.trading.candle_count,
            "results": ranked if results_list else [],
        }
        export_path = artifacts_dir / f"backtest-all-{date.today().isoformat()}.json"
        export_path.write_text(json.dumps(export, indent=2), encoding="utf-8")
        print(f"  Results saved to {export_path}")
        return

    if args.command == "grid-wf-all":
        import json
        from datetime import date

        from crypto_trader.backtest.grid_wf import _approx_sortino, kelly_fraction, run_grid_wf

        grid_strategies = [
            "momentum",
            "momentum_pullback",
            "mean_reversion",
            "kimchi_premium",
            "funding_rate",
            "vpin",
            "volatility_breakout",
            "obi",
            "ema_crossover",
            "consensus",
        ]
        days = args.days
        top_n = args.top_n
        symbols = config.trading.symbols

        # Fetch candles once for all strategies
        candles_map_gw: dict[str, list] = {}
        for sym in symbols:
            try:
                c = market_data.get_ohlcv(sym, interval=config.trading.interval, count=days * 24)
                if c and len(c) >= 100:
                    candles_map_gw[sym] = c
            except Exception as e:
                print(f"  Skipping {sym}: {e}")

        if not candles_map_gw:
            print("No candle data available for grid-wf-all.")
            return

        print(f"\n{'=' * 70}")
        print(f"  GRID-WF-ALL: {len(grid_strategies)} strategies ({days}d, top-{top_n})")
        print(f"{'=' * 70}")

        all_summaries: list[dict] = []

        for strat_name in grid_strategies:
            try:
                print(f"\n  --- {strat_name} ---")
                summary = run_grid_wf(
                    strategy_type=strat_name,
                    candles_by_symbol=candles_map_gw,
                    top_n=top_n,
                    backtest_config=config.backtest,
                    risk_config=config.risk,
                    regime_filter=args.regime,
                )

                print(
                    f"  Tested: {summary.candidates_tested}  "
                    f"Validated: {summary.candidates_validated}"
                )

                best = summary.best_validated
                if best:
                    print(
                        f"  BEST: Sharpe={best.candidate.avg_sharpe:.2f} "
                        f"Sortino={best.candidate.avg_sortino:.2f} "
                        f"Return={best.candidate.avg_return_pct:+.2f}%"
                    )
                    print(f"  Params: {best.candidate.params}")
                else:
                    print("  No validated candidate.")

                summary_dict = summary.to_dict()
                summary_dict["strategy"] = strat_name
                all_summaries.append(summary_dict)
            except Exception as exc:
                print(f"  {strat_name}: ERROR — {exc}")

        # Combined summary
        print(f"\n{'=' * 70}")
        print("  GRID-WF-ALL SUMMARY")
        print(f"{'=' * 70}")
        print(
            f"\n  {'Strategy':<22} {'Validated':>9} {'Best Sharpe':>12} "
            f"{'Best Sortino':>13} {'Best Return':>12}"
        )
        print(f"  {'-' * 70}")
        for s in all_summaries:
            bv = s.get("best_validated")
            if bv:
                print(
                    f"  {s['strategy']:<22} {s['candidates_validated']:>9} "
                    f"{bv['avg_sharpe']:>11.2f} {bv.get('avg_sortino', 0):>12.2f} "
                    f"{bv['avg_return_pct']:>+11.2f}%"
                )
            else:
                print(
                    f"  {s['strategy']:<22} {s['candidates_validated']:>9} "
                    f"{'—':>12} {'—':>13} {'—':>12}"
                )

        print(f"\n{'=' * 70}\n")

        # Save combined results
        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        export_gw = {
            "date": date.today().isoformat(),
            "days": days,
            "top_n": top_n,
            "symbols": list(candles_map_gw.keys()),
            "strategies": all_summaries,
        }
        export_path_gw = artifacts_dir / f"grid-wf-all-{date.today().isoformat()}.json"
        export_path_gw.write_text(json.dumps(export_gw, indent=2), encoding="utf-8")
        print(f"  Results saved to {export_path_gw}")

        # Auto-generate optimized TOML from best validated params
        toml_lines = [
            "# Auto-generated from grid-wf-all",
            f"# Date: {date.today().isoformat()}",
            "",
        ]
        total_kelly = 0.0
        validated_strats: list[dict] = []
        for s in all_summaries:
            bv = s.get("best_validated")
            if bv and bv.get("params"):
                wr = 0.5  # default
                pr = bv.get("avg_profit_factor", 1.0)
                kf = kelly_fraction(wr, pr)
                validated_strats.append(
                    {"strategy": s["strategy"], "params": bv["params"], "kelly": kf}
                )
                total_kelly += kf

        if validated_strats:
            base_capital = 1_000_000.0
            for vs in validated_strats:
                weight = (
                    vs["kelly"] / total_kelly if total_kelly > 0 else 1.0 / len(validated_strats)
                )
                capital = round(base_capital * weight, 0)
                toml_lines.append("[[wallets]]")
                toml_lines.append(f'name = "{vs["strategy"]}_optimized"')
                toml_lines.append(f'strategy = "{vs["strategy"]}"')
                toml_lines.append(f"initial_capital = {capital:.0f}")
                toml_lines.append("")
                toml_lines.append("[wallets.strategy_overrides]")
                for pk, pv in vs["params"].items():
                    if isinstance(pv, str):
                        toml_lines.append(f'{pk} = "{pv}"')
                    else:
                        toml_lines.append(f"{pk} = {pv}")
                toml_lines.append("")

            toml_path = artifacts_dir / f"optimized-{date.today().isoformat()}.toml"
            toml_path.write_text("\n".join(toml_lines), encoding="utf-8")
            print(f"  Optimized TOML saved to {toml_path}")
        return

    if args.command == "strategy-dashboard":
        import glob as globmod
        import json

        # Find latest backtest-all JSON
        pattern = "artifacts/backtest-all-*.json"
        files = sorted(globmod.glob(pattern))
        if not files:
            print("No backtest-all results found. Run backtest-all first.")
            return

        latest = files[-1]
        data = json.loads(Path(latest).read_text(encoding="utf-8"))
        results = data.get("results", [])

        if not results:
            print("No strategy results in latest backtest-all.")
            return

        print(f"\n{'=' * 100}")
        print(f"  STRATEGY HEALTH DASHBOARD — {latest}")
        print(f"{'=' * 100}")

        # Sort by composite score
        ranked = sorted(results, key=lambda r: r.get("composite_score", 0), reverse=True)

        print(
            f"\n  {'#':<4} {'Strategy':<20} {'Score':>6} {'Kelly%':>7} "
            f"{'EV/Trade':>10} {'Return%':>9} {'Sharpe':>7} {'Sortino':>8} "
            f"{'Calmar':>8} {'RecF':>6} {'Tail':>5} {'Action':<18}"
        )
        print(f"  {'-' * 110}")

        for i, r in enumerate(ranked, 1):
            score = r.get("composite_score", 0)
            kf = r.get("kelly_fraction", 0) * 100
            ev = r.get("expected_value_per_trade", 0)
            rec = r.get("recovery_factor", 0)
            tail = r.get("tail_ratio", 0)
            ret = r.get("return_pct", 0)
            sh = r.get("sharpe", 0)
            so = r.get("sortino", 0)
            ca = r.get("calmar", 0)

            if score > 1.0 and ret > 0 and kf > 0:
                action = "DEPLOY"
            elif score > 0.5 and ret > 0:
                action = "RESEARCH"
            elif ret > 0:
                action = "WATCHLIST"
            else:
                action = "DROP"

            print(
                f"  {i:<4} {r['strategy']:<20} {score:>5.2f} {kf:>6.1f}% "
                f"{ev:>+9.0f} {ret:>+8.2f}% {sh:>6.2f} {so:>7.2f} {ca:>7.2f} "
                f"{rec:>5.2f} {tail:>4.2f} {action}"
            )

        # Summary stats
        deploy_count = sum(
            1
            for r in ranked
            if r.get("composite_score", 0) > 1.0
            and r.get("return_pct", 0) > 0
            and r.get("kelly_fraction", 0) > 0
        )
        total_ev = sum(
            r.get("expected_value_per_trade", 0) for r in ranked if r.get("return_pct", 0) > 0
        )
        print(f"\n  Deploy candidates: {deploy_count}/{len(ranked)}")
        print(f"  Total EV (positive strategies): {total_ev:+,.0f} KRW/trade")
        print(f"  Source: {latest}")
        print(f"{'=' * 100}\n")
        return

    if args.command == "run-multi":
        alert_manager = _build_alert_manager(config)

        def runtime_factory(restart_count: int, last_restart_at: str | None) -> MultiSymbolRuntime:
            wallets = build_wallets(config)
            return MultiSymbolRuntime(
                wallets=wallets,
                market_data=market_data,
                config=config,
                restart_count=restart_count,
                last_restart_at=last_restart_at,
                supervisor_active=True,
            )

        supervisor = DaemonSupervisor(
            runtime_factory=runtime_factory,
            alert_manager=alert_manager,
            healthcheck_path=config.runtime.healthcheck_path,
            config_path=config.source_config_path,
            auto_restart_enabled=config.runtime.auto_restart_enabled,
            restart_backoff_seconds=config.runtime.restart_backoff_seconds,
            max_restart_attempts=config.runtime.max_restart_attempts,
            daemon_alert_cooldown_seconds=config.runtime.daemon_alert_cooldown_seconds,
        )
        supervisor.run()
        return

    if args.command == "strategy-report":
        wallets = build_wallets(config)
        latest_prices: dict[str, float] = {}
        for symbol in config.trading.symbols:
            try:
                candles = market_data.get_ohlcv(
                    symbol=symbol,
                    interval=config.trading.interval,
                    count=1,
                )
                if candles:
                    latest_prices[symbol] = candles[-1].close
            except Exception:
                pass
        report_text = StrategyComparisonReport().generate(
            wallets=wallets,
            symbols=config.trading.symbols,
            latest_prices=latest_prices,
        )
        report_path = config.runtime.strategy_report_path
        StrategyComparisonReport().save(report_text, report_path)
        print(report_text)
        return

    if args.command == "signal-summary":
        import json as _json
        from collections import Counter

        journal_path = Path(config.runtime.strategy_run_journal_path)
        if not journal_path.exists():
            print("No strategy run journal found.")
            return
        lines = journal_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            print("Journal is empty.")
            return

        reasons: Counter[str] = Counter()
        by_wallet: dict[str, dict] = {}
        total_records = 0

        for line in lines:
            try:
                r = _json.loads(line)
            except Exception:
                continue
            total_records += 1
            wn = r.get("wallet_name", "unknown") or "unknown"
            action = r.get("signal_action", "hold")
            reason = r.get("signal_reason", "unknown")
            conf = r.get("signal_confidence", 0.0)
            reasons[reason] += 1
            if wn not in by_wallet:
                by_wallet[wn] = {"buy": 0, "sell": 0, "hold": 0, "total": 0, "conf_sum": 0.0}
            by_wallet[wn][action] = by_wallet[wn].get(action, 0) + 1
            by_wallet[wn]["total"] += 1
            by_wallet[wn]["conf_sum"] += conf

        print(f"=== Signal Summary ({total_records} records) ===\n")

        print("--- Hold Reasons (top 15) ---")
        for reason, count in reasons.most_common(15):
            pct = count / total_records * 100
            print(f"  {reason:40s} {count:5d} ({pct:5.1f}%)")

        print("\n--- Per-Wallet Signal Distribution ---")
        print(
            f"  {'Wallet':<30s} {'Buy':>5s} {'Sell':>5s} {'Hold':>5s} "
            f"{'Total':>6s} {'AvgConf':>8s} {'BuyRate':>8s}"
        )
        print(f"  {'-' * 68}")
        for wn, stats in sorted(by_wallet.items()):
            avg_conf = stats["conf_sum"] / stats["total"] if stats["total"] > 0 else 0
            buy_rate = stats["buy"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(
                f"  {wn:<30s} {stats['buy']:5d} {stats['sell']:5d} {stats['hold']:5d} "
                f"{stats['total']:6d} {avg_conf:8.2f} {buy_rate:7.1f}%"
            )

        # Actionable insights
        print("\n--- Actionable Insights ---")
        sum(1 for r, _ in reasons.items() if r != "position_open_waiting")
        if reasons.get("below_ma_filter", 0) > total_records * 0.1:
            print(
                "  [!] MA filter blocking >10% of signals — consider relaxing "
                "ma_filter_period in sideways"
            )
        if reasons.get("adx_too_weak", 0) > total_records * 0.05:
            print(
                "  [!] ADX filter blocking >5% — consider lowering ADX "
                "threshold for sideways regime"
            )
        if reasons.get("cooldown_active", 0) > total_records * 0.15:
            print("  [!] Cooldown blocking >15% — consider shorter cooldown_hours")
        if reasons.get("entry_conditions_not_met", 0) > total_records * 0.4:
            print("  [!] Generic entry block >40% — strategies may need looser sideways thresholds")
        buy_total = sum(s["buy"] for s in by_wallet.values())
        if buy_total == 0:
            print("  [!] ZERO buy signals across all wallets — entry conditions too strict")
        elif buy_total < 5:
            print(f"  [!] Only {buy_total} buy signals — entry frequency very low")

        return

    if args.command == "refresh-artifacts":
        print("=== Refreshing Artifacts ===")
        # 1. Drift report + promotion gate (single-symbol)
        artifacts = generate_operator_artifacts(
            config=config,
            market_data=market_data,
            strategy=strategy,
            risk_manager=risk_manager,
        )
        print(f"  drift-report     : {artifacts.drift_report.status.value}")
        print(f"  promotion-gate   : {artifacts.promotion_decision.status.value}")
        print("  daily-memo       : saved")
        # 2. Portfolio promotion gate (multi-wallet)
        portfolio_gate = PortfolioPromotionGate()
        portfolio_decision = portfolio_gate.evaluate_from_checkpoint(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            journal_path=config.runtime.strategy_run_journal_path,
        )
        portfolio_path = Path(config.runtime.promotion_gate_path).parent / "portfolio-gate.json"
        portfolio_gate.save(portfolio_decision, portfolio_path)
        print(
            f"  portfolio-gate   : {portfolio_decision.status.value} "
            f"({portfolio_decision.profitable_wallets}/"
            f"{portfolio_decision.wallet_count} profitable)"
        )
        # 3. Position snapshot
        cp_path = Path(config.runtime.runtime_checkpoint_path)
        if cp_path.exists():
            cp = json.loads(cp_path.read_text(encoding="utf-8"))
            ws = cp.get("wallet_states", {})
            open_count = sum(v.get("open_positions", 0) for v in ws.values())
            print(f"  positions        : {open_count} open across {len(ws)} wallets")
        gate_progress_path = Path("docs/gate-progress.md")
        generate_gate_progress_report(
            runtime_checkpoint_path=Path(config.runtime.runtime_checkpoint_path),
            backtest_baseline_path=Path(config.runtime.backtest_baseline_path),
            drift_report_path=Path(config.runtime.drift_report_path),
            promotion_gate_path=Path(config.runtime.promotion_gate_path),
            strategy_run_journal_path=Path(config.runtime.strategy_run_journal_path),
            walk_forward_summary_path=Path("artifacts/walk-forward-90d/grid-wf-summary.json"),
            output_path=gate_progress_path,
        )
        print(f"  gate-progress    : {gate_progress_path}")
        report_generator = AutomatedReportGenerator()
        artifacts_dir = Path(config.runtime.daily_performance_path).parent
        daily_report_path = report_generator.default_output_path(
            period="daily",
            artifacts_dir=artifacts_dir,
        )
        weekly_report_path = report_generator.default_output_path(
            period="weekly",
            artifacts_dir=artifacts_dir,
        )
        daily_report = report_generator.generate(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            strategy_run_journal_path=config.runtime.strategy_run_journal_path,
            trade_journal_path=config.runtime.paper_trade_journal_path,
            period="daily",
            hours=24,
        )
        weekly_report = report_generator.generate(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            strategy_run_journal_path=config.runtime.strategy_run_journal_path,
            trade_journal_path=config.runtime.paper_trade_journal_path,
            period="weekly",
            hours=168,
        )
        report_generator.save(daily_report, daily_report_path)
        report_generator.save(weekly_report, weekly_report_path)
        Path(config.runtime.daily_performance_path).write_text(
            json.dumps(
                build_legacy_daily_performance_summary(
                    daily_report,
                    report_path=daily_report_path,
                    weekly_report_path=weekly_report_path,
                ),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  daily-report     : {daily_report_path}")
        print(f"  weekly-report    : {weekly_report_path}")
        print("\nAll artifacts refreshed.")
        return

    if args.command == "sync-artifacts":
        print("=== Syncing Artifacts (offline, no API) ===")
        baseline_store = BacktestBaselineStore(config.runtime.backtest_baseline_path)
        baseline = baseline_store.load()
        if baseline is None:
            print("ERROR: No backtest-baseline.json found. Run backtest first.")
            return
        journal = StrategyRunJournal(config.runtime.strategy_run_journal_path)
        recent_runs = journal.load_recent()
        drift_gen = DriftReportGenerator(config.drift)
        drift_report = drift_gen.generate(
            symbol=config.trading.symbol,
            backtest_baseline=baseline,
            recent_runs=recent_runs,
        )
        drift_gen.save(drift_report, config.runtime.drift_report_path)
        print(
            f"  drift-report     : {drift_report.status.value} "
            f"(baseline return={baseline.total_return_pct:.4%})"
        )
        gate = PromotionGate()
        decision = gate.evaluate(
            symbol=config.trading.symbol,
            backtest_baseline=baseline,
            drift_report=drift_report,
            latest_run=recent_runs[-1] if recent_runs else None,
        )
        gate.save(decision, config.runtime.promotion_gate_path)
        print(f"  promotion-gate   : {decision.status.value}")
        portfolio_gate = PortfolioPromotionGate()
        portfolio_decision = portfolio_gate.evaluate_from_checkpoint(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            journal_path=config.runtime.strategy_run_journal_path,
        )
        portfolio_path = Path(config.runtime.promotion_gate_path).parent / "portfolio-gate.json"
        portfolio_gate.save(portfolio_decision, portfolio_path)
        print(f"  portfolio-gate   : {portfolio_decision.status.value}")
        report_generator = AutomatedReportGenerator()
        artifacts_dir = Path(config.runtime.daily_performance_path).parent
        daily_report_path = report_generator.default_output_path(
            period="daily",
            artifacts_dir=artifacts_dir,
        )
        weekly_report_path = report_generator.default_output_path(
            period="weekly",
            artifacts_dir=artifacts_dir,
        )
        daily_report = report_generator.generate(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            strategy_run_journal_path=config.runtime.strategy_run_journal_path,
            trade_journal_path=config.runtime.paper_trade_journal_path,
            period="daily",
            hours=24,
        )
        weekly_report = report_generator.generate(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            strategy_run_journal_path=config.runtime.strategy_run_journal_path,
            trade_journal_path=config.runtime.paper_trade_journal_path,
            period="weekly",
            hours=168,
        )
        report_generator.save(daily_report, daily_report_path)
        report_generator.save(weekly_report, weekly_report_path)
        Path(config.runtime.daily_performance_path).write_text(
            json.dumps(
                build_legacy_daily_performance_summary(
                    daily_report,
                    report_path=daily_report_path,
                    weekly_report_path=weekly_report_path,
                ),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  daily-report     : {daily_report_path}")
        print(f"  weekly-report    : {weekly_report_path}")
        print("\nArtifacts synced from existing baseline (no market data needed).")
        return

    if args.command == "portfolio-gate":
        portfolio_gate = PortfolioPromotionGate()
        decision = portfolio_gate.evaluate_from_checkpoint(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            journal_path=config.runtime.strategy_run_journal_path,
        )
        portfolio_path = Path(config.runtime.promotion_gate_path).parent / "portfolio-gate.json"
        portfolio_gate.save(decision, portfolio_path)
        print("=== Portfolio Promotion Gate ===")
        print(f"Status            : {decision.status.value}")
        print(f"Wallets           : {decision.wallet_count}")
        print(f"Total equity      : {decision.total_equity:,.0f} KRW")
        print(f"Portfolio return   : {decision.portfolio_return_pct:+.4%}")
        print(f"Realized PnL      : {decision.total_realized_pnl:,.0f} KRW")
        print(f"Profitable wallets: {decision.profitable_wallets}/{decision.wallet_count}")
        print(f"Total trades      : {decision.total_trades}")
        print(f"Paper days        : {decision.paper_days}")
        print()
        for reason in decision.reasons:
            is_pass = decision.status.value == "candidate_for_promotion"
            tag = "PASS" if is_pass else "FAIL"
            print(f"  [{tag}] {reason}")
        if decision.per_wallet:
            print("\n--- Per-Wallet ---")
            for name, info in sorted(decision.per_wallet.items()):
                print(
                    f"  {name}: equity={info['equity']:,.0f} "
                    f"pnl={info['realized_pnl']:+,.0f} "
                    f"trades={info['trades']} "
                    f"return={info['return_pct']:+.4%}"
                )
        return

    use_live = (
        not config.trading.paper_trading
        and config.credentials.has_upbit_credentials
    )
    broker: PaperBroker | LiveBroker
    if use_live:
        broker = LiveBroker(
            access_key=config.credentials.upbit_access_key,
            secret_key=config.credentials.upbit_secret_key,
            starting_cash=config.backtest.initial_capital,
            fee_rate=config.backtest.fee_rate,
        )
    else:
        broker = PaperBroker(
            starting_cash=config.backtest.initial_capital,
            fee_rate=config.backtest.fee_rate,
            slippage_pct=config.backtest.slippage_pct,
        )
    notifier = TelegramNotifier(config.telegram) if config.telegram.enabled else NullNotifier()
    pipeline = TradingPipeline(
        config=config,
        market_data=market_data,
        strategy=strategy,
        risk_manager=risk_manager,
        broker=broker,
        notifier=notifier,
    )
    if args.command == "run-loop":
        runtime_single = TradingRuntime(
            pipeline=pipeline,
            monitor=HealthMonitor(config.runtime.healthcheck_path),
            journal=StrategyRunJournal(config.runtime.strategy_run_journal_path),
            verdict_engine=StrategyVerdictEngine(config.risk),
            paper_trading_operations=PaperTradingOperations(
                config.runtime.paper_trade_journal_path,
                config.runtime.position_snapshot_path,
                config.runtime.daily_performance_path,
            ),
            checkpoint_store=RuntimeCheckpointStore(config.runtime.runtime_checkpoint_path),
            poll_interval_seconds=config.runtime.poll_interval_seconds,
            config_path=config.source_config_path,
        )
        runtime_single.run(config.runtime.max_iterations)
        return

    pipeline_result = pipeline.run_once()
    print(pipeline_result.message)


if __name__ == "__main__":
    main()
