from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExposureCheck:
    allowed: bool
    reason: str
    current_exposure: int
    max_exposure: int


class CorrelationGuard:
    """Prevents over-exposure to correlated assets in multi-wallet portfolio.

    Groups crypto assets into correlation clusters. Limits how many
    wallets can have open positions in the same cluster simultaneously.
    """

    # Default correlation clusters - assets that move together
    DEFAULT_CLUSTERS: dict[str, list[str]] = {
        "major_crypto": ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP"],
    }

    def __init__(
        self,
        max_cluster_exposure: int = 6,
        clusters: dict[str, list[str]] | None = None,
    ) -> None:
        self._max_cluster_exposure = max_cluster_exposure
        self._clusters = clusters or self.DEFAULT_CLUSTERS
        # Reverse map: symbol -> cluster name
        self._symbol_to_cluster: dict[str, str] = {}
        for cluster_name, symbols in self._clusters.items():
            for sym in symbols:
                self._symbol_to_cluster[sym] = cluster_name

    def check_entry(
        self,
        symbol: str,
        wallet_name: str,
        open_positions: dict[str, list[str]],
    ) -> ExposureCheck:
        """Check if a new entry in symbol is allowed given current exposure.

        Args:
            symbol: The symbol to enter (e.g. "KRW-BTC")
            wallet_name: The wallet requesting entry
            open_positions: Map of cluster_name -> list of wallet names with open positions

        Returns:
            ExposureCheck with allowed flag and reason
        """
        cluster = self._symbol_to_cluster.get(symbol)
        if cluster is None:
            return ExposureCheck(
                allowed=True,
                reason="symbol_not_in_cluster",
                current_exposure=0,
                max_exposure=self._max_cluster_exposure,
            )

        current = len(open_positions.get(cluster, []))

        if current >= self._max_cluster_exposure:
            return ExposureCheck(
                allowed=False,
                reason=f"cluster_{cluster}_exposure_{current}/{self._max_cluster_exposure}",
                current_exposure=current,
                max_exposure=self._max_cluster_exposure,
            )

        return ExposureCheck(
            allowed=True,
            reason="within_limits",
            current_exposure=current,
            max_exposure=self._max_cluster_exposure,
        )

    def get_cluster_exposure(
        self,
        wallets_with_positions: list[tuple[str, str]],
    ) -> dict[str, list[str]]:
        """Build cluster exposure map from current wallet positions.

        Args:
            wallets_with_positions: List of (wallet_name, symbol) tuples for open positions

        Returns:
            Map of cluster_name -> list of wallet names
        """
        exposure: dict[str, list[str]] = {}
        seen: dict[str, set[str]] = {}
        for wallet_name, symbol in wallets_with_positions:
            cluster = self._symbol_to_cluster.get(symbol)
            if cluster is not None:
                cluster_seen = seen.setdefault(cluster, set())
                if wallet_name not in cluster_seen:
                    cluster_seen.add(wallet_name)
                    exposure.setdefault(cluster, []).append(wallet_name)
        return exposure
