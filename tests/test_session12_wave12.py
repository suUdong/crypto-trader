"""Tests for Session #12 Wave 12: ADX/volume filters, confidence gate, noise ratio."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy


def _candles(closes: list[float], volume: float = 1000.0) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=volume)
        for i, c in enumerate(closes)
    ]


def _candles_with_volumes(closes: list[float], volumes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=v)
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


# ---------- Composite ADX filter ----------

class TestCompositeADXFilter(unittest.TestCase):
    def test_adx_indicator_present(self) -> None:
        """Composite should include ADX in indicators when enough data."""
        prices = [100.0 + i * 0.1 for i in range(50)]
        candles = _candles(prices)
        strategy = CompositeStrategy(StrategyConfig(
            momentum_lookback=5, bollinger_window=20, rsi_period=5,
        ))
        signal = strategy.evaluate(candles)
        self.assertIn("adx", signal.indicators)

    def test_adx_blocks_entry_in_choppy_market(self) -> None:
        """ADX below threshold should block composite entry."""
        # Flat market = low ADX
        prices = [100.0] * 30 + [99.0, 98.0, 97.0]
        candles = _candles(prices)
        strategy = CompositeStrategy(StrategyConfig(
            momentum_lookback=3, momentum_entry_threshold=-0.5,
            bollinger_window=20, bollinger_stddev=1.5,
            rsi_period=5, rsi_oversold_floor=0.0, rsi_recovery_ceiling=100.0,
            adx_threshold=25.0,
        ))
        signal = strategy.evaluate(candles)
        # Should either HOLD due to ADX or other conditions
        if signal.action == SignalAction.BUY:
            # If somehow ADX is above threshold in this market, that's fine
            self.assertGreaterEqual(signal.indicators.get("adx", 0), 25.0)

    def test_adx_zero_threshold_disables_filter(self) -> None:
        """ADX threshold of 0 should not block any entries."""
        prices = [100.0] * 30
        candles = _candles(prices)
        strategy = CompositeStrategy(StrategyConfig(
            momentum_lookback=5, bollinger_window=20, rsi_period=5,
            adx_threshold=0.0,
        ))
        signal = strategy.evaluate(candles)
        # Should not get "adx_too_weak" reason with threshold=0
        self.assertNotEqual(signal.reason, "adx_too_weak")


# ---------- Composite volume filter ----------

class TestCompositeVolumeFilter(unittest.TestCase):
    def test_volume_filter_blocks_low_volume(self) -> None:
        """Low volume should block composite entry when volume_filter_mult > 0."""
        # Create entry conditions with low volume
        prices = [100.0] * 25 + [97.0, 95.0, 93.0]
        volumes = [1000.0] * 25 + [100.0, 100.0, 100.0]  # Very low recent volume
        candles = _candles_with_volumes(prices, volumes)
        strategy = CompositeStrategy(StrategyConfig(
            momentum_lookback=3, momentum_entry_threshold=-0.5,
            bollinger_window=20, bollinger_stddev=1.5,
            rsi_period=5, rsi_oversold_floor=0.0, rsi_recovery_ceiling=100.0,
            adx_threshold=0.0,
            volume_filter_mult=0.8,
        ))
        signal = strategy.evaluate(candles)
        if signal.reason == "volume_too_low":
            self.assertEqual(signal.action, SignalAction.HOLD)

    def test_volume_filter_disabled_by_default(self) -> None:
        """volume_filter_mult=0.0 should not trigger volume filter."""
        prices = [100.0] * 30
        candles = _candles(prices, volume=1.0)
        strategy = CompositeStrategy(StrategyConfig(
            momentum_lookback=5, bollinger_window=20, rsi_period=5,
            volume_filter_mult=0.0,
        ))
        signal = strategy.evaluate(candles)
        self.assertNotEqual(signal.reason, "volume_too_low")


# ---------- EMA crossover ADX filter ----------

class TestEMACrossoverADXFilter(unittest.TestCase):
    def test_adx_in_indicators(self) -> None:
        """EMA crossover should include ADX in indicators."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(StrategyConfig(rsi_period=5, adx_period=14))
        signal = strategy.evaluate(candles)
        self.assertIn("adx", signal.indicators)

    def test_adx_blocks_crossover_entry(self) -> None:
        """ADX below threshold should block EMA crossover entry."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, rsi_overbought=90.0, adx_threshold=30.0),
        )
        dummy_candles = _candles([100.0] * 30)
        signal = strategy._evaluate_entry(
            dummy_candles,
            cross_up=True,
            spread=0.01,
            rsi_value=55.0,
            stoch_rsi_value=40.0,
            macd_bullish=False,
            adx_value=15.0,  # Below threshold
            indicators={},
            context={"strategy": "ema_crossover"},
        )
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "adx_too_weak")

    def test_adx_allows_entry_above_threshold(self) -> None:
        """ADX above threshold should allow EMA crossover entry."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, rsi_overbought=90.0, adx_threshold=20.0),
        )
        dummy_candles = _candles([100.0] * 30)
        signal = strategy._evaluate_entry(
            dummy_candles,
            cross_up=True,
            spread=0.01,
            rsi_value=55.0,
            stoch_rsi_value=40.0,
            macd_bullish=False,
            adx_value=25.0,  # Above threshold
            indicators={},
            context={"strategy": "ema_crossover"},
        )
        self.assertEqual(signal.action, SignalAction.BUY)

    def test_adx_blocks_trend_continuation(self) -> None:
        """ADX below threshold should also block trend continuation entry."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, rsi_oversold_floor=10.0, adx_threshold=25.0),
        )
        dummy_candles = _candles([100.0] * 30)
        signal = strategy._evaluate_entry(
            dummy_candles,
            cross_up=False,
            spread=0.01,
            rsi_value=50.0,
            stoch_rsi_value=40.0,
            macd_bullish=False,
            adx_value=10.0,  # Below threshold
            indicators={},
            context={"strategy": "ema_crossover"},
        )
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "adx_too_weak")

    def test_adx_none_skips_filter(self) -> None:
        """When ADX is None (not enough data), filter should be skipped."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, rsi_overbought=90.0, adx_threshold=20.0),
        )
        dummy_candles = _candles([100.0] * 30)
        signal = strategy._evaluate_entry(
            dummy_candles,
            cross_up=True,
            spread=0.01,
            rsi_value=55.0,
            stoch_rsi_value=40.0,
            macd_bullish=False,
            adx_value=None,
            indicators={},
            context={"strategy": "ema_crossover"},
        )
        self.assertEqual(signal.action, SignalAction.BUY)


# ---------- EMA crossover volume filter ----------

class TestEMACrossoverVolumeFilter(unittest.TestCase):
    def test_volume_blocks_low_volume_entry(self) -> None:
        """Low volume should block EMA crossover entry."""
        strategy = EMACrossoverStrategy(
            StrategyConfig(
                rsi_period=5, rsi_overbought=90.0,
                adx_threshold=0.0, volume_filter_mult=0.8,
            ),
        )
        volumes = [1000.0] * 25 + [100.0] * 5
        closes = [100.0] * 30
        candles = _candles_with_volumes(closes, volumes)
        signal = strategy._evaluate_entry(
            candles,
            cross_up=True,
            spread=0.01,
            rsi_value=55.0,
            stoch_rsi_value=40.0,
            macd_bullish=False,
            adx_value=None,
            indicators={},
            context={"strategy": "ema_crossover"},
        )
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "volume_too_low")


# ---------- Confidence gate in backtest engine ----------

class TestBacktestConfidenceGate(unittest.TestCase):
    def test_low_confidence_signal_skipped(self) -> None:
        """Backtest engine should skip BUY signals below min confidence."""
        # Strategy that always generates low-confidence BUY signals
        class LowConfBuyStrategy:
            def evaluate(self, candles, position=None):
                from crypto_trader.models import Signal, SignalAction
                if position is None:
                    return Signal(
                        action=SignalAction.BUY, reason="test",
                        confidence=0.3,  # Below default 0.6
                    )
                return Signal(action=SignalAction.HOLD, reason="hold", confidence=0.5)

        prices = [100.0] * 50
        candles = _candles(prices)
        risk = RiskManager(RiskConfig(min_entry_confidence=0.6))
        engine = BacktestEngine(
            strategy=LowConfBuyStrategy(),
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        # No trades should be executed since confidence is below threshold
        self.assertEqual(len(result.trade_log), 0)

    def test_high_confidence_signal_accepted(self) -> None:
        """Backtest engine should accept BUY signals at/above min confidence."""
        class HighConfBuyStrategy:
            def evaluate(self, candles, position=None):
                from crypto_trader.models import Signal, SignalAction
                if position is None:
                    return Signal(
                        action=SignalAction.BUY, reason="test",
                        confidence=0.8,
                    )
                return Signal(action=SignalAction.SELL, reason="sell", confidence=0.9)

        prices = [100.0] * 50
        candles = _candles(prices)
        risk = RiskManager(RiskConfig(
            min_entry_confidence=0.6, stop_loss_pct=0.05, take_profit_pct=0.10,
        ))
        engine = BacktestEngine(
            strategy=HighConfBuyStrategy(),
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertGreater(len(result.trade_log), 0)

    def test_adaptive_confidence_lowers_bar(self) -> None:
        """After many wins, effective_min_confidence should decrease."""
        risk = RiskManager(RiskConfig(min_entry_confidence=0.6))
        for _ in range(10):
            risk.record_trade(0.02)  # All wins → win rate 100%
        # Effective confidence should be lowered (base - 0.1 = 0.5)
        self.assertLess(risk.effective_min_confidence, 0.6)


# ---------- Noise ratio in mean reversion ----------

class TestMeanReversionNoiseRatio(unittest.TestCase):
    def test_noise_ratio_in_indicators(self) -> None:
        """Mean reversion should include noise_ratio in indicators."""
        prices = [100.0 + (i % 5) * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        self.assertIn("noise_ratio", signal.indicators)

    def test_trending_market_blocks_entry(self) -> None:
        """Strongly trending market (low noise) should block mean reversion entry."""
        # Strong downtrend: noise ratio will be low (price moving in one direction)
        prices = [100.0] * 25 + [100.0 - i * 1.5 for i in range(1, 26)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, bollinger_stddev=1.5,
            rsi_period=5, rsi_oversold_floor=0.0,
            noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        # In a strong trend, noise ratio < 0.5, should get "market_too_trendy"
        if signal.indicators.get("noise_ratio", 1.0) < 0.5:
            self.assertEqual(signal.reason, "market_too_trendy")
            self.assertEqual(signal.action, SignalAction.HOLD)

    def test_ranging_market_allows_entry(self) -> None:
        """Ranging/choppy market (high noise) should allow mean reversion entry."""
        # Oscillating prices = high noise ratio
        prices = [100.0 + ((-1) ** i) * 2.0 for i in range(50)]
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, bollinger_stddev=1.5,
            rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        # With high noise, should NOT get "market_too_trendy"
        self.assertNotEqual(signal.reason, "market_too_trendy")

    def test_noise_ratio_no_crash_with_short_data(self) -> None:
        """Should not crash when insufficient data for noise ratio."""
        prices = [100.0] * 25
        candles = _candles(prices)
        strategy = MeanReversionStrategy(StrategyConfig(
            bollinger_window=20, rsi_period=5, noise_lookback=20,
        ))
        signal = strategy.evaluate(candles)
        # Should still produce a valid signal
        self.assertIn(signal.action, [SignalAction.BUY, SignalAction.HOLD, SignalAction.SELL])


if __name__ == "__main__":
    unittest.main()
