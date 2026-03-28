# Crypto-Trader Code Review Report - 2026-03-28

## 1. Executive Summary
The recent 10 commits significantly harden the system's safety profile and refine capital allocation efficiency. Key highlights include the enforcement of a 5% hard daily loss limit, a tiered kill switch with position reduction, and a transition to a multi-metric "enhanced score" for strategy ranking (Sharpe, Sortino, PF). Reliability has been improved through truthful macro fallback reporting and offline-safe backtesting.

## 2. Security & Safety Hardening
### 2.1 Hard Risk Limits (Commit `0f00886`)
- **Hard Max Daily Loss**: `HARD_MAX_DAILY_LOSS_PCT` is now enforced at **5%**. This acts as a global circuit breaker that cannot be overridden by strategy-level configs.
- **Consecutive Loss Auto-Stop**: The system now halts after **3 consecutive losses** (`SAFE_MAX_CONSECUTIVE_LOSSES`), preventing "loss chasing" in volatile conditions.
- **Tiered Kill Switch**:
    - **50% of limit**: Warning issued.
    - **75% of limit**: Position sizes reduced (interp. penalty).
    - **100% of limit**: Full halt and liquidation.
    - *Observation*: The linear interpolation of the penalty between 50% and 75% provides a smooth risk reduction curve.

### 2.2 Credential & Data Safety
- **Read-Only CLI** (Commit `534c0ed`): Artifact inspection commands now bypass exchange credential checks, allowing safe monitoring without exposing API keys.
- **Offline Backtesting** (Commit `59d718a`): Funding rate strategies now use local proxy history instead of network lookups, ensuring deterministic results and zero-network footprint during research.

## 3. Performance & Capital Allocation
### 3.1 Enhanced Strategy Scoring (Commit `a1ae1b9`)
- Shifted from simple Sharpe/MDD scoring to a **weighted blend**:
    - **Sharpe (40%)**
    - **Sortino (30%)** - Better capture of downside-only volatility.
    - **Profit Factor (20%)** - Direct measure of gross profit vs loss.
    - **Win Rate (10%)** - Adjusted for 0.5 baseline.
- *Improvement*: This multi-metric approach reduces the risk of over-allocating to strategies with high Sharpe but poor tail-risk profiles.

### 3.2 ROI-Driven Concentration (Commit `9bdef65`)
- Capital was dynamically moved from underperformers (e.g., `vbreak_xrp`, `mean_reversion_weekend`) to top survivors (`vpin_sol`, `momentum_sol`).
- The use of the **HHI (Herfindahl-Hirschman Index)** in the `CapitalAllocator` allows monitoring of portfolio concentration risk.

## 4. Reliability & Bug Fixes
### 4.1 Truthful Macro Fallbacks (Commit `534c0ed`)
- **Regime Integrity**: When macro feeds fail, the system now explicitly reports `unavailable` instead of reusing stale regime labels.
- **Transition Persistence**: Checkpoint restores now preserve the last *real* regime, preventing "synthetic transitions" that could trigger erroneous reallocations on restart.

### 4.2 Weekend Regime Adaptation (Commit `e29b014`)
- Weekend strategies now prioritize **mean-reversion** over the previous kimchi premium probe, better aligning with the current "Extreme Fear" and low-liquidity weekend conditions.

## 5. Recommendations
- **Concentration Alerts**: While HHI is calculated, consider adding an automated alert if the portfolio concentration ratio exceeds a specific threshold (e.g., > 0.4).
- **Sortino/PF Normalization**: The current 3.0 normalization factor in `enhanced_score` is suitable for current market conditions, but should be reviewed if strategy returns scale significantly (e.g., in a high-volatility bull run).
- **Manual Reset Protocol**: Ensure the manual reset process for the kill switch is documented, as it now requires a state file modification or a specific CLI command.

---
*Reviewer: Gemini CLI (Autonomous Mode)*
*Date: 2026-03-28*
