from __future__ import annotations

import argparse

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import load_config
from crypto_trader.data.pyupbit_client import PyUpbitMarketDataClient
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.logging_utils import setup_logging
from crypto_trader.monitoring import HealthMonitor
from crypto_trader.notifications.telegram import NullNotifier, TelegramNotifier
from crypto_trader.operator.drift import DriftReportGenerator
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.verdicts import StrategyVerdictEngine
from crypto_trader.pipeline import TradingPipeline
from crypto_trader.risk.manager import RiskManager
from crypto_trader.runtime import TradingRuntime
from crypto_trader.strategy.composite import CompositeStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto trader control plane")
    parser.add_argument("command", choices=["run-once", "run-loop", "backtest", "drift-report"])
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config.runtime.log_level)
    strategy = CompositeStrategy(config.strategy)
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
        print(
            f"final_equity={backtest_result.final_equity:.2f} "
            f"return={backtest_result.total_return_pct:.2%} "
            f"win_rate={backtest_result.win_rate:.2%} "
            f"max_drawdown={backtest_result.max_drawdown:.2%}"
        )
        return

    if args.command == "drift-report":
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
        journal = StrategyRunJournal(config.runtime.strategy_run_journal_path)
        report = DriftReportGenerator().generate(
            symbol=config.trading.symbol,
            backtest_result=backtest_result,
            recent_runs=journal.load_recent(),
        )
        DriftReportGenerator().save(report, config.runtime.drift_report_path)
        print(
            f"drift_status={report.status.value} "
            f"paper_pnl={report.paper_realized_pnl_pct:.2%} "
            f"backtest_return={report.backtest_total_return_pct:.2%}"
        )
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
            poll_interval_seconds=config.runtime.poll_interval_seconds,
        )
        runtime.run(config.runtime.max_iterations)
        return

    pipeline_result = pipeline.run_once()
    print(pipeline_result.message)
