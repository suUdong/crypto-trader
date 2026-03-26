"""Grid search + walk-forward combo: find best params then validate OOS."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.backtest.walk_forward import WalkForwardReport, WalkForwardValidator
from crypto_trader.config import BacktestConfig, RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import create_strategy


@dataclass(slots=True)
class GridCandidate:
    """A parameter set with its grid search score."""
    strategy_type: str
    params: dict[str, Any]
    avg_sharpe: float
    avg_return_pct: float
    total_trades: int


@dataclass(slots=True)
class GridWFResult:
    """Combined grid search + walk-forward result."""
    candidate: GridCandidate
    wf_report: WalkForwardReport
    validated: bool


@dataclass(slots=True)
class GridWFSummary:
    """Summary of full grid-wf run."""
    strategy_type: str
    candidates_tested: int
    candidates_validated: int
    results: list[GridWFResult] = field(default_factory=list)

    @property
    def best_validated(self) -> GridWFResult | None:
        validated = [r for r in self.results if r.validated]
        if not validated:
            return None
        return max(validated, key=lambda r: r.candidate.avg_sharpe)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_type": self.strategy_type,
            "candidates_tested": self.candidates_tested,
            "candidates_validated": self.candidates_validated,
            "results": [
                {
                    "params": r.candidate.params,
                    "avg_sharpe": r.candidate.avg_sharpe,
                    "avg_return_pct": r.candidate.avg_return_pct,
                    "total_trades": r.candidate.total_trades,
                    "validated": r.validated,
                    "wf_avg_efficiency_ratio": r.wf_report.avg_efficiency_ratio,
                    "wf_oos_win_rate": r.wf_report.oos_win_rate,
                }
                for r in self.results
            ],
            "best_validated": None if not self.best_validated else {
                "params": self.best_validated.candidate.params,
                "avg_sharpe": self.best_validated.candidate.avg_sharpe,
            },
        }


def _approx_sharpe(equity_curve: list[float]) -> float:
    if len(equity_curve) < 3:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / max(1.0, equity_curve[i - 1])
        for i in range(1, len(equity_curve))
    ]
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = variance**0.5
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * (8760**0.5)


# Minimal param grids for quick in-CLI search
PARAM_GRIDS: dict[str, dict[str, list[Any]]] = {
    "momentum": {
        "momentum_lookback": [10, 15, 20],
        "momentum_entry_threshold": [0.003, 0.005, 0.008],
        "rsi_period": [14, 18],
        "max_holding_bars": [36, 48],
    },
    "mean_reversion": {
        "bollinger_window": [15, 20, 25],
        "bollinger_stddev": [1.5, 1.8, 2.0],
        "rsi_period": [14, 18],
        "max_holding_bars": [36, 48],
    },
    "vpin": {
        "rsi_period": [14, 18],
        "momentum_lookback": [10, 15, 20],
        "max_holding_bars": [36, 48],
    },
    "volatility_breakout": {
        "k_base": [0.3, 0.5, 0.7],
        "noise_lookback": [10, 20],
        "ma_filter_period": [10, 20],
        "max_holding_bars": [24, 36, 48],
    },
    "composite": {
        "momentum_lookback": [15, 20],
        "bollinger_window": [15, 20],
        "bollinger_stddev": [1.5, 1.8],
        "rsi_period": [14, 18],
        "max_holding_bars": [36, 48],
    },
    "kimchi_premium": {
        "rsi_period": [14, 18],
        "max_holding_bars": [24, 36],
    },
    "obi": {
        "rsi_period": [14, 18],
        "momentum_lookback": [10, 15, 20],
        "max_holding_bars": [36, 48],
    },
    "consensus": {
        "momentum_lookback": [10, 15, 20],
        "rsi_period": [14, 18],
        "max_holding_bars": [36, 48],
    },
}


def _run_backtest_with_params(
    strategy_type: str,
    params: dict[str, Any],
    candles: list[Candle],
    symbol: str,
) -> dict[str, float]:
    """Run a single backtest with given params, return metrics."""
    config_fields = set(StrategyConfig.__dataclass_fields__)
    config_kwargs = {k: v for k, v in params.items() if k in config_fields}
    strategy_config = StrategyConfig(**config_kwargs)
    regime_config = RegimeConfig()

    strategy = create_strategy(strategy_type, strategy_config, regime_config, params)
    if strategy_type == "kimchi_premium":
        # Setup mock premium for backtest
        from unittest.mock import MagicMock
        if hasattr(strategy, "_cached_premium"):
            if len(candles) >= 50:
                closes = [c.close for c in candles]
                ma50 = sum(closes[-50:]) / 50.0
                if ma50 > 0:
                    strategy._cached_premium = (closes[-1] - ma50) / ma50
            strategy._binance = MagicMock()
            strategy._fx = MagicMock()
            strategy._binance.get_btc_usdt_price.return_value = None
            strategy._fx.get_usd_krw_rate.return_value = None

    risk_config = RiskConfig()
    risk_manager = RiskManager(risk_config)
    backtest_config = BacktestConfig(
        initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005,
    )
    engine = BacktestEngine(
        strategy=strategy, risk_manager=risk_manager,
        config=backtest_config, symbol=symbol,
    )
    result = engine.run(candles)
    sharpe = _approx_sharpe(result.equity_curve)
    return {
        "return_pct": result.total_return_pct * 100,
        "sharpe": sharpe,
        "mdd_pct": result.max_drawdown * 100,
        "win_rate": result.win_rate * 100,
        "trade_count": len(result.trade_log),
    }


def grid_search(
    strategy_type: str,
    candles_by_symbol: dict[str, list[Candle]],
    top_n: int = 5,
    regime_filter: str | None = None,
) -> list[GridCandidate]:
    """Run grid search across param combinations, return top-N by Sharpe."""
    import itertools

    if regime_filter:
        from crypto_trader.strategy.regime import RegimeDetector
        from crypto_trader.config import RegimeConfig
        detector = RegimeDetector(RegimeConfig())
        filtered_map: dict[str, list[Candle]] = {}
        for sym, candles in candles_by_symbol.items():
            # Keep candles where detected regime matches filter
            filtered: list[Candle] = []
            for i in range(30, len(candles)):
                window = candles[max(0, i-30):i+1]
                if len(window) >= 10:
                    analysis = detector.analyze(window)
                    if analysis.regime.value == regime_filter:
                        filtered.append(candles[i])
            if len(filtered) >= 50:
                filtered_map[sym] = filtered
        candles_by_symbol = filtered_map if filtered_map else candles_by_symbol

    grid = PARAM_GRIDS.get(strategy_type, {})
    if not grid:
        return []

    param_names = list(grid.keys())
    combos = list(itertools.product(*grid.values()))

    scored: list[tuple[dict[str, Any], float, float, int]] = []

    for combo in combos:
        params = dict(zip(param_names, combo, strict=True))
        sharpes: list[float] = []
        returns: list[float] = []
        trades = 0

        for symbol, candles in candles_by_symbol.items():
            try:
                result = _run_backtest_with_params(strategy_type, params, candles, symbol)
                sharpes.append(result["sharpe"])
                returns.append(result["return_pct"])
                trades += int(result["trade_count"])
            except Exception as exc:
                _logger.debug("grid combo failed for %s/%s: %s", strategy_type, symbol, exc)
                continue

        if sharpes:
            avg_sharpe = sum(sharpes) / len(sharpes)
            avg_return = sum(returns) / len(returns)
            scored.append((params, avg_sharpe, avg_return, trades))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [
        GridCandidate(
            strategy_type=strategy_type,
            params=params,
            avg_sharpe=sharpe,
            avg_return_pct=ret,
            total_trades=trades,
        )
        for params, sharpe, ret, trades in scored[:top_n]
    ]


def validate_with_walk_forward(
    candidate: GridCandidate,
    candles_by_symbol: dict[str, list[Candle]],
    backtest_config: BacktestConfig,
    risk_config: RiskConfig,
    n_folds: int = 3,
) -> GridWFResult:
    """Validate a grid search candidate with walk-forward across ALL symbols."""
    from crypto_trader.backtest.walk_forward import WalkForwardFold

    validator = WalkForwardValidator(
        backtest_config=backtest_config,
        risk_config=risk_config,
        n_folds=n_folds,
        train_pct=0.7,
    )

    config_fields = set(StrategyConfig.__dataclass_fields__)

    all_folds: list[WalkForwardFold] = []
    symbols_passed = 0
    symbols_tested = 0

    for symbol, candles in candles_by_symbol.items():
        if len(candles) < 100:
            continue

        def _factory(sym: str = symbol, cndls: list[Candle] = candles) -> object:
            config_kwargs = {k: v for k, v in candidate.params.items() if k in config_fields}
            strategy_config = StrategyConfig(**config_kwargs)
            regime_config = RegimeConfig()
            strategy = create_strategy(
                candidate.strategy_type, strategy_config, regime_config, candidate.params,
            )
            if candidate.strategy_type == "kimchi_premium" and hasattr(strategy, "_cached_premium"):
                from unittest.mock import MagicMock
                if len(cndls) >= 50:
                    closes = [c.close for c in cndls]
                    ma50 = sum(closes[-50:]) / 50.0
                    if ma50 > 0:
                        strategy._cached_premium = (closes[-1] - ma50) / ma50
                strategy._binance = MagicMock()
                strategy._fx = MagicMock()
                strategy._binance.get_btc_usdt_price.return_value = None
                strategy._fx.get_usd_krw_rate.return_value = None
            return strategy

        try:
            report = validator.validate(
                strategy_factory=_factory,
                candles=candles,
                symbol=symbol,
                strategy_name=candidate.strategy_type,
            )
        except Exception as exc:
            _logger.debug("walk-forward failed for %s/%s: %s", candidate.strategy_type, symbol, exc)
            continue

        if report.folds:
            all_folds.extend(report.folds)
            symbols_tested += 1
            if report.passed:
                symbols_passed += 1

    combined_report = WalkForwardReport(
        strategy_name=candidate.strategy_type,
        symbol="multi",
        total_folds=len(all_folds),
        folds=all_folds,
    )

    majority_pass = symbols_tested > 0 and symbols_passed >= (symbols_tested / 2)

    return GridWFResult(
        candidate=candidate,
        wf_report=combined_report,
        validated=combined_report.passed and majority_pass,
    )


def run_grid_wf(
    strategy_type: str,
    candles_by_symbol: dict[str, list[Candle]],
    top_n: int = 5,
    backtest_config: BacktestConfig | None = None,
    risk_config: RiskConfig | None = None,
    regime_filter: str | None = None,
) -> GridWFSummary:
    """Full pipeline: grid search -> walk-forward validation on top candidates."""
    bc = backtest_config or BacktestConfig()
    rc = risk_config or RiskConfig()

    candidates = grid_search(strategy_type, candles_by_symbol, top_n=top_n, regime_filter=regime_filter)

    results: list[GridWFResult] = []
    for candidate in candidates:
        wf_result = validate_with_walk_forward(
            candidate, candles_by_symbol, bc, rc,
        )
        results.append(wf_result)

    validated_count = sum(1 for r in results if r.validated)

    return GridWFSummary(
        strategy_type=strategy_type,
        candidates_tested=len(candidates),
        candidates_validated=validated_count,
        results=results,
    )
