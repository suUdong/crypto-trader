"""
Alpha Watchlist → daemon.toml 반영 스크립트

artifacts/alpha-watchlist.json의 상위 종목을 읽어서
accumulation 지갑의 symbols를 업데이트합니다.
daemon 재시작 전에 수동으로 실행하거나, 자동화하세요.
"""
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from crypto_trader.operator.wallet_config_text import list_wallet_names_by_strategy  # noqa: E402
from scripts import wallet_auto_updater as wau  # noqa: E402

WATCHLIST_PATH = _PROJECT_ROOT / "artifacts" / "alpha-watchlist.json"
DAEMON_CONFIG = _PROJECT_ROOT / "config" / "daemon.toml"


def load_watchlist() -> tuple[list[str], int, str | None]:
    from crypto_trader.alpha_watchlist import extract_rotation_candidates
    from crypto_trader.strategy.alpha_calibrator import load_calibration

    if not WATCHLIST_PATH.exists():
        print(f"ERROR: {WATCHLIST_PATH} not found. Run the lab loop first.")
        sys.exit(1)
    with WATCHLIST_PATH.open() as f:
        data = json.load(f)
    calibration = load_calibration()
    threshold = calibration.threshold if calibration.is_usable else 1.0
    candidates, rotation_source = extract_rotation_candidates(data, threshold=threshold)
    symbols = [row["symbol"] for row in candidates]
    updated_at = data.get("updated_at", "unknown")
    print(f"Watchlist loaded ({updated_at}, source={rotation_source or 'legacy'}): {symbols}")
    return symbols, data.get("cycle", 0), rotation_source


def _load_active_accum_wallets(lines: list[str]) -> list[str]:
    return list_wallet_names_by_strategy(lines, "accumulation_breakout")


def apply_alpha_to_daemon(
    symbols: list[str],
    cycle: int,
    *,
    rotation_source: str | None = None,
) -> None:
    lines = DAEMON_CONFIG.read_text(encoding="utf-8").splitlines()
    target_wallets = _load_active_accum_wallets(lines)
    if not target_wallets:
        print("ERROR: no active accumulation_breakout wallets found in daemon config.")
        sys.exit(1)

    if len(symbols) < len(target_wallets):
        print(
            "ERROR: insufficient approved symbols for active accumulation wallets. "
            f"need={len(target_wallets)} got={len(symbols)}"
        )
        sys.exit(1)

    assignments = list(zip(target_wallets, symbols, strict=False))
    trigger = f"manual_alpha_apply / cycle={cycle} / source={rotation_source or 'legacy'}"
    old_daemon_config = wau.DAEMON_CONFIG
    try:
        wau.DAEMON_CONFIG = DAEMON_CONFIG
        changed = wau.apply_symbol_rotation(assignments, trigger=trigger, restart=False)
    finally:
        wau.DAEMON_CONFIG = old_daemon_config
    if not changed:
        print("\nℹ️ daemon.toml unchanged")
        return
    print(f"\n✅ daemon.toml updated via wallet_auto_updater (Cycle {cycle})")
    print("\n⚠️  daemon 재시작이 필요합니다: scripts/restart_daemon.sh")


def main() -> None:
    print("=" * 60)
    print("  Alpha Watchlist → daemon.toml Applicator")
    print("=" * 60)

    symbols, cycle, rotation_source = load_watchlist()
    if not symbols:
        print(
            "ERROR: approved accumulation rotation candidates are empty. "
            f"source={rotation_source or 'legacy'}"
        )
        sys.exit(1)
    apply_alpha_to_daemon(symbols, cycle, rotation_source=rotation_source)


if __name__ == "__main__":
    main()
