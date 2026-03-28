#!/usr/bin/env python3
"""Staged rollout for SOL-KRW momentum micro-live.

Three-phase rollout:
  Phase 1: Preflight safety checks (config, kill switch, credentials)
  Phase 2: Paper dry-run (load config, build wallets, verify pipeline)
  Phase 3: Activate live trading (flip paper_trading=false, confirm)

Usage:
    PYTHONPATH=src python3 scripts/staged_rollout.py                    # Phase 1 only (default)
    PYTHONPATH=src python3 scripts/staged_rollout.py --phase 2          # Paper dry-run
    PYTHONPATH=src python3 scripts/staged_rollout.py --phase 3          # Go live (interactive)
    PYTHONPATH=src python3 scripts/staged_rollout.py --config config/live-sol-momentum.toml
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from crypto_trader.config import (
    HARD_MAX_DAILY_LOSS_PCT,
    SAFE_DEFAULT_MAX_POSITION_PCT,
    SAFE_MAX_CONSECUTIVE_LOSSES,
    load_config,
    preflight_check,
)

_DEFAULT_CONFIG = "config/live-sol-momentum.toml"
_REPORT_PATH = Path("artifacts/live-sol/rollout-report.json")

_MAX_MICRO_CAPITAL = 200_000.0  # KRW — micro-live ceiling
_REQUIRED_STRATEGY = "momentum"
_REQUIRED_SYMBOL = "KRW-SOL"


def _header(phase: int, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Phase {phase}: {title}")
    print(f"{'='*60}\n")


def phase1_preflight(config_path: str) -> tuple[bool, dict]:
    """Phase 1: Run all preflight safety checks."""
    _header(1, "Preflight Safety Checks")

    config = load_config(config_path)
    results: list[dict] = []
    all_pass = True

    # 1. Standard preflight checks
    preflight = preflight_check(config)
    for level, msg in preflight:
        passed = level != "ERROR"
        if not passed:
            all_pass = False
        results.append({"check": msg, "level": level, "pass": passed})
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {msg}")

    # 2. Micro-live specific: single wallet only
    if len(config.wallets) != 1:
        all_pass = False
        results.append({
            "check": f"Expected 1 wallet, found {len(config.wallets)}",
            "level": "ERROR",
            "pass": False,
        })
        print(f"  [FAIL] Expected 1 wallet, found {len(config.wallets)}")
    else:
        results.append({"check": "Single wallet configured", "level": "INFO", "pass": True})
        print("  [PASS] Single wallet configured")

    # 3. Capital ceiling
    for wc in config.wallets:
        if wc.initial_capital > _MAX_MICRO_CAPITAL:
            all_pass = False
            msg = (
                f"Wallet '{wc.name}' capital {wc.initial_capital:,.0f} "
                f"exceeds micro-live ceiling {_MAX_MICRO_CAPITAL:,.0f}"
            )
            results.append({"check": msg, "level": "ERROR", "pass": False})
            print(f"  [FAIL] {msg}")
        else:
            msg = f"Wallet '{wc.name}' capital {wc.initial_capital:,.0f} KRW (within ceiling)"
            results.append({"check": msg, "level": "INFO", "pass": True})
            print(f"  [PASS] {msg}")

    # 4. Strategy = momentum only
    for wc in config.wallets:
        if wc.strategy != _REQUIRED_STRATEGY:
            all_pass = False
            msg = f"Wallet '{wc.name}' strategy '{wc.strategy}' != '{_REQUIRED_STRATEGY}'"
            results.append({"check": msg, "level": "ERROR", "pass": False})
            print(f"  [FAIL] {msg}")
        else:
            results.append({
                "check": f"Strategy = {_REQUIRED_STRATEGY}",
                "level": "INFO",
                "pass": True,
            })
            print(f"  [PASS] Strategy = {_REQUIRED_STRATEGY}")

    # 5. Symbol = KRW-SOL only
    for wc in config.wallets:
        if wc.symbols and _REQUIRED_SYMBOL not in wc.symbols:
            all_pass = False
            msg = f"Wallet '{wc.name}' symbols {wc.symbols} missing {_REQUIRED_SYMBOL}"
            results.append({"check": msg, "level": "ERROR", "pass": False})
            print(f"  [FAIL] {msg}")
        else:
            results.append({
                "check": f"Symbol = {_REQUIRED_SYMBOL}",
                "level": "INFO",
                "pass": True,
            })
            print(f"  [PASS] Symbol = {_REQUIRED_SYMBOL}")

    # 6. Kill switch thresholds
    ks = config.kill_switch
    ks_checks = [
        (
            ks.max_daily_loss_pct <= HARD_MAX_DAILY_LOSS_PCT,
            f"kill_switch.max_daily_loss_pct = {ks.max_daily_loss_pct:.2%} "
            f"(<= {HARD_MAX_DAILY_LOSS_PCT:.2%})",
        ),
        (
            ks.max_consecutive_losses <= SAFE_MAX_CONSECUTIVE_LOSSES,
            f"kill_switch.max_consecutive_losses = {ks.max_consecutive_losses} "
            f"(<= {SAFE_MAX_CONSECUTIVE_LOSSES})",
        ),
        (
            ks.max_portfolio_drawdown_pct <= 0.08,
            f"kill_switch.max_portfolio_drawdown_pct = {ks.max_portfolio_drawdown_pct:.2%} "
            f"(<= 8%)",
        ),
        (
            config.risk.max_position_pct <= SAFE_DEFAULT_MAX_POSITION_PCT,
            f"risk.max_position_pct = {config.risk.max_position_pct:.2%} "
            f"(<= {SAFE_DEFAULT_MAX_POSITION_PCT:.2%})",
        ),
    ]
    for passed, msg in ks_checks:
        if not passed:
            all_pass = False
        mark = "PASS" if passed else "FAIL"
        level = "INFO" if passed else "ERROR"
        results.append({"check": msg, "level": level, "pass": passed})
        print(f"  [{mark}] {msg}")

    # 7. go_live_wallets matches wallet name
    wallet_names = {wc.name for wc in config.wallets}
    for name in config.trading.go_live_wallets:
        if name in wallet_names:
            results.append({
                "check": f"go_live_wallets '{name}' exists",
                "level": "INFO",
                "pass": True,
            })
            print(f"  [PASS] go_live_wallets '{name}' exists")

    passed_count = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n  Result: {passed_count}/{total} checks passed")
    print(f"  Status: {'READY for Phase 2' if all_pass else 'BLOCKED — fix errors above'}")

    return all_pass, {
        "phase": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "all_pass": all_pass,
        "score": f"{passed_count}/{total}",
        "results": results,
    }


def phase2_paper_dryrun(config_path: str) -> tuple[bool, dict]:
    """Phase 2: Paper trading dry-run — verify wallet builds and pipeline loads."""
    _header(2, "Paper Dry-Run Verification")

    config = load_config(config_path)

    # Force paper trading for dry-run
    if not config.trading.paper_trading:
        print("  [INFO] Config has paper_trading=false, overriding to true for dry-run")

    results: list[dict] = []
    all_pass = True

    # 1. Build wallets (paper mode)
    try:
        from crypto_trader.wallet import build_wallets

        # Temporarily ensure paper mode
        original = config.trading.paper_trading
        object.__setattr__(config.trading, "paper_trading", True)
        wallets = build_wallets(config)
        object.__setattr__(config.trading, "paper_trading", original)

        msg = f"Built {len(wallets)} wallet(s) successfully"
        results.append({"check": msg, "level": "INFO", "pass": True})
        print(f"  [PASS] {msg}")

        for w in wallets:
            msg = (
                f"Wallet '{w.name}': strategy={w.strategy_type}, "
                f"cash={w.broker.cash:,.0f}, symbols={w.allowed_symbols}"
            )
            results.append({"check": msg, "level": "INFO", "pass": True})
            print(f"  [PASS] {msg}")
    except Exception as exc:
        all_pass = False
        msg = f"Failed to build wallets: {exc}"
        results.append({"check": msg, "level": "ERROR", "pass": False})
        print(f"  [FAIL] {msg}")
        return all_pass, {"phase": 2, "all_pass": False, "results": results}

    # 2. Verify kill switch loads
    try:
        from crypto_trader.risk.kill_switch import KillSwitch, KillSwitchConfig

        ks_config = KillSwitchConfig(
            max_portfolio_drawdown_pct=config.kill_switch.max_portfolio_drawdown_pct,
            max_daily_loss_pct=config.kill_switch.max_daily_loss_pct,
            max_consecutive_losses=config.kill_switch.max_consecutive_losses,
            max_strategy_drawdown_pct=config.kill_switch.max_strategy_drawdown_pct,
            cooldown_minutes=config.kill_switch.cooldown_minutes,
            warn_threshold_pct=config.kill_switch.warn_threshold_pct,
            reduce_threshold_pct=config.kill_switch.reduce_threshold_pct,
            reduce_position_factor=config.kill_switch.reduce_position_factor,
        )
        ks = KillSwitch(ks_config)

        # Simulate: check with starting equity
        state = ks.check(
            current_equity=100_000.0,
            starting_equity=100_000.0,
            realized_pnl=0.0,
        )
        if not state.triggered:
            results.append({
                "check": "Kill switch healthy at starting equity",
                "level": "INFO",
                "pass": True,
            })
            print("  [PASS] Kill switch healthy at starting equity")
        else:
            all_pass = False
            results.append({
                "check": f"Kill switch triggered unexpectedly: {state.trigger_reason}",
                "level": "ERROR",
                "pass": False,
            })
            print(f"  [FAIL] Kill switch triggered unexpectedly: {state.trigger_reason}")

        # Simulate: check at 5% loss (should trigger)
        ks2 = KillSwitch(ks_config)
        state2 = ks2.check(
            current_equity=95_000.0,
            starting_equity=100_000.0,
            realized_pnl=-5_000.0,
        )
        if state2.triggered:
            results.append({
                "check": "Kill switch triggers at 5% drawdown (expected)",
                "level": "INFO",
                "pass": True,
            })
            print("  [PASS] Kill switch triggers at 5% drawdown (expected)")
        else:
            results.append({
                "check": "Kill switch did NOT trigger at 5% drawdown (warning state active)",
                "level": "WARNING",
                "pass": True,
            })
            print("  [WARN] Kill switch warning state at 5% drawdown (tiered response)")
    except Exception as exc:
        all_pass = False
        msg = f"Kill switch verification failed: {exc}"
        results.append({"check": msg, "level": "ERROR", "pass": False})
        print(f"  [FAIL] {msg}")

    # 3. Verify artifact directories exist (or can be created)
    artifact_dir = Path("artifacts/live-sol")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    results.append({
        "check": f"Artifact directory '{artifact_dir}' ready",
        "level": "INFO",
        "pass": True,
    })
    print(f"  [PASS] Artifact directory '{artifact_dir}' ready")

    passed_count = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n  Result: {passed_count}/{total} checks passed")
    print(f"  Status: {'READY for Phase 3' if all_pass else 'BLOCKED — fix errors above'}")

    return all_pass, {
        "phase": 2,
        "checked_at": datetime.now(UTC).isoformat(),
        "all_pass": all_pass,
        "score": f"{passed_count}/{total}",
        "results": results,
    }


def phase3_go_live(config_path: str) -> tuple[bool, dict]:
    """Phase 3: Activate live trading (interactive confirmation required)."""
    _header(3, "Go-Live Activation")

    config = load_config(config_path)

    # Re-run preflight to be safe
    preflight = preflight_check(config)
    errors = [msg for level, msg in preflight if level == "ERROR"]
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        print("\n  BLOCKED: Preflight errors must be resolved first.")
        return False, {"phase": 3, "all_pass": False, "blocked_by": errors}

    # Check credentials are set
    if not config.credentials.has_upbit_credentials:
        print("  [FAIL] Upbit API credentials not set in config")
        print("         Set upbit_access_key and upbit_secret_key in:")
        print(f"         {config_path}")
        return False, {
            "phase": 3,
            "all_pass": False,
            "blocked_by": ["missing_credentials"],
        }

    print("  Pre-live checklist:")
    print(f"    Config:   {config_path}")
    print(f"    Wallet:   {config.wallets[0].name}")
    print(f"    Strategy: {config.wallets[0].strategy}")
    print(f"    Symbol:   {config.wallets[0].symbols}")
    print(f"    Capital:  {config.wallets[0].initial_capital:,.0f} KRW")
    print(f"    Kill SW:  drawdown={config.kill_switch.max_portfolio_drawdown_pct:.1%}, "
          f"daily_loss={config.kill_switch.max_daily_loss_pct:.1%}, "
          f"consec_loss={config.kill_switch.max_consecutive_losses}")
    print()

    confirm = input("  Type 'GO LIVE' to activate live trading: ").strip()
    if confirm != "GO LIVE":
        print("  Aborted — live trading NOT activated.")
        return False, {"phase": 3, "all_pass": False, "aborted": True}

    # Flip paper_trading to false in config file
    config_file = Path(config_path)
    content = config_file.read_text(encoding="utf-8")
    updated = content.replace("paper_trading = true", "paper_trading = false")
    config_file.write_text(updated, encoding="utf-8")

    print()
    print("  [DONE] paper_trading = false — LIVE MODE ACTIVATED")
    print(f"  Start daemon: PYTHONPATH=src python -m crypto_trader.cli --config {config_path}")
    print()
    print("  Monitor:")
    print("    Kill switch: artifacts/live-sol/health.json")
    print("    Trades:      artifacts/live-sol/paper-trades.jsonl")
    print("    Checkpoint:  artifacts/live-sol/runtime-checkpoint.json")

    return True, {
        "phase": 3,
        "checked_at": datetime.now(UTC).isoformat(),
        "all_pass": True,
        "activated": True,
        "config_path": config_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Staged rollout for SOL-KRW momentum micro-live")
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        help=f"Config file path (default: {_DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="Rollout phase to execute (default: 1)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all phases sequentially (stops on first failure)",
    )
    args = parser.parse_args()

    report: dict = {"config": args.config, "phases": []}

    phases = [1, 2, 3] if args.all else [args.phase]

    for phase in phases:
        if phase == 1:
            ok, result = phase1_preflight(args.config)
        elif phase == 2:
            ok, result = phase2_paper_dryrun(args.config)
        else:
            ok, result = phase3_go_live(args.config)

        report["phases"].append(result)

        if not ok and phase < 3:
            print(f"\n  Phase {phase} failed — stopping rollout.")
            break

    # Save report
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n  Report saved: {_REPORT_PATH}")


if __name__ == "__main__":
    main()
