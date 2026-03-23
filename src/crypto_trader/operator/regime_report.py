from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, RegimeReport
from crypto_trader.strategy.regime import MarketRegime, RegimeDetector


class RegimeReportGenerator:
    def __init__(self, regime_config: RegimeConfig) -> None:
        self._detector = RegimeDetector(regime_config)

    def generate(
        self,
        *,
        symbol: str,
        strategy: StrategyConfig,
        candles: list[Candle],
    ) -> RegimeReport:
        analysis = self._detector.analyze(candles)
        adjusted = self._detector.adjust(strategy, analysis.regime)
        reasons = self._reasons_for_regime(
            analysis.regime,
            analysis.short_return_pct,
            analysis.long_return_pct,
        )
        return RegimeReport(
            generated_at=datetime.now(UTC).isoformat(),
            symbol=symbol,
            market_regime=analysis.regime.value,
            short_return_pct=analysis.short_return_pct,
            long_return_pct=analysis.long_return_pct,
            base_parameters=_strategy_view(strategy),
            adjusted_parameters=_strategy_view(adjusted),
            reasons=reasons,
        )

    def save(self, report: RegimeReport, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    def _reasons_for_regime(
        self,
        regime: MarketRegime,
        short_return_pct: float,
        long_return_pct: float,
    ) -> list[str]:
        if regime is MarketRegime.BULL:
            return [
                f"short return is positive at {short_return_pct:.2%}",
                f"long return is positive at {long_return_pct:.2%}",
                "strategy can tolerate a longer hold and slightly looser recovery ceiling",
            ]
        if regime is MarketRegime.BEAR:
            return [
                f"short return is negative at {short_return_pct:.2%}",
                f"long return is negative at {long_return_pct:.2%}",
                "strategy should tighten entries and shorten holds",
            ]
        return [
            f"short return is mixed at {short_return_pct:.2%}",
            f"long return is mixed at {long_return_pct:.2%}",
            "strategy stays near baseline parameters in sideways conditions",
        ]


def _strategy_view(config: StrategyConfig) -> dict[str, float | int]:
    return {
        "momentum_lookback": config.momentum_lookback,
        "momentum_entry_threshold": config.momentum_entry_threshold,
        "momentum_exit_threshold": config.momentum_exit_threshold,
        "bollinger_window": config.bollinger_window,
        "bollinger_stddev": config.bollinger_stddev,
        "rsi_period": config.rsi_period,
        "rsi_oversold_floor": config.rsi_oversold_floor,
        "rsi_recovery_ceiling": config.rsi_recovery_ceiling,
        "rsi_overbought": config.rsi_overbought,
        "max_holding_bars": config.max_holding_bars,
    }
