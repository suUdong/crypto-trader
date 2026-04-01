# 플랜: 불장 전→후 최대 수익 로테이션 전략

**작성**: 2026-04-02  
**기한**: 1주일 (우선순위 높은 것부터)  
**목표**: 불장 시작 전 진입 → 불장 종료 시 청산, 최대 수익

---

## 핵심 인사이트 (현재까지 백테스트에서)

- 3-gate stealth 룰은 유효하지만 **전체 기간 평균은 하락장이 오염**
- 불장 구간만 골라서 백테스트해야 전략 평가 가능
- BTC stealth 92.9% win rate은 **BTC 자체 수익** 기준 — 불장 직전 신호
- 알트 순환: BTC 먼저 → 대형알트 → 중형알트 → 소형알트 시차 존재

---

## Opus 리뷰 피드백 (2026-04-02)

1. 불장 정의 → **Option A(SMA50 골든크로스)로 확정**
2. `src/crypto_trader/strategy/btc_regime_rotation.py` 이미 존재 → 새로 짜지 말고 불장 필터 추가
3. Phase 3(알트 시차)은 1주일 내 불필요 → 제거
4. 청산: `BTC SMA20 이탈 + 2봉 연속 확인`으로 구체화

---

## Phase 1 — 불장 구간 라벨링 ⭐ 최우선

**목표**: 과거 BTC 데이터에서 불장 시작/종료 날짜 명확히 추출

```python
# 불장 정의: BTC SMA50 골든크로스(SMA20 > SMA50) → 데스크로스 (확정)
bull_start = sma20 crosses above sma50
bull_end   = sma20 crosses below sma50  OR  고점 대비 -20% (2봉 연속)
```

**역사적 불장 기간 (웹서치 확인):**
| 사이클 | 시작 | 고점 | 수익률 |
|---|---|---|---|
| 2017 | ~2017.01 | 2017.12 $19,800 | +9,879% |
| 2020~21 | ~2020.10 | 2021.11 $69,000 | +1,614% |
| 2024~25 | **2024.10** (SMA50/200 골든크로스) | 2024.12 $108K → 2025.10 $126K | +72%~ |

→ **현재 테스트 데이터(83일 ≈ 2026.01~04)는 2024~25 불장 고점 이후 조정 구간**
→ **데이터 400일 이상으로 늘려야 불장 구간 포함 가능 (COUNT=2500+ for 4h bars)**

**스크립트**: `scripts/identify_bull_periods.py`
**아웃풋**: `artifacts/bull_periods.json` (시작일, 종료일, 고점, 상승률)

---

## Phase 2 — 불장 전 선행 신호 분석 ⭐⭐ 핵심

**목표**: 불장 시작 몇 봉 전에 BTC stealth 발동되는지 측정

```
불장 시작 T=0 기준:
  T-24h: BTC stealth 발동률?
  T-48h: BTC stealth 발동률?
  T-72h: BTC stealth 발동률?
```

**기대**: BTC stealth가 불장 시작 24~48h 전에 집중 → 선행 진입 가능

**스크립트**: `scripts/backtest_bull_leadup.py`

---

## Phase 3 — 알트 로테이션 시차 분석

**목표**: 불장 내 어떤 종목이 먼저 오르는지 순서 파악

```
불장 구간 내:
  T+0 ~ T+48h:  BTC + ETH 먼저
  T+48h ~ T+5d: 대형 알트 (SOL, BNB 등)
  T+5d ~:       중소형 알트 순환
```

**스크립트**: `scripts/backtest_rotation_timing.py`

---

## Phase 4 — 통합 백테스트 (불장 구간만)

**목표**: Phase 1~3 결과로 최적 파라미터 도출

진입 조건:
```
1. BTC stealth 발동 (불장 T-48h 선행)
2. 불장 초기: BTC/ETH/SOL
3. 불장 중기: 중형 알트 (stealth 순서대로)
4. 청산: 불장 종료 신호 (SMA 이탈 or 고점 대비 -20%)
```

목표 지표: 승률 >55%, avg수익 >+2%, Sharpe >1.0

---

## Phase 5 — 데몬 적용

- `daemon.toml`에 `btc_regime_rotation` 월렛 추가
- paper trading 1주 → live 소액

---

## 우선순위 (1주일 기한, Opus 리뷰 반영)

| 순서 | 작업 | 예상 시간 | 상태 |
|---|---|---|---|
| 1 | Phase 1: 불장 구간 라벨링 (SMA50 기준) | 2h | ⬜ 대기 |
| 2 | Phase 2: BTC stealth 선행 분석 | 3h | ⬜ 대기 |
| 3 | Phase 4: 기존 btc_regime_rotation.py에 불장 필터 추가 | 4h | ⬜ 대기 |
| 4 | Phase 5: 데몬 적용 (paper trading) | 2h | ⬜ 대기 |
| ~~5~~ | ~~Phase 3: 알트 로테이션 시차~~ | 제거 | ❌ 다음주 |

**1주일 현실적 목표**: Phase 1~2 + btc_regime_rotation 확장 + paper trading 시작
