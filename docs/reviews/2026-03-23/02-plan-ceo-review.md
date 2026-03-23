# /plan-ceo-review — 10-Star Product Review

Status: DONE
Mode: Selective expansion
Date: 2026-03-23
Input: `docs/reviews/2026-03-23/01-office-hours.md`

## Executive Verdict

`crypto-trader` should **not** become a generic “AI auto-trading bot.”

That path is crowded, weakly differentiated, hard to trust, and strategically lazy.

The 10-star version is:

> **A KRW-market strategy operating system that tells serious traders when a strategy deserves capital, when it should stay in paper, and when it should be shut down.**

That is a product. The generic bot framing is a feature pile.

## Step 0: Nuclear Scope Challenge

### Is this the right problem?

Partially.

The current project solves a proxy problem:

- proxy problem: automate trades
- real problem: decide whether a strategy is safe, trustworthy, and capital-worthy

If you optimize for the proxy, you ship another bot.
If you optimize for the real problem, you can build a trust product.

### Existing code leverage

The current codebase already covers the right early primitives:

- strategy definition
- backtest engine
- paper broker
- monitoring
- notifications

What it does **not** yet express is product judgment:

- no promotion gate
- no trust score
- no regime fitness layer
- no operator-facing decision surface

### Dream-state map

```
CURRENT
Single-strategy paper-trading engine for Upbit KRW

THIS PLAN
Reframe product around proof, trust, and controlled capital promotion

12-MONTH IDEAL
KRW strategy operating system with validation, monitoring, and capital-allocation discipline
```

## Three Implementation Directions

### Approach A: Generic Bot Expansion

Summary:
Add more exchanges, more indicators, and live trading quickly.

Effort: M
Risk: High

Pros:

- easy roadmap to explain
- matches common retail expectations
- feature count grows fast

Cons:

- no moat
- trust remains weak
- product becomes commodity immediately

Recommendation:

Reject.

### Approach B: Strategy Lab

Summary:
Keep one exchange and one strategy family, but build the strongest possible proof-and-monitoring loop around it.

Effort: M
Risk: Medium

Pros:

- tightly aligned with existing code
- builds trust before live execution
- much stronger first wedge

Cons:

- narrower initial story
- less flashy than “full auto-trading”

Recommendation:

Strong candidate.

### Approach C: Operator Control Plane

Summary:
Make the product a capital-allocation and risk-decision cockpit for KRW strategies: backtest, paper, drift detection, regime fit, daily recommendation memo, and controlled promotion gates.

Effort: L
Risk: Medium

Pros:

- strongest moat
- strongest trust story
- best long-term product platform

Cons:

- requires product discipline
- demands better UX and reporting than the repo currently has

Recommendation:

Best long-term direction. Start by shipping Approach B as the entry wedge and grow into C.

## My CEO Call

Choose:

> **B now, C as the intentional destination.**

In other words:

- near-term product: Strategy Lab
- long-term product: Operator Control Plane

## What Makes This 10-Star Instead of 7-Star

Seven-star product:

- lets me run a strategy
- sends alerts
- maybe auto-trades eventually

Ten-star product:

- tells me whether I should trust the strategy today
- explains why a signal happened
- shows whether paper performance still matches backtest assumptions
- tells me when the market regime invalidates the model
- prevents me from allocating capital just because I am emotionally tempted

That difference matters. One is software. The other changes behavior.

## Selective Expansion Decisions

### Expansion 1: Daily strategy verdict

Accept.

Every run should eventually roll up into a verdict like:

- promote
- continue paper
- reduce size
- pause strategy

This is the product’s opinion layer.

### Expansion 2: Regime drift detection

Accept.

Without this, backtests become false comfort.

### Expansion 3: Strategy memo / explainability report

Accept.

A serious trader wants:

- what happened
- why it happened
- whether today’s conditions still resemble the tested conditions

### Expansion 4: Multi-exchange support now

Reject for now.

This is scope expansion without strategy.

### Expansion 5: “Live trading” as headline value proposition

Reject for now.

Live execution is a downstream capability, not the wedge.

## Product Risks

### 1. Commodity risk

If the homepage pitch becomes “automated crypto trading bot,” differentiation collapses.

### 2. Trust gap

If the system can act but cannot explain itself, users will hesitate exactly when confidence matters most.

### 3. False precision

Backtest metrics alone can create fake conviction. The product needs “confidence under current conditions,” not just historical ROI.

### 4. Audience confusion

Retail gamblers, systematic traders, and internal desk operators are different customers. Pick one.

## Recommended Customer

Start with:

> serious solo trader / small desk operator focused on Upbit KRW spot who already experiments with systematic strategies but lacks a reliable validation-to-operations loop

Do not start with:

- casual retail trader seeking passive income
- fully institutional multi-exchange quant desk
- broad “anyone who trades crypto”

## What The Product Should Say

Not:

> “Automate your crypto trading with AI.”

Say:

> “Prove a KRW strategy deserves capital before it touches real money.”

And then:

> “Backtest it. Paper-trade it. Watch regime drift. Get an explicit operator verdict.”

## Failure Modes Registry

### Failure mode 1: The product becomes a toolbox

Symptoms:

- more indicators
- more knobs
- more exchanges
- no clearer user outcome

### Failure mode 2: The product becomes an execution engine without judgment

Symptoms:

- live trading implemented before trust/reporting
- strong infra, weak product decision layer

### Failure mode 3: The product markets alpha, not discipline

Symptoms:

- exaggerated positioning
- weak trust with serious users
- attracts the wrong audience

## 90-Day CEO Roadmap

### Phase 1

Ship the strongest possible Strategy Lab:

- one strategy family
- one exchange
- one or a few KRW pairs
- robust backtest + paper runtime + operator alerts

### Phase 2

Add trust primitives:

- daily strategy memo
- backtest vs paper drift report
- promotion gate
- explicit strategy health score

### Phase 3

Add control-plane features:

- compare multiple strategy variants
- capital-allocation recommendation
- pause/promote/reduce-size workflow

## Final Recommendation

The winning move is not “be a better bot.”

The winning move is:

> **Own the decision layer between strategy idea and capital allocation for KRW crypto traders.**

That is the version of `crypto-trader` that could actually become a 10-star product.
