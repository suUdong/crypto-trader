from __future__ import annotations

import logging

from crypto_trader.config import StrategyConfig
from crypto_trader.macro.client import MacroSnapshot
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.indicators import rsi

logger = logging.getLogger(__name__)

class EtfFlowAdmissionStrategy:
    """
    [Cycle 228/229 Research Implementation]
    Fear Capitulation strategy with Dynamic ETF Flow Admission Filter.
    
    Admission Logic:
    - Only buys during 'Extreme Fear' (F&G < 20).
    - Requires 'Kimchi Premium' to be negative (Local discount).
    - Requires US Spot BTC ETF flows to be positive and statistically significant.
      Threshold = max(20M, 0.5 * StdDev_20d).
    """

    def __init__(
        self,
        config: StrategyConfig,
        max_fear_index: int = 20,
        max_kimchi_premium: float = -0.002, # -0.2%
        rsi_oversold: float = 30.0,
        std_multiplier: float = 0.5,
        min_absolute_flow: float = 20.0,
    ) -> None:
        self._config = config
        self._max_fear_index = max_fear_index
        self._max_kimchi_premium = max_kimchi_premium
        self._rsi_oversold = rsi_oversold
        self._std_multiplier = std_multiplier
        self._min_absolute_flow = min_absolute_flow

    def evaluate(
        self,
        candles: list[Candle],
        macro: MacroSnapshot | None = None,
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        # Standard safety checks
        if len(candles) < self._config.rsi_period + 1:
            return Signal(SignalAction.HOLD, "insufficient_data", 0.0)

        if position is not None:
            return self._evaluate_exit(candles, position)

        if macro is None:
            return Signal(SignalAction.HOLD, "missing_macro_data", 0.0)

        # 1. Fear Regime Check
        fng = macro.fear_greed_index
        if fng is None or fng > self._max_fear_index:
            return Signal(SignalAction.HOLD, f"fear_not_extreme (F&G={fng})", 0.0)

        # 2. Local Market Context (Kimchi Premium)
        kp = macro.kimchi_premium
        if kp is None or kp > self._max_kimchi_premium:
            return Signal(SignalAction.HOLD, f"kimchi_premium_not_discounted ({kp})", 0.0)

        # 3. Dynamic ETF Flow Admission (The Core Research)
        etf_flow = macro.etf_flow_musd
        etf_std = macro.etf_flow_std_20d or 0.0
        
        if etf_flow is None:
            return Signal(SignalAction.HOLD, "missing_etf_flow_data", 0.0)
            
        dynamic_threshold = max(
            self._min_absolute_flow,
            etf_std * self._std_multiplier
        )
        
        if etf_flow < dynamic_threshold:
            return Signal(
                SignalAction.HOLD,
                (
                    f"etf_flow_admission_rejected "
                    f"(flow={etf_flow:.1f} < thresh={dynamic_threshold:.1f})"
                ),
                0.0,
            )

        # 4. Micro-structure confirmation (RSI/Bollinger)
        closes = [c.close for c in candles]
        rsi_val = rsi(closes, self._config.rsi_period)
        if rsi_val > self._rsi_oversold:
            return Signal(SignalAction.HOLD, f"rsi_not_oversold ({rsi_val:.1f})", 0.0)

        # Signal Generation
        return Signal(
            action=SignalAction.BUY,
            reason=f"etf_flow_admitted_fear_buy (F&G={fng}, ETF={etf_flow:.1f}M)",
            confidence=0.85,
            indicators={
                "fear_greed": float(fng),
                "kimchi_premium": kp,
                "etf_flow": etf_flow,
                "rsi": rsi_val
            },
            context={"strategy": "etf_flow_admission", "force_fear_buy": "true"}
        )

    def _evaluate_exit(self, candles: list[Candle], position: Position) -> Signal:
        # Exit on RSI recovery or max holding
        closes = [c.close for c in candles]
        rsi_val = rsi(closes, self._config.rsi_period)
        
        if rsi_val >= 50.0:
            return Signal(SignalAction.SELL, "rsi_mean_reversion_exit", 1.0)
            
        holding_bars = len(candles) - (position.entry_index or 0)
        if holding_bars >= self._config.max_holding_bars:
            return Signal(SignalAction.SELL, "max_holding_reached", 1.0)
            
        return Signal(SignalAction.HOLD, "waiting_for_recovery", 0.0)
