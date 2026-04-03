from __future__ import annotations

import numpy as np
from crypto_trader.config import StrategyConfig
from crypto_trader.models import (
    Candle,
    OrderbookSnapshot,
    Position,
    Signal,
    SignalAction,
)
from crypto_trader.strategy.indicators import rsi, average_directional_index, _ema
from crypto_trader.strategy.vpin import VPINStrategy


class TruthSeekerV3Strategy:
    """
    Truth-Seeker v3 (Quant Master Edition)
    
    New in v3:
    - Hurst Exponent: Detects if market is Trending vs Mean Reverting.
    - CVD (Cumulative Volume Delta): Tracks net market aggression.
    - BTC Correlation Filter: Prevents entries if BTC trend is negative.
    """

    def __init__(
        self,
        config: StrategyConfig,
        vpin_threshold: float = 0.45,
        obi_threshold: float = 0.12,
        hurst_threshold: float = 0.55, # > 0.5 is trending
    ) -> None:
        self._config = config
        self._vpin_threshold = vpin_threshold
        self._obi_threshold = obi_threshold
        self._hurst_threshold = hurst_threshold
        self._vpin_strategy = VPINStrategy(config=config, vpin_high_threshold=vpin_threshold, bucket_count=24)

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
        btc_candles: list[Candle] | None = None, # BTC reference
    ) -> Signal:
        if len(candles) < 60: # Hurst needs more data
            return Signal(action=SignalAction.HOLD, reason="insufficient_data", confidence=0.0)

        closes = [c.close for c in candles]
        rsi_val = rsi(closes, self._config.rsi_period)
        vpin_val = self._vpin_strategy._calculate_vpin(candles)
        
        # --- v3 New Indicators ---
        hurst_val = self._calculate_hurst(closes)
        cvd_val = self._calculate_cvd(candles)
        btc_safe = self._check_btc_safety(btc_candles) if btc_candles else True

        indicators = {
            "rsi": rsi_val, "vpin": vpin_val, 
            "hurst": hurst_val, "cvd": cvd_val,
            "btc_safe": 1.0 if btc_safe else 0.0
        }

        if position is not None:
            return self._evaluate_exit(position, indicators, candles)

        # --- v3 Decision Logic ---
        # 1. BTC must be stable or bullish
        # 2. Market must show trending properties (Hurst > 0.55)
        # 3. VPIN and CVD must align
        
        is_trending = hurst_val > self._hurst_threshold
        is_buying_aggressive = vpin_val > self._vpin_threshold and cvd_val > 0
        
        if btc_safe and is_trending and is_buying_aggressive and rsi_val < 65:
            return Signal(
                action=SignalAction.BUY,
                reason="quant_master_confirmed_trend",
                confidence=(vpin_val + hurst_val) / 2,
                indicators=indicators
            )

        return Signal(action=SignalAction.HOLD, reason="waiting_for_quant_sync", confidence=0.0, indicators=indicators)

    def _calculate_hurst(self, series: list[float]) -> float:
        """Simplified Hurst Exponent to detect trend persistence."""
        lags = range(2, 20)
        tau = [np.sqrt(np.std(np.subtract(series[lag:], series[:-lag]))) for lag in lags]
        reg = np.polyfit(np.log(lags), np.log(tau), 1)
        return reg[0] * 2.0

    def _calculate_cvd(self, candles: list[Candle]) -> float:
        """Calculate Cumulative Volume Delta for recent 20 bars."""
        recent = candles[-20:]
        delta = sum(c.volume if c.close >= c.open else -c.volume for c in recent)
        return delta

    def _check_btc_safety(self, btc_candles: list[Candle]) -> bool:
        """Check if BTC is in a strong downtrend."""
        if not btc_candles: return True
        closes = [c.close for c in btc_candles[-20:]]
        ma20 = sum(closes) / 20
        return btc_candles[-1].close > ma20 # Simple MA filter for BTC

    def _evaluate_exit(self, position: Position, ind: dict[str, float], candles: list[Candle]) -> Signal:
        # Exit if trend breaks (Hurst drops) or RSI overbought
        if ind["rsi"] > 75.0 or ind["hurst"] < 0.45:
            return Signal(action=SignalAction.SELL, reason="trend_exhaustion", confidence=1.0)
        
        holding_bars = len(candles) - (position.entry_index or 0)
        if holding_bars > self._config.max_holding_bars:
            return Signal(action=SignalAction.SELL, reason="max_holding_time", confidence=1.0)
        return Signal(action=SignalAction.HOLD, reason="holding_trend", confidence=0.0)
