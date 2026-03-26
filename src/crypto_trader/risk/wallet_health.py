"""Auto-disable wallets that have been losing for N consecutive days."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(slots=True)
class WalletHealthConfig:
    """Configuration for wallet health monitoring."""
    negative_days_threshold: int = 7  # Days of negative return to trigger disable
    check_interval_hours: int = 24    # How often to re-evaluate


@dataclass(slots=True)
class WalletHealthStatus:
    """Health status for a single wallet."""
    wallet_name: str
    disabled: bool = False
    disabled_reason: str = ""
    disabled_at: str = ""
    consecutive_negative_days: int = 0
    last_checked: str = ""


class WalletHealthMonitor:
    """Monitors wallet PnL history and auto-disables persistent losers.

    Reads from pnl-snapshots.jsonl to determine per-wallet daily returns.
    If a wallet has negative cumulative return over the last N days, it
    gets flagged as disabled.
    """

    def __init__(
        self,
        snapshot_path: str | Path,
        config: WalletHealthConfig | None = None,
    ) -> None:
        self._snapshot_path = Path(snapshot_path)
        self._config = config or WalletHealthConfig()
        self._logger = logging.getLogger(__name__)
        self._statuses: dict[str, WalletHealthStatus] = {}
        self._state_path = self._snapshot_path.parent / "wallet-health.json"
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted wallet health state."""
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                for entry in data.get("wallets", []):
                    status = WalletHealthStatus(
                        wallet_name=entry["wallet_name"],
                        disabled=entry.get("disabled", False),
                        disabled_reason=entry.get("disabled_reason", ""),
                        disabled_at=entry.get("disabled_at", ""),
                        consecutive_negative_days=entry.get("consecutive_negative_days", 0),
                        last_checked=entry.get("last_checked", ""),
                    )
                    self._statuses[status.wallet_name] = status
            except (json.JSONDecodeError, KeyError):
                self._logger.warning("Failed to load wallet health state, starting fresh")

    def _save_state(self) -> None:
        """Persist wallet health state to disk."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now(UTC).isoformat(),
            "wallets": [
                {
                    "wallet_name": s.wallet_name,
                    "disabled": s.disabled,
                    "disabled_reason": s.disabled_reason,
                    "disabled_at": s.disabled_at,
                    "consecutive_negative_days": s.consecutive_negative_days,
                    "last_checked": s.last_checked,
                }
                for s in self._statuses.values()
            ],
        }
        self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def evaluate(self, wallet_names: list[str] | None = None) -> dict[str, WalletHealthStatus]:
        """Check all wallets against PnL snapshot history.

        Returns dict of wallet_name -> WalletHealthStatus.
        """
        snapshots = self._load_snapshots()
        if not snapshots:
            return self._statuses

        now = datetime.now(UTC)
        threshold_days = self._config.negative_days_threshold
        cutoff = now - timedelta(days=threshold_days + 1)

        # Group snapshots by date (use the date portion of the timestamp)
        daily_returns: dict[str, dict[str, float]] = {}  # date -> {wallet -> return_pct}
        for snap in snapshots:
            ts_str = snap.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                continue

            date_key = ts.date().isoformat()
            wallets_data = snap.get("wallets", [])
            for w in wallets_data:
                wname = w.get("wallet", "")
                ret = w.get("return_pct", 0.0)
                if wname:
                    daily_returns.setdefault(date_key, {})[wname] = ret

        # Determine which wallets to check
        all_wallet_names = set()
        for day_data in daily_returns.values():
            all_wallet_names.update(day_data.keys())
        if wallet_names:
            all_wallet_names = all_wallet_names & set(wallet_names)

        for wname in all_wallet_names:
            # Get returns across available days, sorted by date
            sorted_dates = sorted(daily_returns.keys())
            wallet_returns = [
                daily_returns[d].get(wname, 0.0)
                for d in sorted_dates
                if wname in daily_returns[d]
            ]

            # Count consecutive negative days from the most recent
            consecutive_neg = 0
            for ret in reversed(wallet_returns):
                if ret < 0:
                    consecutive_neg += 1
                else:
                    break

            status = self._statuses.get(wname, WalletHealthStatus(wallet_name=wname))
            status.consecutive_negative_days = consecutive_neg
            status.last_checked = now.isoformat()

            if consecutive_neg >= threshold_days and not status.disabled:
                status.disabled = True
                status.disabled_reason = (
                    f"Negative return for {consecutive_neg} consecutive days "
                    f"(threshold: {threshold_days})"
                )
                status.disabled_at = now.isoformat()
                self._logger.warning(
                    "Auto-disabling wallet %s: %s", wname, status.disabled_reason,
                )
            elif consecutive_neg < threshold_days and status.disabled:
                # Re-enable if wallet recovers (return to positive for enough days)
                if consecutive_neg == 0:
                    status.disabled = False
                    status.disabled_reason = ""
                    status.disabled_at = ""
                    self._logger.info("Re-enabling wallet %s: returned to positive", wname)

            self._statuses[wname] = status

        self._save_state()
        return self._statuses

    def is_disabled(self, wallet_name: str) -> bool:
        """Check if a wallet is currently disabled."""
        status = self._statuses.get(wallet_name)
        return status.disabled if status else False

    def get_disabled_wallets(self) -> list[str]:
        """Return list of currently disabled wallet names."""
        return [name for name, s in self._statuses.items() if s.disabled]

    def get_status(self, wallet_name: str) -> WalletHealthStatus | None:
        """Get health status for a specific wallet."""
        return self._statuses.get(wallet_name)

    def _load_snapshots(self) -> list[dict]:
        """Load PnL snapshots from JSONL file."""
        if not self._snapshot_path.exists():
            return []
        entries = []
        for line in self._snapshot_path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries
