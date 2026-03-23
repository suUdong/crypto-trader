# /office-hours — Crypto Trader Product Direction Redefinition

Status: DONE
Mode: Startup mode
Date: 2026-03-23
Project: `crypto-trader`

## What This Project Is Today

`crypto-trader` is currently an Upbit-first crypto trading system with:

- one composite strategy: momentum + Bollinger Bands + RSI
- backtesting
- paper trading
- Telegram alerts
- runtime health snapshots
- CI, Docker, and basic operational hardening

In plain terms: it is not yet a “product.” It is a technically credible trading engine skeleton for one operator and one strategy family.

## What Problem It *Looks* Like It Is Solving

At first glance, the project appears to solve:

> “I want an automated bot that trades Korean crypto markets for me.”

That framing is too weak. It leads straight into commodity territory:

- dozens of generic trading bots already exist
- “auto-trade for me” is not a trustworthy wedge without real edge proof
- users do not actually want automation for its own sake; they want confidence, discipline, and capital protection

## What Problem It *Should* Be Solving

The stronger problem statement is:

> “Korean crypto traders need a trustworthy way to test, monitor, and gradually operationalize a strategy on Upbit without risking real capital before the strategy proves itself.”

That is a better wedge because it aligns with what the code already does:

- strategy definition
- backtest
- paper execution
- audit/health output
- operator notifications

## The Six Forcing Questions

### 1. Demand Reality

There is no evidence in the repo of real demand yet.

What would count as real demand here:

- traders repeatedly asking for KRW-market-specific validation tools
- users importing their own candidate strategies and comparing results
- users treating paper-trading drift or runtime downtime as urgent
- users paying to avoid silent losses and notebook/spreadsheet glue work

Current diagnosis:

- demand is unproven
- the repo demonstrates implementation intent, not customer pull

### 2. Status Quo

The likely current workaround for the target user is:

- TradingView alerts
- manual Upbit execution
- Python notebooks or ad hoc scripts
- spreadsheets for PnL tracking
- Telegram messages with no true auditability

That workaround is painful because it is fragmented, error-prone, and psychologically hard to trust.

### 3. Desperate Specificity

The sharpest plausible initial user is:

> A solo Korean crypto trader or small trading desk operator who runs discretionary or semi-systematic KRW spot strategies on Upbit and wants a controlled path from idea to paper validation to eventual real execution.

What gets this person promoted or keeps them in the game:

- not blowing up capital
- proving a strategy before sizing it up
- having an audit trail for every signal and trade decision

### 4. Narrowest Wedge

The narrowest sellable wedge is not “multi-exchange auto-trading.”

It is:

> “Upbit KRW Strategy Lab: define one strategy, backtest it on Upbit data, run it in paper mode continuously, and receive an explainable daily/real-time report on whether it deserves capital.”

That wedge is small, concrete, and already close to the current code.

### 5. Observation & Surprise

There is no evidence of real user observation yet.

The most likely future surprise:

- users may care less about automatic order placement than about trust, explainability, and false-positive reduction
- they may want “should I trust this strategy today?” more than “place a trade now”

### 6. Future-Fit

If crypto markets become more efficient and retail traders get flooded with commodity bots, generic automation becomes less valuable.

What becomes *more* valuable:

- strategy validation
- explainability
- risk governance
- KRW-market-specific workflows
- operational reliability

That means the strongest 3-year thesis is not “best bot,” but:

> “best KRW-market strategy validation and operator control layer.”

## Redefined Product Direction

### Bad Direction

“Build a full auto-trading bot with more exchanges and more indicators.”

Why this is weak:

- easy to copy
- crowded market
- weak trust moat
- expands scope faster than it increases value

### Strong Direction

“Build the operating system for proving a KRW crypto strategy deserves capital.”

This product would help a trader answer four questions every day:

1. Is the strategy in regime or out of regime?
2. Did today’s signals match historical expectations?
3. Is execution behaving safely?
4. Should I keep this strategy in paper, size it up, or shut it down?

## 12-Month Ideal

```
CURRENT STATE
Single-strategy engine with backtest, paper execution, and operator alerts

NEXT STATE
Upbit KRW strategy validation cockpit with explainable reports, paper runtime, and regime/risk monitoring

12-MONTH IDEAL
Portfolio-level KRW strategy operations platform:
- multi-strategy comparison
- parameter/risk experiments
- explainable daily decision memos
- paper-to-live promotion gates
- capital allocation policy layer
```

## Product Thesis

### Core thesis

Users do not want “automation.”
Users want “confidence to allocate capital.”

### Moat thesis

The moat is not indicators.
The moat is:

- KRW-market specialization
- trust and explainability
- disciplined paper-to-live promotion workflow
- operational safety primitives

### Positioning thesis

Do not position this as:

- AI trading bot
- passive income bot
- no-code quant platform

Position it as:

> “The safest path from KRW strategy idea to production trading decision.”

## What To Build Next If This Direction Is Accepted

1. Strategy evaluation report layer
   - daily/weekly explainable summary
   - backtest vs paper drift
   - kill-switch recommendation
2. Promotion gate
   - explicit checklist from backtest -> paper -> live
   - minimum confidence thresholds
3. Regime awareness
   - detect when current market conditions differ from training/test assumptions
4. Operator UX
   - one-page control surface for status, risk, and latest signal rationale

## What Not To Do Next

- multi-exchange expansion before product wedge is proven
- adding many more indicators before strategy trust/reporting exists
- implementing live trading as the headline value proposition
- marketing it as autonomous alpha generation

## Final Diagnosis

The current project is strongest when treated as a **strategy validation and operations product**, not a generic trading bot.

## Recommendation

Reframe `crypto-trader` as:

> “Upbit KRW Strategy Lab and Operator Control Plane.”

That is the narrowest direction that:

- matches the current code
- creates room for a real product thesis
- avoids the commodity trap
- builds toward a trust-based moat instead of a feature checklist
