from __future__ import annotations

import argparse

from crypto_trader.backtest.baseline import BacktestBaselineStore, build_baseline
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import load_config
from crypto_trader.data.pyupbit_client import PyUpbitMarketDataClient
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.logging_utils import setup_logging
from crypto_trader.monitoring import HealthMonitor
from crypto_trader.notifications.telegram import NullNotifier, TelegramNotifier
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.paper_trading import PaperTradingOperations
from crypto_trader.operator.regime_report import RegimeReportGenerator
from crypto_trader.operator.services import generate_operator_artifacts
from crypto_trader.operator.verdicts import StrategyVerdictEngine
from crypto_trader.pipeline import TradingPipeline
from crypto_trader.risk.manager import RiskManager
from crypto_trader.runtime import TradingRuntime
from crypto_trader.strategy.composite import CompositeStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto trader control plane")
    parser.add_argument(
        "command",
        choices=[
            "run-once",
            "run-loop",
            "backtest",
            "regime-report",
            "drift-report",
            "promotion-gate",
            "daily-memo",
        ],
    )
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config.runtime.log_level)
    strategy = CompositeStrategy(config.strategy, config.regime)
    risk_manager = RiskManager(config.risk)
    market_data = PyUpbitMarketDataClient()

    if args.command == "backtest":
        candles = market_data.get_ohlcv(
            config.trading.symbol,
            interval=config.trading.interval,
            count=config.trading.candle_count,
        )
        engine = BacktestEngine(
            strategy=strategy,
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
        runtime = TradingRuntime(
            pipeline=pipeline,
            monitor=HealthMonitor(config.runtime.healthcheck_path),
            journal=StrategyRunJournal(config.runtime.strategy_run_journal_path),
            verdict_engine=StrategyVerdictEngine(config.risk),
            paper_trading_operations=PaperTradingOperations(
                config.runtime.paper_trade_journal_path,
                config.runtime.position_snapshot_path,
                config.runtime.daily_performance_path,
            ),
            poll_interval_seconds=config.runtime.poll_interval_seconds,
        )
        runtime.run(config.runtime.max_iterations)
        return

    pipeline_result = pipeline.run_once()
    print(pipeline_result.message)


if __name__ == "__main__":
    main()
