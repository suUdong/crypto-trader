from __future__ import annotations

import logging
from dataclasses import dataclass
from math import sqrt

from crypto_trader.models import Candle

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExposureCheck:
    allowed: bool
    reason: str
    current_exposure: int
    max_exposure: int
    blocking_symbols: tuple[str, ...] = ()


@dataclass(slots=True)
class CorrelationSnapshot:
    pairwise: dict[tuple[str, str], float]
    high_correlation_pairs: list[tuple[str, str]]
    symbol_exposure: dict[str, list[str]]
    max_correlation: float
    lookback_bars: int

    def correlation_for(self, left: str, right: str) -> float:
        if left == right:
            return 1.0
        pair = (left, right) if left < right else (right, left)
        return self.pairwise.get(pair, 0.0)

    def to_dict(self) -> dict[str, object]:
        return {
            "lookback_bars": self.lookback_bars,
            "max_correlation": self.max_correlation,
            "symbol_exposure": self.symbol_exposure,
            "high_correlation_pairs": [
                {
                    "left": left,
                    "right": right,
                    "correlation": round(self.pairwise.get((left, right), 0.0), 4),
                }
                for left, right in self.high_correlation_pairs
            ],
        }


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
        max_cluster_exposure: int = 2,
        clusters: dict[str, list[str]] | None = None,
        *,
        max_correlation: float = 0.85,
        max_high_correlation_exposure: int = 1,
    ) -> None:
        self._max_cluster_exposure = max_cluster_exposure
        self._clusters = clusters or self.DEFAULT_CLUSTERS
        self._max_correlation = max_correlation
        self._max_high_correlation_exposure = max_high_correlation_exposure
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
        *,
        correlation_snapshot: CorrelationSnapshot | None = None,
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

        if correlation_snapshot is not None:
            correlated_wallets: set[str] = set()
            blocking_symbols: list[str] = []
            for active_symbol, active_wallets in correlation_snapshot.symbol_exposure.items():
                correlation = correlation_snapshot.correlation_for(symbol, active_symbol)
                if correlation < self._max_correlation:
                    continue
                correlated_wallets.update(active_wallets)
                blocking_symbols.append(active_symbol)

            if len(correlated_wallets) >= self._max_high_correlation_exposure:
                ordered = tuple(sorted(set(blocking_symbols)))
                return ExposureCheck(
                    allowed=False,
                    reason=(
                        "high_correlation_"
                        f"{len(correlated_wallets)}/{self._max_high_correlation_exposure}"
                    ),
                    current_exposure=len(correlated_wallets),
                    max_exposure=self._max_high_correlation_exposure,
                    blocking_symbols=ordered,
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

    def get_symbol_exposure(
        self,
        wallets_with_positions: list[tuple[str, str]],
    ) -> dict[str, list[str]]:
        exposure: dict[str, list[str]] = {}
        seen: dict[str, set[str]] = {}
        for wallet_name, symbol in wallets_with_positions:
            symbol_seen = seen.setdefault(symbol, set())
            if wallet_name in symbol_seen:
                continue
            symbol_seen.add(wallet_name)
            exposure.setdefault(symbol, []).append(wallet_name)
        return exposure

    def build_snapshot(
        self,
        candles_by_symbol: dict[str, list[Candle]],
        wallets_with_positions: list[tuple[str, str]],
        *,
        lookback_bars: int = 24,
    ) -> CorrelationSnapshot:
        pairwise: dict[tuple[str, str], float] = {}
        high_pairs: list[tuple[str, str]] = []
        symbols = sorted(candles_by_symbol)
        for idx, left in enumerate(symbols):
            for right in symbols[idx + 1 :]:
                correlation = self._correlate(
                    candles_by_symbol.get(left, []),
                    candles_by_symbol.get(right, []),
                    lookback_bars,
                )
                if correlation is None:
                    continue
                pair = (left, right)
                pairwise[pair] = correlation
                if correlation >= self._max_correlation:
                    high_pairs.append(pair)
        return CorrelationSnapshot(
            pairwise=pairwise,
            high_correlation_pairs=high_pairs,
            symbol_exposure=self.get_symbol_exposure(wallets_with_positions),
            max_correlation=self._max_correlation,
            lookback_bars=lookback_bars,
        )

    def _correlate(
        self,
        left_candles: list[Candle],
        right_candles: list[Candle],
        lookback_bars: int,
    ) -> float | None:
        left_returns = self._returns(left_candles, lookback_bars)
        right_returns = self._returns(right_candles, lookback_bars)
        length = min(len(left_returns), len(right_returns))
        if length < 3:
            return None
        left = left_returns[-length:]
        right = right_returns[-length:]
        left_mean = sum(left) / length
        right_mean = sum(right) / length
        numerator = sum(
            (a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)
        )
        left_var = sum((a - left_mean) ** 2 for a in left)
        right_var = sum((b - right_mean) ** 2 for b in right)
        denominator = sqrt(left_var * right_var)
        if denominator <= 0:
            return None
        return numerator / denominator

    def _returns(self, candles: list[Candle], lookback_bars: int) -> list[float]:
        if len(candles) < 2:
            return []
        closes = [c.close for c in candles[-(lookback_bars + 1) :]]
        returns: list[float] = []
        for previous, current in zip(closes, closes[1:], strict=False):
            if previous <= 0:
                continue
            returns.append((current - previous) / previous)
        return returns
