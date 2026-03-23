# Crypto Trader Next Priorities

Date: 2026-03-24
Inputs:

- `SESSION_HANDOFF.md`
- `docs/brainstorm/2026-03-23-product-direction.md`
- `docs/reviews/2026-03-23/00-summary.md`
- `docs/reviews/2026-03-23/03-plan-eng-review.md`

## Current Read

The project is no longer just a trading kernel. It now has:

- strategy evaluation
- regime awareness
- drift reporting
- promotion gating
- memo generation
- real-data operator artifact verification

What it still lacks is a truly usable **paper-trading operating environment** that runs like a product instead of a collection of commands.

## Candidate Directions

## 1. Runnable Paper-Trading Operations Layer

What it means:

- real Upbit price feed into `run-loop`
- paper trades persisted automatically
- open positions tracked continuously
- daily performance report generated from actual trade history

Why it matters:

This is the shortest path from “strategy lab primitives” to “something a trader can actually leave running.”

Implementation direction:

- extend the existing `PaperBroker` and operator layer instead of creating a new subsystem
- persist closed trades and open position snapshots as artifacts
- add a daily performance artifact derived from the persisted trade journal
- keep everything paper-first

Difficulty:

- medium

Expected effect:

- highest immediate product value
- strongest operational realism
- unlocks richer memo/reporting later

Recommendation:

Top priority.

## 2. Regime Report Artifact

What it means:

- explicit artifact explaining detected regime
- adjusted parameters shown side-by-side with base parameters
- rationale surfaced for operator trust

Why it matters:

Right now regime state exists in code and journals, but not as a first-class operator output.

Difficulty:

- low to medium

Expected effect:

- better explainability
- easier threshold tuning
- improves memo usefulness

Recommendation:

Second priority.

## 3. Baseline / Drift Calibration Toolkit

What it means:

- compare baseline results across longer windows
- tune regime-aware drift thresholds from more than one short sample
- surface “how much deviation is normal” per market state

Why it matters:

The drift system now works, but its thresholds are still heuristic defaults.

Difficulty:

- medium

Expected effect:

- higher signal quality
- fewer false positives / false comfort cases

Recommendation:

Third priority.

## 4. Richer Operator Report

What it means:

- one unified report artifact combining:
  - baseline
  - regime
  - drift
  - promotion
  - memo summary

Why it matters:

The operator currently gets several separate artifacts. A single report would make the system feel like one product.

Difficulty:

- medium

Expected effect:

- better usability
- easier Telegram / future UI integration

Recommendation:

Fourth priority.

## 5. Long-Lived Session Reliability

What it means:

- stronger restart behavior
- replay-safe runtime state
- more durable periodic execution semantics

Why it matters:

This matters for real operation, but only after the paper-trading environment is product-credible.

Difficulty:

- medium to high

Expected effect:

- operator confidence
- less babysitting

Recommendation:

Fifth priority.

## Priority Order

1. Runnable paper-trading operations layer
2. Regime report artifact
3. Baseline / drift calibration toolkit
4. Richer operator report
5. Long-lived session reliability

## Why Priority 1 Wins

The strategy lab already knows how to:

- detect signals
- adapt to regime
- compare paper behavior to a baseline
- gate promotion

But it still does not fully behave like a paper-trading product you can run continuously and inspect later.

That is the highest-leverage gap because it turns the existing intelligence into a usable operating environment.

## Immediate Build Recommendation

Implement Priority 1 now by extending the current `PaperBroker` + `operator/` layer with:

1. persisted trade journal
2. open position snapshot artifact
3. daily performance artifact
4. runtime sync that updates these artifacts automatically during paper execution
