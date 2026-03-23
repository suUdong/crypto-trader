# /plan-eng-review — Architecture and Engineering Review

Status: DONE_WITH_CONCERNS
Date: 2026-03-23
Inputs:

- `docs/reviews/2026-03-23/01-office-hours.md`
- `docs/reviews/2026-03-23/02-plan-ceo-review.md`
- current code in `src/crypto_trader/`
- current tests in `tests/`

## Executive Verdict

The codebase is **well-scaffolded for a serious prototype** and unusually disciplined for an early-stage trading project:

- clear module boundaries
- paper-trading safety by default
- test coverage on core decision paths
- basic runtime observability

But it is **not yet architected for the 10-star product direction** defined in the CEO review.

The current system is best understood as:

> a single-strategy execution kernel

not yet:

> a strategy operating system

## Step 0: Scope Challenge

### What already solves sub-problems well

- `strategy/` cleanly isolates indicator and decision logic
- `risk/` isolates sizing and stop/take-profit rules
- `execution/` isolates paper-broker behavior
- `backtest/` is separated from runtime execution
- `pipeline.py` defines the live loop boundary clearly

These are good decisions. They give you a place to evolve without rewriting everything.

### Minimum architecture that achieves the next goal

If the next goal is the Strategy Lab wedge, the minimum required additions are:

1. strategy verdict/reporting layer
2. experiment/result persistence
3. explicit promotion gate from backtest -> paper
4. stronger runtime recovery semantics

You do **not** need yet:

- live order routing
- Binance
- multi-strategy orchestration framework
- a database-heavy architecture

### Complexity check

The current code is still within healthy complexity for a prototype. The smell is not “too many files.” The smell is:

- important state still lives only in memory
- product-level abstractions are not yet reflected in code boundaries

## Architecture Review

## What is strong

### 1. Boundaries are sane

The main pipeline is legible:

```
market data
  -> strategy signal
    -> risk gate
      -> execution
        -> notification
          -> health snapshot
```

This is the right skeleton.

### 2. Paper-safety posture is correct

Rejecting live mode instead of pretending it exists is the right engineering decision.

### 3. Backtest and runtime are separate

This matters. Many trading repos entangle strategy logic with exchange execution; this repo mostly avoids that trap.

## Main concerns

### Concern 1: The system is stateless where the product needs memory

The product direction now wants:

- drift detection
- promotion gates
- strategy health
- historical operator verdicts

None of that fits cleanly into the current in-memory runtime.

Right now, important runtime state is ephemeral:

- session starting equity
- open positions
- health progression
- signal history
- paper-vs-backtest comparisons

Implication:

Restarting the service loses product memory. That is acceptable for a prototype, but it blocks the Strategy Lab / Control Plane direction.

### Concern 2: `config.py` is becoming the god object

`src/crypto_trader/config.py` is already 278 lines and mixes:

- schema definition
- env parsing
- TOML parsing
- validation rules
- future-mode policy

It is still manageable today, but it is on the path to becoming the repo’s implicit control plane.

Recommendation:

- keep the current file for now
- next meaningful product expansion should split schema, loading, and validation into separate layers

### Concern 3: Strategy evaluation is single-shot, not lifecycle-aware

The code can answer:

- “buy/sell/hold now?”

It cannot yet answer:

- “how has this strategy behaved over the last week?”
- “is the current regime similar to the validated regime?”
- “should we continue allocating attention or capital?”

That is not a bug. It is the next architecture boundary you need.

### Concern 4: Runtime recovery is too light for operations software

`runtime.py` is an in-process sleep loop. That is fine for early execution, but not enough for an operator product because:

- no checkpointing of last processed iteration
- no persistent order/signal journal beyond health snapshot
- no restart/replay model
- no scheduler abstraction

For a 10-star product, “can recover cleanly after restart” is table stakes.

## Code Quality Review

## What is working

- naming is explicit
- modules are mostly small enough to reason about
- no unnecessary framework sprawl
- abstractions are still concrete rather than speculative

## Main code-quality risks

### 1. Domain model is still execution-centric

The model layer understands:

- candles
- signals
- positions
- orders
- trades

It does **not** yet understand product concepts such as:

- strategy run
- experiment
- verdict
- promotion decision
- regime snapshot

If the product direction changes but the model layer stays execution-centric, the repo will fight you later.

### 2. Recalculation model is simple but not scalable

The backtest engine repeatedly slices candle windows and recomputes indicators from scratch. That is okay for current scope, but becomes expensive when you add:

- longer histories
- more symbols
- parameter sweeps
- multi-strategy comparison

Recommendation:

- keep this implementation for now
- do not optimize early
- but treat a feature like “grid search / experiment runner” as the forcing function for a vectorized or cached feature pipeline

### 3. No persistent result model yet

A control-plane product needs stable artifacts:

- run result
- signal log
- drift report
- daily memo

Today the system computes decisions but does not yet produce a durable product object around them.

## Test Review

The current test posture is solid for a prototype:

- config loading
- indicators and strategy behavior
- risk manager
- paper broker
- pipeline behavior
- monitoring
- contract tests

### Coverage diagram

```
CONFIG
  load_config
    -> defaults
    -> env overrides
    -> unsupported live mode rejection

STRATEGY
  indicators
    -> momentum
    -> bollinger
    -> rsi
  composite strategy
    -> buy path
    -> max-hold sell path

EXECUTION
  paper broker
    -> buy fill
    -> sell fill
    -> fee-inclusive pnl

PIPELINE
  run_once
    -> normal buy flow
    -> error path
    -> stable daily-loss baseline

BACKTEST
  run
    -> fee-adjusted pnl consistency

MONITORING
  health snapshot write
```

### Biggest gaps

1. No CLI integration test
2. No runtime loop test
3. No adapter contract test around `pyupbit`
4. No persistence/replay tests because persistence does not exist yet

These are acceptable now. They become unacceptable once the product starts making longitudinal claims.

## Performance Review

Current performance posture is acceptable for:

- one exchange
- one symbol or a small symbol set
- one strategy family
- light paper runtime

It is not ready for:

- research-scale backtesting
- portfolio-level scanning
- parameter search
- low-latency execution

That is fine. Just do not confuse prototype performance with platform readiness.

## Recommended Architecture Moves

### Now

1. Add a persisted “strategy run” artifact
2. Add a daily/periodic “strategy verdict” artifact
3. Add a promotion-gate layer between backtest and paper

### Next

1. Separate config schema/loading/validation
2. Introduce persistent journal storage for signals, decisions, and runtime health
3. Add a reporting layer that turns raw trading events into operator decisions

### Later

1. Experiment runner for multi-parameter comparisons
2. Regime detection subsystem
3. Real execution adapter only after operator-grade guardrails exist

## Opinionated Recommendation

Do **not** spend the next engineering cycle on live trading or Binance.

Spend it on:

- durable result artifacts
- strategy verdict generation
- promotion-gate mechanics

That is the minimum architecture work that moves the repo from “bot prototype” toward “strategy operating system.”

## Final Verdict

This is a **good prototype architecture** with a clean kernel and respectable tests.

It is **not yet the right architecture for the product you should build next**, but it is close enough that you should evolve it rather than rewrite it.

If you keep the current kernel and add a persistent decision/reporting layer, the repo can grow into the stronger product direction without wasting the work already done.
