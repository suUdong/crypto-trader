from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import (
    Candle,
    OrderbookSnapshot,
    Position,
    Signal,
    SignalAction,
)
from crypto_trader.strategy.indicators import average_directional_index, rsi
from crypto_trader.strategy.vpin import VPINStrategy


class TruthSeekerStrategy:
    """
    'Truth-Seeker' Strategy (VPIN + OBI Ensemble with Anti-Spoofing Filter)
    
    Logic:
    1. Detect potential informed trading using VPIN.
    2. Verify intent using Order Book Imbalance (OBI).
    3. Filter out 'Spoofing' (Fake Walls): 
       - If OBI is high (buy wall) but VPIN shows selling pressure, it's a TRAP.
       - Only enter when both OBI and VPIN point in the same direction with high confidence.
    """

    def __init__(
        self,
        config: StrategyConfig,
        vpin_threshold: float = 0.65,
        obi_threshold: float = 0.45,
        anti_spoof_buffer: float = 0.2, # Minimum VPIN/OBI alignment required
    ) -> None:
        self._config = config
        self._vpin_threshold = vpin_threshold
        self._obi_threshold = obi_threshold
        self._anti_spoof_buffer = anti_spoof_buffer
        self._vpin_strategy = VPINStrategy(
            config=config,
            vpin_high_threshold=vpin_threshold,
            bucket_count=24
        )

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
        orderbook: OrderbookSnapshot | None = None,
    ) -> Signal:
        # 1. Basic Data Sufficiency Check
        min_candles = max(30, self._config.rsi_period + 1)
        if len(candles) < min_candles:
            return Signal(
                action=SignalAction.HOLD,
                reason="insufficient_data",
                confidence=0.0
            )

        # 2. Calculate Indicators
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        
        rsi_val = rsi(closes, self._config.rsi_period)
        vpin_val = self._vpin_strategy._calculate_vpin(candles)
        obi_val = self._calculate_obi(candles, orderbook)
        adx_val = average_directional_index(highs, lows, closes, 14)

        indicators = {
            "rsi": rsi_val,
            "vpin": vpin_val,
            "obi": obi_val,
            "adx": adx_val
        }

        # 3. Exit Logic (If position is open)
        if position is not None:
            return self._evaluate_exit(position, indicators, candles)

        # 4. Entry Logic (Truth-Seeker Filter)
        return self._evaluate_entry(indicators)

    def _calculate_obi(self, candles: list[Candle], orderbook: OrderbookSnapshot | None) -> float:
        if orderbook:
            bid_vol = sum(b.size for b in orderbook.bids)
            ask_vol = sum(a.size for a in orderbook.asks)
            return (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0.0
        
        # Fallback to Candle-based OBI proxy
        recent = candles[-5:]
        buys = sum(c.volume for c in recent if c.close >= c.open)
        sells = sum(c.volume for c in recent if c.close < c.open)
        return (buys - sells) / (buys + sells) if (buys + sells) > 0 else 0.0

    def _evaluate_entry(self, ind: dict[str, float]) -> Signal:
        vpin = ind["vpin"]
        obi = ind["obi"]
        rsi_val = ind["rsi"]
        adx = ind["adx"]

        # --- THE TRUTH-SEEKER CORE FILTER ---
        # Rule: OBI (Intent) must be backed by VPIN (Reality)
        # If OBI > 0.5 (Huge Buy Wall) but VPIN < 0.4 (Actual trades are selling), it's a SPOOF.
        
        is_buying_genuine = obi > self._obi_threshold and vpin > (0.5 - self._anti_spoof_buffer)
        is_trend_strong = adx > 20.0
        is_not_overbought = rsi_val < 65.0

        if vpin > self._vpin_threshold and is_buying_genuine and is_trend_strong and is_not_overbought:
            confidence = (vpin + obi) / 2.0
            return Signal(
                action=SignalAction.BUY,
                reason="genuine_informed_buying_detected",
                confidence=confidence,
                indicators=ind
            )

        return Signal(
            action=SignalAction.HOLD, 
            reason="no_genuine_signal", 
            confidence=0.0,
            indicators=ind
        )

    def _evaluate_exit(self, position: Position, ind: dict[str, float], candles: list[Candle]) -> Signal:
        # Exit if OBI turns sharply negative (Sell wall appears)
        if ind["obi"] < -0.4:
            return Signal(
                action=SignalAction.SELL, 
                reason="heavy_sell_pressure_detected", 
                confidence=0.8,
                indicators=ind
            )
        
        # Standard RSI exit
        if ind["rsi"] > 75.0:
            return Signal(
                action=SignalAction.SELL, 
                reason="rsi_overbought", 
                confidence=0.9,
                indicators=ind
            )
            
        # Max hold time
        holding_bars = len(candles) - (position.entry_index or 0)
        if holding_bars > self._config.max_holding_bars:
            return Signal(
                action=SignalAction.SELL, 
                reason="max_holding_time", 
                confidence=1.0,
                indicators=ind
            )

        return Signal(
            action=SignalAction.HOLD, 
            reason="waiting_for_exit_target",
            confidence=0.0,
            indicators=ind
        )
