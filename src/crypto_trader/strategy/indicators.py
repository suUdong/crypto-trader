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


def bollinger_band_width(
    values: list[float], window: int, stddev_multiplier: float,
) -> float:
    """Bollinger Band Width: (upper - lower) / middle.

    Low width indicates a squeeze (low volatility), often preceding a breakout.
    """
    upper, middle, lower = bollinger_bands(values, window, stddev_multiplier)
    if middle == 0:
        return 0.0
    return (upper - lower) / middle


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


def stochastic_rsi(
    values: list[float],
    rsi_period: int = 14,
    stoch_period: int = 14,
) -> float:
    """Normalize recent RSI readings into a 0-100 oscillator."""
    min_len = rsi_period + stoch_period + 1
    if len(values) < min_len:
        raise ValueError(
            f"Need at least {min_len} values for Stochastic RSI, got {len(values)}"
        )

    rsi_values: list[float] = []
    for i in range(stoch_period + 1):
        idx = len(values) - stoch_period + i
        if idx > rsi_period:
            rsi_values.append(rsi(values[:idx], rsi_period))
        else:
            rsi_values.append(50.0)

    rsi_min = min(rsi_values)
    rsi_max = max(rsi_values)
    rsi_range = rsi_max - rsi_min
    if rsi_range == 0:
        return 50.0
    return ((rsi_values[-1] - rsi_min) / rsi_range) * 100.0


def true_range(high: float, low: float, prev_close: float) -> float:
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def average_true_range(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int,
) -> float:
    """Average True Range over the given period."""
    if len(closes) <= period:
        raise ValueError("Not enough values for ATR")
    tr_values = []
    for i in range(-period, 0):
        tr_values.append(true_range(highs[i], lows[i], closes[i - 1]))
    return sum(tr_values) / period


def average_directional_index(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14,
) -> float:
    """Average Directional Index (ADX) — measures trend strength (0-100).

    ADX < 20: weak/no trend (choppy market)
    ADX 20-40: developing trend
    ADX > 40: strong trend
    """
    n = len(closes)
    if n < period + 2 or len(highs) < n or len(lows) < n:
        raise ValueError("Not enough values for ADX")

    # Compute +DM, -DM, TR series
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr_list: list[float] = []

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        tr_list.append(true_range(highs[i], lows[i], closes[i - 1]))

    if len(tr_list) < period:
        raise ValueError("Not enough values for ADX")

    # Wilder smoothing for first period
    smoothed_plus_dm = sum(plus_dm[:period])
    smoothed_minus_dm = sum(minus_dm[:period])
    smoothed_tr = sum(tr_list[:period])

    dx_values: list[float] = []

    for i in range(period, len(tr_list)):
        smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dm[i]
        smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dm[i]
        smoothed_tr = smoothed_tr - (smoothed_tr / period) + tr_list[i]

        if smoothed_tr == 0:
            dx_values.append(0.0)
            continue

        plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
        minus_di = 100.0 * smoothed_minus_dm / smoothed_tr
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_values.append(0.0)
        else:
            dx_values.append(100.0 * abs(plus_di - minus_di) / di_sum)

    if len(dx_values) < period:
        # Not enough DX values for full ADX smoothing, return average of what we have
        return sum(dx_values) / len(dx_values) if dx_values else 0.0

    # ADX = Wilder-smoothed DX
    adx = sum(dx_values[:period]) / period
    for i in range(period, len(dx_values)):
        adx = (adx * (period - 1) + dx_values[i]) / period

    return adx


def volume_sma(volumes: list[float], window: int) -> float:
    """Simple moving average of volume over the last `window` bars."""
    if len(volumes) < window:
        raise ValueError("Not enough values for volume SMA")
    return sum(volumes[-window:]) / window


def rolling_correlation(series_a: list[float], series_b: list[float], window: int) -> float:
    """Pearson correlation of two price series over the last `window` bars."""
    if len(series_a) < window or len(series_b) < window:
        raise ValueError("Not enough values for correlation")
    a = series_a[-window:]
    b = series_b[-window:]
    mean_a = sum(a) / window
    mean_b = sum(b) / window
    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(window)) / window
    std_a = math.sqrt(sum((x - mean_a) ** 2 for x in a) / window)
    std_b = math.sqrt(sum((x - mean_b) ** 2 for x in b) / window)
    if std_a == 0 or std_b == 0:
        return 0.0
    return cov / (std_a * std_b)


def _ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average. Returns list same length as input (NaN-free)."""
    if not values or period <= 0:
        return []
    alpha = 2.0 / (period + 1)
    result = [values[0]]
    for i in range(1, len(values)):
        result.append(alpha * values[i] + (1.0 - alpha) * result[-1])
    return result


def macd(
    closes: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[float, float, float]:
    """MACD indicator: (macd_line, signal_line, histogram).

    macd_line = EMA(fast) - EMA(slow)
    signal_line = EMA(macd_line, signal_period)
    histogram = macd_line - signal_line

    Raises ValueError if not enough data (need at least slow_period + signal_period).
    """
    min_len = slow_period + signal_period
    if len(closes) < min_len:
        raise ValueError(f"Need at least {min_len} values for MACD, got {len(closes)}")
    ema_fast = _ema(closes, fast_period)
    ema_slow = _ema(closes, slow_period)
    macd_line_series = [f - s for f, s in zip(ema_fast, ema_slow, strict=True)]
    signal_series = _ema(macd_line_series, signal_period)
    ml = macd_line_series[-1]
    sl = signal_series[-1]
    return ml, sl, ml - sl


def rsi_divergence(
    closes: list[float], rsi_period: int = 14, lookback: int = 20,
) -> tuple[bool, bool]:
    """Detect RSI divergence over the last `lookback` bars.

    Returns (bullish_divergence, bearish_divergence).
    - Bullish: price makes lower low but RSI makes higher low
    - Bearish: price makes higher high but RSI makes lower high
    """
    min_len = rsi_period + lookback + 1
    if len(closes) < min_len:
        return False, False

    # Compute RSI for the lookback window
    rsi_values = []
    for i in range(lookback + 1):
        idx = len(closes) - lookback + i
        if idx > rsi_period:
            rsi_values.append(rsi(closes[:idx], rsi_period))
        else:
            rsi_values.append(50.0)

    price_window = closes[-lookback - 1:]

    # Find local lows and highs (simple: compare with neighbors)
    price_lows: list[tuple[int, float]] = []
    price_highs: list[tuple[int, float]] = []
    rsi_at: list[float] = rsi_values

    for i in range(1, len(price_window) - 1):
        if price_window[i] <= price_window[i - 1] and price_window[i] <= price_window[i + 1]:
            price_lows.append((i, price_window[i]))
        if price_window[i] >= price_window[i - 1] and price_window[i] >= price_window[i + 1]:
            price_highs.append((i, price_window[i]))

    bullish = False
    bearish = False

    # Bullish divergence: last two lows — price lower, RSI higher
    if len(price_lows) >= 2:
        prev_low = price_lows[-2]
        curr_low = price_lows[-1]
        if curr_low[1] < prev_low[1] and rsi_at[curr_low[0]] > rsi_at[prev_low[0]]:
            bullish = True

    # Bearish divergence: last two highs — price higher, RSI lower
    if len(price_highs) >= 2:
        prev_high = price_highs[-2]
        curr_high = price_highs[-1]
        if curr_high[1] > prev_high[1] and rsi_at[curr_high[0]] < rsi_at[prev_high[0]]:
            bearish = True

    return bullish, bearish


def noise_ratio(closes: list[float], lookback: int) -> float:
    """Noise ratio: 1 - |net_move| / sum(|bar_moves|). Lower = stronger trend."""
    if len(closes) <= lookback:
        raise ValueError("Not enough values for noise_ratio")
    net_move = abs(closes[-1] - closes[-lookback - 1])
    gross_move = sum(
        abs(closes[i] - closes[i - 1])
        for i in range(len(closes) - lookback, len(closes))
    )
    if gross_move == 0:
        return 1.0
    return 1.0 - (net_move / gross_move)
