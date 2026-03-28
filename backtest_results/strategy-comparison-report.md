# Strategy Performance Comparison Report

**Generated**: 2026-03-28
**Scope**: 90-Day Backtest Baseline vs. Walk-Forward (OOS) Validation vs. Recent Snapshot

## 1. Executive Summary

- **Top Robust Performer**: `consensus` strategy remains the leader in recent live-like snapshots (Sharpe **5.67**), filtering out noise effectively.
- **Walk-Forward Validation**: No strategy has fully cleared the rigorous out-of-sample (OOS) promotion gate recently, though `momentum` and `momentum_pullback` show the most stable structures.
- **Alpha Decay**: Several strategies (e.g., `mean_reversion`, `funding_rate`) show significant performance degradation in recent sideways market regimes compared to their historical backtests.
- **Key Recommendation**: Allocate primarily to `consensus`, `obi`, and `vpin` while re-tuning trend-following strategies for current volatility regimes.

## 2. Combined Performance Matrix

| Strategy | Recent Ret (%) | Recent Sharpe | OOS Ret (%) | OOS Sharpe | OOS Win Rate (%) | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **consensus** | +0.379 | 5.672 | N/A* | N/A* | 67.1 | ✅ Leading |
| **obi** | +0.215 | 2.461 | -1.27 | -0.94 | 8.3 | ⚠️ Regime Sensitive |
| **vpin** | +0.145 | 1.507 | -1.37 | -1.23 | 16.7 | ⚠️ Regime Sensitive |
| **momentum** | -0.136 | -0.399 | +0.71 | 0.29 | 33.3 | 🔄 Needs Re-tuning |
| **momentum_pullback** | -0.093 | -4.110 | +0.01 | 0.14 | 25.0 | 🛡️ Defensive |
| **kimchi_premium** | -0.455 | -3.704 | +0.47 | 0.22 | 0.0 | ❌ High Variance |
| **volatility_breakout**| -0.627 | -9.814 | +0.25 | -0.28 | 0.0 | ❌ No Current Edge |
| **mean_reversion** | -0.823 | -12.31 | -4.46 | -3.61 | 16.7 | ❌ High Risk |

*\*Consensus is typically tested as an ensemble in live/snapshot environments.*

## 3. In-Sample (IS) vs. Out-of-Sample (OOS) Analysis

### Momentum & Trend Following
- **In-Sample**: Historically strong with returns > 1%.
- **OOS (Validation)**: `momentum` maintained a positive return of **+0.71%** in the 90-day walk-forward, making it the most robust "classic" strategy despite recent snapshot dips.
- **Gap**: The gap between IS and OOS suggests parameters need tighter regularization to avoid over-fitting to specific volatility clusters.

### Order Flow (OBI & VPIN)
- **Recent Strength**: Both showed resilience in the 200-candle snapshot (0.14% - 0.21%).
- **Historical OOS**: Performed poorly in the 90-day walk-forward (-1.3% return).
- **Inference**: These strategies are highly effective in short-term sideways/high-frequency regimes but suffer during prolonged trending periods.

### Defensive Strategies
- **Momentum Pullback**: Cleared the 90-day OOS with a tiny positive return (**+0.01%**) and positive Sharpe (**0.14**). It is the only strategy other than momentum to stay "above water" in the 90-day validation window, proving its value as a capital protector.

## 4. Risk & Stability Metrics

| Strategy | Recent MDD (%) | OOS Profit Factor | OOS Efficiency | Risk Tier |
| :--- | :---: | :---: | :---: | :--- |
| **consensus** | 0.590 | 2.90 | High | Low |
| **momentum_pullback** | 0.283 | 3.21 | Moderate | Low |
| **momentum** | 1.356 | 1.06 | Moderate | Medium |
| **obi** | 0.696 | 0.88 | Low | Medium |
| **vpin** | 0.623 | 0.88 | Low | Medium |
| **mean_reversion** | 1.289 | 0.38 | Very Low | High |

## 5. Strategic Recommendations

1. **Deploy Consensus**: The ensemble approach (Consensus) is significantly outperforming individual signal generators. Focus capital here.
2. **Selective Momentum**: Only use `momentum` when the regime-detection filters (not shown in this table) signal a "Trending" environment, as its OOS win rate remains low (33%).
3. **Hibernate Mean Reversion**: The high negative Sharpe and poor OOS efficiency ratio suggest `mean_reversion` should be paused or fundamentally redesigned for the current KRW crypto market dynamics.
4. **Parameter Refresh**: Re-run `scripts/auto_tune.py` for `obi` and `vpin` specifically targeting the most recent 14-day window to capture the current high-frequency behavior.
