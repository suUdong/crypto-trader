# Strategy Plugin Registry + pdh_pdl / VWM Parity Implementation

**Date**: 2026-04-12
**Status**: APPROVED (operator delegated decisions on flexibility/extensibility)
**Goal**: Introduce a plugin registry so new strategies are single-file drops, then use it to implement `pdh_pdl_sweep_reclaim` and `volume_weighted_momentum` at 1e-6 parity with auto-research-engine specs.

## 1. Strategy Plugin Registry

### Problem

Adding a strategy currently requires editing 3+ files:
- `wallet.py::create_strategy` (add elif branch, ~20 lines)
- `config.py::valid_strategies` (add string)
- `config.py::_STRATEGY_EXTRA_OVERRIDE_FIELDS` (add override set)
- `strategy/__init__.py` (optional export)

28 strategies are wired this way. The if/elif in `create_strategy` is 336+ lines.

### Solution: `src/crypto_trader/strategy/registry.py`

```python
@dataclass(frozen=True)
class StrategySpec:
    name: str
    factory: StrategyFactory  # (StrategyConfig, RegimeConfig, params) -> StrategyProtocol
    override_fields: frozenset[str]

_REGISTRY: dict[str, StrategySpec] = {}

def register(name, *, override_fields=frozenset()):
    """Decorator for a factory function. Self-registers at import time."""
```

Public API: `get_spec(name)`, `known_names()`, `known_override_fields(name)`.

### Integration points (additive only, no existing code rewrite)

| File | Change | Lines |
|---|---|---|
| `wallet.py::create_strategy` | Top-of-function: `spec = registry.get_spec(...)` → early return | +4 |
| `config.py::_validate_config` | `valid_strategies \|= registry.known_names()` | +1 |
| `config.py::_strategy_override_names` | `\|= registry.known_override_fields(name)` | +1 |
| `strategy/__init__.py` | Side-effect imports for new strategy modules | +2 |

Existing 28 strategies: zero changes. They stay in the legacy elif chain. Future migration is optional and incremental.

### BTC candle injection convention

Strategies that need cross-symbol BTC data expose `set_btc_candles(candles)`. The registry factory can return any object satisfying `StrategyProtocol`; the runtime already calls `set_btc_candles` if the method exists (see `bb_squeeze_independent` pattern in wallet runtime). No registry involvement needed.

## 2. `pdh_pdl_sweep_reclaim` Strategy

### Signal (ARE `PdhPdlSweepReclaim.compute` — 84 lines)

Per bar `i` (warmup = max(n, L, 48) = 93 for Candidate A):
1. `ref_low = min(lows[i-48:i-24])` (use_prev_day=True)
2. `sweep = lows[i] < ref_low * (1 - eps)`
3. `reclaim = closes[i] > ref_low`
4. `clv = (close - low) / (high - low + 1e-12)` >= `clv_min`
5. `rvol = krw_vol[i] / mean(krw_vol[i-L:i] + 1e-12)` >= `rvol_min`
6. `flags = sum([sweep, reclaim, strong, liquid])` (0..4)
7. `score = sigmoid(5 * (flags - 2.5))`, BUY if score > 0.5

### Parameters (exact, no rounding)

use_prev_day=True, n=22, eps=0.0018262133038232326, L=93,
clv_min=0.6868883402451547, rvol_min=2.076067713758879, hold_bars=3

### Gate: btc_above_sma(period=251)
Via `set_btc_candles()` injector. Fallback: use target candles.

### Gate: liquidity_min(min_24h_krw=7_844_751_368.066064)
`sum(krw_vol[i-23:i+1]) >= threshold`. Fail if `i < 23`.

### Exit: trailing_stop
trail_pct=0.08183584818420675, activation_pct=0.032930819383335294, max_holding_bars=68.
hold_bars=3 minimum-hold enforced in `_evaluate_exit`.

### Parity fixtures (3)

| # | Bar 95 override | Expected score | Action |
|---|---|---|---|
| F1 | open=99.3 h=99.40 l=98.90 c=99.35 v=2500 | 0.999447 | BUY |
| F2 | open=99.3 h=99.55 l=98.90 c=99.10 v=2500 | 0.075858 | HOLD |
| F3 | (base bar unchanged) | 0.000553 | HOLD |

100-bar series, base=Candle(100,100.3,99.7,100.05,1000). PDL dip at [60..70].

## 3. `volume_weighted_momentum` Strategy

### Signal (ARE `VolumeWeightedMomentum.compute` — 59 lines)

Per bar `i` (warmup: i < period):
1. `returns[j] = (close[j] - close[j-1]) / close[j-1]`; returns[0] = 0
2. Window `[i-period+1 .. i]` inclusive (period=24 bars)
3. `vwm = sum(returns[j]*vol[j]) / sum(vol[j])`
4. `score = sigmoid(alpha * vwm)`, BUY if score > 0.5 (strict)
5. If vol_sum == 0: score = 0.5, HOLD

### Parameters (exact)

period=24, alpha=264.8908943094896

### Gate: btc_above_sma(period=221)
### Gate: liquidity_min(min_24h_krw=975_695_489.5449693)

### Exit: fixed_tp_sl
tp_pct=0.09956445995940857, sl_pct=0.04054993005364031, max_holding_bars=28.
SL checked before TP (SL priority per parity contract).

### Parity fixtures (4)

| # | Construction | Expected score @ bar 24 | Action |
|---|---|---|---|
| F1 | +0.1%/bar, vol=1000 | 0.565838 | BUY |
| F2 | flat close=100, vol=1000 | 0.500000 | HOLD |
| F3 | -0.1%/bar, vol=1000 | 0.434162 | HOLD |
| F4 | alternating -0.1%(v=10000) / +0.3%(v=100) | 0.438110 | HOLD |

## 4. File inventory

| File | New/Edit | Purpose |
|---|---|---|
| `src/crypto_trader/strategy/registry.py` | New | Plugin registry |
| `src/crypto_trader/strategy/pdh_pdl_sweep_reclaim.py` | New | Strategy + factory |
| `src/crypto_trader/strategy/volume_weighted_momentum.py` | New | Strategy + factory |
| `src/crypto_trader/strategy/__init__.py` | Edit (+2 lines) | Side-effect imports |
| `src/crypto_trader/wallet.py` | Edit (+4 lines) | Registry hook |
| `src/crypto_trader/config.py` | Edit (+3 lines) | Registry union |
| `tests/test_strategy_registry.py` | New | Registry unit tests |
| `tests/test_pdh_pdl_sweep_reclaim.py` | New | Parity fixtures |
| `tests/test_volume_weighted_momentum.py` | New | Parity fixtures |

## 5. Out of scope

- Migrating existing 28 strategies to registry
- `[[strategies]]` TOML table-array (sticking with `[[wallets]]` pattern)
- Hot-reload, runtime activation/deactivation beyond daemon.toml
- Signal/Gate/Exit component decomposition (ARE genome architecture)
- daemon.toml modification (operator P2 action)
- Backtest engine changes
