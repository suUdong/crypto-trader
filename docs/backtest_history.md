# Backtest History

모든 백테스트 결과를 누적 기록. CLAUDE.md 토큰 절약 목적.
새 테스트 완료 시 반드시 이 파일에 추가할 것.

---

## 포맷

| 날짜 | 전략 | 파라미터 | 거래수 | 승률 | avg수익 | Sharpe | 결론 |
|---|---|---|---|---|---|---|---|

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
