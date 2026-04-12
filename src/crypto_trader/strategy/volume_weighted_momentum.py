"""Volume-Weighted Momentum strategy.

Parity implementation of auto-research-engine VolumeWeightedMomentum.
Signal: sigmoid(alpha * vwm) where vwm = volume-weighted mean of bar returns.

ARE reference: engine/genome/components/signals/volume_weighted_momentum.py
Parity spec: docs/specs/2026-04-12-crypto-trader-vwm-parity-spec.md (ARE repo)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.registry import register


@dataclass(frozen=True, slots=True)
class SignalResult:
    """Lightweight per-bar signal for parity testing."""

    action: SignalAction
    score: float


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


class VolumeWeightedMomentumStrategy:
    """Volume-weighted momentum -- ARE-parity signal + gates + exit."""

    def __init__(
        self,
        config: StrategyConfig,
        *,
        period: int = 24,
        alpha: float = 200.0,
        # Gate params
        btc_sma_period: int = 221,
        liquidity_min_krw_24h: float = 975_695_489.5449693,
        # Exit params
        tp_pct: float = 0.09956445995940857,
        sl_pct: float = 0.04054993005364031,
        max_holding_bars: int = 28,
    ) -> None:
        self._config = config
        self._period = period
        self._alpha = alpha
        self._btc_sma_period = btc_sma_period
        self._liquidity_min_krw_24h = liquidity_min_krw_24h
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct
        self._max_holding_bars = max_holding_bars
        self._btc_candles: list[Candle] = []

    def set_btc_candles(self, candles: list[Candle]) -> None:
        """Inject BTC candles for btc_above_sma gate."""
        self._btc_candles = candles

    # ------------------------------------------------------------------
    # Core signal (ARE parity)
    # ------------------------------------------------------------------
    def generate_signals(self, candles: list[Candle]) -> list[SignalResult]:
        """Compute per-bar signals for the entire series.

        Matches ARE VolumeWeightedMomentum.compute() to within 1e-6.
        """
        n = len(candles)
        if n == 0:
            return []

        returns = [0.0] * n
        for i in range(1, n):
            prev_close = candles[i - 1].close
            if prev_close != 0.0:
                returns[i] = (candles[i].close - prev_close) / prev_close

        signals: list[SignalResult] = []
        for i in range(n):
            if i < self._period:
                signals.append(SignalResult(action=SignalAction.HOLD, score=0.0))
                continue

            vol_sum = 0.0
            weighted_ret = 0.0
            for j in range(i - self._period + 1, i + 1):
                vol_sum += candles[j].volume
                weighted_ret += returns[j] * candles[j].volume

            if vol_sum == 0.0:
                signals.append(SignalResult(action=SignalAction.HOLD, score=0.5))
                continue

            vwm = weighted_ret / vol_sum
            score = _sigmoid(self._alpha * vwm)
            action = SignalAction.BUY if score > 0.5 else SignalAction.HOLD
            signals.append(SignalResult(action=action, score=score))

        return signals

    # ------------------------------------------------------------------
    # Daemon interface
    # ------------------------------------------------------------------
    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        ctx: dict[str, str] = {"strategy": "volume_weighted_momentum"}

        if len(candles) < self._period + 1:
            return Signal(
                action=SignalAction.HOLD, reason="insufficient_data",
                confidence=0.0, context=ctx,
            )

        if position is not None:
            return self._evaluate_exit(candles, position, ctx)

        gate_result = self._check_gates(candles, ctx)
        if gate_result is not None:
            return gate_result

        signals = self.generate_signals(candles)
        last = signals[-1]

        if last.action == SignalAction.BUY:
            return Signal(
                action=SignalAction.BUY, reason="vwm_positive",
                confidence=last.score, context=ctx,
                indicators={"vwm_score": last.score},
            )
        return Signal(
            action=SignalAction.HOLD, reason="vwm_not_positive",
            confidence=1.0 - last.score, context=ctx,
            indicators={"vwm_score": last.score},
        )

    def _check_gates(
        self, candles: list[Candle], ctx: dict[str, str],
    ) -> Signal | None:
        """Return a HOLD Signal if any gate blocks, else None."""
        btc_ref = self._btc_candles if self._btc_candles else candles
        if len(btc_ref) > self._btc_sma_period:
            btc_closes = [c.close for c in btc_ref]
            sma = sum(btc_closes[-self._btc_sma_period:]) / self._btc_sma_period
            if btc_closes[-1] <= sma:
                return Signal(
                    action=SignalAction.HOLD, reason="btc_below_sma",
                    confidence=0.1, context=ctx,
                )

        if len(candles) >= 24:
            krw_vol_24h = sum(c.close * c.volume for c in candles[-24:])
            if krw_vol_24h < self._liquidity_min_krw_24h:
                return Signal(
                    action=SignalAction.HOLD, reason="liquidity_too_low",
                    confidence=0.1, context=ctx,
                )

        return None

    def _evaluate_exit(
        self, candles: list[Candle], position: Position, ctx: dict[str, str],
    ) -> Signal:
        """Fixed TP/SL exit with SL priority."""
        entry = position.entry_price
        if entry <= 0:
            return Signal(
                action=SignalAction.HOLD, reason="invalid_entry_price",
                confidence=0.0, context=ctx,
            )

        holding_bars = 0
        if position.entry_index is not None:
            holding_bars = len(candles) - 1 - position.entry_index

        indicators: dict[str, float] = {
            "holding_bars": float(holding_bars),
            "pnl_pct": (candles[-1].close - entry) / entry,
        }

        if holding_bars > self._max_holding_bars:
            return Signal(
                action=SignalAction.SELL, reason="max_holding_bars",
                confidence=1.0, indicators=indicators, context=ctx,
            )

        sl_price = entry * (1.0 - self._sl_pct)
        if candles[-1].low <= sl_price:
            return Signal(
                action=SignalAction.SELL, reason="stop_loss",
                confidence=1.0, indicators=indicators, context=ctx,
            )

        tp_price = entry * (1.0 + self._tp_pct)
        if candles[-1].high >= tp_price:
            return Signal(
                action=SignalAction.SELL, reason="take_profit",
                confidence=0.9, indicators=indicators, context=ctx,
            )

        return Signal(
            action=SignalAction.HOLD, reason="holding_position",
            confidence=0.3, indicators=indicators, context=ctx,
        )


@register(
    "volume_weighted_momentum",
    override_fields=frozenset({
        "period", "alpha",
        "btc_sma_period", "liquidity_min_krw_24h",
        "tp_pct", "sl_pct", "max_holding_bars",
    }),
)
def _vwm_factory(
    strategy_config: StrategyConfig,
    regime_config: object,
    params: dict[str, object],
) -> VolumeWeightedMomentumStrategy:
    return VolumeWeightedMomentumStrategy(
        strategy_config,
        period=int(params.get("period", 24)),
        alpha=float(params.get("alpha", 200.0)),
        btc_sma_period=int(params.get("btc_sma_period", 221)),
        liquidity_min_krw_24h=float(
            params.get("liquidity_min_krw_24h", 975_695_489.5449693),
        ),
        tp_pct=float(params.get("tp_pct", 0.09956445995940857)),
        sl_pct=float(params.get("sl_pct", 0.04054993005364031)),
        max_holding_bars=int(params.get("max_holding_bars", 28)),
    )
