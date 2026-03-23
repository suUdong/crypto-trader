# Crypto Trader Product Direction Brainstorm

Date: 2026-03-23
Inputs:

- `docs/reviews/2026-03-23/01-office-hours.md`
- `docs/reviews/2026-03-23/02-plan-ceo-review.md`
- `docs/reviews/2026-03-23/03-plan-eng-review.md`

## Working Product Thesis

`crypto-trader` should evolve as:

> **Upbit KRW Strategy Lab -> Operator Control Plane**

The near-term product is not a generic trading bot. It is a system that helps a serious KRW-market trader answer:

- does this strategy deserve trust?
- does it deserve more capital?
- should it stay in paper or be shut down?

The long-term product is an operating system for strategy validation, promotion, and risk-aware operation on KRW spot markets.

## 1. Current Codebase Strengths and Weaknesses

## Strengths

### 1. Clear kernel boundaries

The code already separates:

- strategy logic
- risk logic
- execution
- backtesting
- runtime orchestration

That is exactly the shape you want if the system later grows from “single strategy engine” into “strategy operating system.”

### 2. Paper-first safety

The repo defaults to paper mode and explicitly rejects unsupported live mode. That is a strong product signal because the new wedge is trust, not reckless automation.

### 3. Good prototype test posture

The project already has tests around:

- config loading
- strategy logic
- risk management
- backtest behavior
- paper broker accounting
- pipeline behavior

That means future product features can be added onto a disciplined foundation rather than a pile of scripts.

### 4. Early operational thinking

Logging, health snapshots, Docker, and CI are already present. Many early trading tools ignore operations until too late; this repo did not.

### 5. Strong alignment with the new wedge

The current code is already closer to “validation system” than to “full auto-trading product” because it has:

- backtests
- paper execution
- runtime monitoring
- risk gates

That means the reframed product direction uses what already exists instead of fighting it.

## Weaknesses

### 1. No durable product memory

The system has execution state, but not product state.

Missing persistent concepts:

- strategy run history
- paper-vs-backtest drift history
- regime snapshots
- verdict history
- promotion decisions

Without these, the product cannot become a real control plane.

### 2. Too execution-centric

The domain model still describes trading mechanics:

- candles
- signals
- positions
- orders
- trades

It does not yet describe product concepts:

- experiment
- strategy evaluation
- operator memo
- promotion gate
- capital recommendation

### 3. No explainability layer

The system can generate a signal, but it cannot yet explain the signal in product terms a serious operator can trust every day.

### 4. No persistence-backed reporting loop

The product direction requires longitudinal judgment:

- is the strategy improving or degrading?
- is paper behavior diverging from expected behavior?
- has market regime changed?

The current system is too ephemeral to answer these cleanly.

### 5. Current scope is still “one good engine,” not “one good product”

The repo is technically credible, but the product surface is still thin. There is no clear opinion layer yet.

## 2. Core Features To Build Next

## Feature 1: Strategy Verdict Engine

What it is:

A layer that converts raw signals, recent paper performance, and risk state into a daily or periodic verdict such as:

- continue paper
- reduce risk
- pause strategy
- candidate for promotion

Why it matters:

This is the first real “product judgment” layer. It moves the system from tool to advisor.

## Feature 2: Backtest vs Paper Drift Report

What it is:

A persistent comparison of expected behavior versus live paper behavior:

- trade frequency drift
- win-rate drift
- drawdown drift
- signal-quality drift

Why it matters:

This directly supports the trust wedge. Users need to know when historical confidence is no longer valid.

## Feature 3: Promotion Gate Workflow

What it is:

A formal set of rules and recorded decisions governing movement from:

- design/backtest
- backtest to paper
- paper to future live mode

Why it matters:

This is the product’s discipline mechanism. It prevents emotional or arbitrary promotion of weak strategies.

## Feature 4: Strategy Run Journal and Persistence Layer

What it is:

A durable store for:

- run metadata
- signals
- decisions
- runtime health
- verdicts

Why it matters:

Without persistence, the product cannot accumulate trust or support any serious operator workflow.

## Feature 5: Operator Daily Memo / Control Surface

What it is:

A concise operator-facing output that says:

- what happened
- why it happened
- what changed
- what the system recommends next

This can begin as a generated markdown/Telegram summary before it becomes a fuller UI.

Why it matters:

This is how the product becomes usable as an operating system rather than just a backend engine.

## 3. Priorities and Reasons

## Priority 1: Strategy Verdict Engine + Strategy Run Journal

Why first:

- it is the clearest expression of the new product thesis
- it creates user-facing product value without needing live trading
- it can be built mostly on top of existing kernel pieces
- verdicts without durable history risk becoming shallow and untrustworthy

These two capabilities should ship as one first slice:

- the journal gives the product memory
- the verdict layer turns that memory into operator judgment

If this pair does not exist, the product is still just infrastructure.

## Priority 2: Backtest vs Paper Drift Report

Why second:

- it turns persistence into trust
- it gives users a concrete reason to run the product daily
- it distinguishes the product from a plain trading bot

This is the feature that starts proving the moat.

## Priority 3: Promotion Gate Workflow

Why third:

- once the system can persist and compare behavior, it can make disciplined go/no-go decisions
- this converts the product from “observer” into “governor”

It should come after verdict + drift because otherwise the gate is arbitrary.

## Priority 4: Operator Daily Memo / Control Surface

Why fourth:

- the system can ship value earlier as generated reports
- a full control surface is valuable, but should be built on top of stable product judgment and persistent data

In other words:

- do not build a dashboard for data that is not yet worth looking at

## What Is Intentionally Not Prioritized

### Multi-exchange support

Reason:

- expands scope without proving the wedge
- weakens focus on KRW specialization

### More indicators and strategy families

Reason:

- easy to add, hard to justify
- risks turning the product into a toolbox

### Live trading

Reason:

- downstream capability, not current wedge
- trust/reporting/product judgment need to exist first

## 4. Product Roadmap Draft

## Phase 0: Current State

What exists now:

- one strategy family
- one exchange focus
- backtest engine
- paper broker
- runtime monitoring
- notifications
- basic operational hardening

This is the kernel.

## Phase 1: Strategy Lab

Goal:

Help one serious KRW trader prove whether a strategy deserves continued attention.

Deliverables:

- persistent strategy run journal
- strategy verdict engine
- daily strategy memo
- first paper-vs-backtest comparison report

Success condition:

The user can run one strategy daily and understand whether confidence is rising or falling.

## Phase 2: Trust and Promotion

Goal:

Convert the product from “analysis tool” into “disciplined operating workflow.”

Deliverables:

- promotion gate rules
- confidence thresholds
- pause/reduce/promote recommendations
- stronger regime-awareness inputs

Success condition:

The product can make an explicit recommendation about whether a strategy should remain in paper, be paused, or become a promotion candidate.

## Phase 3: Operator Control Plane

Goal:

Create a genuine operator experience around strategy oversight.

Deliverables:

- portfolio view of multiple strategies
- run history and verdict history
- risk and drift summaries across strategies
- operator-facing control surface

Success condition:

The user is managing a portfolio of strategy candidates, not just running one bot.

## Phase 4: Capital Policy Layer

Goal:

Turn the system into a decision layer for allocation, not just signal generation.

Deliverables:

- capital allocation recommendations
- strategy ranking
- parameter experiment comparison
- “where should the next unit of risk budget go?” logic

Success condition:

The product helps the operator decide how capital should move across validated KRW strategies.

## Phase 5: Carefully Gated Live Execution

Goal:

Support real execution only after the trust and governance layers exist.

Deliverables:

- real execution adapter
- live-mode audit trail
- stronger credential and secret-handling policy
- kill switches and escalation rules

Success condition:

Live trading is the consequence of proven operator workflow, not the initial pitch.

## Key Strategic Rule

Every roadmap decision should pass this test:

> Does this help a serious KRW trader decide whether a strategy deserves capital?

If yes, it is likely on-strategy.
If not, it is probably feature creep.

## Recommended Immediate Next Build Cycle

If choosing just one concrete next cycle, build:

1. persistent strategy run journal
2. first version of strategy verdict generation
3. first backtest-vs-paper drift output

Then add:

4. daily memo output

That sequence is the shortest path from “trading engine prototype” to “Strategy Lab product” without creating a shallow verdict layer.

## Final Recommendation

Do not grow outward first.
Grow upward.

Meaning:

- do not add more exchanges
- do not add more automation slogans
- do not add more indicators for their own sake

Instead, add:

- memory
- judgment
- trust

That is how `crypto-trader` becomes a real product instead of another bot repo.
