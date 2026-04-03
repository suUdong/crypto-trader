from __future__ import annotations

from crypto_trader.config import StrategyConfig
from crypto_trader.models import (
    Candle,
    OrderbookSnapshot,
    Position,
    Signal,
    SignalAction,
)
from crypto_trader.strategy.indicators import rsi, average_directional_index
from crypto_trader.strategy.vpin import VPINStrategy


class TruthSeekerV2Strategy:
    """
    Truth-Seeker v2 (Iceberg Breakout Edition)
    
    New in v2:
    - Iceberg Detection: VPIN > 0.8 indicates aggressive informed flow.
    - Toxic Convergence: Entry on high VPIN breakout even if OBI is neutral.
    """

    def __init__(
        self,
        config: StrategyConfig,
        vpin_threshold: float = 0.45,
        obi_threshold: float = 0.12,
        toxic_vpin_threshold: float = 0.80, # Research Cycle 43
    ) -> None:
        self._config = config
        self._vpin_threshold = vpin_threshold
        self._obi_threshold = obi_threshold
        self._toxic_vpin_threshold = toxic_vpin_threshold
        self._vpin_strategy = VPINStrategy(config=config, vpin_high_threshold=vpin_threshold, bucket_count=24)

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
        orderbook: OrderbookSnapshot | None = None,
    ) -> Signal:
        if len(candles) < 30:
            return Signal(action=SignalAction.HOLD, reason="insufficient_data", confidence=0.0)

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        
        rsi_val = rsi(closes, self._config.rsi_period)
        vpin_val = self._vpin_strategy._calculate_vpin(candles)
        obi_val = self._calculate_obi(candles, orderbook)
        adx_val = average_directional_index(highs, lows, closes, 14)

        indicators = {"rsi": rsi_val, "vpin": vpin_val, "obi": obi_val, "adx": adx_val}

        if position is not None:
            return self._evaluate_exit(position, indicators, candles)

        # --- v2 Iceberg Breakout Logic ---
        # If VPIN is extremely high, it's a breakout signal regardless of OBI (Toxic Flow)
        if vpin_val > self._toxic_vpin_threshold and rsi_val < 70:
            return Signal(
                action=SignalAction.BUY,
                reason="iceberg_breakout_toxic_flow",
                confidence=vpin_val,
                indicators=indicators
            )

        # Normal Truth-Seeker entry
        if vpin_val > self._vpin_threshold and obi_val > self._obi_threshold and adx_val > 20:
            return Signal(
                action=SignalAction.BUY,
                reason="genuine_informed_buying",
                confidence=(vpin_val + obi_val) / 2,
                indicators=indicators
            )

        return Signal(action=SignalAction.HOLD, reason="no_signal", confidence=0.0, indicators=indicators)

    def _calculate_obi(self, candles: list[Candle], orderbook: OrderbookSnapshot | None) -> float:
        if orderbook:
            bid_vol = sum(b.size for b in orderbook.bids)
            ask_vol = sum(a.size for a in orderbook.asks)
            return (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0.0
        recent = candles[-5:]
        buys = sum(c.volume for c in recent if c.close >= c.open)
        sells = sum(c.volume for c in recent if c.close < c.open)
        return (buys - sells) / (buys + sells) if (buys + sells) > 0 else 0.0

    def _evaluate_exit(self, position: Position, ind: dict[str, float], candles: list[Candle]) -> Signal:
        if ind["rsi"] > 75.0:
            return Signal(action=SignalAction.SELL, reason="rsi_overbought", confidence=1.0)
        holding_bars = len(candles) - (position.entry_index or 0)
        if holding_bars > self._config.max_holding_bars:
            return Signal(action=SignalAction.SELL, reason="max_holding_time", confidence=1.0)
        return Signal(action=SignalAction.HOLD, reason="waiting", confidence=0.0)
