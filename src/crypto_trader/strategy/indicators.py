from __future__ import annotations

import math


def simple_moving_average(values: list[float], window: int) -> float:
    if len(values) < window:
        raise ValueError("Not enough values for moving average")
    subset = values[-window:]
    return sum(subset) / window


def standard_deviation(values: list[float], window: int) -> float:
    if len(values) < window:
        raise ValueError("Not enough values for standard deviation")
    subset = values[-window:]
    mean = sum(subset) / window
    variance = sum((value - mean) ** 2 for value in subset) / window
    return math.sqrt(variance)


def bollinger_bands(
    values: list[float],
    window: int,
    stddev_multiplier: float,
) -> tuple[float, float, float]:
    middle = simple_moving_average(values, window)
    deviation = standard_deviation(values, window) * stddev_multiplier
    return middle + deviation, middle, middle - deviation


def momentum(values: list[float], lookback: int) -> float:
    if len(values) <= lookback:
        raise ValueError("Not enough values for momentum")
    previous = values[-lookback - 1]
    if previous == 0:
        raise ValueError("Previous price cannot be zero")
    return (values[-1] / previous) - 1.0


def rsi(values: list[float], period: int) -> float:
    if len(values) <= period:
        raise ValueError("Not enough values for RSI")
    gains = 0.0
    losses = 0.0
    for index in range(len(values) - period, len(values)):
        delta = values[index] - values[index - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta

    if losses == 0:
        return 100.0
    average_gain = gains / period
    average_loss = losses / period
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def true_range(high: float, low: float, prev_close: float) -> float:
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def average_true_range(highs: list[float], lows: list[float], closes: list[float], period: int) -> float:
    """Average True Range over the given period."""
    if len(closes) <= period:
        raise ValueError("Not enough values for ATR")
    tr_values = []
    for i in range(-period, 0):
        tr_values.append(true_range(highs[i], lows[i], closes[i - 1]))
    return sum(tr_values) / period


def noise_ratio(closes: list[float], lookback: int) -> float:
    """Noise ratio: 1 - |net_move| / sum(|bar_moves|). Lower = stronger trend."""
    if len(closes) <= lookback:
        raise ValueError("Not enough values for noise_ratio")
    net_move = abs(closes[-1] - closes[-lookback - 1])
    gross_move = sum(abs(closes[i] - closes[i - 1]) for i in range(len(closes) - lookback, len(closes)))
    if gross_move == 0:
        return 1.0
    return 1.0 - (net_move / gross_move)
