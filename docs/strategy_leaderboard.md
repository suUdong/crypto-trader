# Strategy Leaderboard

자동 생성 — `scripts/strategy_tournament.py`  
Sharpe 기준 정렬. 매 실행마다 누적 기록.

---

## 전략 목록

| 전략 | 타입 | 설명 |
|---|---|---|
| `momentum` | engine | 가격 모멘텀 |
| `momentum_pullback` | engine | 모멘텀 + 눌림목 |
| `volume_spike` | engine | 거래량 급등 |
| `vpin` | engine | VPIN 지표 |
| `bollinger_rsi` | engine | 볼린저 + RSI |
| `ema_crossover` | engine | EMA 크로스오버 |
| `volatility_breakout` | engine | 변동성 돌파 |
| `mean_reversion` | engine | 평균 회귀 |
| `consensus` | engine | 멀티 전략 합의 |
| `stealth_3gate` | custom | BTC>SMA20 + BTC stealth + Alt RS/Acc 3단계 (검증됨) |
| `volume_breakout` | custom | 볼륨 2배 + 가격 상승 |
| `rsi_oversold` | custom | RSI<30 반등 |
| `btc_bull_momentum` | custom | BTC 불장 + 알트 5봉 상승 |
| `dip_in_uptrend` | custom | 상승 추세 눌림목 |
| `accumulation_only` | custom | 강한 acc > 1.5 신호 |
| `low_rs_high_acc` | custom | RS < 1.0 + acc > 1.2 (pre-breakout) |

---

*아직 tournament 실행 결과 없음. `python scripts/strategy_tournament.py --quick` 으로 첫 실행.*

## 2026-04-02 03:09 UTC  `quick`  5 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `accumulation_only` | +1.174 | 69.6% | +9.50% | 3.3% | 36 | 5 |
| 🥈 | `volume_breakout` | +1.098 | 65.8% | +5.78% | 2.2% | 32 | 5 |
| 🥉 | `btc_bull_momentum` | +1.098 | 59.1% | +7.77% | 5.6% | 44 | 4 |
| 4. | `stealth_3gate` | +0.301 | 62.5% | +0.67% | 3.2% | 11 | 4 |
| 5. | `low_rs_high_acc` | +0.249 | 61.2% | +1.77% | 3.2% | 24 | 4 |
| 6. | `rsi_oversold` | -411982719.215 | 37.5% | -0.33% | 0.8% | 11 | 4 |
| 7. | `dip_in_uptrend` | -682602785.811 | 36.7% | -2.44% | 0.8% | 10 | 5 |

## 2026-04-02 03:16 UTC  `quick`  5 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `dip_in_uptrend` | -0.309 | 52.9% | -1.51% | 5.6% | 17 | 1 |
| 🥈 | `volume_breakout` | -0.621 | 40.0% | -1.88% | 3.4% | 10 | 1 |
| 🥉 | `accumulation_only` | -1.498 | 29.2% | -11.21% | 14.8% | 24 | 1 |
| 4. | `rsi_oversold` | -2.385 | 40.0% | -3.06% | 1.7% | 5 | 1 |

## 2026-04-02 03:17 UTC  `quick`  5 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `dip_in_uptrend` | +1.489 | 60.0% | +2.50% | 0.4% | 5 | 1 |
| 🥈 | `volume_breakout` | +0.785 | 40.0% | +1.39% | 0.2% | 5 | 1 |
| 🥉 | `low_rs_high_acc` | -0.431 | 51.0% | -1.27% | 3.2% | 28 | 4 |
| 4. | `accumulation_only` | -0.684 | 39.4% | -2.60% | 5.1% | 45 | 5 |
| 5. | `btc_bull_momentum` | -1.350 | 32.4% | -3.90% | 3.8% | 49 | 4 |

## 2026-04-02 03:18 UTC  `quick`  5 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `accumulation_only` | +1.174 | 69.6% | +9.50% | 3.3% | 36 | 5 |
| 🥈 | `volume_breakout` | +1.098 | 65.8% | +5.78% | 2.2% | 32 | 5 |
| 🥉 | `btc_bull_momentum` | +1.098 | 59.1% | +7.77% | 5.6% | 44 | 4 |
| 4. | `low_rs_high_acc` | +0.249 | 61.2% | +1.77% | 3.2% | 24 | 4 |

## 2026-04-02 03:44 UTC  `GPU quick`  49 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `rsi_oversold` | +2.039 | 50.9% | +344.46% | 80.2% | 523 | 42 |
| 🥈 | `stealth_3gate` | +1.243 | 59.0% | +45.70% | 24.9% | 39 | 31 |
| 🥉 | `low_rs_high_acc` | +1.085 | 49.9% | +80.87% | 88.1% | 447 | 48 |
| 4. | `volatility_squeeze` | +0.823 | 49.2% | +32.67% | 29.1% | 65 | 38 |
| 5. | `accumulation_only` | -2.647 | 45.3% | -98.58% | 98.8% | 643 | 49 |
| 6. | `ema_cross_bull` | -5.212 | 24.1% | -83.18% | 82.9% | 83 | 41 |
| 7. | `volume_breakout` | -5.783 | 28.2% | -99.03% | 99.1% | 181 | 47 |
| 8. | `dip_in_uptrend` | -8.928 | 26.2% | -99.21% | 99.2% | 309 | 46 |
| 9. | `btc_bull_momentum` | -10.046 | 32.3% | -100.00% | 100.0% | 914 | 48 |

## 2026-04-02 03:46 UTC  `GPU quick`  49 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `low_rs_high_acc` | +3.709 | 55.3% | +0.54% | 46.2% | 1033 | 47 |
| 🥈 | `stealth_3gate` | +3.319 | 73.4% | +2.14% | 20.2% | 64 | 38 |
| 🥉 | `rsi_oversold` | +3.290 | 52.2% | +0.40% | 58.0% | 945 | 47 |
| 4. | `volatility_squeeze` | +0.541 | 49.3% | +0.19% | 31.3% | 136 | 44 |
| 5. | `dip_in_uptrend` | -0.811 | 43.7% | -0.12% | 64.3% | 877 | 48 |
| 6. | `accumulation_only` | -2.512 | 46.7% | -0.33% | 65.4% | 1414 | 48 |
| 7. | `ema_cross_bull` | -2.591 | 37.4% | -0.77% | 87.8% | 198 | 48 |
| 8. | `btc_bull_momentum` | -5.509 | 43.0% | -0.54% | 76.8% | 2480 | 47 |
| 9. | `volume_breakout` | -7.345 | 33.7% | -1.71% | 99.3% | 499 | 48 |

## 2026-04-03 03:23 UTC  `GPU full`  237 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `stealth_3gate` | +6.631 | 70.6% | +2.15% | 23.1% | 289 | 191 |
| 🥈 | `low_rs_high_acc` | +3.135 | 49.7% | +0.26% | 50.0% | 3909 | 235 |
| 🥉 | `rsi_oversold` | +0.558 | 47.3% | +0.04% | 52.3% | 4047 | 231 |
| 4. | `ema_cross_bull` | +0.423 | 49.4% | +0.10% | 70.6% | 635 | 235 |
| 5. | `volatility_squeeze` | -0.357 | 48.8% | -0.07% | 70.4% | 490 | 200 |
| 6. | `accumulation_only` | -3.272 | 46.0% | -0.25% | 48.9% | 5379 | 236 |
| 7. | `volume_breakout` | -10.068 | 36.9% | -1.38% | 98.0% | 2002 | 236 |
| 8. | `btc_bull_momentum` | -10.543 | 40.6% | -0.68% | 91.8% | 8926 | 235 |
| 9. | `dip_in_uptrend` | -12.075 | 28.9% | -1.62% | 96.6% | 1821 | 229 |

## 2026-04-03 06:48 UTC  `GPU quick`  28 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `low_rs_high_acc` | +3.608 | 55.5% | +0.76% | 42.3% | 562 | 26 |
| 🥈 | `stealth_3gate` | +3.136 | 78.8% | +2.59% | 15.9% | 33 | 20 |
| 🥉 | `rsi_oversold` | +0.317 | 49.6% | +0.05% | 53.1% | 542 | 26 |
| 4. | `dip_in_uptrend` | -0.019 | 40.2% | -0.00% | 48.2% | 410 | 27 |
| 5. | `btc_bull_momentum` | -0.611 | 46.6% | -0.09% | 68.8% | 1360 | 26 |
| 6. | `volatility_squeeze` | -0.655 | 49.3% | -0.31% | 24.7% | 67 | 22 |
| 7. | `accumulation_only` | -1.447 | 46.0% | -0.29% | 75.5% | 819 | 27 |
| 8. | `ema_cross_bull` | -1.806 | 32.4% | -0.95% | 71.9% | 111 | 27 |
| 9. | `volume_breakout` | -3.212 | 37.6% | -1.23% | 93.7% | 290 | 27 |

## 2026-04-03 13:09 UTC  `GPU full`  230 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `stealth_3gate` | +6.315 | 70.0% | +2.11% | 16.8% | 277 | 182 |
| 🥈 | `low_rs_high_acc` | +2.157 | 48.9% | +0.18% | 52.7% | 3923 | 228 |
| 🥉 | `rsi_oversold` | +0.415 | 47.5% | +0.03% | 41.6% | 3935 | 222 |
| 4. | `ema_cross_bull` | -0.144 | 48.9% | -0.03% | 52.7% | 657 | 228 |
| 5. | `volatility_squeeze` | -0.557 | 47.7% | -0.11% | 41.9% | 497 | 199 |
| 6. | `accumulation_only` | -3.166 | 45.9% | -0.25% | 55.4% | 5394 | 229 |
| 7. | `volume_breakout` | -9.197 | 37.2% | -1.28% | 84.8% | 1994 | 229 |
| 8. | `dip_in_uptrend` | -11.340 | 30.0% | -1.54% | 98.1% | 1768 | 222 |
| 9. | `btc_bull_momentum` | -11.429 | 40.1% | -0.71% | 96.6% | 9136 | 228 |

## 2026-04-07 04:29 UTC  `GPU full`  233 symbols

| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 🥇 | `stealth_3gate` | +6.195 | 70.0% | +2.08% | 20.9% | 277 | 185 |
| 🥈 | `low_rs_high_acc` | +3.281 | 49.5% | +0.26% | 33.5% | 4408 | 230 |
| 🥉 | `rsi_oversold` | +0.481 | 46.9% | +0.04% | 45.7% | 4426 | 225 |
| 4. | `volatility_squeeze` | -0.340 | 49.1% | -0.06% | 59.2% | 556 | 207 |
| 5. | `ema_cross_bull` | -0.398 | 46.6% | -0.08% | 61.9% | 771 | 230 |
| 6. | `accumulation_only` | -3.047 | 46.1% | -0.22% | 72.3% | 6152 | 231 |
| 7. | `volume_breakout` | -10.392 | 36.6% | -1.36% | 98.4% | 2255 | 231 |
| 8. | `btc_bull_momentum` | -10.420 | 40.0% | -0.64% | 66.9% | 9950 | 230 |
| 9. | `dip_in_uptrend` | -10.427 | 33.6% | -1.25% | 97.7% | 2166 | 226 |
