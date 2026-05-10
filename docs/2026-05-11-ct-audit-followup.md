# CT Paper Audit Follow-up — P1 Backlog

**Source**: `research/reports/fire-w11-ct-paper-audit.md` (Gemini, 2026-05-11, 480 trades)
**Status of recommendations**:

| # | Recommendation | Status | Notes |
|---|---|---|---|
| 1 | Disable MANA, BAT wallets | ✅ DONE (pre-session) | `bc09959` already disabled vpin_mana, vpin_bat, vpin_orbs, stealth_3gate_1 |
| 2 | Time-of-day blackout (UTC 23-02) | ✅ DONE (`6db77e9`) | Implemented as `RiskConfig.entry_blackout_utc_hours = (23, 0, 1, 2)`. Audit said "KST" but data is in UTC; verified directly on `artifacts/paper-trades.jsonl` |
| 3 | Volatility buffering (raise ATR multiplier 15-20%) | ⏭️ SKIP (already mitigated) | `atr_stop_multiplier = 0.0` globally since `5916050`. The 148 `atr_stop_loss` losses in the audit are historical, pre-disable. Re-enabling would reverse the fix that flipped paper PnL positive |
| 4 | Symbol-level circuit breaker (3 losses / 48h auto-disable) | 🔜 P1 BACKLOG | Architectural change: requires per-symbol rolling-window loss tracking in RiskManager or StrategyWallet plus persistent state across daemon restarts |
| 5 | Confidence floor `< 0.2` | ⏭️ ALREADY COVERED | `daemon.toml [risk] min_entry_confidence = 0.30` is already stricter than 0.20. The 5 sub-0.2 trades in the dataset have `entry_confidence = 0.0` (March pre-confidence-logging) |
| 6 | Regime-adjusted sizing (smaller positions in late-bull) | 🔜 P1 BACKLOG | Architectural change: requires bull-late detection in macro adapter + multiplier wiring in capital_allocator |

## Items 4 & 6 — Implementation Notes

### Item 4: Symbol circuit breaker
Required components:
- `RiskManager` (or new `SymbolHealth` service): rolling 48h losses per symbol.
- Persistence: append to `artifacts/symbol-health.jsonl` so 48h state survives daemon restarts (current restart cadence is hours-to-days).
- Auto-disable: when symbol crosses 3 losses inside 48h, treat the wallet's `allowed_symbols` as if the symbol were excluded for the cool-off period.
- Recovery: auto-re-enable after `cooldown_hours` (default 48h after the 3rd loss).
- Tests: window-boundary, multi-symbol independence, persistence across restart.

### Item 6: Regime-adjusted sizing
The macro adapter already has multiplier logic (`MacroRegimeAdapter`). The audit insight is that `bull` regimes paradoxically have larger average losses, suggesting late-bull = top-buy risk.
Required components:
- A "late-bull" sub-regime detection (e.g. RSI > 70 on BTC daily + 30-bar drawdown ≥ 0 + macro `expansionary`).
- A multiplier reduction in `macro_position_size_multiplier` (e.g. 0.5x) when late-bull is detected.
- Wire into `capital_allocator` so wallet sizing scales down.
- Tests: synthetic candles producing late-bull / not-late-bull, verify multiplier difference.

## Validation Plan for the Next Snapshot

Targets after `6db77e9` + prior disables/sizing:
- `portfolio_sharpe` ≥ **-0.20** (current -0.37)
- `portfolio_mdd_pct` ≤ **3.0%** (current 1.65%)
- `portfolio_return_pct` trending toward positive
- New trades at UTC 23-02 should be **zero** — verify by grepping latest `paper-trades.jsonl` after 24h
- `vpin_ondo_wallet`, `vpin_sol_wallet`, `vpin_pundix_wallet` should not appear in new trades

Cadence: re-run `scripts/analyze_paper_losses.py` after ~30 new closed trades (~48h at current paper rate) and re-rank surviving wallets. If any wallet still net-negative with n ≥ 20, disable.
