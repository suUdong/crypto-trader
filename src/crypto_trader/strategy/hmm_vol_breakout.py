from __future__ import annotations

import logging
from typing import Any

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.hmm_regime import HMMRegimeDetector, HMMState
from crypto_trader.strategy.indicators import average_true_range as atr
from crypto_trader.strategy.registry import register

logger = logging.getLogger(__name__)

@register("hmm_vol_breakout")
def _factory(strategy_config: StrategyConfig, regime_config: RegimeConfig, params: dict[str, Any]):
    return HMMVolBreakoutStrategy(
        strategy_config,
        regime_config,
        enabled=bool(params.get("enabled", False)),
    )

class HMMVolBreakoutStrategy:
    """Intraday Vol-Targeting Breakout with HMM Micro-Regime."""
    
    def __init__(
        self,
        config: StrategyConfig,
        regime_config: RegimeConfig,
        *,
        enabled: bool = True,
    ) -> None:
        self._config = config
        self._detector = HMMRegimeDetector()
        self._is_trained = False
        self._enabled = enabled

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        if not self._enabled:
            return Signal(SignalAction.HOLD, "hmm_vol_breakout_disabled", 0.0)

        if len(candles) < 100:
            return Signal(SignalAction.HOLD, "insufficient_data", 0.0)

        # 1. Lazy training
        if not self._is_trained:
            self._is_trained = self._detector.train(candles[:-1])
            
        if not self._is_trained:
            return Signal(SignalAction.HOLD, "hmm_training_failed", 0.0)

        # 2. Detect Regime
        analysis = self._detector.predict(candles)
        context = {
            "regime": "TREND" if analysis.state == HMMState.TREND else "NOISE",
            "confidence": f"{analysis.confidence:.2f}",
            "strategy": "hmm_vol_breakout"
        }

        if analysis.state != HMMState.TREND or analysis.confidence < 0.65:
            return Signal(SignalAction.HOLD, "noise_regime", analysis.confidence, context=context)

        # 3. Volatility Breakout Logic
        closes = [c.close for c in candles]
        current_price = closes[-1]
        prev_candle = candles[-2]
        prev_range = prev_candle.high - prev_candle.low
        
        # entry = prev_close + k * prev_range
        k = self._config.k_base
        entry_threshold = prev_candle.close + (k * prev_range)
        
        if position is not None:
            # Simple exit: Trail by 1.5 * ATR or exit after max_holding_bars
            holding_bars = len(candles) - (position.entry_index or 0)
            if holding_bars >= self._config.max_holding_bars:
                return Signal(SignalAction.SELL, "max_holding", 1.0, context=context)
            
            # ATR-based trailing stop
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            current_atr = atr(highs, lows, closes, 14)
            if current_price < position.entry_price - (1.5 * current_atr):
                return Signal(SignalAction.SELL, "atr_stop", 1.0, context=context)
                
            return Signal(SignalAction.HOLD, "waiting", 0.0, context=context)

        if current_price > entry_threshold:
            return Signal(
                action=SignalAction.BUY,
                reason="hmm_trend_confirmed_breakout",
                confidence=analysis.confidence,
                context=context
            )
            
        return Signal(SignalAction.HOLD, "waiting_breakout", 0.0, context=context)
