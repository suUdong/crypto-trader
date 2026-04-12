# Strategy Plugin Registry + Parity Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a plugin registry for zero-touch strategy addition, then implement `pdh_pdl_sweep_reclaim` and `volume_weighted_momentum` at 1e-6 parity with auto-research-engine specs.

**Architecture:** New `registry.py` module provides `@register` decorator. Strategy files self-register at import time. `wallet.py::create_strategy` checks registry first, falls back to existing elif chain. `config.py` unions registry names/fields with legacy sets.

**Tech Stack:** Python 3.12+, pytest, mypy (strict), ruff, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-12-strategy-plugin-registry-design.md`

**Parity specs (auto-research-engine):**
- `../auto-research-engine/docs/specs/2026-04-12-crypto-trader-pdh-pdl-parity-spec.md`
- `../auto-research-engine/docs/specs/2026-04-12-crypto-trader-vwm-parity-spec.md`

---

## File Structure

| File | New/Edit | Responsibility |
|---|---|---|
| `src/crypto_trader/strategy/registry.py` | New | Plugin registry: `@register`, `get_spec`, `known_names`, `known_override_fields` |
| `tests/test_strategy_registry.py` | New | Registry unit tests |
| `src/crypto_trader/strategy/volume_weighted_momentum.py` | New | VWM strategy class + `@register` factory |
| `tests/test_volume_weighted_momentum.py` | New | 4 parity fixtures + edge cases |
| `src/crypto_trader/strategy/pdh_pdl_sweep_reclaim.py` | New | PDH/PDL strategy class + `@register` factory |
| `tests/test_pdh_pdl_sweep_reclaim.py` | New | 3 parity fixtures + edge cases |
| `src/crypto_trader/strategy/__init__.py` | Edit | Side-effect imports |
| `src/crypto_trader/wallet.py` | Edit | Registry hook in `create_strategy` |
| `src/crypto_trader/config.py` | Edit | Union registry names/fields |

---

## Task 1: Strategy Plugin Registry

**Files:**
- Create: `src/crypto_trader/strategy/registry.py`
- Create: `tests/test_strategy_registry.py`

### Step 1.1: Write failing registry tests

```python
# tests/test_strategy_registry.py
"""Tests for strategy plugin registry."""
from __future__ import annotations

import pytest

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Signal, SignalAction


def test_register_and_retrieve():
    """A decorated factory is retrievable by name."""
    from crypto_trader.strategy.registry import StrategySpec, _REGISTRY, register

    # Use a unique name to avoid cross-test pollution
    name = "__test_register_and_retrieve__"

    @register(name, override_fields=frozenset({"alpha"}))
    def _factory(strategy_config, regime_config, params):
        return object()

    spec = _REGISTRY.get(name)
    assert spec is not None
    assert spec.name == name
    assert "alpha" in spec.override_fields
    # Cleanup
    del _REGISTRY[name]


def test_duplicate_registration_raises():
    """Registering the same name twice raises ValueError."""
    from crypto_trader.strategy.registry import _REGISTRY, register

    name = "__test_duplicate__"

    @register(name)
    def _factory1(sc, rc, p):
        return object()

    with pytest.raises(ValueError, match="already registered"):
        @register(name)
        def _factory2(sc, rc, p):
            return object()

    del _REGISTRY[name]


def test_known_names_includes_registered():
    """known_names() returns all registered strategy names."""
    from crypto_trader.strategy.registry import _REGISTRY, known_names, register

    name = "__test_known_names__"

    @register(name)
    def _factory(sc, rc, p):
        return object()

    assert name in known_names()
    del _REGISTRY[name]


def test_known_override_fields():
    """known_override_fields() returns fields for a registered strategy."""
    from crypto_trader.strategy.registry import (
        _REGISTRY,
        known_override_fields,
        register,
    )

    name = "__test_override_fields__"

    @register(name, override_fields=frozenset({"x", "y"}))
    def _factory(sc, rc, p):
        return object()

    assert known_override_fields(name) == frozenset({"x", "y"})
    assert known_override_fields("nonexistent") == frozenset()
    del _REGISTRY[name]


def test_get_spec_returns_none_for_unknown():
    """get_spec() returns None for unregistered names."""
    from crypto_trader.strategy.registry import get_spec

    assert get_spec("__never_registered__") is None
```

- [ ] Run: `pytest tests/test_strategy_registry.py -v` — Expected: FAIL (module not found)

### Step 1.2: Implement registry module

```python
# src/crypto_trader/strategy/registry.py
"""Strategy plugin registry.

New strategies self-register via @register decorator at import time.
This replaces the need to edit wallet.py / config.py for each new strategy.

Usage in a strategy file:
    from crypto_trader.strategy.registry import register

    @register("my_strategy", override_fields=frozenset({"param_a", "param_b"}))
    def _factory(strategy_config, regime_config, params):
        return MyStrategy(strategy_config, param_a=float(params.get("param_a", 1.0)))
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Signal


class StrategyProtocol(Protocol):
    def evaluate(
        self, candles: list[Candle], *args: Any, **kwargs: Any
    ) -> Signal: ...


StrategyFactory = Callable[
    [StrategyConfig, RegimeConfig, Mapping[str, Any]],
    StrategyProtocol,
]


@dataclass(frozen=True)
class StrategySpec:
    name: str
    factory: StrategyFactory
    override_fields: frozenset[str]


_REGISTRY: dict[str, StrategySpec] = {}


def register(
    name: str,
    *,
    override_fields: frozenset[str] = frozenset(),
) -> Callable[[StrategyFactory], StrategyFactory]:
    """Decorator that registers a strategy factory function."""

    def _decorator(factory: StrategyFactory) -> StrategyFactory:
        if name in _REGISTRY:
            raise ValueError(f"strategy '{name}' already registered")
        _REGISTRY[name] = StrategySpec(
            name=name, factory=factory, override_fields=override_fields
        )
        return factory

    return _decorator


def get_spec(name: str) -> StrategySpec | None:
    """Return the StrategySpec for *name*, or None if not registered."""
    return _REGISTRY.get(name)


def known_names() -> frozenset[str]:
    """Return all registered strategy names."""
    return frozenset(_REGISTRY)


def known_override_fields(name: str) -> frozenset[str]:
    """Return override fields for *name*, or empty frozenset if unknown."""
    spec = _REGISTRY.get(name)
    return spec.override_fields if spec is not None else frozenset()
```

- [ ] Run: `pytest tests/test_strategy_registry.py -v` — Expected: 5 PASS
- [ ] Run: `mypy src/crypto_trader/strategy/registry.py --strict` — Expected: clean
- [ ] Run: `ruff check src/crypto_trader/strategy/registry.py` — Expected: clean

### Step 1.3: Commit

```
feat(strategy): add plugin registry with @register decorator
```

---

## Task 2: `volume_weighted_momentum` — Signal Parity

**Files:**
- Create: `src/crypto_trader/strategy/volume_weighted_momentum.py`
- Create: `tests/test_volume_weighted_momentum.py`

### Step 2.1: Write failing parity tests (4 fixtures)

```python
# tests/test_volume_weighted_momentum.py
"""Parity tests for VolumeWeightedMomentumStrategy.

Fixtures from auto-research-engine parity spec §5.
Tolerance: |score - expected| < 1e-6.
"""
from __future__ import annotations

import math
from datetime import datetime

import pytest

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction


def _ts(i: int) -> datetime:
    return datetime(2026, 1, 1, i % 24)


def _make_fixture_1() -> list[Candle]:
    """30 bars, +0.1%/bar, volume=1000."""
    bars: list[Candle] = []
    prev = 100.0
    for i in range(30):
        cl = prev * 1.001
        bars.append(Candle(
            timestamp=_ts(i), open=prev, high=cl + 0.05,
            low=prev - 0.05, close=cl, volume=1000.0,
        ))
        prev = cl
    return bars


def _make_fixture_2() -> list[Candle]:
    """30 bars, flat close=100, volume=1000."""
    return [
        Candle(timestamp=_ts(i), open=100.0, high=100.0,
               low=100.0, close=100.0, volume=1000.0)
        for i in range(30)
    ]


def _make_fixture_3() -> list[Candle]:
    """30 bars, -0.1%/bar, volume=1000."""
    bars: list[Candle] = []
    prev = 100.0
    for i in range(30):
        cl = prev * 0.999
        bars.append(Candle(
            timestamp=_ts(i), open=prev, high=prev + 0.05,
            low=cl - 0.05, close=cl, volume=1000.0,
        ))
        prev = cl
    return bars


def _make_fixture_4() -> list[Candle]:
    """24 bars alternating (-0.1% vol=10000, +0.3% vol=100), then 6 bars +0.1% vol=1000."""
    bars: list[Candle] = []
    prev = 100.0
    for i in range(24):
        if i % 2 == 0:
            cl = prev * 0.999
            vol = 10000.0
        else:
            cl = prev * 1.003
            vol = 100.0
        bars.append(Candle(
            timestamp=_ts(i), open=prev, high=max(cl, prev) + 0.05,
            low=min(cl, prev) - 0.05, close=cl, volume=vol,
        ))
        prev = cl
    for i in range(24, 30):
        cl = prev * 1.001
        bars.append(Candle(
            timestamp=_ts(i), open=prev, high=cl + 0.05,
            low=prev - 0.05, close=cl, volume=1000.0,
        ))
        prev = cl
    return bars


class TestVWMSignalParity:
    """Core signal parity tests — no gates, no exit."""

    def test_fixture_1_buy_positive_vwm(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )
        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_1())
        assert sig[24].action == SignalAction.BUY
        assert abs(sig[24].score - 0.565838) < 1e-6

    def test_fixture_2_hold_zero_vwm(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )
        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_2())
        assert sig[24].action == SignalAction.HOLD
        assert sig[24].score == 0.5

    def test_fixture_3_hold_negative_vwm(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )
        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_3())
        assert sig[24].action == SignalAction.HOLD
        assert abs(sig[24].score - 0.434162) < 1e-6

    def test_fixture_4_hold_volume_weighted_asymmetry(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )
        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_4())
        assert sig[24].action == SignalAction.HOLD
        assert abs(sig[24].score - 0.438110) < 1e-6


class TestVWMWarmup:
    """Warmup boundary: i < period → HOLD with score 0.0."""

    def test_bar_23_is_warmup(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )
        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_1())
        assert sig[23].action == SignalAction.HOLD
        assert sig[23].score == 0.0

    def test_bar_24_is_first_signal(self) -> None:
        from crypto_trader.strategy.volume_weighted_momentum import (
            VolumeWeightedMomentumStrategy,
        )
        s = VolumeWeightedMomentumStrategy(
            StrategyConfig(), period=24, alpha=264.8908943094896,
        )
        sig = s.generate_signals(_make_fixture_1())
        assert sig[24].score != 0.0
```

Note: `generate_signals` returns a list of lightweight signal results indexed by bar, separate from the `evaluate()` method (which processes one bar at a time for daemon use). This is the parity-testable core computation. The `evaluate()` method wraps it for daemon integration (gates, exit).

- [ ] Run: `pytest tests/test_volume_weighted_momentum.py -v` — Expected: FAIL (module not found)

### Step 2.2: Implement VWM strategy

The strategy exposes two interfaces:
- `generate_signals(candles) -> list[SignalResult]` — full-series parity-testable core (matches ARE `compute`)
- `evaluate(candles, position, *, symbol) -> Signal` — daemon interface (applies gates, handles exit)

```python
# src/crypto_trader/strategy/volume_weighted_momentum.py
"""Volume-Weighted Momentum strategy.

Parity implementation of auto-research-engine VolumeWeightedMomentum.
Signal: sigmoid(alpha * vwm) where vwm = volume-weighted mean of bar returns.

ARE reference: engine/genome/components/signals/volume_weighted_momentum.py
Parity spec: ../auto-research-engine/docs/specs/2026-04-12-crypto-trader-vwm-parity-spec.md
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
    """Volume-weighted momentum — ARE-parity signal + gates + exit."""

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

        This is the parity-testable core. Matches ARE VolumeWeightedMomentum.compute()
        to within 1e-6 on all spec fixtures.
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

        # --- Exit logic (when holding) ---
        if position is not None:
            return self._evaluate_exit(candles, position, ctx)

        # --- Gates ---
        gate_result = self._check_gates(candles, ctx)
        if gate_result is not None:
            return gate_result

        # --- Core signal (last bar) ---
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
        # Gate 1: BTC above SMA
        btc_ref = self._btc_candles if self._btc_candles else candles
        if len(btc_ref) > self._btc_sma_period:
            btc_closes = [c.close for c in btc_ref]
            sma = sum(btc_closes[-self._btc_sma_period:]) / self._btc_sma_period
            if btc_closes[-1] <= sma:
                return Signal(
                    action=SignalAction.HOLD, reason="btc_below_sma",
                    confidence=0.1, context=ctx,
                )

        # Gate 2: Liquidity minimum (24-bar trailing KRW volume)
        if len(candles) >= 24:
            krw_vol_24h = sum(
                c.close * c.volume for c in candles[-24:]
            )
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
        close = candles[-1].close
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
            "pnl_pct": (close - entry) / entry,
        }

        # Max holding
        if holding_bars > self._max_holding_bars:
            return Signal(
                action=SignalAction.SELL, reason="max_holding_bars",
                confidence=1.0, indicators=indicators, context=ctx,
            )

        # SL first (conservative)
        sl_price = entry * (1.0 - self._sl_pct)
        if candles[-1].low <= sl_price:
            return Signal(
                action=SignalAction.SELL, reason="stop_loss",
                confidence=1.0, indicators=indicators, context=ctx,
            )

        # TP second
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
            params.get("liquidity_min_krw_24h", 975_695_489.5449693)
        ),
        tp_pct=float(params.get("tp_pct", 0.09956445995940857)),
        sl_pct=float(params.get("sl_pct", 0.04054993005364031)),
        max_holding_bars=int(params.get("max_holding_bars", 28)),
    )
```

- [ ] Run: `pytest tests/test_volume_weighted_momentum.py -v` — Expected: 6 PASS
- [ ] Run: `mypy src/crypto_trader/strategy/volume_weighted_momentum.py --strict`
- [ ] Run: `ruff check src/crypto_trader/strategy/volume_weighted_momentum.py`

### Step 2.3: Commit

```
feat(strategy): add volume_weighted_momentum with parity fixtures
```

---

## Task 3: `pdh_pdl_sweep_reclaim` — Signal Parity

**Files:**
- Create: `src/crypto_trader/strategy/pdh_pdl_sweep_reclaim.py`
- Create: `tests/test_pdh_pdl_sweep_reclaim.py`

### Step 3.1: Write failing parity tests (3 fixtures)

```python
# tests/test_pdh_pdl_sweep_reclaim.py
"""Parity tests for PdhPdlSweepReclaimStrategy.

Fixtures from auto-research-engine parity spec §5.
Tolerance: |score - expected| < 1e-6.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction


def _ts(i: int) -> datetime:
    return datetime(2026, 1, 1, i % 24)


def _base_candle(i: int) -> Candle:
    return Candle(
        timestamp=_ts(i), open=100.0, high=100.3,
        low=99.7, close=100.05, volume=1000.0,
    )


def _pdl_candle(i: int) -> Candle:
    return Candle(
        timestamp=_ts(i), open=99.4, high=99.6,
        low=99.2, close=99.5, volume=1200.0,
    )


def _make_series(bar95_override: Candle | None = None) -> list[Candle]:
    """100-bar series with PDL dip at [60..70].

    If bar95_override is given, replace bar 95 with it.
    """
    bars = [_base_candle(i) for i in range(100)]
    for i in range(60, 71):
        bars[i] = _pdl_candle(i)
    if bar95_override is not None:
        bars[95] = bar95_override
    return bars


# Candidate A params
_PARAMS = dict(
    use_prev_day=True,
    n=22,
    eps=0.0018262133038232326,
    L=93,
    clv_min=0.6868883402451547,
    rvol_min=2.076067713758879,
    hold_bars=3,
)


class TestPdhPdlSignalParity:
    """Core signal parity — no gates, no exit."""

    def test_fixture_1_buy_all_flags(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )
        bars = _make_series(Candle(
            timestamp=_ts(95), open=99.3, high=99.40,
            low=98.90, close=99.35, volume=2500.0,
        ))
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        assert sig[95].action == SignalAction.BUY
        assert abs(sig[95].score - 0.999447) < 1e-6

    def test_fixture_2_hold_reclaim_fails(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )
        bars = _make_series(Candle(
            timestamp=_ts(95), open=99.3, high=99.55,
            low=98.90, close=99.10, volume=2500.0,
        ))
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        assert sig[95].action == SignalAction.HOLD
        assert abs(sig[95].score - 0.075858) < 1e-6

    def test_fixture_3_hold_no_sweep(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )
        bars = _make_series()  # bar 95 = base candle, no sweep
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        assert sig[95].action == SignalAction.HOLD
        assert abs(sig[95].score - 0.000553) < 1e-6


class TestPdhPdlWarmup:
    """Warmup boundary: bar < 93 → HOLD with score 0.0."""

    def test_bar_92_is_warmup(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )
        bars = _make_series()
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        assert sig[92].action == SignalAction.HOLD
        assert sig[92].score == 0.0

    def test_bar_93_is_not_warmup(self) -> None:
        from crypto_trader.strategy.pdh_pdl_sweep_reclaim import (
            PdhPdlSweepReclaimStrategy,
        )
        bars = _make_series()
        s = PdhPdlSweepReclaimStrategy(StrategyConfig(), **_PARAMS)
        sig = s.generate_signals(bars)
        # bar 93 should have a computed score (not 0.0 warmup)
        assert sig[93].score != 0.0 or sig[93].action == SignalAction.HOLD
        # It should be the base bar → flags=1 (only reclaim) → score ~0.000553
        assert abs(sig[93].score - 0.000553) < 1e-6
```

- [ ] Run: `pytest tests/test_pdh_pdl_sweep_reclaim.py -v` — Expected: FAIL

### Step 3.2: Implement PDH/PDL strategy

```python
# src/crypto_trader/strategy/pdh_pdl_sweep_reclaim.py
"""PDH/PDL Sweep & Reclaim strategy.

Parity implementation of auto-research-engine PdhPdlSweepReclaim.
Signal: mean-reversion / microstructure — detects a bar that sweeps a previous-day
low then recovers strongly with high CLV and elevated relative volume.

ARE reference: engine/genome/components/signals/pdh_pdl_sweep_reclaim.py
Parity spec: ../auto-research-engine/docs/specs/2026-04-12-crypto-trader-pdh-pdl-parity-spec.md
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
    """PDH/PDL sweep & reclaim — ARE-parity signal + gates + exit."""

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
        self._btc_candles = candles

    # ------------------------------------------------------------------
    # Core signal (ARE parity)
    # ------------------------------------------------------------------
    def generate_signals(self, candles: list[Candle]) -> list[SignalResult]:
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
            window_mean = sum(window_krw) / len(window_krw) if window_krw else _EPS
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
                indicators={"pdh_pdl_score": last.score, "hold_bars_hint": float(self._hold_bars)},
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

        # Max holding
        if holding_bars > self._max_holding_bars:
            return Signal(
                action=SignalAction.SELL, reason="max_holding_bars",
                confidence=1.0, indicators=indicators, context=ctx,
            )

        # Minimum hold enforcement (hold_bars)
        if holding_bars < self._hold_bars:
            return Signal(
                action=SignalAction.HOLD, reason="minimum_hold",
                confidence=0.3, indicators=indicators, context=ctx,
            )

        # Trailing stop: find peak since entry
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
            params.get("liquidity_min_krw_24h", 7_844_751_368.066064)
        ),
        trail_pct=float(params.get("trail_pct", 0.08183584818420675)),
        activation_pct=float(params.get("activation_pct", 0.032930819383335294)),
        max_holding_bars=int(params.get("max_holding_bars", 68)),
    )
```

- [ ] Run: `pytest tests/test_pdh_pdl_sweep_reclaim.py -v` — Expected: 5 PASS
- [ ] Run: `mypy src/crypto_trader/strategy/pdh_pdl_sweep_reclaim.py --strict`
- [ ] Run: `ruff check src/crypto_trader/strategy/pdh_pdl_sweep_reclaim.py`

### Step 3.3: Commit

```
feat(strategy): add pdh_pdl_sweep_reclaim with parity fixtures
```

---

## Task 4: Wire Registry into Existing Infrastructure

**Files:**
- Modify: `src/crypto_trader/strategy/__init__.py`
- Modify: `src/crypto_trader/wallet.py` (line ~92, top of `create_strategy`)
- Modify: `src/crypto_trader/config.py` (lines ~1193 and ~1058)

### Step 4.1: Side-effect imports in `__init__.py`

Add to the top of `src/crypto_trader/strategy/__init__.py`:

```python
# Registry-based strategies — import triggers @register
from crypto_trader.strategy import pdh_pdl_sweep_reclaim as _pdh_pdl_reg  # noqa: F401
from crypto_trader.strategy import volume_weighted_momentum as _vwm_reg  # noqa: F401
```

### Step 4.2: Registry hook in `wallet.py::create_strategy`

At the top of `create_strategy` (after `params = extra_params or {}`), add:

```python
    from crypto_trader.strategy import registry
    spec = registry.get_spec(strategy_type)
    if spec is not None:
        return spec.factory(strategy_config, regime_config, params)
```

### Step 4.3: Registry union in `config.py`

In `_validate_config`, change the `valid_strategies` set to union with registry:

```python
    from crypto_trader.strategy import registry as _strategy_registry
    valid_strategies = {
        "momentum",
        # ... existing entries unchanged ...
        "bb_squeeze_independent",
    } | _strategy_registry.known_names()
```

In `_strategy_override_names` function, add registry union:

```python
def _strategy_override_names(strategy_name: str) -> set[str]:
    from crypto_trader.strategy import registry as _strategy_registry
    return (
        _STRATEGY_FIELD_NAMES
        | _COMMON_WALLET_OVERRIDE_FIELDS
        | _STRATEGY_EXTRA_OVERRIDE_FIELDS.get(strategy_name, set())
        | _strategy_registry.known_override_fields(strategy_name)
    )
```

### Step 4.4: Run full test suite

- [ ] Run: `pytest -x -q` — Expected: all pass, no regressions
- [ ] Run: `mypy src/` — Expected: clean
- [ ] Run: `ruff check src/ tests/ scripts/` — Expected: clean

### Step 4.5: Commit

```
feat(strategy): wire plugin registry into wallet + config
```

---

## Task 5: Verification & Cleanup

### Step 5.1: Integration test — create_strategy with registry names

```python
# Add to tests/test_strategy_registry.py

def test_create_strategy_via_registry():
    """create_strategy finds registry-based strategies."""
    from crypto_trader.config import RegimeConfig, StrategyConfig
    from crypto_trader.wallet import create_strategy

    for name in ("volume_weighted_momentum", "pdh_pdl_sweep_reclaim"):
        s = create_strategy(name, StrategyConfig(), RegimeConfig())
        assert hasattr(s, "evaluate")
        assert hasattr(s, "set_btc_candles")
```

- [ ] Run: `pytest tests/test_strategy_registry.py -v` — Expected: 6 PASS

### Step 5.2: Existing config tests still pass

- [ ] Run: `pytest tests/test_config.py -v` — Expected: all PASS

### Step 5.3: Full verify

- [ ] Run: `pytest -x -q && mypy src/ && ruff check src/ tests/ scripts/`

### Step 5.4: Commit

```
test(strategy): add registry integration tests
```

---

## Commit Summary

| # | Message | Files |
|---|---|---|
| 1 | `feat(strategy): add plugin registry with @register decorator` | registry.py + tests |
| 2 | `feat(strategy): add volume_weighted_momentum with parity fixtures` | vwm.py + tests |
| 3 | `feat(strategy): add pdh_pdl_sweep_reclaim with parity fixtures` | pdh_pdl.py + tests |
| 4 | `feat(strategy): wire plugin registry into wallet + config` | __init__.py, wallet.py, config.py |
| 5 | `test(strategy): add registry integration tests` | test additions |
