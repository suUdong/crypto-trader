# 90-Day Strategy Comparison Report

Date: 2026-03-28

## Scope

- Window: latest **90 days** of hourly Upbit candles
- Symbols: `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`
- Strategies: 13 tested
- Total results: 52

## Strategy Ranking (by avg Sharpe ratio)

| Rank | Strategy | Avg Sharpe | Avg Sortino | Avg Calmar | Avg MDD% | Avg Return% | Avg WinRate% | Total Trades |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | momentum | 0.98 | 1.66 | 2.96 | 0.34 | +0.16 | 51.0 | 54 |
| 2 | composite | 0.92 | 4.29 | 8.75 | 0.07 | +0.02 | 50.0 | 4 |
| 3 | vpin | 0.65 | 0.92 | 1.52 | 0.67 | +0.24 | 55.5 | 68 |
| 4 | consensus | 0.39 | 0.78 | 1.66 | 0.47 | +0.08 | 53.9 | 55 |
| 5 | funding_rate | -0.10 | 0.12 | 1.65 | 0.51 | +0.03 | 39.3 | 29 |
| 6 | kimchi_premium | -0.26 | -0.27 | -0.03 | 0.59 | -0.12 | 53.1 | 34 |
| 7 | ema_crossover | -0.60 | -0.73 | -0.49 | 0.76 | -0.23 | 47.9 | 28 |
| 8 | obi | -0.94 | -1.16 | -1.09 | 0.54 | -0.18 | 47.9 | 47 |
| 9 | volatility_breakout | -0.98 | -0.69 | -0.47 | 0.36 | +0.04 | 34.8 | 55 |
| 10 | momentum_pullback | -1.13 | -1.49 | -1.89 | 0.60 | -0.27 | 41.7 | 36 |
| 11 | volume_spike | -1.45 | -1.94 | -2.66 | 0.44 | -0.28 | 31.9 | 23 |
| 12 | mean_reversion | -2.18 | -2.53 | -2.83 | 0.57 | -0.41 | 30.6 | 22 |
| 13 | bollinger_rsi | -2.30 | -2.72 | -2.51 | 0.98 | -0.58 | 50.0 | 41 |

## Per-Strategy Detail

### `momentum`

- Avg Sharpe: **0.98**
- Avg Sortino: 1.66
- Avg Calmar: 2.96
- Avg MDD: 0.34%
- Avg MDD Duration: 1996 bars
- Avg Return: +0.16%
- Avg Profit Factor: 2.65
- Total Trades: 54

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.02 | 0.34 | -0.12 | -0.18 | 50.0 | 20 | 0.96 |
| KRW-ETH | +0.08 | 0.11 | 0.83 | 1.41 | 33.3 | 9 | 1.49 |
| KRW-XRP | +0.18 | 0.69 | 0.60 | 0.87 | 57.1 | 14 | 1.22 |
| KRW-SOL | +0.41 | 0.21 | 2.60 | 4.54 | 63.6 | 11 | 6.92 |

### `composite`

- Avg Sharpe: **0.92**
- Avg Sortino: 4.29
- Avg Calmar: 8.75
- Avg MDD: 0.07%
- Avg MDD Duration: 607 bars
- Avg Return: +0.02%
- Avg Profit Factor: inf
- Total Trades: 4

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | +0.07 | 0.01 | 2.43 | 14.51 | 100.0 | 1 | inf |
| KRW-ETH | -0.04 | 0.24 | -0.24 | -0.35 | 0.0 | 2 | 0.00 |
| KRW-XRP | +0.04 | 0.03 | 1.48 | 3.00 | 100.0 | 1 | inf |
| KRW-SOL | +0.00 | 0.00 | 0.00 | 0.00 | 0.0 | 0 | 0.00 |

### `vpin`

- Avg Sharpe: **0.65**
- Avg Sortino: 0.92
- Avg Calmar: 1.52
- Avg MDD: 0.67%
- Avg MDD Duration: 1886 bars
- Avg Return: +0.24%
- Avg Profit Factor: 1.31
- Total Trades: 68

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | +0.16 | 0.35 | 0.61 | 0.89 | 60.0 | 15 | 1.32 |
| KRW-ETH | +0.10 | 0.60 | 0.38 | 0.53 | 47.1 | 17 | 1.17 |
| KRW-XRP | +0.14 | 0.92 | 0.46 | 0.65 | 55.6 | 9 | 1.18 |
| KRW-SOL | +0.58 | 0.81 | 1.14 | 1.61 | 59.3 | 27 | 1.55 |

### `consensus`

- Avg Sharpe: **0.39**
- Avg Sortino: 0.78
- Avg Calmar: 1.66
- Avg MDD: 0.47%
- Avg MDD Duration: 1885 bars
- Avg Return: +0.08%
- Avg Profit Factor: 1.39
- Total Trades: 55

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.11 | 0.28 | -0.93 | -1.38 | 50.0 | 8 | 0.57 |
| KRW-ETH | +0.51 | 0.24 | 2.74 | 4.82 | 60.0 | 10 | 3.10 |
| KRW-XRP | -0.06 | 0.74 | -0.20 | -0.28 | 50.0 | 10 | 0.90 |
| KRW-SOL | -0.02 | 0.62 | -0.03 | -0.04 | 55.6 | 27 | 0.99 |

### `funding_rate`

- Avg Sharpe: **-0.10**
- Avg Sortino: 0.12
- Avg Calmar: 1.65
- Avg MDD: 0.51%
- Avg MDD Duration: 1955 bars
- Avg Return: +0.03%
- Avg Profit Factor: 1.32
- Total Trades: 29

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.01 | 0.26 | -0.03 | -0.05 | 40.0 | 5 | 0.97 |
| KRW-ETH | +0.09 | 0.40 | 0.34 | 0.50 | 40.0 | 5 | 1.41 |
| KRW-XRP | -0.84 | 0.98 | -3.24 | -3.77 | 20.0 | 5 | 0.08 |
| KRW-SOL | +0.90 | 0.39 | 2.54 | 3.81 | 57.1 | 14 | 2.82 |

### `kimchi_premium`

- Avg Sharpe: **-0.26**
- Avg Sortino: -0.27
- Avg Calmar: -0.03
- Avg MDD: 0.59%
- Avg MDD Duration: 1905 bars
- Avg Return: -0.12%
- Avg Profit Factor: 1.48
- Total Trades: 34

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.13 | 0.46 | -0.65 | -0.87 | 50.0 | 8 | 0.70 |
| KRW-ETH | -0.37 | 0.79 | -0.96 | -1.34 | 50.0 | 8 | 0.52 |
| KRW-XRP | -0.40 | 0.77 | -0.95 | -1.23 | 50.0 | 10 | 0.57 |
| KRW-SOL | +0.43 | 0.34 | 1.53 | 2.35 | 62.5 | 8 | 4.13 |

### `ema_crossover`

- Avg Sharpe: **-0.60**
- Avg Sortino: -0.73
- Avg Calmar: -0.49
- Avg MDD: 0.76%
- Avg MDD Duration: 1392 bars
- Avg Return: -0.23%
- Avg Profit Factor: 0.81
- Total Trades: 28

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | +0.22 | 0.28 | 1.20 | 1.93 | 60.0 | 5 | 1.81 |
| KRW-ETH | -0.74 | 1.09 | -2.27 | -2.98 | 33.3 | 6 | 0.19 |
| KRW-XRP | -0.05 | 1.03 | -0.12 | -0.17 | 58.3 | 12 | 0.96 |
| KRW-SOL | -0.35 | 0.64 | -1.22 | -1.69 | 40.0 | 5 | 0.30 |

### `obi`

- Avg Sharpe: **-0.94**
- Avg Sortino: -1.16
- Avg Calmar: -1.09
- Avg MDD: 0.54%
- Avg MDD Duration: 1992 bars
- Avg Return: -0.18%
- Avg Profit Factor: 0.76
- Total Trades: 47

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.17 | 0.29 | -1.55 | -2.06 | 50.0 | 10 | 0.56 |
| KRW-ETH | +0.09 | 0.44 | 0.51 | 0.80 | 44.4 | 9 | 1.22 |
| KRW-XRP | -0.62 | 0.95 | -2.67 | -3.26 | 44.4 | 9 | 0.29 |
| KRW-SOL | -0.02 | 0.48 | -0.07 | -0.10 | 52.6 | 19 | 0.97 |

### `volatility_breakout`

- Avg Sharpe: **-0.98**
- Avg Sortino: -0.69
- Avg Calmar: -0.47
- Avg MDD: 0.36%
- Avg MDD Duration: 1984 bars
- Avg Return: +0.04%
- Avg Profit Factor: 0.77
- Total Trades: 55

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.17 | 0.17 | -4.05 | -4.16 | 0.0 | 3 | 0.00 |
| KRW-ETH | -0.16 | 0.23 | -1.17 | -1.82 | 40.0 | 10 | 0.44 |
| KRW-XRP | +0.74 | 0.44 | 2.20 | 4.45 | 52.0 | 25 | 1.93 |
| KRW-SOL | -0.26 | 0.60 | -0.90 | -1.24 | 47.1 | 17 | 0.72 |

### `momentum_pullback`

- Avg Sharpe: **-1.13**
- Avg Sortino: -1.49
- Avg Calmar: -1.89
- Avg MDD: 0.60%
- Avg MDD Duration: 1922 bars
- Avg Return: -0.27%
- Avg Profit Factor: 0.54
- Total Trades: 36

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.39 | 0.45 | -1.86 | -2.51 | 40.0 | 10 | 0.35 |
| KRW-ETH | -0.10 | 0.41 | -0.64 | -0.85 | 40.0 | 5 | 0.75 |
| KRW-XRP | -0.18 | 0.57 | -0.83 | -1.04 | 33.3 | 6 | 0.45 |
| KRW-SOL | -0.43 | 0.97 | -1.18 | -1.57 | 53.3 | 15 | 0.62 |

### `volume_spike`

- Avg Sharpe: **-1.45**
- Avg Sortino: -1.94
- Avg Calmar: -2.66
- Avg MDD: 0.44%
- Avg MDD Duration: 1602 bars
- Avg Return: -0.28%
- Avg Profit Factor: 0.36
- Total Trades: 23

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.15 | 0.23 | -0.98 | -1.43 | 25.0 | 4 | 0.19 |
| KRW-ETH | -0.29 | 0.64 | -1.02 | -1.47 | 44.4 | 9 | 0.58 |
| KRW-XRP | -0.23 | 0.32 | -2.14 | -2.85 | 25.0 | 4 | 0.28 |
| KRW-SOL | -0.45 | 0.56 | -1.64 | -2.01 | 33.3 | 6 | 0.37 |

### `mean_reversion`

- Avg Sharpe: **-2.18**
- Avg Sortino: -2.53
- Avg Calmar: -2.83
- Avg MDD: 0.57%
- Avg MDD Duration: 1819 bars
- Avg Return: -0.41%
- Avg Profit Factor: 0.29
- Total Trades: 22

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.12 | 0.49 | -0.77 | -1.09 | 37.5 | 8 | 0.77 |
| KRW-ETH | -0.57 | 0.68 | -3.35 | -3.85 | 25.0 | 4 | 0.16 |
| KRW-XRP | -0.41 | 0.52 | -2.00 | -2.57 | 40.0 | 5 | 0.16 |
| KRW-SOL | -0.55 | 0.60 | -2.59 | -2.62 | 20.0 | 5 | 0.06 |

### `bollinger_rsi`

- Avg Sharpe: **-2.30**
- Avg Sortino: -2.72
- Avg Calmar: -2.51
- Avg MDD: 0.98%
- Avg MDD Duration: 1864 bars
- Avg Return: -0.58%
- Avg Profit Factor: 0.41
- Total Trades: 41

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | -0.36 | 0.63 | -1.70 | -2.18 | 63.6 | 11 | 0.47 |
| KRW-ETH | -1.04 | 1.15 | -4.41 | -4.99 | 42.9 | 7 | 0.20 |
| KRW-XRP | -0.68 | 0.84 | -2.46 | -2.88 | 25.0 | 4 | 0.14 |
| KRW-SOL | -0.24 | 1.29 | -0.64 | -0.84 | 68.4 | 19 | 0.85 |

