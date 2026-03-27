import math
import unittest

from crypto_trader.strategy.indicators import (
    bollinger_bands,
    momentum,
    rsi,
    simple_moving_average,
    standard_deviation,
)


class TestSimpleMovingAverage(unittest.TestCase):
    def test_basic_calculation(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = simple_moving_average(values, 3)
        self.assertAlmostEqual(result, 4.0)

    def test_uses_last_window_values(self):
        values = [100.0, 1.0, 2.0, 3.0]
        result = simple_moving_average(values, 3)
        self.assertAlmostEqual(result, 2.0)

    def test_window_equals_length(self):
        values = [10.0, 20.0, 30.0]
        result = simple_moving_average(values, 3)
        self.assertAlmostEqual(result, 20.0)

    def test_insufficient_data_raises(self):
        with self.assertRaises(ValueError):
            simple_moving_average([1.0, 2.0], 5)


class TestStandardDeviation(unittest.TestCase):
    def test_basic_calculation(self):
        # population stddev of [2, 4, 4, 4, 5, 5, 7, 9] window=4 -> last 4: [5,5,7,9]
        # mean=6.5, variance=((5-6.5)^2+(5-6.5)^2+(7-6.5)^2+(9-6.5)^2)/4
        # = (2.25+2.25+0.25+6.25)/4 = 11/4 = 2.75, stddev=sqrt(2.75)
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        result = standard_deviation(values, 4)
        self.assertAlmostEqual(result, math.sqrt(2.75))

    def test_identical_values_gives_zero(self):
        values = [5.0, 5.0, 5.0]
        result = standard_deviation(values, 3)
        self.assertAlmostEqual(result, 0.0)

    def test_insufficient_data_raises(self):
        with self.assertRaises(ValueError):
            standard_deviation([1.0], 3)


class TestBollingerBands(unittest.TestCase):
    def test_returns_three_tuple(self):
        values = [10.0, 11.0, 12.0, 11.0, 10.0]
        result = bollinger_bands(values, 3, 2.0)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_band_order_upper_middle_lower(self):
        values = [10.0, 11.0, 12.0, 11.0, 10.0]
        upper, middle, lower = bollinger_bands(values, 3, 2.0)
        self.assertGreater(upper, middle)
        self.assertGreater(middle, lower)

    def test_middle_equals_sma(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        upper, middle, lower = bollinger_bands(values, 3, 2.0)
        expected_middle = simple_moving_average(values, 3)
        self.assertAlmostEqual(middle, expected_middle)

    def test_symmetric_bands(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        upper, middle, lower = bollinger_bands(values, 3, 2.0)
        self.assertAlmostEqual(upper - middle, middle - lower)

    def test_zero_multiplier_collapses_bands(self):
        values = [1.0, 2.0, 3.0]
        upper, middle, lower = bollinger_bands(values, 3, 0.0)
        self.assertAlmostEqual(upper, middle)
        self.assertAlmostEqual(lower, middle)


class TestMomentum(unittest.TestCase):
    def test_positive_momentum(self):
        # values[-1]=110, values[-2]=100 -> (110/100)-1 = 0.1
        values = [100.0, 110.0]
        result = momentum(values, 1)
        self.assertAlmostEqual(result, 0.1)

    def test_negative_momentum(self):
        # values[-1]=90, values[-2]=100 -> (90/100)-1 = -0.1
        values = [100.0, 90.0]
        result = momentum(values, 1)
        self.assertAlmostEqual(result, -0.1)

    def test_lookback_longer_than_one(self):
        # lookback=2: values[-1]=120, values[-lookback-1]=values[-3]=105
        # -> (120/105)-1
        values = [100.0, 105.0, 110.0, 120.0]
        result = momentum(values, 2)
        self.assertAlmostEqual(result, (120.0 / 105.0) - 1.0)

    def test_insufficient_data_raises(self):
        with self.assertRaises(ValueError):
            momentum([100.0], 1)

    def test_zero_previous_price_raises(self):
        with self.assertRaises(ValueError):
            momentum([0.0, 100.0], 1)


class TestRsi(unittest.TestCase):
    def test_all_gains_returns_100(self):
        # strictly increasing prices -> no losses -> RSI = 100.0
        values = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
        result = rsi(values, 5)
        self.assertAlmostEqual(result, 100.0)

    def test_result_in_valid_range(self):
        values = [
            44.34,
            44.09,
            44.15,
            43.61,
            44.33,
            44.83,
            45.10,
            45.15,
            43.61,
            44.33,
            44.83,
            45.10,
            45.15,
            43.61,
        ]
        result = rsi(values, 13)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 100.0)

    def test_basic_rsi_calculation(self):
        # 5 prices: [100, 102, 101, 103, 102]
        # deltas over period=4: +2, -1, +2, -1
        # gains=4, losses=2, avg_gain=1.0, avg_loss=0.5
        # RS=2.0, RSI=100-(100/3)=66.666...
        values = [100.0, 102.0, 101.0, 103.0, 102.0]
        result = rsi(values, 4)
        self.assertAlmostEqual(result, 100.0 - (100.0 / 3.0), places=5)

    def test_insufficient_data_raises(self):
        with self.assertRaises(ValueError):
            rsi([1.0, 2.0, 3.0], 3)


if __name__ == "__main__":
    unittest.main()
