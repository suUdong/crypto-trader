from __future__ import annotations

import argparse
from pathlib import Path

from crypto_trader.backtest.baseline import BacktestBaselineStore, build_baseline
from crypto_trader.capital_allocator import CapitalAllocator
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import load_config
from crypto_trader.data.pyupbit_client import PyUpbitMarketDataClient
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.logging_utils import setup_logging
from crypto_trader.monitoring import HealthMonitor
from crypto_trader.multi_runtime import MultiSymbolRuntime
from crypto_trader.notifications.telegram import NullNotifier, TelegramNotifier
from crypto_trader.operator.calibration import DriftCalibrationToolkit
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.paper_trading import PaperTradingOperations
from crypto_trader.operator.performance_report import generate_performance_report
from crypto_trader.operator.pnl_report import PnLReportGenerator
from crypto_trader.operator.promotion import MicroLiveCriteria
from crypto_trader.operator.regime_report import RegimeReportGenerator
from crypto_trader.operator.report import OperatorReportBuilder
from crypto_trader.operator.runtime_state import RuntimeCheckpointStore
from crypto_trader.operator.services import generate_operator_artifacts
from crypto_trader.operator.strategy_report import StrategyComparisonReport
from crypto_trader.operator.verdicts import StrategyVerdictEngine
from crypto_trader.pipeline import TradingPipeline
from crypto_trader.risk.manager import RiskManager
from crypto_trader.runtime import TradingRuntime
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.wallet import build_wallets, create_strategy


def _build_risk_manager(config) -> RiskManager:
    return RiskManager(
        config.risk,
        trailing_stop_pct=config.risk.trailing_stop_pct,
        atr_stop_multiplier=config.risk.atr_stop_multiplier,
    )


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
            "performance-report",
            "micro-live-check",
            "rebalance-capital",
        ],
    )
    parser.add_argument("--config", default=None)
    parser.add_argument(
        "--strategy",
        choices=[
            "momentum", "mean_reversion", "composite",
            "kimchi_premium", "obi", "vpin", "volatility_breakout",
        ],
        default="composite",
        help="Strategy type for backtest (default: composite)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config.runtime.log_level)
    strategy = CompositeStrategy(config.strategy, config.regime)
    risk_manager = _build_risk_manager(config)
    market_data = PyUpbitMarketDataClient()

    if args.command == "backtest":
        backtest_strategy = create_strategy(args.strategy, config.strategy, config.regime)
        candles = market_data.get_ohlcv(
            config.trading.symbol,
            interval=config.trading.interval,
            count=config.trading.candle_count,
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
        print(
            f"promotion_status={artifacts.promotion_decision.status.value} "
            f"paper_runs={artifacts.promotion_decision.observed_paper_runs} "
            f"drift_status={artifacts.promotion_decision.drift_status.value}"
        )
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
        report = generator.generate_from_checkpoint(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            trade_journal_path=config.runtime.paper_trade_journal_path,
            period="daily",
        )
        output_path = "artifacts/pnl-report.md"
        generator.save(report, output_path)
        print(generator.to_markdown(report))
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

    if args.command == "micro-live-check":
        ready, reasons, metrics = MicroLiveCriteria.evaluate_from_artifacts(
            checkpoint_path=config.runtime.runtime_checkpoint_path,
            journal_path=config.runtime.paper_trade_journal_path,
        )
        for reason in reasons:
            status = "PASS" if ready or reason.startswith("All micro-live") else "FAIL"
            print(f"[{status}] {reason}")
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
        print(f"\n{'='*60}")
        print("  CAPITAL REBALANCE — Concentrate on Top Performers")
        print(f"{'='*60}")
        print(f"\n  {'Rank':<5} {'Strategy':<22} {'Score':>7} {'Weight':>8} {'Capital':>14}")
        print(f"  {'-'*58}")
        for a in result.allocations:
            print(f"  #{a.rank:<4} {a.strategy:<22} {a.score:>6.3f} {a.weight:>7.1%} {a.capital:>13,.0f}")
        print(f"\n  Concentration (HHI): {result.concentration_ratio:.4f}")
        print(f"  TOML wallets:\n")
        print(allocator.to_toml_wallets(result.allocations))
        print(f"\n  Report saved to {report_path}")
        return

    if args.command == "run-multi":
        wallets = build_wallets(config)
        runtime = MultiSymbolRuntime(
            wallets=wallets,
            market_data=market_data,
            config=config,
        )
        runtime.run()
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
        )
        runtime_single.run(config.runtime.max_iterations)
        return

    pipeline_result = pipeline.run_once()
    print(pipeline_result.message)


if __name__ == "__main__":
    main()
