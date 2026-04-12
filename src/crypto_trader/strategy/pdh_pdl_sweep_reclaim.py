"""PDH/PDL Sweep & Reclaim strategy.

Parity implementation of auto-research-engine PdhPdlSweepReclaim.
Signal: mean-reversion / microstructure -- detects a bar that sweeps a
previous-day low then recovers strongly with high CLV and elevated
relative volume.

ARE reference: engine/genome/components/signals/pdh_pdl_sweep_reclaim.py
Parity spec: docs/specs/2026-04-12-crypto-trader-pdh-pdl-parity-spec.md (ARE repo)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.strategy.registry import register

_EPS = 1e-12


@dataclass(frozen=True, slots=True)
class SignalResult:
    """Lightweight per-bar signal for parity testing."""

    action: SignalAction
    score: float


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


class PdhPdlSweepReclaimStrategy:
    """PDH/PDL sweep & reclaim -- ARE-parity signal + gates + exit."""

    def __init__(
        self,
        config: StrategyConfig,
        *,
        use_prev_day: bool = True,
        n: int = 22,
        eps: float = 0.0018262133038232326,
        L: int = 93,
        clv_min: float = 0.6868883402451547,
        rvol_min: float = 2.076067713758879,
        hold_bars: int = 3,
        # Gate params
        btc_sma_period: int = 251,
        liquidity_min_krw_24h: float = 7_844_751_368.066064,
        # Exit params (trailing stop)
        trail_pct: float = 0.08183584818420675,
        activation_pct: float = 0.032930819383335294,
        max_holding_bars: int = 68,
    ) -> None:
        self._config = config
        self._use_prev_day = use_prev_day
        self._n = n
        self._eps = eps
        self._L = L
        self._clv_min = clv_min
        self._rvol_min = rvol_min
        self._hold_bars = hold_bars
        self._btc_sma_period = btc_sma_period
        self._liquidity_min_krw_24h = liquidity_min_krw_24h
        self._trail_pct = trail_pct
        self._activation_pct = activation_pct
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

        Matches ARE PdhPdlSweepReclaim.compute() to within 1e-6.
        """
        n_bars = len(candles)
        if n_bars == 0:
            return []

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        krw_vols = [c.close * c.volume for c in candles]

        day_bars = 24
        warmup = max(self._n, self._L, 2 * day_bars)

        signals: list[SignalResult] = []
        for i in range(n_bars):
            if i < warmup:
                signals.append(SignalResult(action=SignalAction.HOLD, score=0.0))
                continue

            if self._use_prev_day:
                ref_low = min(lows[i - 2 * day_bars: i - day_bars])
            else:
                ref_low = min(lows[i - self._n: i])

            rng = highs[i] - lows[i]
            clv = (closes[i] - lows[i]) / (rng + _EPS)

            window_krw = krw_vols[i - self._L: i]
            window_mean = (
                sum(window_krw) / len(window_krw) if window_krw else _EPS
            )
            rvol = krw_vols[i] / (window_mean + _EPS)

            sweep = lows[i] < ref_low * (1.0 - self._eps)
            reclaim = closes[i] > ref_low
            strong = clv >= self._clv_min
            liquid = rvol >= self._rvol_min

            flags = float(sweep) + float(reclaim) + float(strong) + float(liquid)
            score = _sigmoid(5.0 * (flags - 2.5))
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
        ctx: dict[str, str] = {"strategy": "pdh_pdl_sweep_reclaim"}
        warmup = max(self._n, self._L, 48)

        if len(candles) < warmup + 1:
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
                action=SignalAction.BUY, reason="sweep_reclaim",
                confidence=last.score, context=ctx,
                indicators={
                    "pdh_pdl_score": last.score,
                    "hold_bars_hint": float(self._hold_bars),
                },
            )
        return Signal(
            action=SignalAction.HOLD, reason="no_sweep_reclaim",
            confidence=1.0 - last.score, context=ctx,
            indicators={"pdh_pdl_score": last.score},
        )

    def _check_gates(
        self, candles: list[Candle], ctx: dict[str, str],
    ) -> Signal | None:
        btc_ref = self._btc_candles if self._btc_candles else candles
        if len(btc_ref) > self._btc_sma_period:
            btc_closes = [c.close for c in btc_ref]
            sma = (
                sum(btc_closes[-self._btc_sma_period:]) / self._btc_sma_period
            )
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
        """Trailing stop with activation + hold_bars minimum-hold."""
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

        if holding_bars < self._hold_bars:
            return Signal(
                action=SignalAction.HOLD, reason="minimum_hold",
                confidence=0.3, indicators=indicators, context=ctx,
            )

        entry_idx = position.entry_index or 0
        peak = entry
        for c in candles[entry_idx + 1:]:
            if c.high > peak:
                peak = c.high

        activated = (peak - entry) / entry >= self._activation_pct
        indicators["trail_peak"] = peak
        indicators["trail_activated"] = float(activated)

        if activated:
            stop_price = peak * (1.0 - self._trail_pct)
            if candles[-1].low <= stop_price:
                return Signal(
                    action=SignalAction.SELL, reason="trailing_stop",
                    confidence=1.0, indicators=indicators, context=ctx,
                )

        return Signal(
            action=SignalAction.HOLD, reason="holding_position",
            confidence=0.3, indicators=indicators, context=ctx,
        )


@register(
    "pdh_pdl_sweep_reclaim",
    override_fields=frozenset({
        "use_prev_day", "n", "eps", "L", "clv_min", "rvol_min", "hold_bars",
        "btc_sma_period", "liquidity_min_krw_24h",
        "trail_pct", "activation_pct", "max_holding_bars",
    }),
)
def _pdh_pdl_factory(
    strategy_config: StrategyConfig,
    regime_config: object,
    params: dict[str, object],
) -> PdhPdlSweepReclaimStrategy:
    def _bool(v: object) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes")

    return PdhPdlSweepReclaimStrategy(
        strategy_config,
        use_prev_day=_bool(params.get("use_prev_day", True)),
        n=int(params.get("n", 22)),
        eps=float(params.get("eps", 0.0018262133038232326)),
        L=int(params.get("L", 93)),
        clv_min=float(params.get("clv_min", 0.6868883402451547)),
        rvol_min=float(params.get("rvol_min", 2.076067713758879)),
        hold_bars=int(params.get("hold_bars", 3)),
        btc_sma_period=int(params.get("btc_sma_period", 251)),
        liquidity_min_krw_24h=float(
            params.get("liquidity_min_krw_24h", 7_844_751_368.066064),
        ),
        trail_pct=float(params.get("trail_pct", 0.08183584818420675)),
        activation_pct=float(
            params.get("activation_pct", 0.032930819383335294),
        ),
        max_holding_bars=int(params.get("max_holding_bars", 68)),
    )
