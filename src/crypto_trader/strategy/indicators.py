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
