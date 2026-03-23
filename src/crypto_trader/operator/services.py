from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import AppConfig
from crypto_trader.data.base import MarketDataClient
from crypto_trader.models import DriftReport, PromotionGateDecision
from crypto_trader.operator.drift import DriftReportGenerator
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.memo import OperatorDailyMemo
from crypto_trader.operator.promotion import PromotionGate
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy


@dataclass(slots=True)
class OperatorArtifacts:
    drift_report: DriftReport
    promotion_decision: PromotionGateDecision
    daily_memo: str


def generate_operator_artifacts(
    *,
    config: AppConfig,
    market_data: MarketDataClient,
    strategy: CompositeStrategy,
    risk_manager: RiskManager,
) -> OperatorArtifacts:
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
    recent_runs = journal.load_recent()
    drift_generator = DriftReportGenerator()
    drift_report = drift_generator.generate(
        symbol=config.trading.symbol,
        backtest_result=backtest_result,
        recent_runs=recent_runs,
    )
    drift_generator.save(drift_report, config.runtime.drift_report_path)
    promotion_gate = PromotionGate()
    decision = promotion_gate.evaluate(
        symbol=config.trading.symbol,
        backtest_result=backtest_result,
        drift_report=drift_report,
        latest_run=recent_runs[-1] if recent_runs else None,
    )
    promotion_gate.save(decision, config.runtime.promotion_gate_path)
    memo = OperatorDailyMemo().render(
        latest_run=recent_runs[-1] if recent_runs else None,
        drift_report=drift_report,
        promotion_decision=decision,
    )
    OperatorDailyMemo().save(memo, config.runtime.daily_memo_path)
    return OperatorArtifacts(
        drift_report=drift_report,
        promotion_decision=decision,
        daily_memo=memo,
    )
