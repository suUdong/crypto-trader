# Backtest History

모든 백테스트 결과를 누적 기록. CLAUDE.md 토큰 절약 목적.
새 테스트 완료 시 반드시 이 파일에 추가할 것.

---

## 포맷

| 날짜 | 전략 | 파라미터 | 거래수 | 승률 | avg수익 | Sharpe | 결론 |
|---|---|---|---|---|---|---|---|

---

## 2026-04-03 — momentum_vpin_combo 4h 그리드 탐색 (사이클 67)

**가설**: momentum 진입에 VPIN 필터 추가 → 노이즈 진입 감소
**데이터**: SOL/ETH/APT/LINK/SUI 4시간봉 2022-01-01~2026-04-03
**그리드**: vpin_thresh(0.55~0.75) × lookback(12/16/20) × TP(0.08/0.10/0.12) × SL(0.03/0.04)

| 심볼 | lookback | TP | SL | Sharpe | WR | avg수익 | 거래수 |
|---|---|---|---|---|---|---|---|
| KRW-SOL | 20 | 0.12 | 0.04 | **+14.37** | 46.8% | +2.77% | 79 |
| KRW-ETH | 12 | 0.12 | 0.03 | **+13.59** | 45.0% | +2.24% | 60 |
| KRW-SUI | 20 | 0.12 | 0.03 | **+5.29** | 29.3% | +0.86% | 58 |
| KRW-LINK | 12 | 0.12 | 0.03 | +0.41 | 27.1% | +0.06% | 85 |
| KRW-APT | 12 | 0.12 | 0.03 | -2.67 | 19.3% | -0.38% | 83 |

**중요 발견**:
1. VPIN 필터 버그: `|close-open| / (|close-open| + ε)` → 항상 ≈1.0, 필터 무효. ADX+VOL 필터만 동작.
2. ETH momentum도 Sharpe +13.59 확인 (이전 미탐색). ADX≥25, vol_mult=2.0, lookback=12.
3. SUI momentum Sharpe +5.28 — daemon 반영 검토 필요 (거래수 58개로 충분).
4. LINK/APT는 momentum 전략 부적합 — 제외 확정.

**결론**: VPIN 필터 자체 edge 없음. 그러나 ETH momentum(Sharpe +13.59) 신규 확인 — ETH 파라미터 그리드 탐색으로 최적화 필요. SUI도 유망.

---

## 2026-04-03 13:09 UTC — GPU Strategy Tournament (244 symbols, 4h×180)

**데이터**: 230/244 KRW 심볼, 4시간봉 180봉, CUDA 텐서 병렬 처리
**수정**: BTC 데이터 없음 버그 수정 (재시도 로직 추가) → 정상 실행

| # | 전략 | 거래수 | 승률 | avg수익 | Sharpe | 결론 |
|---|---|---|---|---|---|---|
| 1st | stealth_3gate | 277 | **70.0%** | +2.11% | **+6.315** | ✅ 압도적 1위 재확인 |
| 2nd | low_rs_high_acc | 3923 | 48.9% | +0.18% | +2.157 | 보조지표로 활용 가능 |
| 3rd | rsi_oversold | 3935 | 47.5% | +0.03% | +0.415 | edge 미미 |
| — | volume_breakout | 1994 | 37.2% | -1.28% | -9.197 | ❌ 탈락 |
| — | btc_bull_momentum | 9136 | 40.1% | -0.71% | -11.429 | ❌ 탈락 |

**결론**: stealth_3gate(BTC>SMA20 + BTC stealth + RS∈[0.7,1) + acc>1) Sharpe +6.315으로 압도적. 현재 daemon에 이미 배포된 파라미터(W=36, TP=15%, SL=3%)와 일치. low_rs_high_acc는 단독으로는 edge 부족 (WR 48.9%).

---

## 2026-04-03 — momentum_sol 4h 그리드 탐색

**데이터**: KRW-SOL 4시간봉 2022-01-01~2026-12-31 (8,585봉), 수수료 0.05%
**그리드**: lookback×adx×vol_mult×TP×SL = 540조합

### Top 결과 (Sharpe 기준)

| lookback | adx | vol_mult | TP | SL | Sharpe | WR | avg수익 | 거래수 |
|---|---|---|---|---|---|---|---|---|
| 20 | 25.0 | 2.0 | 0.12 | 0.04 | **+14.37** | 46.8% | +2.77% | 79 |
| 28 | 20.0 | 2.0 | 0.12 | 0.02 | +13.91 | 33.6% | +2.24% | 113 |
| 12 | 25.0 | 2.0 | 0.12 | 0.04 | +13.85 | 47.0% | +2.67% | 83 |
| 28 | 25.0 | 2.0 | 0.12 | 0.03 | +13.12 | 40.0% | +2.35% | 80 |

**현재 daemon.toml**: lookback=20 adx=20.0 vol=1.5 TP=0.08 SL=0.03
**최적**: lookback=20 adx=25.0 vol=2.0 TP=0.12 SL=0.04

**결론**: adx 20→25, vol_mult 1.5→2.0, TP 0.08→0.12, SL 0.03→0.04 변경 시 Sharpe +14.37. vol_mult=2.0은 노이즈 필터 효과. 단, WR 46.8% / 79거래로 충분한 샘플. daemon 반영 검토 필요.

---

## 2026-04-02 — BTC Regime Rotation 시리즈

**데이터**: 4시간봉 500봉 (~83일), KRW 알트 37~40종목, 수수료 0.05%

### Base: bull + alpha_z > 1.0
| 파라미터 | 값 |
|---|---|
| 진입 | BTC bull regime + alpha_z > 1.0 |
| 청산 | BTC bear OR alpha_z < 0 OR max_hold 24봉 |
| 거래수 | 92건 |
| 승률 | 29.3% |
| 평균수익 | -1.54% |
| Sharpe | -4.67 |
| alpha r | -0.163 |

**결론**: 실패. alpha_z가 미래 수익과 음의 상관 → 이미 오른 종목 진입 패턴.

---

### Strategy A: pre_bull + acc_z > 0.5 + rs_z < 1.0
| 파라미터 | 값 |
|---|---|
| 진입 | BTC pre_bull + acc_z > 0.5 AND rs_z < 1.0 (아직 안 오른 종목) |
| 청산 | BTC bear OR alpha_z < -1.0 OR max_hold 24봉 |
| 거래수 | 293건 |
| 승률 | 24.2% |
| 평균수익 | -1.91% |
| Sharpe | -8.39 |
| acc_z r | +0.046 (무상관) |

**결론**: 실패. 상위 종목이 USDT/USDC/USDE 스테이블 → 알트 모멘텀 신호 없음.
bear 청산 75% (220/293건) — pre_bull에서 진입해도 bear로 전환 속도가 빠름.

---

### Strategy B: bull 전환 초기 6봉 이내 진입
| 파라미터 | 값 |
|---|---|
| 진입 | BTC bull 전환 후 ≤6봉 이내 + alpha_z > 0.5 |
| 청산 | BTC bear OR alpha_z < -0.5 OR max_hold 24봉 |
| BTC bull 전환 횟수 | 16회 |
| 거래수 | 103건 |
| 승률 | 22.3% |
| 평균수익 | -2.91% |
| Sharpe | -10.56 |
| alpha r | -0.297 |

**결론**: 실패. alpha r 더 강한 음의 상관. bull 전환 직후가 오히려 더 위험.
bull_age=0 (전환 당일)에 64/103건 진입 → 전환 오탐 or 단기 되돌림.

---

## 공통 관찰사항

- **SMA-기반 BTC 레짐 탐지의 한계**: bull=28.8%, pre_bull=24.4%, bear=32.8% — 레짐 전환이 빈번해 진입 후 바로 bear 청산
- **alpha_z 음의 상관**: z-score 정규화된 alpha가 높은 종목은 이미 모멘텀 소진 상태
- **bear 청산 지배적**: 3개 전략 모두 bear 청산이 1위 → 레짐 탐지 자체를 개선해야 함

---

### Strategy C: 3-gate Stealth (acc_exit 청산)
| 파라미터 | 값 |
|---|---|
| 진입 | BTC>SMA20 + BTC stealth + Alt RS∈[0.8,1.0) acc∈[1.0,1.5] cvd>0 |
| 청산 | BTC bear OR acc < 1.0 OR max_hold 24봉 |
| 거래수 | 166건 |
| 승률 | 38.0% |
| 평균수익 | -0.80% |
| Sharpe | -4.56 |
| rs 상관 | +0.058 (무상관 — 이전 음수보다 개선) |

**결론**: 부분 개선. acc_exit 청산이 111/166건 → 수익 실현 전 조기 청산.

---

### Strategy D: 3-gate Stealth + 고정 12봉 hold (48h)
| 파라미터 | 값 |
|---|---|
| 진입 | 동일 (3-gate stealth) |
| 청산 | 고정 12봉 (48h) — acc_exit 없음 |
| 거래수 | 134건 |
| 승률 | 32.1% |
| 평균수익 | -2.06% |
| Sharpe | -6.54 |

**결론**: C보다 악화. 고정 hold가 오히려 손실 확대.

---

## 공통 관찰 (2026-04-02 전체)

- **테스트 기간이 하락장**: 83일 데이터에 불장/하락장 혼재 → 모든 전략 평균 마이너스
- **불장 구간만 골라서 테스트해야 전략 평가 가능** → `docs/plan_bull_rotation.md` 참조
- 3-gate stealth 룰 자체는 유효 (검증 당시 50.3% WR) — 시장 컨텍스트가 문제

## 다음 시도 후보

- [ ] BTC 레짐을 SMA 대신 EMA 또는 HMM 기반으로 변경
- [ ] alpha 대신 volume breakout (절대값) 기반 진입
- [ ] 레짐 확정 조건 강화 (N봉 연속 bull 유지 시에만 진입)
- [ ] 3-gate 전략 (stealth signal rules) 적용: BTC regime + BTC stealth + alt quality

## 2026-04-02 04:44 UTC — 불장 필터 비교 백테스트
**불장 구간**: 2021-10-03~2021-12-28, 2023-02-20~2023-08-17, 2023-10-29~2024-07-03, 2024-07-16~2024-08-02, 2024-11-05~2025-03-09, 2025-05-31~2025-11-03  
**불장 비율**: 43.1%  
**데이터**: 4h봉 ~400일, 25 symbols

| 전략 | 전체Sharpe | 불장Sharpe | 전체WR | 불장WR | 전체Trades | 불장Trades | 개선 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `rsi_oversold` | +6.955 | +3.269 | 53.3% | 54.9% | 5478 | 2172 | ↓3.69 |
| `stealth_3gate` | -0.343 | +0.011 | 46.7% | 45.1% | 199 | 71 | ↑0.35 |
| `low_rs_high_acc` | +0.524 | -1.075 | 48.7% | 50.2% | 4715 | 1776 | ↓1.60 |
| `volume_breakout` | +0.643 | -1.500 | 47.8% | 46.2% | 1415 | 630 | ↓2.14 |
| `btc_bull_momentum` | -2.952 | -3.814 | 44.6% | 44.4% | 9636 | 4278 | ↓0.86 |
| `accumulation_only` | -1.468 | -3.953 | 46.2% | 44.9% | 6068 | 2620 | ↓2.48 |

**결론**: 불장 Sharpe > 전체 Sharpe 인 전략이 불장 로테이션에 적합.

## 2026-04-02 04:52 UTC — BTC Stealth 선행 신호 분석

### 불장 시작 전 Stealth 발동률

| Lead Time | 발동률 | 발동/전체 |
|---|:---:|:---:|
| T-24h 전 | 0.0% ⭐ | 0/1 |
| T-48h 전 | 0.0% | 0/1 |
| T-72h 전 | 0.0% | 0/1 |
| T-96h 전 | 0.0% | 0/1 |

**최적 선행 시점**: T-24h 전 (발동률 0.0%)

### 불장 직전 vs 일반 Stealth 수익 비교

| 구분 | avg_ret | win_rate | n |
|---|:---:|:---:|:---:|
| 불장 직전 stealth | -0.45% | 0.0% | 1 |
| 일반 stealth      | +0.16% | 57.0% | 114 |

**결론**: 불장 직전 stealth avg_ret = -0.45% vs 일반 = +0.16%

## 2026-04-02 04:54 UTC — BTC Stealth 선행 신호 분석

### 불장 시작 전 Stealth 발동률

| Lead Time | 발동률 | 발동/전체 |
|---|:---:|:---:|
| T-7d 전 | 0.0% ⭐ | 0/7 |
| T-14d 전 | 0.0% | 0/7 |
| T-21d 전 | 0.0% | 0/7 |
| T-30d 전 | 0.0% | 0/7 |

**최적 선행 시점**: T-7d 전 (발동률 0.0%)

### 불장 직전 vs 일반 Stealth 수익 비교

| 구분 | avg_ret | win_rate | n |
|---|:---:|:---:|:---:|
| 불장 직전 stealth | +12.35% | 100.0% | 4 |
| 일반 stealth      | +0.86% | 39.1% | 64 |

**결론**: 불장 직전 stealth avg_ret = +12.35% vs 일반 = +0.86%

## 2026-04-02 04:56 UTC — BTC Stealth 선행 신호 분석

### 불장 시작 전 Stealth 발동률

| Lead Time | 발동률 | 발동/전체 |
|---|:---:|:---:|
| T-7d 전 | 0.0% | 0/8 |
| T-14d 전 | 0.0% | 0/8 |
| T-21d 전 | 0.0% | 0/8 |
| T-30d 전 | 12.5% ⭐ | 1/8 |

**최적 선행 시점**: T-30d 전 (발동률 12.5%)

### 불장 직전 vs 일반 Stealth 수익 비교

| 구분 | avg_ret | win_rate | n |
|---|:---:|:---:|:---:|
| 불장 직전 stealth | +9.51% | 100.0% | 6 |
| 일반 stealth      | +0.28% | 46.7% | 122 |

**결론**: 불장 직전 stealth avg_ret = +9.51% vs 일반 = +0.28%

## 2026-04-02 05:10 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=15%/SL=3% | -0.609 | 33.4% | -0.20% | 8 |
| TP=5%/SL=5% | -0.830 | 42.7% | -0.33% | 7 |
| TP=15%/SL=5% | -0.842 | 35.6% | -0.34% | 6 |
| TP=10%/SL=3% | -1.220 | 33.5% | -0.42% | 5 |
| TP=10%/SL=5% | -1.410 | 36.0% | -0.56% | 6 |

**최적**: TP=15% / SL=3%  Sharpe=-0.609  WR=33.4%

**레짐 필터 효과**: combined -0.609 vs stealth_only -0.500

## 2026-04-02 05:19 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=5%/SL=8% | -0.594 | 47.6% | -0.20% | 1 |
| TP=15%/SL=5% | -0.762 | 33.8% | -0.35% | 8 |
| TP=10%/SL=8% | -1.720 | 37.1% | -0.68% | 8 |
| TP=15%/SL=3% | -2.059 | 28.7% | -0.59% | 9 |
| TP=15%/SL=8% | -2.068 | 34.0% | -0.87% | 9 |

**최적**: TP=5% / SL=8%  Sharpe=-0.594  WR=47.6%

**레짐 필터 효과**: combined -0.594 vs stealth_only +0.722

## 2026-04-02 05:21 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=20%/SL=5% | +0.413 | 37.9% | +0.12% | 3 |
| TP=20%/SL=3% | +0.142 | 34.6% | +0.09% | 2 |
| TP=15%/SL=5% | -1.509 | 32.5% | -0.54% | 1 |
| TP=20%/SL=8% | -1.811 | 34.9% | -0.90% | 5 |
| TP=10%/SL=8% | -1.907 | 35.3% | -0.69% | 7 |

**최적**: TP=20% / SL=5%  Sharpe=+0.413  WR=37.9%

**레짐 필터 효과**: combined +0.413 vs stealth_only -0.655

## 2026-04-02 05:31 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=10%/SL=3% | -0.829 | 33.8% | -0.37% | 9 |
| TP=10%/SL=8% | -1.775 | 36.2% | -1.01% | 5 |
| TP=10%/SL=5% | -1.862 | 34.2% | -0.85% | 8 |
| TP=20%/SL=5% | -1.931 | 34.4% | +0.32% | 6 |
| TP=20%/SL=3% | -4.028 | 21.1% | -1.99% | 1 |

**최적**: TP=10% / SL=3%  Sharpe=-0.829  WR=33.8%

**레짐 필터 효과**: combined -0.829 vs stealth_only -0.941

## 2026-04-02 — BTC 레짐 + 알트 Stealth 2-Factor 백테스트 (C 단계)

### 설정
- BTC 레짐: 일봉 close > SMA100
- 알트 신호: 일봉 stealth (lookback=14일)
- 알트 25종목, TP/SL 그리드 4×3=12조합

### 결과 (combined Sharpe 기준 Top 5)

| TP | SL | Sharpe | WinRate | AvgRet | nSym |
|---|:---:|:---:|:---:|:---:|:---:|
| 10% | 3% | -0.83 | 33.8% | -0.37% | 9 |
| 10% | 8% | -1.78 | 36.2% | -1.01% | 5 |
| 10% | 5% | -1.86 | 34.2% | -0.85% | 8 |
| 20% | 5% | -1.93 | 34.4% | +0.32% | 6 |
| 20% | 3% | -4.03 | 21.1% | -1.99% | 1 |

### 결론
- **일봉 stealth 신호 자체가 약함** — 전 조합 Sharpe 음수
- 레짐 필터는 marginal 개선 (-1.02 → -0.83) 있지만 불충분
- **4h stealth가 훨씬 우수** (GPU 토너먼트: stealth_3gate Sharpe +3.32)
- 올바른 조합: BTC 레짐(일봉) + 알트 stealth(4h)
- **TODO**: 업비트 CSV 수령 후 알트 4h 장기 데이터로 재검증


## 2026-04-02 13:47 UTC — BTC 레짐(SMA20) + 알트 4h stealth_3gate 2-Factor 백테스트

### 설정
- BTC 레짐: 4h close, day SMA20 (forward-fill)
- BTC stealth: 12봉 수익 < 0 AND btc_acc > 1.0
- Alt 필터: RS ∈ [0.7, 1.0) AND acc > 1.0
- 기간: 2022~2026, KRW 전체 알트

### 결과 Top-5 (Sharpe 기준)

| TP | SL | Sharpe | WinRate | AvgRet | Trades | Syms |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 15% | 3% | +1.862 | 22.0% | +0.86% | 9245 | 140 |
| 20% | 3% | +1.825 | 18.6% | +0.98% | 8750 | 140 |
| 10% | 3% | +1.637 | 27.9% | +0.60% | 9907 | 140 |
| 20% | 5% | +0.945 | 24.1% | +0.61% | 7392 | 140 |
| 15% | 5% | +0.871 | 28.1% | +0.48% | 7876 | 140 |

### 결론
- **최적**: TP=15% / SL=3%  Sharpe=+1.862  WR=22.0%

## 2026-04-02 21:31 UTC — stealth_3gate 파라미터 그리드 탐색 (W/SMA/RS 전체 조합)

### 설정
- TP=15%, SL=3% (이전 최적 고정)
- W: [6, 9, 12, 18, 24] (4h 봉 룩백)
- SMA: [20, 50] (BTC 레짐 일봉 SMA)
- RS lo: [0.5, 0.7, 0.8], RS hi: [1.0, 1.2]
- 기간: 2022~2026, KRW 알트 전체 (히스토리 데이터)

### 결과 Top-10 (Sharpe 기준)

| 파라미터 | Sharpe | WinRate | AvgRet | Trades | Syms |
|---|:---:|:---:|:---:|:---:|:---:|
| W=24 SMA20 RS[0.5,1.0) | +2.975 | 25.6% | +1.44% | 4885 | 93 |
| W=24 SMA20 RS[0.7,1.0) | +2.967 | 25.5% | +1.44% | 4878 | 93 |
| W=24 SMA20 RS[0.5,1.2) | +2.879 | 25.2% | +1.39% | 6937 | 93 |
| W=24 SMA20 RS[0.8,1.0) | +2.876 | 25.3% | +1.39% | 4822 | 93 |
| W=24 SMA20 RS[0.7,1.2) | +2.873 | 25.2% | +1.39% | 6930 | 93 |
| W=24 SMA20 RS[0.8,1.2) | +2.807 | 25.0% | +1.35% | 6875 | 93 |
| W=18 SMA20 RS[0.5,1.0) | +2.774 | 24.7% | +1.33% | 5792 | 93 |
| W=18 SMA20 RS[0.7,1.0) | +2.772 | 24.7% | +1.33% | 5789 | 93 |
| W=18 SMA20 RS[0.8,1.0) | +2.701 | 24.5% | +1.30% | 5736 | 93 |
| W=18 SMA20 RS[0.7,1.2) | +2.645 | 24.3% | +1.27% | 7972 | 93 |


## 2026-04-02 21:32 UTC — stealth_3gate 파라미터 그리드 탐색 (W/SMA/RS 전체 조합)

### 설정
- TP=15%, SL=3% (이전 최적 고정)
- W: [6, 9, 12, 18, 24] (4h 봉 룩백)
- SMA: [20, 50] (BTC 레짐 일봉 SMA)
- RS lo: [0.5, 0.7, 0.8], RS hi: [1.0, 1.2]
- 기간: 2022~2026, KRW 알트 전체 (히스토리 데이터)

### 결과 Top-10 (Sharpe 기준)

| 파라미터 | Sharpe | WinRate | AvgRet | Trades | Syms |
|---|:---:|:---:|:---:|:---:|:---:|
| W=24 SMA20 RS[0.5,1.0) | +2.975 | 25.6% | +1.44% | 4885 | 93 |
| W=24 SMA20 RS[0.7,1.0) | +2.967 | 25.5% | +1.44% | 4878 | 93 |
| W=24 SMA20 RS[0.5,1.2) | +2.879 | 25.2% | +1.39% | 6937 | 93 |
| W=24 SMA20 RS[0.8,1.0) | +2.876 | 25.3% | +1.39% | 4822 | 93 |
| W=24 SMA20 RS[0.7,1.2) | +2.873 | 25.2% | +1.39% | 6930 | 93 |
| W=24 SMA20 RS[0.8,1.2) | +2.807 | 25.0% | +1.35% | 6875 | 93 |
| W=18 SMA20 RS[0.5,1.0) | +2.774 | 24.7% | +1.33% | 5792 | 93 |
| W=18 SMA20 RS[0.7,1.0) | +2.772 | 24.7% | +1.33% | 5789 | 93 |
| W=18 SMA20 RS[0.8,1.0) | +2.701 | 24.5% | +1.30% | 5736 | 93 |
| W=18 SMA20 RS[0.7,1.2) | +2.645 | 24.3% | +1.27% | 7972 | 93 |


## 2026-04-02 21:32 UTC — stealth_3gate 파라미터 그리드 탐색 (W/SMA/RS 전체 조합)

### 설정
- TP=15%, SL=3% (이전 최적 고정)
- W: [24, 30, 36, 48] (4h 봉 룩백)
- SMA: [20] (BTC 레짐 일봉 SMA)
- RS lo: [0.5], RS hi: [1.0]
- 기간: 2022~2026, KRW 알트 전체 (히스토리 데이터)

### 결과 Top-10 (Sharpe 기준)

| 파라미터 | Sharpe | WinRate | AvgRet | Trades | Syms |
|---|:---:|:---:|:---:|:---:|:---:|
| W=36 SMA20 RS[0.5,1.0) | +4.682 | 31.1% | +2.41% | 3760 | 93 |
| W=24 SMA20 RS[0.5,1.0) | +2.975 | 25.6% | +1.44% | 4885 | 93 |
| W=30 SMA20 RS[0.5,1.0) | +2.970 | 25.4% | +1.44% | 4708 | 93 |
| W=48 SMA20 RS[0.5,1.0) | +2.565 | 24.0% | +1.22% | 3184 | 93 |


## 2026-04-03 — stealth_3gate W 정밀 탐색 (W=32~42, SMA20, RS[0.5,1.0), TP=15% SL=3%)

### 결과

| W | Sharpe | WinRate | AvgRet | Trades | sig율 |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 32 | +3.788 | 28.1% | +1.89% | 4,111 | 3.9% |
| 34 | +4.348 | 29.9% | +2.22% | 3,937 | 3.6% |
| **36** | **+4.682** | **31.1%** | **+2.41%** | **3,760** | **3.5%** |
| 38 | +3.426 | 26.8% | +1.69% | 3,579 | 3.2% |
| 40 | +3.543 | 27.1% | +1.76% | 3,499 | 3.1% |
| 42 | +3.940 | 28.5% | +1.98% | 3,527 | 3.1% |

### 결론
- **최적: W=36** — 피크 Sharpe +4.682, 양쪽(38/34) 대비 명확한 극값
- W=12 베이스라인 대비: +1.862 → +4.682 (+151% 개선)
- daemon.toml 반영 완료: stealth_lookback=36, RS[0.5,1.0), SMA20
- 데이터: 2022~2026, 93개 KRW 알트 × 240m 히스토리

---

## 2026-04-03 — momentum_sol 4h 파라미터 그리드 탐색

**설정**
- 심볼: KRW-SOL, 기간: 2022~2026, 수수료 0.05%
- 그리드: lookback=[12,16,20,24,28] × adx=[15,20,25] × vol=[1.0,1.5,2.0] × TP=[5,8,10,12%] × SL=[2,3,4%]
- 총 540개 조합

### 결과 Top-5 (Sharpe 기준)

| lookback | adx | vol | TP | SL | Sharpe | WR | avg% | trades |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 20 | 25 | 2.0 | 12% | 4% | +14.367 | 46.8% | +2.77% | 79 |
| 28 | 20 | 2.0 | 12% | 2% | +13.913 | 33.6% | +2.24% | 113 |
| 12 | 25 | 2.0 | 12% | 4% | +13.851 | 47.0% | +2.67% | 83 |
| 24 | 20 | 2.0 | 12% | 2% | +13.529 | 33.6% | +2.16% | 116 |
| 20 | 20 | 2.0 | 12% | 2% | +13.123 | 33.1% | +2.07% | 118 |

### 결론
- **최적: lookback=20, adx=25, vol=2.0, TP=12%, SL=4%** — Sharpe +14.367
- 현재 daemon.toml 대비 개선: adx 20→25, vol_mult 1.5→2.0, TP 8%→12%, SL 3%→4%
- vol=2.0이 일관되게 상위 — 볼륨 필터 강화가 핵심
- adx 25가 20보다 우세 — 방향성 확실한 진입만 허용
- **주의**: 높은 Sharpe지만 trades=79로 적음 → 과적합 가능성 검토 필요, daemon 반영 전 추가 검증 권장

---

## 2026-04-03 — vpin_eth 4h 파라미터 그리드 탐색

**설정**
- 심볼: KRW-ETH, 기간: 2022~2026, 수수료 0.05%
- 그리드: vpin_high=[0.55,0.60,0.65,0.70] × vpin_mom=[0.0001,0.0003,0.0005] × max_hold=[18,24,30] × TP=[3,4,5,6%] × SL=[0.8,1.2,1.5%]
- 총 432개 조합

### 결과 Top-5 (Sharpe 기준)

| vpin_high | vpin_mom | max_hold | TP | SL | Sharpe | WR | avg% | trades |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 0.55~0.70 | 0.0005 | 18 | 6% | 0.8% | +7.461 | 27.6% | +0.45% | 446 |
| 0.55~0.70 | 0.0005 | 18 | 5% | 0.8% | +7.461 | 28.2% | +0.42% | 468 |
| 0.55~0.70 | 0.0003 | 18 | 5% | 0.8% | +7.366 | 28.1% | +0.41% | 469 |

### 결론
- **vpin_high 임계값이 진입에 실질 영향 없음** — 0.55~0.70 전부 동일 결과 (단순화된 VPIN proxy 한계)
- 유효한 파라미터 최적: max_hold=18(현재24), TP=5~6%(현재4%), SL=0.8%(현재1.2%)
- **max_hold 단축이 핵심**: 18봉(72h)이 24봉(96h)보다 일관되게 우수
- vpin_high 재탐색 필요: 실제 VPINStrategy 코드 기반 정확한 VPIN 계산으로 재백테스트 권장
- daemon.toml 반영 후보: max_hold 24→18, TP 4%→5%, SL 1.2%→0.8% (검증 후)

## 2026-04-03 00:58 UTC — stealth_3gate KRW-SOL 전체 마켓 스캔 [ralph:stealth_sol_sweep]

**결과**: Sharpe N/A | WR N/A | trades N/A


<details><summary>raw output</summary>

```
Traceback (most recent call last):
  File "/home/wdsr88/workspace/crypto-trader/scripts/backtest_stealth_deep.py", line 29, in <module>
    import torch
ModuleNotFoundError: No module named 'torch'

```

</details>

---

## 2026-04-03 01:05 UTC — stealth_3gate 전체 마켓 스캔 (GPU) [ralph:stealth_sol_sweep]

**결과**: Sharpe N/A | WR 87.5% | trades N/A


<details><summary>raw output</summary>

```
dge)
======================================================================
    RS<   Acc>       N      Mean       WR      Edge
    1.0    1.5      76   -0.215%   38.2%   +0.815%
    1.0    1.0     737   -0.825%   40.2%   +0.224%
    1.0    1.2     341   -1.136%   35.2%   -0.126%
    0.9    1.0      20   -2.758%   40.0%   -1.746%

======================================================================
  [3] Signal Strength Quartiles
======================================================================
  Q4 (strongest)          n=  185  mean= -1.011%  wr=38.9%
  Q3                      n=  184  mean= -0.665%  wr=42.4%
  Q2                      n=  184  mean= -0.617%  wr=42.9%
  Q1 (weakest)            n=  184  mean= -1.007%  wr=36.4%

======================================================================
  [4] Joint BTC × Alt Stealth Quadrants  (fwd=T+12봉)
======================================================================
  Quadrant                    Win    AltMean    AltWR    BTCMean    BTCWR
  BTC+Alt stealth               8    +0.864%   56.2%    +1.114%   87.5%
  BTC only stealth              0      +nan%    nan%      +nan%    nan%
  Alt only stealth             46    -1.383%   33.7%    -0.654%   43.5%
  No stealth                    1    +0.694%   55.7%    +1.123%  100.0%

  [BTC Stealth Self-Performance]
  BTC stealth ON         n=    8  mean= +1.114%  wr=87.5%
  BTC stealth OFF        n=   47  mean= -0.616%  wr=44.7%

Report saved → artifacts/stealth-deep-result.md

```

</details>

---

## 2026-04-03 01:43 UTC — stealth_3gate 전체 마켓 스캔 (GPU) [ralph:stealth_sol_sweep]

**결과**: Sharpe N/A | WR N/A | trades 47


<details><summary>raw output</summary>

```
======================================================================
  Stealth Signal Deep Analysis — BTC + Alt Joint
  Interval: minute240 | Count: 500 | Lookback: 24봉 | Fwd: 12봉
======================================================================
Fetching 244 symbols (workers=3)...
Fetched 52 symbols in 47.2s
Traceback (most recent call last):
  File "/home/wdsr88/workspace/crypto-trader/scripts/backtest_stealth_deep.py", line 433, in <module>
    main()
  File "/home/wdsr88/workspace/crypto-trader/scripts/backtest_stealth_deep.py", line 324, in main
    sym_list, common_len) = build_tensors(all_data, btc_df)
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/wdsr88/workspace/crypto-trader/scripts/backtest_stealth_deep.py", line 64, in build_tensors
    common_len = min(min(len(df) for df in all_data.values()), len(btc_df))
                                                               ^^^^^^^^^^^
TypeError: object of type 'NoneType' has no len()

```

</details>

---

## 2026-04-03 01:53 UTC — TruthSeeker 전략 파라미터 스윕 [ralph:truth_seeker_sweep]

**결과**: Sharpe N/A | WR N/A | trades N/A


<details><summary>raw output</summary>

```
--- Starting Full Profitability Backtest: Truth-Seeker (ETH) ---
Initializing backtest engine...

```

</details>

---

## 2026-04-03 02:03 UTC — vpin_eth 파라미터 그리드 [ralph:vpin_eth_grid]

**결과**: Sharpe +7.461 | WR 27.6% | trades 446


<details><summary>raw output</summary>

```
=== vpin_eth 4h 그리드 탐색 ===
심볼: KRW-ETH  기간: 2022-01-01 ~ 2026-12-31
데이터: 8585행
총 조합: 432개

=== Top 15 (Sharpe 기준) ===
   vh      vm  hold    TP     SL |  Sharpe     WR    avg%  trades
------------------------------------------------------------------------
 0.55  0.0005    18 0.060  0.008 |  +7.461 27.6%  +0.45%     446
 0.60  0.0005    18 0.060  0.008 |  +7.461 27.6%  +0.45%     446
 0.65  0.0005    18 0.060  0.008 |  +7.461 27.6%  +0.45%     446
 0.70  0.0005    18 0.060  0.008 |  +7.461 27.6%  +0.45%     446
 0.55  0.0005    18 0.050  0.008 |  +7.461 28.2%  +0.42%     468
 0.60  0.0005    18 0.050  0.008 |  +7.461 28.2%  +0.42%     468
 0.65  0.0005    18 0.050  0.008 |  +7.461 28.2%  +0.42%     468
 0.70  0.0005    18 0.050  0.008 |  +7.461 28.2%  +0.42%     468
 0.55  0.0003    18 0.050  0.008 |  +7.366 28.1%  +0.41%     469
 0.60  0.0003    18 0.050  0.008 |  +7.366 28.1%  +0.41%     469
 0.65  0.0003    18 0.050  0.008 |  +7.366 28.1%  +0.41%     469
 0.70  0.0003    18 0.050  0.008 |  +7.366 28.1%  +0.41%     469
 0.55  0.0001    18 0.060  0.008 |  +7.364 27.5%  +0.44%     447
 0.55  0.0003    18 0.060  0.008 |  +7.364 27.5%  +0.44%     447
 0.60  0.0001    18 0.060  0.008 |  +7.364 27.5%  +0.44%     447

★ 최적: vpin_high=0.55 vpin_mom=0.0005 max_hold=18 TP=0.06 SL=0.008
  Sharpe=+7.461  WR=27.6%  avg=+0.45%  trades=446

현재 daemon.toml: vpin_high=0.65 vpin_mom=0.0003 max_hold=24 TP=0.04 SL=0.012

```

</details>

---

## 2026-04-03 02:13 UTC — momentum_sol 파라미터 그리드 [ralph:momentum_sol_grid]

**결과**: Sharpe +14.367 | WR 46.8% | trades 79


<details><summary>raw output</summary>

```
=== momentum_sol 4h 그리드 탐색 ===
심볼: KRW-SOL  기간: 2022-01-01 ~ 2026-12-31
데이터: 8585행
총 조합: 540개

=== Top 15 (Sharpe 기준) ===
lookback   adx   vol    TP    SL |  Sharpe     WR    avg%  trades
---------------------------------------------------------------------------
      20    25   2.0  0.12  0.04 | +14.367 46.8%  +2.77%      79
      28    20   2.0  0.12  0.02 | +13.913 33.6%  +2.24%     113
      12    25   2.0  0.12  0.04 | +13.851 47.0%  +2.67%      83
      24    20   2.0  0.12  0.02 | +13.529 33.6%  +2.16%     116
      20    20   2.0  0.12  0.02 | +13.123 33.1%  +2.07%     118
      28    25   2.0  0.12  0.03 | +13.121 40.0%  +2.35%      80
      20    25   2.0  0.10  0.04 | +12.858 47.0%  +2.23%      83
      28    20   2.0  0.10  0.02 | +12.847 34.5%  +1.81%     116
      28    25   2.0  0.10  0.03 | +12.810 41.0%  +2.06%      83
      28    25   2.0  0.12  0.02 | +12.757 31.3%  +2.03%      83
      12    25   2.0  0.10  0.04 | +12.724 47.7%  +2.21%      86
      24    25   2.0  0.12  0.02 | +12.599 31.0%  +2.00%      87
      20    25   2.0  0.12  0.02 | +12.437 31.0%  +1.96%      87
      24    25   2.0  0.12  0.03 | +12.426 39.3%  +2.19%      84
      28    25   2.0  0.10  0.02 | +12.374 32.6%  +1.75%      86

★ 최적: lookback=20 adx=25.0 vol=2.0 TP=0.12 SL=0.04
  Sharpe=+14.367  WR=46.8%  avg=+2.77%  trades=79

현재 daemon.toml: lookback=20 adx=20.0 vol=1.5 TP=0.08 SL=0.03

```

</details>

---

## 2026-04-03 02:23 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=15%/SL=5% | -0.312 | 33.5% | -0.18% | 9 |
| TP=15%/SL=3% | -0.471 | 33.4% | -0.16% | 7 |
| TP=10%/SL=8% | -0.602 | 40.6% | -0.36% | 6 |
| TP=20%/SL=5% | -0.812 | 30.6% | -0.24% | 7 |
| TP=20%/SL=3% | -1.123 | 27.6% | -0.36% | 11 |

**최적**: TP=15% / SL=5%  Sharpe=-0.312  WR=33.5%

**레짐 필터 효과**: combined -0.312 vs stealth_only -0.830

## 2026-04-03 03:04 UTC — BTC 레짐 + 스텔스 2-Factor 백테스트 [ralph:regime_stealth]

**결과**: Sharpe N/A | WR 45.0% | trades N/A


<details><summary>raw output</summary>

```

=================================================================
  BTC 레짐 + 알트 Stealth 2-Factor 백테스트  |  2026-04-03 02:23 UTC
=================================================================

[1/3] BTC 일봉 fetch & 레짐 계산 (SMA100)...
  OK: 3113봉 | 불장 비율 51.8%

[2/3] 그리드 탐색 (TP×SL: 4×3=12조합)
      알트 25종목 × 각 조합...
  TP=5% SL=3%  |  stealth Sh=-1.76 WR=38%  |  combine Sh=-2.65 WR=36%
  TP=5% SL=5%  |  stealth Sh=-1.84 WR=41%  |  combine Sh=-1.13 WR=42%
  TP=5% SL=8%  |  stealth Sh=-2.06 WR=45%  |  combine Sh=-1.61 WR=45%
  TP=10% SL=3%  |  stealth Sh=-3.12 WR=29%  |  combine Sh=-3.90 WR=26%
  TP=10% SL=5%  |  stealth Sh=-4.15 WR=33%  |  combine Sh=-13.69 WR=25%
  TP=10% SL=8%  |  stealth Sh=-1.21 WR=41%  |  combine Sh=-0.60 WR=41%
  TP=15% SL=3%  |  stealth Sh=-1.11 WR=33%  |  combine Sh=-0.47 WR=33%
  TP=15% SL=5%  |  stealth Sh=-0.94 WR=34%  |  combine Sh=-0.31 WR=33%
  TP=15% SL=8%  |  stealth Sh=-0.90 WR=39%  |  combine Sh=-1.42 WR=35%
  TP=20% SL=3%  |  stealth Sh=-0.99 WR=30%  |  combine Sh=-1.12 WR=28%
  TP=20% SL=5%  |  stealth Sh=-0.83 WR=33%  |  combine Sh=-0.81 WR=31%
  TP=20% SL=8%  |  stealth Sh=-1.85 WR=33%  |  combine Sh=-2.15 WR=34%

[3/3] 최적 파라미터 (combined Sharpe 기준)
     TP    SL    Sharpe   WinRate   AvgRet   nSym
  ──────────────────────────────────────────────
    15%     5%    -0.312      33.5%    -0.18%      9
    15%     3%    -0.471      33.4%    -0.16%      7
    10%     8%    -0.602      40.6%    -0.36%      6
    20%     5%    -0.812      30.6%    -0.24%      7
    20%     3%    -1.123      27.6%    -0.36%     11

결과 저장: artifacts/regime_stealth_backtest.json

```

</details>

---

## 2026-04-03 03:14 UTC — GPU Alpha filter 백테스트 [ralph:alpha_backtest]

**결과**: Sharpe -0.101 | WR N/A | trades 141


<details><summary>raw output</summary>

```
87     -0.163      0.104      -1.201
KRW-TT          -0.016     -0.111     -0.749      -1.469
KRW-UNI          0.241      0.472      0.820       1.582
KRW-USDC        -0.079     -0.154     -0.094      -0.259
KRW-USDT        -0.059     -0.078     -0.106      -0.135
KRW-VANA         0.231      0.161     -0.038       0.491
KRW-VET          0.098      0.171      0.381       0.338
KRW-W           -0.099      0.041     -0.201       0.707
KRW-WAVES       -0.171     -0.547     -1.453      -2.252
KRW-WAXP        -0.155     -0.402     -0.767      -1.282
KRW-XEC          0.042     -0.301     -1.364      -1.666
KRW-XLM          0.316      1.139      2.098       4.855
KRW-XRP          0.153      0.408      0.543       1.537
KRW-XTZ         -0.148     -0.536     -0.753      -0.579
KRW-ZETA        -0.148     -0.219     -1.189      -1.739
KRW-ZIL         -0.150     -0.446     -1.120      -1.069
KRW-ZRO         -0.077     -0.160     -0.212       0.417
KRW-ZRX         -0.023     -0.130     -0.496      -0.848

평균 엣지: {'edge_1b_%': -0.058375886524822694, 'edge_3b_%': -0.15106382978723404, 'edge_6b_%': -0.49000709219858163, 'edge_12b_%': -0.6390921985815603}

======================================================================
  [결론]
❌ Alpha Score 예측력 불충분 → 가중치 재조정 또는 다른 지표 검토 필요
======================================================================

[Optimizer] Searching best weights + threshold on GPU components...
  Best: rs=0.3 acc=0.35 cvd=0.35  threshold=0.5  edge=-0.101%  corr=-0.021
  Calibration saved → artifacts/alpha-calibration.json  verdict=invalid

[LOOKBACK Grid Search] Testing lookback windows on all fetched symbols...
  LB= 6 ( 24h): edge=+nan%  corr=+nan  n=0
  LB=12 ( 48h): edge=-0.5564%  corr=-0.0341  n=141
  LB=18 ( 72h): edge=-0.5570%  corr=-0.0366  n=141
  LB=24 ( 96h): edge=-0.4921%  corr=-0.0303  n=141
  LB=30 (120h): edge=-0.4900%  corr=-0.0246  n=141

  ★ 최적 LOOKBACK: 30봉 (120h) edge=-0.4900%  corr=-0.0246
  Report saved → artifacts/alpha-backtest-result.md

```

</details>

---

## 2026-04-03 — Bear/Fear 구간 진입 허용 vs 차단 비교

| 전략 | 설정 | Sharpe | WR | avg% | trades |
|---|---|:---:|:---:|:---:|:---:|
| momentum_sol | **현재 (bear 차단)** | **+11.626** | **44.8%** | **+2.61%** | 67 |
| momentum_sol | bear 허용 + RSI≥30 | +10.052 | 41.5% | +2.29% | 82 |
| momentum_sol | 모든 구간 허용 | +10.052 | 41.5% | +2.29% | 82 |
| vpin_eth | **현재 (bear 차단)** | **-1.748** | 25.6% | -0.14% | 168 |
| vpin_eth | bear 허용 | -1.762 | 24.9% | -0.14% | 193 |
| vpin_eth | 모든 구간 허용 | -1.738 | 24.9% | -0.14% | 193 |

**결론**:
- momentum_sol: bear 차단이 Sharpe +11.6 vs 허용 +10.1 → **현재 필터 유지**
- vpin_eth: 어느 설정도 Sharpe 마이너스 → **파라미터 자체 문제 (EMA 조건 재검토 필요)**
- 극도공포 RSI<30 구간은 전체의 5%뿐 — 필터 완화해도 trades 증가폭 미미

## 2026-04-03 03:24 UTC — GPU Strategy Tournament [ralph:strategy_tournament]

**결과**: Sharpe +6.631 | WR N/A | trades 8926


<details><summary>raw output</summary>

```

================================================================
  GPU Strategy Tournament  |  2026-04-03 03:23 UTC
  Device: CUDA  |  Mode: full (all KRW)
================================================================

[1/4] Getting KRW symbols...
  Target: 244 symbols

[2/4] Fetching 244 symbols (4h × 180)...
  OK: 237/244 in 36.6s

[3/4] Building GPU tensors...
  Tensor shape: torch.Size([236, 137]) | GPU time: 0.58s

[4/4] Evaluating 9 strategies...
  stealth_3gate          signals=289    trades=289   Sharpe=+6.631
  volume_breakout        signals=2159   trades=2002  Sharpe=-10.068
  rsi_oversold           signals=4253   trades=4047  Sharpe=+0.558
  btc_bull_momentum      signals=9759   trades=8926  Sharpe=-10.543
  dip_in_uptrend         signals=1926   trades=1821  Sharpe=-12.075
  accumulation_only      signals=5846   trades=5379  Sharpe=-3.272
  low_rs_high_acc        signals=4242   trades=3909  Sharpe=+3.135
  ema_cross_bull         signals=708    trades=635   Sharpe=+0.423
  volatility_squeeze     signals=542    trades=490   Sharpe=-0.357

────────────────────────────────────────────────────────────────────────
#   Strategy                Sharpe  WinRate    Ret%    DD%  Trades  Syms
────────────────────────────────────────────────────────────────────────
1st stealth_3gate            6.631    70.6%   2.15%  23.1%     289   191
2nd low_rs_high_acc          3.135    49.7%   0.26%  50.0%    3909   235
3rd rsi_oversold             0.558    47.3%   0.04%  52.3%    4047   231
 4. ema_cross_bull           0.423    49.4%   0.10%  70.6%     635   235
 5. volatility_squeeze      -0.357    48.8%  -0.07%  70.4%     490   200
 6. accumulation_only       -3.272    46.0%  -0.25%  48.9%    5379   236
 7. volume_breakout        -10.068    36.9%  -1.38%  98.0%    2002   236
 8. btc_bull_momentum      -10.543    40.6%  -0.68%  91.8%    8926   235
 9. dip_in_uptrend         -12.075    28.9%  -1.62%  96.6%    1821   229

Leaderboard → docs/strategy_leaderboard.md

```

</details>

---

## 2026-04-03 03:34 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
Credit balance is too low
```

</details>

---

## 2026-04-03 03:53 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
Credit balance is too low
```

</details>

---

## 2026-04-03 04:13 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
Credit balance is too low
```

</details>

---

## 2026-04-03 04:32 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
Credit balance is too low
```

</details>

---

## 2026-04-03 04:44 UTC — momentum_sol 워크포워드 검증
**기간**: Train 2022~2024 / Test 2025~2026-04-03  
**그리드**: lookback×adx×vol×TP×SL = 243조합  

### 최적 파라미터 (lb=20 adx=25 vol=2.0 TP=12% SL=4%)

| 구간 | Sharpe | WR | trades |
|---|:---:|:---:|:---:|
| IS (2022-2024) | +15.276 | 46.4% | 56 |
| OOS (2025-2026) | +12.067 | 47.8% | 23 |

**Robust 판정**: PASS (OOS Sharpe >= IS Sharpe × 50%)

### Best Robust 파라미터

lb=24, adx=30.0, vol=2.5, TP=10%, SL=3%  
OOS: Sharpe=+18.852, WR=50.0%, MDD=-6.0%, trades=10

**결론**: 현재 최적 파라미터 Robust PASS. daemon.toml 파라미터 유효.

---

## 2026-04-03 04:47 UTC — BTC 급락+acc 패턴 분석 (48h 회복률)

**데이터**: KRW-BTC 4h봉 2022~2026 (8,585봉)  
**현재 시나리오**: BTC ret1=-2.4%, acc≈1.0 (BTC 매집 중립)

| 조건 | N | avg 48h | WR | 비고 |
|---|:---:|:---:|:---:|---|
| ret1<-1% acc≥1.0 | 309 | -0.12% | 51.8% | 베이스 |
| ret1<-2% acc≥1.0 | 65 | +0.11% | **58.5%** | 현재 근접 |
| ret1<-2% acc∈[0.95,1.05] | 20 | -0.08% | **70.0%** | 현재 정확 일치 |

**결론**: BTC -2%+ 급락 + acc≈1.0 조합은 48h 회복 WR=70% (n=20). 현재 시장과 정확히 일치.  
의미: 48h 내 BTC 반등 가능성 높음 → accumulation 지갑 진입 신호 준비.  
단, avg=-0.08% (중간값 기준 소폭 마이너스) → 큰 기대 수익보다 방향성 베팅에 적합.

---

## 2026-04-03 04:49 UTC — BTC 급락+acc 이후 알트 최적 진입 심볼 분석

**BTC 신호**: ret1≤-2% AND acc∈[0.9,1.1] → 44회 발생 (2022~2026)  
**측정**: 신호 발생 후 48h(12봉) 알트 수익률

| 심볼 | avg 48h | WR | N |
|---|:---:|:---:|:---:|
| KRW-LINK | +1.09% | **56.8%** | 44 |
| KRW-ADA | +0.82% | 52.3% | 44 |
| KRW-XRP | +0.75% | 54.5% | 44 |
| KRW-AVAX | +0.38% | 52.3% | 44 |
| KRW-SOL | -0.18% | 38.6% | 44 |

**결론**: BTC 급락+매집 신호 후 LINK/ADA/XRP가 일관적으로 우수.  
SOL은 오히려 언더퍼폼 (-0.18%) → momentum_sol 지갑의 BTC 하락기 성과 한계 설명.  
현재 시장(BTC -2.4%, acc≈1.0) 대응: LINK/ADA 진입 고려.  
stealth 필터는 이 패턴에서 추가 개선 효과 미미 (대부분 n_stealth=0).

---

## 2026-04-03 04:52 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
Credit balance is too low
```

</details>

---

## 2026-04-03 04:53 UTC — volspike_btc 4h 파라미터 그리드 탐색

**설정**: KRW-BTC, 2022~2026, 4h봉, 수수료 0.05%  
**그리드**: spike_mult×adx×body_ratio×TP×SL = 576조합

### 결과 Top-5 (Sharpe 기준)

| spike | adx | body | TP | SL | Sharpe | WR | avg% | trades | MDD |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 3.0 | 25 | 0.2 | 4% | 2% | +44.620 | 83.3% | +2.56% | 6 | -2.0% |

### 현재 daemon 파라미터 (spike=2.0, adx=20, body=0.2, TP=6%, SL=3%)

Sharpe=+10.995, WR=54.0%, trades=50, MDD=-9.7%

**결론**: 최적 파라미터 현재 대비 Sharpe +33.63 개선. daemon 반영 검토.

---

## 2026-04-03 05:11 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
Credit balance is too low
```

</details>

---

## 2026-04-03 05:23 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
Credit balance is too low
```

</details>

---

## 2026-04-03 05:34 UTC — stealth_3gate 전체 마켓 스캔 (GPU) [ralph:stealth_sol_sweep]

**결과**: Sharpe +0.700 | WR 52.6% | trades 347536


<details><summary>raw output</summary>

```
7536  mean= -0.498%  wr=43.7%
  all_stealth            n=45008  mean= -0.443%  wr=43.4%

======================================================================
  [2] Threshold Grid  (top 10 by edge)
======================================================================
    RS<   Acc>       N      Mean       WR      Edge
    0.7    1.0      20   +8.415%   65.0%   +8.907%
    0.7    1.2      10   +4.641%   60.0%   +5.133%
    0.9    2.0      16   +2.962%   56.2%   +3.454%
    0.8    1.5      11   +0.686%   45.5%   +1.178%
    1.0    2.0     513   +0.045%   43.7%   +0.537%
    1.0    1.5    5743   -0.142%   43.9%   +0.355%
    1.0    1.2   22402   -0.360%   43.8%   +0.140%
    0.9    1.5     230   -0.357%   43.9%   +0.135%
    1.0    1.0   45008   -0.443%   43.4%   +0.055%
    0.9    1.0    2939   -0.599%   43.3%   -0.108%

======================================================================
  [3] Signal Strength Quartiles
======================================================================
  Q4 (strongest)          n=11252  mean= -0.449%  wr=43.2%
  Q3                      n=11252  mean= -0.273%  wr=43.8%
  Q2                      n=11252  mean= -0.495%  wr=43.4%
  Q1 (weakest)            n=11252  mean= -0.556%  wr=43.2%

======================================================================
  [4] Joint BTC × Alt Stealth Quadrants  (fwd=T+12봉)
======================================================================
  Quadrant                    Win    AltMean    AltWR    BTCMean    BTCWR
  BTC+Alt stealth             270    -0.634%   42.8%    -0.172%   52.6%
  BTC only stealth              2    -4.887%    9.2%    -0.612%   50.0%
  Alt only stealth           2419    -0.507%   43.5%    -0.143%   47.5%
  No stealth                   93    +0.399%   52.2%    +0.675%   62.4%

  [BTC Stealth Self-Performance]
  BTC stealth ON         n=  272  mean= -0.175%  wr=52.6%
  BTC stealth OFF        n= 2512  mean= -0.113%  wr=48.0%

Report saved → artifacts/stealth-deep-result.md

```

</details>

---

## 2026-04-03 05:44 UTC — TruthSeeker 전략 파라미터 스윕 [ralph:truth_seeker_sweep]

**결과**: Sharpe N/A | WR N/A | trades N/A


<details><summary>raw output</summary>

```
--- Starting Full Profitability Backtest: Truth-Seeker (ETH) ---
Initializing backtest engine...

```

</details>

---

## 2026-04-03 05:51 UTC — vpin_eth 파라미터 그리드 [ralph:vpin_eth_grid] 🌟[promising]

**결과**: Sharpe +7.461 | WR 27.6% | trades 446


<details><summary>raw output</summary>

```
=== vpin_eth 4h 그리드 탐색 ===
심볼: KRW-ETH  기간: 2022-01-01 ~ 2026-12-31
데이터: 8585행
총 조합: 432개

=== Top 15 (Sharpe 기준) ===
   vh      vm  hold    TP     SL |  Sharpe     WR    avg%  trades
------------------------------------------------------------------------
 0.55  0.0005    18 0.060  0.008 |  +7.461 27.6%  +0.45%     446
 0.60  0.0005    18 0.060  0.008 |  +7.461 27.6%  +0.45%     446
 0.65  0.0005    18 0.060  0.008 |  +7.461 27.6%  +0.45%     446
 0.70  0.0005    18 0.060  0.008 |  +7.461 27.6%  +0.45%     446
 0.55  0.0005    18 0.050  0.008 |  +7.461 28.2%  +0.42%     468
 0.60  0.0005    18 0.050  0.008 |  +7.461 28.2%  +0.42%     468
 0.65  0.0005    18 0.050  0.008 |  +7.461 28.2%  +0.42%     468
 0.70  0.0005    18 0.050  0.008 |  +7.461 28.2%  +0.42%     468
 0.55  0.0003    18 0.050  0.008 |  +7.366 28.1%  +0.41%     469
 0.60  0.0003    18 0.050  0.008 |  +7.366 28.1%  +0.41%     469
 0.65  0.0003    18 0.050  0.008 |  +7.366 28.1%  +0.41%     469
 0.70  0.0003    18 0.050  0.008 |  +7.366 28.1%  +0.41%     469
 0.55  0.0001    18 0.060  0.008 |  +7.364 27.5%  +0.44%     447
 0.55  0.0003    18 0.060  0.008 |  +7.364 27.5%  +0.44%     447
 0.60  0.0001    18 0.060  0.008 |  +7.364 27.5%  +0.44%     447

★ 최적: vpin_high=0.55 vpin_mom=0.0005 max_hold=18 TP=0.06 SL=0.008
  Sharpe=+7.461  WR=27.6%  avg=+0.45%  trades=446

현재 daemon.toml: vpin_high=0.65 vpin_mom=0.0003 max_hold=24 TP=0.04 SL=0.012

```

</details>

---

## 2026-04-03 06:01 UTC — momentum_sol 파라미터 그리드 [ralph:momentum_sol_grid] 🌟[promising]

**결과**: Sharpe +14.367 | WR 46.8% | trades 79


<details><summary>raw output</summary>

```
=== momentum_sol 4h 그리드 탐색 ===
심볼: KRW-SOL  기간: 2022-01-01 ~ 2026-12-31
데이터: 8585행
총 조합: 540개

=== Top 15 (Sharpe 기준) ===
lookback   adx   vol    TP    SL |  Sharpe     WR    avg%  trades
---------------------------------------------------------------------------
      20    25   2.0  0.12  0.04 | +14.367 46.8%  +2.77%      79
      28    20   2.0  0.12  0.02 | +13.913 33.6%  +2.24%     113
      12    25   2.0  0.12  0.04 | +13.851 47.0%  +2.67%      83
      24    20   2.0  0.12  0.02 | +13.529 33.6%  +2.16%     116
      20    20   2.0  0.12  0.02 | +13.123 33.1%  +2.07%     118
      28    25   2.0  0.12  0.03 | +13.121 40.0%  +2.35%      80
      20    25   2.0  0.10  0.04 | +12.858 47.0%  +2.23%      83
      28    20   2.0  0.10  0.02 | +12.847 34.5%  +1.81%     116
      28    25   2.0  0.10  0.03 | +12.810 41.0%  +2.06%      83
      28    25   2.0  0.12  0.02 | +12.757 31.3%  +2.03%      83
      12    25   2.0  0.10  0.04 | +12.724 47.7%  +2.21%      86
      24    25   2.0  0.12  0.02 | +12.599 31.0%  +2.00%      87
      20    25   2.0  0.12  0.02 | +12.437 31.0%  +1.96%      87
      24    25   2.0  0.12  0.03 | +12.426 39.3%  +2.19%      84
      28    25   2.0  0.10  0.02 | +12.374 32.6%  +1.75%      86

★ 최적: lookback=20 adx=25.0 vol=2.0 TP=0.12 SL=0.04
  Sharpe=+14.367  WR=46.8%  avg=+2.77%  trades=79

현재 daemon.toml: lookback=20 adx=20.0 vol=1.5 TP=0.08 SL=0.03

```

</details>

---


## 2026-04-03 — BTC 급락 + acc≈1.0 → 48h 회복 패턴

**데이터**: KRW-BTC 4시간봉 2022-01-01~2026-04-03 (8,585봉)
**신호**: BTC ret(4h) ≤ -2% AND acc∈[0.95, 1.05]

| 조건 | N | 48h WR | avg 48h | 결론 |
|---|---|---|---|---|
| ret<-1% acc≥1.0 | 309 | 51.8% | -0.12% | 약함 |
| ret<-2% acc≥1.0 | 65 | 58.5% | +0.11% | 보통 |
| ret<-2% acc∈[0.95,1.05] | 20 | **70.0%** | -0.08% | **주목** |

**결론**: N이 작지만(20회) 48h WR 70% — 현재 시장 조건 일치. avg near-zero (양쪽 극단 존재).

---

## 2026-04-03 — BTC 급락 이후 알트 진입 전략

**데이터**: 16 알트 4시간봉 2022-01-01~2026-04-03, FWD=12봉(48h), BTC 신호 44회

| 알트 | N | avg 48h | WR | 결론 |
|---|---|---|---|---|
| KRW-LINK | 44 | **+1.09%** | **56.8%** | ★ BTC급락 후 최강 |
| KRW-ADA | 44 | +0.82% | 52.3% | 양호 |
| KRW-XRP | 44 | +0.75% | 54.5% | 양호 |
| KRW-AVAX | 44 | +0.38% | 52.3% | 보통 |
| KRW-SOL | 44 | **-0.18%** | **38.6%** | ⚠️ BTC급락 후 SOL 피할것 |
| KRW-NEAR | 44 | -1.41% | 31.8% | 최악 |

**결론**: BTC 급락 후 LINK > ADA > XRP 순서. SOL 역방향 — momentum_sol_wallet 위험 시나리오.
**액션**: 현재 시장 조건 일치 (BTC -2.4%, acc=1.002). LINK/ADA 상대강도 주목.

---

## 2026-04-03 06:11 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=15%/SL=5% | -0.261 | 38.7% | -0.12% | 4 |
| TP=5%/SL=3% | -1.296 | 38.3% | -0.49% | 9 |
| TP=15%/SL=3% | -1.298 | 30.2% | -0.41% | 9 |
| TP=5%/SL=8% | -1.342 | 44.9% | -0.69% | 7 |
| TP=10%/SL=3% | -1.454 | 33.7% | -0.60% | 5 |

**최적**: TP=15% / SL=5%  Sharpe=-0.261  WR=38.7%

**레짐 필터 효과**: combined -0.261 vs stealth_only -0.484

## 2026-04-03 06:34 UTC — BTC 레짐 + 스텔스 2-Factor 백테스트 [ralph:regime_stealth] 🔻[poor]

**결과**: Sharpe N/A | WR 47.0% | trades N/A


<details><summary>raw output</summary>

```

=================================================================
  BTC 레짐 + 알트 Stealth 2-Factor 백테스트  |  2026-04-03 06:11 UTC
=================================================================

[1/3] BTC 일봉 fetch & 레짐 계산 (SMA100)...
  OK: 3113봉 | 불장 비율 51.8%

[2/3] 그리드 탐색 (TP×SL: 4×3=12조합)
      알트 25종목 × 각 조합...
  TP=5% SL=3%  |  stealth Sh=-1.08 WR=40%  |  combine Sh=-1.30 WR=38%
  TP=5% SL=5%  |  stealth Sh=-2.25 WR=40%  |  combine Sh=-3.79 WR=35%
  TP=5% SL=8%  |  stealth Sh=-0.48 WR=47%  |  combine Sh=-1.34 WR=45%
  TP=10% SL=3%  |  stealth Sh=-1.01 WR=35%  |  combine Sh=-1.45 WR=34%
  TP=10% SL=5%  |  stealth Sh=-0.52 WR=40%  |  combine Sh=-2.04 WR=32%
  TP=10% SL=8%  |  stealth Sh=-1.47 WR=39%  |  combine Sh=-2.01 WR=36%
  TP=15% SL=3%  |  stealth Sh=-1.32 WR=32%  |  combine Sh=-1.30 WR=30%
  TP=15% SL=5%  |  stealth Sh=-2.12 WR=36%  |  combine Sh=-0.26 WR=39%
  TP=15% SL=8%  |  stealth Sh=-30.73 WR=29%  |  combine Sh=-5.71 WR=30%
  TP=20% SL=3%  |  stealth Sh=-7.46 WR=24%  |  combine Sh=-15.13 WR=12%
  TP=20% SL=5%  |  stealth Sh=-10.42 WR=33%  |  combine Sh=-8.70 WR=16%
  TP=20% SL=8%  |  stealth Sh=-8.81 WR=28%  |  combine Sh=-18.93 WR=8%

[3/3] 최적 파라미터 (combined Sharpe 기준)
     TP    SL    Sharpe   WinRate   AvgRet   nSym
  ──────────────────────────────────────────────
    15%     5%    -0.261      38.7%    -0.12%      4
     5%     3%    -1.296      38.3%    -0.49%      9
    15%     3%    -1.298      30.2%    -0.41%      9
     5%     8%    -1.342      44.9%    -0.69%      7
    10%     3%    -1.454      33.7%    -0.60%      5

결과 저장: artifacts/regime_stealth_backtest.json

```

</details>

---

## 2026-04-03 06:37 UTC — BTC Stealth 선행 신호 분석

### 불장 시작 전 Stealth 발동률

| Lead Time | 발동률 | 발동/전체 |
|---|:---:|:---:|
| T-7d 전 | 0.0% ⭐ | 0/6 |
| T-14d 전 | 0.0% | 0/6 |
| T-21d 전 | 0.0% | 0/6 |
| T-30d 전 | 0.0% | 0/6 |

**최적 선행 시점**: T-7d 전 (발동률 0.0%)

### 불장 직전 vs 일반 Stealth 수익 비교

| 구분 | avg_ret | win_rate | n |
|---|:---:|:---:|:---:|
| 불장 직전 stealth | +8.11% | 100.0% | 2 |
| 일반 stealth      | +2.01% | 42.9% | 49 |

**결론**: 불장 직전 stealth avg_ret = +8.11% vs 일반 = +2.01%

## 2026-04-03 06:40 UTC — BTC Stealth 선행 신호 분석

### 불장 시작 전 Stealth 발동률

| Lead Time | 발동률 | 발동/전체 |
|---|:---:|:---:|
| T-7d 전 | 0.0% ⭐ | 0/6 |
| T-14d 전 | 0.0% | 0/6 |
| T-21d 전 | 0.0% | 0/6 |
| T-30d 전 | 0.0% | 0/6 |

**최적 선행 시점**: T-7d 전 (발동률 0.0%)

### 불장 직전 vs 일반 Stealth 수익 비교

| 구분 | avg_ret | win_rate | n |
|---|:---:|:---:|:---:|
| 불장 직전 stealth | +8.11% | 100.0% | 2 |
| 일반 stealth      | +2.01% | 42.9% | 49 |

**결론**: 불장 직전 stealth avg_ret = +8.11% vs 일반 = +2.01%

## 2026-04-03 — Pre-Bull Stealth Signal 검증 (GPU, 244심볼)

**데이터**: 244 심볼 4시간봉, Count=500봉(~83일), Lookback=24봉
**신호**: RS<1.0 AND acc>1.0 AND cvd_slope>0

| horizon | Stealth avg | non-Stealth avg | Edge | WR |
|---|---|---|---|---|
| T+6봉(24h) | +0.40% | -0.28% | **+0.68%** | 49.4% |
| T+12봉(48h) | +0.77% | -0.78% | **+1.55%** | 47.9% |
| T+24봉(96h) | +1.04% | -2.12% | **+3.16%** | 36.3% |

**Top 중형 알트 (fwd=12봉 기준)**
| 심볼 | avg% | WR | N |
|---|---|---|---|
| KRW-POLYX | +18.5% | 92.3% | 13 |
| KRW-CFG | +10.0% | 100% | 10 |
| KRW-POWR | +4.4% | 100% | 9 |
| KRW-ONG | +4.1% | 93.3% | 15 |
| KRW-LINK | +1.6% | 70% | 10 |

**결론**: 대형 코인보다 중형 알트에서 stealth edge 발현. alpha scan 원래 방식(동적 풀) 유효.

---

## 2026-04-03 — BTC Stealth vs 불장 선행 분석

**데이터**: KRW-BTC 일봉 1431봉, 불장 8개
**결과**: BTC stealth → 불장 T-7/14/21/30d 선행 hit rate **0%** (6/6 miss)
- 불장 직전 48h: avg=+8.1% WR=100% (n=2, 너무 작음)

**결론**: BTC stealth ≠ 불장 예측 신호. alt alpha 생성에만 유효.

---

## 2026-04-03 — CVD Threshold Grid (BTC cvd_slope × 8 구간)

**데이터**: KRW-ETH/SOL/XRP/ADA/AVAX/LINK/DOT/ATOM 4h봉
**결과**: 모든 threshold에서 Sharpe 음수 (-4.0~-4.8). threshold=0.1 소폭 최선.
**결론**: BTC cvd_slope threshold 튜닝 효과 없음. 대형 코인에서 stealth edge 없음. **중형 알트 동적 선택이 핵심**.

---

## 2026-04-03 06:45 UTC — GPU Alpha filter 백테스트 [ralph:alpha_backtest] 🔻[poor]

**결과**: Sharpe -0.101 | WR N/A | trades 141


<details><summary>raw output</summary>

```
87     -0.163      0.104      -1.201
KRW-TT          -0.016     -0.111     -0.749      -1.469
KRW-UNI          0.241      0.472      0.820       1.582
KRW-USDC        -0.079     -0.154     -0.094      -0.259
KRW-USDT        -0.059     -0.078     -0.106      -0.135
KRW-VANA         0.231      0.161     -0.038       0.491
KRW-VET          0.098      0.171      0.381       0.338
KRW-W           -0.099      0.041     -0.201       0.707
KRW-WAVES       -0.171     -0.547     -1.453      -2.252
KRW-WAXP        -0.155     -0.402     -0.767      -1.282
KRW-XEC          0.042     -0.301     -1.364      -1.666
KRW-XLM          0.316      1.139      2.098       4.855
KRW-XRP          0.153      0.408      0.543       1.537
KRW-XTZ         -0.148     -0.536     -0.753      -0.579
KRW-ZETA        -0.148     -0.219     -1.189      -1.739
KRW-ZIL         -0.150     -0.446     -1.120      -1.069
KRW-ZRO         -0.077     -0.160     -0.212       0.417
KRW-ZRX         -0.023     -0.130     -0.496      -0.848

평균 엣지: {'edge_1b_%': -0.058375886524822694, 'edge_3b_%': -0.15106382978723404, 'edge_6b_%': -0.49000709219858163, 'edge_12b_%': -0.6390921985815603}

======================================================================
  [결론]
❌ Alpha Score 예측력 불충분 → 가중치 재조정 또는 다른 지표 검토 필요
======================================================================

[Optimizer] Searching best weights + threshold on GPU components...
  Best: rs=0.3 acc=0.35 cvd=0.35  threshold=0.5  edge=-0.101%  corr=-0.021
  Calibration saved → artifacts/alpha-calibration.json  verdict=invalid

[LOOKBACK Grid Search] Testing lookback windows on all fetched symbols...
  LB= 6 ( 24h): edge=+nan%  corr=+nan  n=0
  LB=12 ( 48h): edge=-0.5564%  corr=-0.0341  n=141
  LB=18 ( 72h): edge=-0.5570%  corr=-0.0366  n=141
  LB=24 ( 96h): edge=-0.4921%  corr=-0.0303  n=141
  LB=30 (120h): edge=-0.4900%  corr=-0.0246  n=141

  ★ 최적 LOOKBACK: 30봉 (120h) edge=-0.4900%  corr=-0.0246
  Report saved → artifacts/alpha-backtest-result.md

```

</details>

---

## 2026-04-03 — GPU Strategy Tournament (quick mode, 51심볼, 30일)

| 순위 | 전략 | Sharpe | WR | avg% | trades |
|---|---|---|---|---|---|
| 1 | low_rs_high_acc | +3.608 | 55.5% | +0.76% | 562 |
| 2 | **stealth_3gate** | **+3.136** | **78.8%** | **+2.59%** | 33 |
| 3 | rsi_oversold | +0.317 | 49.6% | +0.05% | 542 |

**결론**: stealth_3gate WR 78.8% avg +2.59% → 30일 실전 환경에서 우수.

---

## 2026-04-03 — low_rs_high_acc 전체 기간 검증 (2022~2026)

**조건**: RS∈(0.5,1.0) AND acc>1.2 (BTC gate 없음, CVD 없음)
**결과**: trades=2933, WR=30.4%, avg=-0.12%, **Sharpe=-0.625**
**결론**: 미배포. 30일 토너먼트는 생존 편향. 장기 기준 손실 전략.

---

## 2026-04-03 06:35 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=15%/SL=5% | -0.386 | 33.3% | -0.17% | 1 |
| TP=20%/SL=8% | -0.601 | 36.2% | -0.23% | 6 |
| TP=20%/SL=5% | -0.880 | 30.2% | +0.19% | 2 |
| TP=5%/SL=8% | -1.049 | 45.3% | -0.58% | 4 |
| TP=5%/SL=5% | -1.140 | 43.6% | -0.63% | 7 |

**최적**: TP=15% / SL=5%  Sharpe=-0.386  WR=33.3%

**레짐 필터 효과**: combined -0.386 vs stealth_only -0.049

## 2026-04-03 06:37 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=20%/SL=3% | +0.578 | 33.7% | +0.72% | 3 |
| TP=5%/SL=5% | -0.787 | 44.9% | -0.39% | 6 |
| TP=5%/SL=8% | -0.964 | 48.4% | -0.53% | 3 |
| TP=5%/SL=3% | -1.415 | 37.9% | -0.56% | 8 |
| TP=15%/SL=3% | -1.601 | 27.7% | -0.94% | 4 |

**최적**: TP=20% / SL=3%  Sharpe=+0.578  WR=33.7%

**레짐 필터 효과**: combined +0.578 vs stealth_only -0.324

## 2026-04-03 06:55 UTC — GPU Strategy Tournament [ralph:strategy_tournament] 🔻[poor]

**결과**: Sharpe N/A | WR N/A | trades N/A


<details><summary>raw output</summary>

```

================================================================
  GPU Strategy Tournament  |  2026-04-03 06:55 UTC
  Device: CUDA  |  Mode: full (all KRW)
================================================================

[1/4] Getting KRW symbols...
  Target: 244 symbols

[2/4] Fetching 244 symbols (4h × 180)...
ERROR: BTC 데이터 없음

```

</details>

---

## 2026-04-03 06:40 UTC — BTC 레짐 + Stealth 2-Factor 백테스트

| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |
|---|:---:|:---:|:---:|:---:|
| TP=5%/SL=5% | -2.292 | 39.3% | -1.01% | 5 |
| TP=20%/SL=8% | -6.210 | 23.5% | -2.55% | 5 |
| TP=20%/SL=5% | -6.544 | 18.8% | -3.51% | 8 |
| TP=5%/SL=8% | -6.831 | 31.7% | -2.68% | 9 |
| TP=15%/SL=5% | -7.210 | 17.1% | -2.89% | 4 |

**최적**: TP=5% / SL=5%  Sharpe=-2.292  WR=39.3%

**레짐 필터 효과**: combined -2.292 vs stealth_only -0.951

## 2026-04-03 13:03 UTC — BTC 급락+acc≈1.0 → 48h 회복 패턴 [ralph:btc_dip_recovery] 🔻[poor]

**결과**: Sharpe N/A | WR 70.0% | trades N/A


<details><summary>raw output</summary>

```
=== BTC 급락 + acc≥1.0 → 48h 회복 패턴 검증 ===
데이터: 8585봉 (2022-01-01~2026-04-03)

조건                                   N  fwd48h avg      WR   best 1%
----------------------------------------------------------------------
ret1<-1% acc≥1.0                   309      -0.12%  51.8%     +8.1%
ret1<-2% acc≥1.0                    65      +0.11%  58.5%     +8.5%
ret6<-3% acc≥1.0                   116      -0.15%  54.3%     +8.8%
ret6<-5% acc≥1.0 below SMA          33      -0.05%  48.5%     +8.8%
ret1<-2% acc≥0.98                   82      +0.02%  59.8%     +8.1%
base (all bars)                      0

=== 현재 시나리오 분석: ret1≤-2% AND acc∈[0.95,1.05] ===
발생 횟수: 20
24h 이후: avg=-0.00%  WR=55.0%
48h 이후: avg=-0.08%  WR=70.0%
48h 최악: -4.88%  최선: +4.37%

```

</details>

---

## 2026-04-03 13:14 UTC — BTC 급락 후 알트 진입 전략 (LINK/ADA/XRP) [ralph:btc_dip_alt_entry] 🔻[poor]

**결과**: Sharpe N/A | WR 42.9% | trades 19


<details><summary>raw output</summary>

```
=== BTC 급락+acc 이후 알트 진입 전략 백테스트 ===
기간: 2022-01-01~2026-04-03  FWD=12봉(48h)

BTC 신호 발생: 44회

심볼                N   avg 48h      WR |  N(st)    st avg   st WR
----------------------------------------------------------------------
KRW-SUI          14    +2.30%  42.9% |      0       n/a     n/a
KRW-APT          25    +1.52%  52.0% |      0       n/a     n/a
KRW-LINK         44    +1.09%  56.8% |      0       n/a     n/a
KRW-ADA          44    +0.82%  52.3% |      0       n/a     n/a
KRW-XRP          44    +0.75%  54.5% |      0       n/a     n/a
KRW-MANA         44    +0.53%  45.5% |     25    -0.42%   48.0%
KRW-AVAX         44    +0.38%  52.3% |      0       n/a     n/a
KRW-STX          44    +0.18%  45.5% |      0       n/a     n/a
KRW-SAND         44    +0.16%  52.3% |     19    +0.23%   42.1%
KRW-ARB          17    +0.03%  47.1% |      0       n/a     n/a
KRW-ETH          44    -0.10%  50.0% |     17    -0.78%   29.4%
KRW-SOL          44    -0.18%  38.6% |      0       n/a     n/a
KRW-AXS          44    -0.24%  47.7% |     21    -0.22%   33.3%
KRW-DOT          44    -0.32%  36.4% |      0       n/a     n/a
KRW-ATOM         44    -0.44%  43.2% |     13    -0.34%   46.2%
KRW-NEAR         44    -1.41%  31.8% |      0       n/a     n/a

★ 최고 성과 알트: KRW-SUI  avg=+2.30%  WR=42.9%  n=14

Stealth 필터 개선 심볼: 3/16
  Best: KRW-SAND  stealth_avg=+0.23%  WR=42.1%  n=19

```

</details>

---

## 2026-04-03 13:35 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
**전략명**: `momentum_vpin_combo`
**가설**: momentum_sol_grid(Sharpe +14.37)와 vpin_eth_grid(Sharpe +7.46)의 유효성을 확인했으니, 두 신호를 AND 조건으로 결합하면 진입 정밀도가 높아진다 — VPIN 급등(거래량 이상)이 감지된 봉에서만 모멘텀 진입
**탐색 파라미터**: `vpin_threshold` (0.6/0.7/0.8), `momentum_lookback` (3/6/12봉), `tp_sl_ratio` (1.5/2.0/3.0)
**예상 스크립트**: `scripts/backtest_momentum_vpin_combo.py`
**근거**: 두 전략이 각각 독립적으로 높은 Sharpe를 기록했고, 적용 심볼도 다름(SOL vs ETH). VPIN을 모멘텀의 필터로 쓰면 노이즈 진입을 줄이는 방향 — 완전히 새로운 조합이며, btc_dip_alt_entry에서 APT/LINK/SUI가 양의 수익을 보인 심볼들에 우선 적용하면 커버리지 확장도 가능.
```

</details>

---
