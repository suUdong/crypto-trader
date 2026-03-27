from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.kimchi_premium import KimchiPremiumStrategy


def build_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


def _make_strategy(
    binance_price: float | None = 78.0,
    fx_rate: float | None = 1300.0,
    min_trade_interval_bars: int = 0,
    min_confidence: float = 0.0,
    cooldown_hours: float = 0.0,
    **config_overrides: object,
) -> KimchiPremiumStrategy:
    """Build a KimchiPremiumStrategy with mocked external clients."""
    defaults: dict[str, object] = dict(rsi_period=14, max_holding_bars=48)
    defaults.update(config_overrides)
    config = StrategyConfig(**defaults)  # type: ignore[arg-type]

    mock_binance = MagicMock()
    mock_binance.get_btc_usdt_price.return_value = binance_price
    mock_binance.get_usdt_price.return_value = binance_price
    mock_fx = MagicMock()
    mock_fx.get_usd_krw_rate.return_value = fx_rate

    return KimchiPremiumStrategy(
        config,
        binance_client=mock_binance,
        fx_client=mock_fx,
        min_trade_interval_bars=min_trade_interval_bars,
        min_confidence=min_confidence,
        cooldown_hours=cooldown_hours,
    )


# 30 flat candles at a given close price — enough for RSI(14) to have data
def _flat_closes(price: float, count: int = 30) -> list[float]:
    return [price] * count


class TestKimchiPremiumStrategy(unittest.TestCase):
    # ------------------------------------------------------------------
    # 1. Insufficient data -> HOLD
    # ------------------------------------------------------------------
    def test_insufficient_data_returns_hold(self) -> None:
        """Fewer candles than rsi_period + 1 → HOLD reason=insufficient_data."""
        strategy = _make_strategy(rsi_period=14)
        # rsi_period=14, minimum=15; give only 5
        candles = build_candles([100_000.0] * 5)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    # ------------------------------------------------------------------
    # 2. Contrarian BUY when premium < -2%
    # ------------------------------------------------------------------
    def test_contrarian_buy_on_negative_premium(self) -> None:
        """upbit=100000, binance=78.5, fx=1300 → global=102050, premium≈-2.01% → BUY."""
        # global_krw = 78.5 * 1300.0 = 102_050
        # premium = (100_000 - 102_050) / 102_050 ≈ -0.0201 (< -0.02)
        strategy = _make_strategy(binance_price=78.5, fx_rate=1300.0)
        candles = build_candles(_flat_closes(100_000.0))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "kimchi_premium_contrarian_buy")
        self.assertIn("kimchi_premium", signal.indicators)
        self.assertLess(signal.indicators["kimchi_premium"], -0.02)

    # ------------------------------------------------------------------
    # 3. HOLD when premium > 5% (no entry allowed)
    # ------------------------------------------------------------------
    def test_hold_when_premium_too_high(self) -> None:
        """upbit=110000, binance=78.0, fx=1300 → global=101400, premium≈+8.5% → HOLD."""
        # global_krw = 78.0 * 1300.0 = 101_400
        # premium = (110_000 - 101_400) / 101_400 ≈ +0.0848 (> 0.05)
        strategy = _make_strategy(binance_price=78.0, fx_rate=1300.0)
        candles = build_candles(_flat_closes(110_000.0))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "premium_too_high_for_entry")
        self.assertIn("kimchi_premium", signal.indicators)
        self.assertGreater(signal.indicators["kimchi_premium"], 0.05)

    # ------------------------------------------------------------------
    # 4. Safe zone BUY: 0% < premium < 5%, RSI in range
    # ------------------------------------------------------------------
    def test_safe_zone_buy_with_deep_rsi_reset(self) -> None:
        """Small premium + deeper RSI reset -> BUY safe zone."""
        closes = [
            103_500.0,
            103_200.0,
            102_900.0,
            102_600.0,
            102_300.0,
            102_000.0,
            101_800.0,
            101_700.0,
            101_650.0,
            101_600.0,
            101_550.0,
            101_500.0,
            101_450.0,
            101_420.0,
            101_390.0,
            101_410.0,
            101_430.0,
            101_460.0,
            101_500.0,
            101_550.0,
        ]
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_period=14,
            rsi_oversold_floor=20.0,
            rsi_recovery_ceiling=75.0,
        )
        candles = build_candles(closes)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "kimchi_premium_safe_zone_rsi_entry")
        premium = signal.indicators["kimchi_premium"]
        self.assertGreater(premium, 0.0)
        self.assertLess(premium, 0.003)
        self.assertLess(signal.indicators["rsi"], 40.0)

    def test_safe_zone_blocks_when_premium_is_too_high(self) -> None:
        """Safe-zone entry should stay HOLD when premium is too wide."""
        upbit_price = 103_428.0
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_period=14,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
        )
        candles = build_candles(_flat_closes(upbit_price))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "safe_zone_premium_too_high")

    def test_safe_zone_blocks_when_rsi_not_reset_enough(self) -> None:
        """Small premium alone is not enough when RSI is still too elevated."""
        closes = [
            102_500.0,
            102_200.0,
            101_900.0,
            101_700.0,
            101_500.0,
            101_300.0,
            101_200.0,
            101_100.0,
            101_000.0,
            100_950.0,
            100_900.0,
            100_850.0,
            100_900.0,
            100_980.0,
            101_050.0,
            101_120.0,
            101_200.0,
            101_280.0,
            101_360.0,
            101_520.0,
        ]
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_period=14,
            rsi_oversold_floor=20.0,
            rsi_recovery_ceiling=75.0,
        )
        signal = strategy.evaluate(build_candles(closes))
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "safe_zone_rsi_not_reset")

    def test_safe_zone_confidence_rewards_deeper_reset(self) -> None:
        """Deeper reset and stronger discount should score higher confidence."""
        stronger = [
            103_500.0,
            103_200.0,
            102_900.0,
            102_600.0,
            102_300.0,
            102_000.0,
            101_800.0,
            101_700.0,
            101_650.0,
            101_600.0,
            101_550.0,
            101_500.0,
            101_450.0,
            101_420.0,
            101_390.0,
            101_410.0,
            101_430.0,
            101_460.0,
            101_500.0,
            101_550.0,
        ]
        marginal = [
            103_500.0,
            103_200.0,
            102_900.0,
            102_600.0,
            102_300.0,
            102_000.0,
            101_800.0,
            101_650.0,
            101_540.0,
            101_480.0,
            101_430.0,
            101_390.0,
            101_360.0,
            101_330.0,
            101_300.0,
            101_320.0,
            101_340.0,
            101_380.0,
            101_500.0,
            101_640.0,
        ]
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_period=14,
            rsi_oversold_floor=20.0,
            rsi_recovery_ceiling=75.0,
        )
        stronger_signal = strategy.evaluate(build_candles(stronger))
        marginal_signal = strategy.evaluate(build_candles(marginal))
        self.assertEqual(stronger_signal.action, SignalAction.BUY)
        self.assertEqual(marginal_signal.action, SignalAction.BUY)
        self.assertGreater(stronger_signal.confidence, marginal_signal.confidence)

    # ------------------------------------------------------------------
    # 5. SELL when position open and premium >= 7%
    # ------------------------------------------------------------------
    def test_sell_on_premium_overheated(self) -> None:
        """Position open + premium >= 7% → SELL reason=kimchi_premium_overheated."""
        # global_krw = 78.0 * 1300.0 = 101_400
        # upbit = 109_000 → premium = (109_000 - 101_400) / 101_400 ≈ +0.075 (7.5%)
        upbit_price = 109_000.0
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_overbought=90.0,  # high threshold so RSI doesn't fire first
            max_holding_bars=1000,
        )
        candles = build_candles(_flat_closes(upbit_price))
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=upbit_price,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "kimchi_premium_overheated")
        self.assertGreaterEqual(signal.indicators["kimchi_premium"], 0.07)

    # ------------------------------------------------------------------
    # 6. HOLD when binance price unavailable (None)
    # ------------------------------------------------------------------
    def test_hold_when_data_unavailable(self) -> None:
        """Binance returns None -> HOLD premium_data_unavailable."""
        strategy = _make_strategy(binance_price=None, fx_rate=1300.0)
        candles = build_candles(_flat_closes(100_000.0))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "premium_data_unavailable")

    def test_hold_when_premium_is_outlier(self) -> None:
        """Extreme premium values should be treated as suspect feed data."""
        strategy = _make_strategy(binance_price=2_500.0, fx_rate=1300.0)
        candles = build_candles(_flat_closes(100_000.0))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "premium_outlier")

    # ------------------------------------------------------------------
    # 7. SELL on max_holding_bars regardless of premium
    # ------------------------------------------------------------------
    def test_sell_on_max_holding_bars(self) -> None:
        """Position entered at index 0 with max_holding_bars=2 → SELL after enough candles."""
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            max_holding_bars=2,
        )
        closes = _flat_closes(100_000.0, count=30)
        candles = build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100_000.0,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        # holding_bars = len(candles) - 0 - 1 = 29 >= 2
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")

    # ------------------------------------------------------------------
    # 8. SELL on RSI overbought with position open
    # ------------------------------------------------------------------
    def test_sell_on_rsi_overbought(self) -> None:
        """Rising prices → RSI near 100 > rsi_overbought=30 → SELL reason=rsi_overbought."""
        # Use a premium in the neutral zone (0-5%) so it doesn't fire first
        # global_krw = 78.0 * 1300.0 = 101_400; upbit ~103_428 → premium ~2%
        upbit_price = 103_428.0
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_overbought=30.0,  # very low threshold — rising prices breach it easily
            max_holding_bars=1000,
        )
        # Steadily rising prices ensure RSI is high (all gains, no losses → RSI=100)
        closes = [upbit_price + i * 100 for i in range(30)]
        candles = build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=closes[0],
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "rsi_overbought")

    # ------------------------------------------------------------------
    # 9. Cooldown blocks re-entry within cooldown_hours
    # ------------------------------------------------------------------
    def test_cooldown_blocks_reentry(self) -> None:
        """After a BUY, next evaluate within cooldown_hours → HOLD cooldown_active."""
        strategy = _make_strategy(
            binance_price=78.5,
            fx_rate=1300.0,
            min_trade_interval_bars=4,
            min_confidence=0.0,
            cooldown_hours=24.0,
        )
        # First call: contrarian buy (premium ~ -2.01%)
        candles = build_candles(_flat_closes(100_000.0, count=30))
        signal1 = strategy.evaluate(candles)
        self.assertEqual(signal1.action, SignalAction.BUY)

        # Second call 1 hour later → cooldown (within 24h)
        candles2 = build_candles(_flat_closes(100_000.0, count=31))
        signal2 = strategy.evaluate(candles2)
        self.assertEqual(signal2.action, SignalAction.HOLD)
        self.assertEqual(signal2.reason, "cooldown_active")

    # ------------------------------------------------------------------
    # 10. Cooldown resets after cooldown_hours pass
    # ------------------------------------------------------------------
    def test_cooldown_resets_after_interval(self) -> None:
        """After cooldown_hours pass, entry is allowed again."""
        strategy = _make_strategy(
            binance_price=78.5,
            fx_rate=1300.0,
            min_trade_interval_bars=4,
            min_confidence=0.0,
            cooldown_hours=2.0,  # 2 hour cooldown
        )
        # Trigger BUY at bar 29 (30 candles, each 1 hour apart)
        candles = build_candles(_flat_closes(100_000.0, count=30))
        signal1 = strategy.evaluate(candles)
        self.assertEqual(signal1.action, SignalAction.BUY)

        # 3 hours later (33 candles): cooldown expired (3h > 2h)
        candles2 = build_candles(_flat_closes(100_000.0, count=33))
        signal2 = strategy.evaluate(candles2)
        self.assertEqual(signal2.action, SignalAction.BUY)

    # ------------------------------------------------------------------
    # 10b. Timestamp cooldown works with fixed-size candle window
    # ------------------------------------------------------------------
    def test_cooldown_works_with_fixed_window(self) -> None:
        """Cooldown must work when candle count doesn't change (live trading scenario)."""
        strategy = _make_strategy(
            binance_price=78.5,
            fx_rate=1300.0,
            min_trade_interval_bars=4,
            min_confidence=0.0,
            cooldown_hours=12.0,
        )
        # First call: BUY with 200 candles
        candles = build_candles(_flat_closes(100_000.0, count=200))
        signal1 = strategy.evaluate(candles)
        self.assertEqual(signal1.action, SignalAction.BUY)

        # Same 200 candles (simulating live fixed window) → should block
        signal2 = strategy.evaluate(candles)
        self.assertEqual(signal2.action, SignalAction.HOLD)
        self.assertEqual(signal2.reason, "cooldown_active")

    # ------------------------------------------------------------------
    # 11. Confidence filter blocks low-confidence entries
    # ------------------------------------------------------------------
    def test_confidence_filter_blocks_low_confidence(self) -> None:
        """Safe-zone entry with low confidence < min_confidence → HOLD."""
        closes = [
            103_500.0,
            103_200.0,
            102_900.0,
            102_600.0,
            102_300.0,
            102_000.0,
            101_800.0,
            101_650.0,
            101_540.0,
            101_480.0,
            101_430.0,
            101_390.0,
            101_360.0,
            101_330.0,
            101_300.0,
            101_320.0,
            101_340.0,
            101_380.0,
            101_500.0,
            101_640.0,
        ]
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_period=14,
            rsi_oversold_floor=20.0,
            rsi_recovery_ceiling=75.0,
            min_confidence=0.5,
        )
        candles = build_candles(closes)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "confidence_below_threshold")

    # ------------------------------------------------------------------
    # 12. Exit signals are NOT blocked by cooldown
    # ------------------------------------------------------------------
    def test_exit_not_blocked_by_cooldown(self) -> None:
        """SELL signals must fire even during cooldown period."""
        strategy = _make_strategy(
            binance_price=78.5,
            fx_rate=1300.0,
            min_trade_interval_bars=100,  # very long cooldown
            max_holding_bars=2,
        )
        # Trigger a BUY first to set cooldown
        candles = build_candles(_flat_closes(100_000.0, count=30))
        signal1 = strategy.evaluate(candles)
        self.assertEqual(signal1.action, SignalAction.BUY)

        # Now with a position, max_holding_bars=2 should trigger SELL
        candles2 = build_candles(_flat_closes(100_000.0, count=32))
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100_000.0,
            entry_time=candles2[0].timestamp,
            entry_index=0,
        )
        signal2 = strategy.evaluate(candles2, position)
        self.assertEqual(signal2.action, SignalAction.SELL)

    # ------------------------------------------------------------------
    # 13. Verify hardcoded thresholds: -2% contrarian, 24h default cooldown
    # ------------------------------------------------------------------
    def test_contrarian_threshold_is_minus_two_percent(self) -> None:
        """Contrarian buy threshold must be exactly -0.02 (-2%)."""
        strategy = _make_strategy()
        self.assertEqual(strategy._contrarian_buy_threshold, -0.02)

    def test_default_cooldown_is_24_hours(self) -> None:
        """Default cooldown_hours must be 24.0."""
        config = StrategyConfig(rsi_period=14, max_holding_bars=48)
        strategy = KimchiPremiumStrategy(config)
        self.assertEqual(strategy._cooldown_hours, 24.0)

    # ------------------------------------------------------------------
    # 14. Boundary: premium exactly at -2% triggers contrarian buy
    # ------------------------------------------------------------------
    def test_contrarian_buy_at_exact_boundary(self) -> None:
        """Premium exactly -2.0% must trigger contrarian buy."""
        # global_krw = binance * fx; premium = (upbit - global) / global = -0.02
        # upbit = global * 0.98 = binance * fx * 0.98
        binance = 100.0
        fx = 1000.0
        global_krw = binance * fx  # 100_000
        upbit = global_krw * 0.98  # 98_000 → premium = -0.02 exactly
        strategy = _make_strategy(binance_price=binance, fx_rate=fx)
        candles = build_candles(_flat_closes(upbit))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "kimchi_premium_contrarian_buy")

    # ------------------------------------------------------------------
    # 15. Cooldown 24h: entry blocked at 23h, allowed at 25h
    # ------------------------------------------------------------------
    def test_cooldown_24h_boundary(self) -> None:
        """24h cooldown: blocked at 23h mark, allowed at 25h mark."""
        strategy = _make_strategy(
            binance_price=78.5,
            fx_rate=1300.0,
            cooldown_hours=24.0,
        )
        # First BUY at bar 29 (t=29h from start)
        candles = build_candles(_flat_closes(100_000.0, count=30))
        signal1 = strategy.evaluate(candles)
        self.assertEqual(signal1.action, SignalAction.BUY)

        # 23h later → still in cooldown (30+23=53 candles)
        candles_23h = build_candles(_flat_closes(100_000.0, count=53))
        signal2 = strategy.evaluate(candles_23h)
        self.assertEqual(signal2.action, SignalAction.HOLD)
        self.assertEqual(signal2.reason, "cooldown_active")

        # 25h later → cooldown expired (30+25=55 candles)
        candles_25h = build_candles(_flat_closes(100_000.0, count=55))
        signal3 = strategy.evaluate(candles_25h)
        self.assertEqual(signal3.action, SignalAction.BUY)


if __name__ == "__main__":
    unittest.main()
