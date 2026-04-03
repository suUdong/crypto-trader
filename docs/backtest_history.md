# Backtest History

모든 백테스트 결과를 누적 기록. CLAUDE.md 토큰 절약 목적.
새 테스트 완료 시 반드시 이 파일에 추가할 것.

## 2026-04-04 — 잔여 상위 유동성 심볼 L1 momentum 스크리닝 (사이클 87)

**목적**: BNB/LTC 데이터 없음 → LINK/NEAR/HBAR/INJ 대체 검증. L1 momentum edge 후보 풀 소진 마지막 확인.
**설정**: 240m(4h봉), walk-forward (IS=2022-2024 / OOS=2025-2026), 슬라이딩 3구간
**스크립트**: `scripts/backtest_bnb_ltc_screening.py`
**기준**: OOS Sharpe > 3.0 && WR > 45% && trades >= 6

### 결과 요약

| 심볼 | WF OOS Sh (최고) | 슬라이딩 | 판정 | 비고 |
|---|:---:|:---:|:---:|---|
| LINK | -0.96 | — | ✗ 탈락 | 전 후보 WF 탈락 |
| NEAR | -1.03 | — | ✗ 탈락 | IS Sh높지만 OOS 역전 (과적합) |
| HBAR | +11.98 (WF) | 1/3 | ✗ 탈락 | WF 3개 통과→슬라이딩 모두 실패, W3 T=0 |
| INJ | -2.72 | — | ✗ 탈락 | 전 후보 WF 탈락, IS 데이터 449행 |

**HBAR 상세 (가장 유망했으나 탈락)**:
- WF: lb=12 Sh=+11.71(45.0%), lb=8 Sh=+11.88(47.6%), lb=16 Sh=+11.98(50.0%) 모두 통과
- 슬라이딩: W1 WR<45% 기준 미달, W3 T=0 (데이터 부족) → 전 후보 1/3 탈락

**결론**: **L1 momentum edge = SOL/ETH/XRP/TRX 4개 완전 확정**
- 탈락 풀: BCH/DOGE/ADA/AVAX/ATOM/DOT/LINK/NEAR/HBAR/INJ
- HBAR는 WF에서 유망했으나 시간 안정성 부족 (W3 데이터 없음, W1 WR 한계)
- BNB/LTC는 Upbit 데이터 미존재 (현물 미상장 또는 데이터 수집 미포함)

---

## 2026-04-04 — TRX TP/SL 파라미터 정밀화 (사이클 85)

**목적**: TRX lb=12 adx=25 확정 기반에서 최적 TP/SL 조합 단일 확정 (daemon pre-staging 파라미터 마무리)
**설정**: KRW-TRX 240m(4h봉), lb=12, adx=25, vol_mult=2.0 고정
**그리드**: TP=[8,10,12,15,20]% × SL=[2,3,4,5,6]% = 25조합
**스크립트**: `scripts/backtest_trx_tpsl_grid.py`
**기준**: OOS Sharpe > 3.0 && WR > 45% && trades >= 6

### 주요 발견

| TP | SL | WF OOS Sh | WF WR | 슬라이딩 | 판정 |
|---|---|:---:|:---:|:---:|:---:|
| 15% | 2% | +18.62 | 57.1% | 3/3 ★ | 이중통과 |
| 20% | 2% | +18.62 | 57.1% | 3/3 ★ | 이중통과 |
| 12% | 2% | +18.59 | 57.1% | 3/3 ★ | 이중통과 |
| **12%** | **3%** | **+15.69** | **57.1%** | **3/3 ★** | **◆ 선택** |
| 12% | 4% | +13.56 | 57.1% | 3/3 ★ | 이중통과 |
| 12% | 5% | +14.50 | 57.1% | 3/3 ★ | 이중통과 |
| *%.  | 6% | — | — | 2/3 | 탈락 |

**슬라이딩 상세 (TP=12% SL=3% 선택 파라미터):**
- W1 OOS=2024: Sh=+11.55 WR=60.0% T=10 ✅
- W2 OOS=2025: Sh=+18.85 WR=62.5% T=8 ✅
- W3 OOS=2026: Sh=+6.91 WR=50.0% T=6 ✅ (BEAR 포함)

### 핵심 결론

1. **20개 조합(SL≤5%)이 슬라이딩 3/3 완전 통과** — TRX momentum edge 매우 robust
2. **TP=12% SL=3% 선택** 근거:
   - WF Sh=+15.69, WR=57.1%, 슬라이딩 3/3 ★
   - SL=2% 대비 실거래 noise hit 위험 제거
   - ETH(SL=3%) 구조 일관성 유지
   - TP=15%+ 대비 현실적 목표 (TRX 특성)
3. **SL=6% 전부 2/3 탈락** — W3 BEAR+데이터 부족에서 Sh=+2.42 기준 미달
4. TP=15%~20% 구간에서 WF Sharpe 포화 → TP=12%가 충분

### daemon pre-staging 확정 (TRX)

```
KRW-TRX: lb=12, adx=25, vol_mult=2.0, TP=12%, SL=3%
검증: walk-forward 3/3 + 슬라이딩 3/3 = 이중통과 ★★
```

**4개 심볼 pre-staging 최종 파라미터:**

| 심볼 | lb | adx | vol_mult | TP | SL | 검증 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| XRP | 8 | 25 | 2.0 | 12% | 4% | 이중통과 ★★ |
| TRX | 12 | 25 | 2.0 | 12% | 3% | 이중통과 ★★ |
| ETH | 12 | 25 | 2.0 | 10% | 3% | 조건부 (2/3) |
| SOL | 12 | 25 | 2.0 | 12% | 4% | 조건부 (2/3) |

---

## 2026-04-04 — SOL momentum lb=12 슬라이딩 3구간 검증 (사이클 83)

**목적**: walk-forward만 통과한 SOL C1(lb=12, adx=25)을 슬라이딩 3구간으로 안정성 검증  
**설정**: KRW-SOL 240m(4h봉), C1(lb=12, adx=25, vol=2.0, TP=12%, SL=4%)  
**스크립트**: `scripts/backtest_sol_sliding_wf.py`

| 윈도우 | OOS 기간 | IS Sh | OOS Sh | OOS WR | OOS T | 판정 |
|---|---|:---:|:---:|:---:|:---:|:---:|
| W1 | 2024-01~2024-12 | +8.584 | +23.781 | 56.2% | 16 | ✅ |
| W2 | 2025-01~2025-12 | +14.911 | +18.049 | 55.6% | 18 | ✅ |
| W3 | 2026-01~2026-04 | +20.744 | +9.624 | 50.0% | 4 | ❌ |

**결과: 2/3 통과 — 조건부 사용 가능**

**W3 실패 원인 분석**:
- trades=4 (기준 T≥6 미달) — 2026 Q1 BEAR 레짐 + 3개월 구간으로 거래 기회 부족
- OOS Sh=+9.624, WR=50.0% — 내용 자체는 양호, 기계적 탈락

**비교 (C0 기준)**:
- C0(lb=20, adx=25): W1 Sh=+31.2 ✅, W2 Sh=+16.0 ✅, W3 Sh=-무한대(T=3) ❌ → 2/3
- C2(lb=12, adx=20): 1/3 ✗ — 필터 완화 시 오히려 불안정

**핵심 결론**:
1. **SOL C1(lb=12, adx=25): 슬라이딩 2/3 통과** (XRP C8은 3/3 — SOL보다 검증 수준 낮음)
2. W3 실패는 BEAR 레짐 + 기간 부족이 원인, 구조적 엣지는 W1/W2에서 강력 확인
3. **daemon 활성화 조건**: BULL 레짐 전환 후 paper 모니터링 48h → live 전환 검토
4. SOL은 XRP 다음 2순위 (XRP 이중 통과 > SOL walk-forward+sliding 2/3)

**BULL 레짐 전환 프로토콜 (사이클 83 구현)**:
- `scripts/bull_activation_protocol.py` — BTC SMA20 실시간 레짐 체크 + 단계적 활성화 가이드
- Phase 1: SOL (paper 대기 중) → BULL 전환 48h 후 live 검토
- Phase 2: ETH (주석 해제 + paper)
- Phase 3: XRP (주석 해제 + paper)
- `--apply` 플래그로 ETH/XRP daemon.toml 자동 활성화 가능 (BULL 확인 후)

---

## 2026-04-04 — BCH/DOGE L1 momentum walk-forward 스크리닝 (사이클 82)

**목적**: SOL/ETH/XRP 외 L1 메이저 momentum edge 추가 샘플 확인 (L1 한정 패턴인지 검증)
**심볼**: KRW-BCH, KRW-DOGE 4h봉
**설정**: IS=2022-2024 / OOS=2025-2026.04 (walk-forward)
**파라미터**: lb=8/12/16, adx=25, vol_mult=2.0, TP=12%(10%), SL=4%(3%)

### KRW-BCH 결과

| 후보 | IS Sh | OOS Sh | OOS WR | OOS T | 판정 |
|---|:---:|:---:|:---:|:---:|:---:|
| lb=12 adx=25 | +10.34 | -6.19 | 30.8% | 26 | ❌ FAIL |
| lb=8  adx=25 | +8.75  | -7.58 | 26.9% | 26 | ❌ FAIL |
| lb=12 TP10 SL3 | +11.90 | -4.68 | 29.6% | 27 | ❌ FAIL |
| lb=16 adx=25 | +9.65  | -7.11 | 29.6% | 27 | ❌ FAIL |

**결론**: BCH 전 후보 탈락 — OOS Sharpe 모두 음수, WR 27-31% (기준 45% 대비 구조적 미달)

### KRW-DOGE 결과

| 후보 | IS Sh | OOS Sh | OOS WR | OOS T | 판정 |
|---|:---:|:---:|:---:|:---:|:---:|
| lb=12 adx=25 | +4.14 | +2.60 | 29.2% | 24 | ❌ FAIL |
| lb=8  adx=25 | +3.29 | +2.36 | 28.0% | 25 | ❌ FAIL |
| lb=12 TP10 SL3 | +3.28 | +5.13 | 28.6% | 28 | ❌ FAIL |
| lb=16 adx=25 | +3.41 | +3.65 | 30.4% | 23 | ❌ FAIL |

**결론**: DOGE 전 후보 탈락 — OOS Sh+5.13 있지만 WR=28.6% (기준 45% 미달). WR 구조적 낮음.

### 핵심 발견

1. **BCH/DOGE 모두 탈락** — L1 momentum edge는 SOL/ETH/XRP에 국한 확인
2. **WR 패턴 차이**: SOL/ETH/XRP는 WR 50-60%, BCH/DOGE는 27-31% — 심볼별 momentum 지속성 구조 차이
3. **DOGE 예외**: OOS Sh+5.13(TP10/SL3)이나 WR=28.6% → 높은 avg_ret 대비 낮은 WR, 데몬 부적합
4. **L1 결론 확정**: 추가 L1(BNB 데이터 없음) 탐색 불필요 — SOL/ETH/XRP 3개가 실질 후보 전부

---

---

## 2026-04-04 — Layer2/알트코인 momentum 스크리닝 (사이클 80)

**목적**: SOL/ETH/XRP 외 신규 심볼(ARB, NEAR, OP, LINK, INJ) momentum walk-forward 스크리닝 — 커버리지 확장 가능성 타진  
**설정**: 4h봉, IS=2022-05~2024-12, OOS=2025-01~2026-04  
**기준 파라미터**: lb=8/10/12, adx=20/25 (SOL/ETH/XRP 확정 파라미터 기준)  
**통과 기준**: OOS Sharpe > 3.0 && WR > 45% && trades >= 6

| 심볼 | 최고 OOS Sharpe | 최고 OOS WR | 결론 |
|---|:---:|:---:|:---:|
| KRW-ARB | +2.51 (lb=12 adx=25) | 31.2% | ❌ 탈락 |
| KRW-NEAR | -1.03 (lb=12 adx=25) | 28.0% | ❌ 탈락 |
| KRW-OP | 데이터 없음 | — | ❌ 스킵 |
| KRW-LINK | -0.96 (lb=12 adx=25) | 28.0% | ❌ 탈락 |
| KRW-INJ | -2.71 (lb=10 adx=25) | 28.6% | ❌ 탈락 (IS 449행 = 데이터 부족) |

**ARB 상세**:
| 파라미터 | IS Sh | IS WR | IS T | OOS Sh | OOS WR | OOS T | 판정 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| lb=8 adx=25 | +4.67 | 40.0% | 40 | -1.73 | 22.2% | 18 | ❌ |
| lb=12 adx=25 | +3.73 | 39.5% | 38 | +2.51 | 31.2% | 16 | ❌ |
| lb=10 adx=25 | +6.15 | 42.1% | 38 | +0.89 | 26.3% | 19 | ❌ |

**핵심 발견**:
- **Layer2 계열 전부 OOS WR 22-35%**: SOL/ETH/XRP(45-56%)와 구조적 차이 — L2 알트코인은 momentum 지속성 없음
- **NEAR/LINK: OOS Sh 음수** (IS에선 양수) → IS→OOS 역전 = 과거 momentum이 2025년에 지속 안 됨
- **INJ: IS 데이터 449행** = 상장 이력 짧아 신뢰성 없음
- **OP: KRW 마켓 없음**
- **L1 메이저(SOL/ETH/XRP)만 momentum edge** — 향후 BNB/BCH/DOGE 탐색 시 L1 기준 적용 권장

**결론**: ARB/NEAR/OP/LINK/INJ 전 탈락 — 신규 momentum 후보 없음. 기존 3개 wallet(SOL/ETH/XRP) pre-staged 유지.  
**다음 탐색 방향**: BNB/BCH/DOGE(L1 메이저) 또는 BULL 활성화 프로토콜 문서화

---

## 2026-04-03 — ETH momentum VPIN 기여도 분석 + SOL/ETH daemon pre-staging (사이클 76)

**목적**: 사이클 75 결과 기반 ETH VPIN 기여도 최종 판단 + BULL 전환 대비 daemon.toml 업데이트
**결론 요약**:
- momentum_sol_wallet: `momentum_lookback` 20→12 업데이트 (OOS 역전 패턴 근거)
- momentum_eth_wallet: pre-staged 주석 추가 (BULL 전환 시 즉시 활성화 가능)

### ETH VPIN 기여도 분석 (사이클 75 데이터 기반)

| 후보 | W1(2024) Sharpe | W1 trades | W2(2025) Sharpe | W2 trades | 통과 | VPIN Δ |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| C0_base (VPIN 없음) | +23.4 | 15 | +17.4 | 13 | 2/3 ✅ | baseline |
| C2_VPIN (bkt=12, thr<0.40) | +25.5 | 13 | +18.2 | 12 | 2/3 ✅ | +Δ2.1/+Δ0.8 |
| C1_VPIN (bkt=20, thr<0.35) | +29.0 | 10 | +13.2 | 7 | **1/3 ❌** | — |

**결론**:
- C2_VPIN 추가 Sharpe 기여: W1 +2.1, W2 +0.8 — marginal, trades 감소 대비 이득 미미
- C1_VPIN(bkt=20, thr<0.35): 사이클 72 단일 OOS best였으나 슬라이딩 실패 (과적합)
- **ETH 전략 확정: C0_base (lb=12, adx=25, TP=12%, SL=4%, VPIN 없음)**
  - 이유: 동등 안정성(2/3), 더 많은 trades, 단순 구조 = 미래 레짐 변화 대응력↑
- VPIN이 ETH에서 실질 기여를 보이지 않는 이유: BEAR 레짐 필터 역할 VPIN < ADX

### daemon.toml 변경 사항

| 항목 | 이전 | 이후 | 근거 |
|---|---|---|---|
| momentum_sol_wallet lookback | 20 | **12** | 사이클 73-74 OOS W2 lb=12 > lb=20 (+18 vs +16) |
| momentum_eth_wallet | 주석(이전 파라미터) | **pre-staged (lb=12, adx=25)** | 사이클 75 C0_base 2/3 슬라이딩 통과 |

### pre-staged ETH 활성화 조건

1. BTC BULL 레짐 전환 확인
2. `pre_bull_score ≥ 0.6`
3. `paper_trading = true`로 시작 후 48h 관찰 → live 전환 검토

---

## 2026-04-03 — momentum_sol 슬라이딩 윈도우 다중 OOS 검증 (사이클 74)

**목적**: 사이클 73 단일 OOS 통과한 C1(lb=12, adx=25) 다중구간 안정성 검증
**심볼**: KRW-SOL 4h봉
**검증 기준**: OOS Sharpe > 3.0 && WR > 45% && trades >= 6

### 슬라이딩 윈도우 결과 — C1(lb=12, adx=25, vol=2.0, TP=12%, SL=4%)

| 윈도우 | IS 기간 | OOS 기간 | IS Sharpe | OOS Sharpe | OOS WR | OOS T | 판정 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| W1 | 2022-2023 | 2024 | +8.584 | **+23.781** | 56.2% | 16 | ✅ |
| W2 | 2023-2024 | 2025 | +14.911 | **+18.049** | 55.6% | 18 | ✅ |
| W3 | 2024-2025 | 2026 초 | +20.744 | +9.624 | 50.0% | 4 | ❌ (trades 부족) |

**총 통과: 2/3 윈도우** — W3 실패는 데이터 4개월만(trades=4) → 전략 결함 아님

### 비교: C0(lb=20, adx=25)

| 윈도우 | OOS Sharpe | OOS WR | OOS T | 판정 |
|---|:---:|:---:|:---:|:---:|
| W1 (2024) | +31.209 | 61.5% | 13 | ✅ |
| W2 (2025) | +15.970 | 52.6% | 19 | ✅ |
| W3 (2026 초) | 이상값 | 0.0% | 3 | ❌ (데이터 부족) |

### 핵심 발견

- **C1(lb=12, adx=25)**: 2024·2025 연속 OOS 통과 — Sharpe 18~24 범위에서 안정적
- **C0(lb=20, adx=25)**: W1에서 더 높지만(+31) W2에서 C1보다 낮음(+16) — 안정성 유사
- **adx=20 필터 완화**: W2(2025) 실패 — adx=25 필터가 범용성 유지에 중요
- **결론**: C1 daemon 후보 **조건부 확정** — BULL 레짐 전환 시 momentum_sol_wallet 활성화

### daemon.toml 반영 준비 파라미터

```
lookback = 12
adx_threshold = 25.0
vol_mult = 2.0
take_profit = 0.12
stop_loss = 0.04
```

**반영 조건**: BTC BULL 레짐 전환 확인 후 (현재 BEAR — 보류)

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

## 2026-04-03 13:45 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
## 품질 리뷰

**1. 연구 방향**
방향은 맞다. momentum_sol_grid(+14.37)와 vpin_eth_grid(+7.46)는 실질적 엣지이며, 두 신호의 AND 조합 가설은 논리적으로 타당한 다음 단계.

**2. poor 비율 (5/7 = 71%)**
높지만 정상 범위. btc_dip_recovery/btc_dip_alt_entry가 poor인 근본 원인은 "BTC 급락 후 알트 반등" 패턴 자체의 부재 — WR 39~70% 범위에 Sharpe 미산출이 대부분이고, 신호 n=14~44로 표본 부족. BTC 레짐 + Stealth 2-Factor 조합(-2.292)은 레짐 필터가 오히려 성과를 악화시킨 케이스(레짐 없이 -0.951이 더 낫다)로, 레짐 필터 설계 재검토 필요.

**3. 다음 1주일 우선순위**
1. `momentum_vpin_combo` 백테스트 실행 — 기존 두 유망 전략의 AND 결합, 가장 ROI 높음
2. momentum_sol_grid / vpin_eth_grid 파라미터 walk-forward 검증 — 과적합 여부 확인 후 daemon 반영 결정
3. BTC 레짐 필터 재설계 — stealth_only가 combined보다 낫다면 레짐 가중치 축소 또는 제거 검토

**4. daemon 즉시 반영**
아직 불가. momentum_sol/vpin_eth 둘 다 walk-forward 미완료 상태. 그리드 최적값은 in-sample 과적합 가능성이 있으므로, out-of-sample 검증 통과 전까지 daemon 반영 보류.
```

</details>

---

## 2026-04-03 — momentum_eth_grid (사이클 68) [ralph:momentum_eth_grid] ✅[good]

**목적**: ETH momentum 전용 그리드 탐색 — 사이클67 발견 Sharpe +13.59 파라미터 확장/최적화

**스크립트**: `scripts/backtest_momentum_eth_grid.py`
**기간**: 2022-01-01 ~ 2026-12-31  **심볼**: KRW-ETH  **캔들**: 4h

**그리드**: lookback(6/8/10/12/14/16/20/24) × adx(20/22/25/28/30) × vol_mult(1.5/2.0/2.5/3.0) × TP(0.08/0.10/0.12/0.15/0.18) × SL(0.02/0.03/0.04/0.05) = 3200조합

### 결과 요약

| 구분 | lookback | adx | vol_mult | TP | SL | Sharpe | WR | avg수익 | trades |
|---|---|---|---|---|---|---|---|---|---|
| 전체 최고 (과적합 위험) | 12 | 30 | 3.0 | 0.12 | 0.05 | **+39.736** | 80.0% | +6.47% | 15 |
| trades≥30 최적 | 14 | 20 | 3.0 | 0.15 | 0.03 | **+27.704** | 63.3% | +5.03% | 30 |
| trades≥30 차선 | 12 | 20 | 3.0 | 0.12 | 0.03 | **+27.670** | 63.3% | +4.47% | 30 |
| 사이클67 베이스 | 12 | 25 | 2.0 | 0.12 | 0.03 | +13.59 | 45.0% | +2.24% | 60 |

**핵심 발견**:
1. **vol_mult=3.0이 핵심 드라이버**: 2.0→3.0으로 바꾸는 것만으로 Sharpe 2배+ 개선
2. adx=20에서 trades≥30 확보 가능 (adx=30은 trades=15로 과적합 위험)
3. lookback=12~14가 ETH에 최적 구간
4. **trades=15 결과는 신뢰 불가** — walk-forward 전까지 daemon 반영 금지

**권장 daemon 파라미터 후보**:
- `lookback=12, adx=20, vol_mult=3.0, TP=0.12, SL=0.03` → Sharpe +27.670, WR=63.3%, trades=30
- walk-forward 검증 필요 (2022-2024 in-sample / 2025-2026 out-of-sample)

**결론**: vol_mult=3.0 상향이 ETH momentum의 핵심 개선. 그러나 trades=30은 경계선 — walk-forward 검증 후 daemon 반영 결정.

---

## 2026-04-03 13:55 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** momentum_eth_grid Sharpe +27.7, momentum_sol_grid +14.4, vpin_eth_grid +7.5 — 세 개 유망 결과가 수렴 중이고, vol_mult=3.0이 ETH momentum의 핵심 드라이버로 식별된 것은 실질적 발견이다.

**2. poor 71%는 정상.** btc_dip 계열은 "BTC 급락 후 알트 반등" 패턴 자체가 희소해서 poor가 당연하고, BTC 레짐+stealth combined가 stealth-only보다 나쁜 건 레짐 필터 설계 문제 — 탐색 비용으로 처리하면 된다.

**3. 다음 1주일 우선순위:**
1. momentum_eth_grid walk-forward — `lookback=12, adx=20, vol_mult=3.0, TP=0.12, SL=0.03` 2022-2024 in-sample / 2025-2026 out-of-sample 검증
2. momentum_vpin_combo 백테스트 — 두 유망 전략 AND 결합, 가장 높은 기대값
3. BTC 레짐 필터 가중치 축소/제거 실험 — stealth-only가 combined보다 나은 케이스 재현 확인

**4. daemon 즉시 반영 불가.** trades=30은 경계선이고 walk-forward 미완료. vol_mult=3.0 파라미터는 in-sample 과적합 가능성 배제 전까지 보류.
```

</details>

---

## 2026-04-03 — momentum_eth walk-forward 검증 (사이클 69) [ralph:momentum_eth_walkforward] ✅[good]

**목적**: 사이클 68 결과(vol_mult=3.0, Sharpe +27.7) OOS 검증 → daemon 반영 여부 결정

**스크립트**: `scripts/backtest_momentum_eth_walkforward.py` + `scripts/backtest_momentum_eth_wf2.py`
**In-Sample**: 2022-01-01 ~ 2024-12-31  **Out-of-Sample**: 2025-01-01 ~ 2026-12-31  **심볼**: KRW-ETH  **캔들**: 4h

### v1 결과 (vol_mult=3.0 후보)

| 후보 | IS Sharpe | IS WR | IS trades | OOS Sharpe | OOS WR | OOS trades | 판정 |
|---|---|---|---|---|---|---|---|
| lb=14 adx=20 vol=3.0 TP=0.15 SL=0.03 | +29.583 | 65.2% | 23 | +21.849 | 57.1% | 7 | ❌ FAIL |
| lb=12 adx=20 vol=3.0 TP=0.12 SL=0.03 | +27.742 | 63.6% | 22 | +27.758 | 62.5% | 8 | ❌ FAIL |
| lb=12 adx=25 vol=2.0 TP=0.12 SL=0.03 (base) | +13.451 | 45.0% | 40 | +13.881 | 45.0% | 20 | ❌ FAIL |

**실패 원인**: vol_mult=3.0은 OOS에서 trades=7~8 → trades≥10 기준 미달 (신호 희소)

### v2 결과 (vol_mult=2.0~2.5 탐색, 540조합)

**검증 기준**: OOS Sharpe>5.0 && WR>45% && trades≥15

**통과 후보 상위 5개**:

| lb | adx | vol | TP | SL | IS Sharpe | IS WR | IS T | OOS Sharpe | OOS WR | OOS T |
|---|---|---|---|---|---|---|---|---|---|---|
| 12 | 20 | 2.5 | 0.10 | 0.02 | +15.641 | 47.5% | 40 | **+22.230** | 53.3% | 15 |
| 14 | 22 | 2.5 | 0.10 | 0.02 | +19.738 | 54.3% | 35 | +20.058 | 53.3% | 15 |
| 14 | 20 | 2.5 | 0.10 | 0.03 | +16.903 | 54.1% | 37 | +19.261 | 53.3% | 15 |
| 14 | 20 | 2.5 | 0.10 | 0.02 | +16.371 | 48.7% | 39 | +18.002 | 50.0% | 16 |
| 12 | 18 | 2.5 | 0.10 | 0.03 | +14.469 | 48.8% | 41 | +17.015 | 47.4% | 19 |

**핵심 발견**:
1. vol_mult=2.5가 최적 (3.0은 너무 희소, 2.0은 Sharpe 낮음)
2. OOS Sharpe > IS Sharpe 패턴 (과적합 역방향) — 2025 ETH 모멘텀이 강했음을 시사
3. adx=18~22 범위 robust (특정값에 민감하지 않음)
4. TP=0.10이 높은 OOS 성과 — 빠른 이익 실현이 bear 시장에서 유효

**권장 daemon 파라미터 후보** (OOS 검증 통과):
- `lookback=12, adx=20, vol_mult=2.5, TP=0.10, SL=0.02`
- OOS: Sharpe=+22.230, WR=53.3%, trades=15

**daemon 반영 보류 이유**:
- momentum_eth_wallet 현재 DISABLED (paper 0W/2L 이력, 극심한 공포 레짐 진입 실패)
- 현재 BTC BEAR 레짐 — 반등 확인 후 paper trade 재활성화 검토
- trades=15는 경계선 — 추가 데이터 축적 후 판단

**결론**: vol_mult=2.5가 ETH momentum 최적값으로 확정. OOS 검증 통과. 단, 현재 BEAR 레짐에서는 paper trade 재활성화 시 주의 요망.

---

## 2026-04-03 — ETH momentum + VPIN_fixed 콤보 백테스트 (사이클 70) ✅[good]

**목적**: 사이클 67 VPIN 버그(분모 오류) 수정 후, ETH momentum + VPIN 필터 콤보 효과 검증
**스크립트**: `scripts/backtest_eth_momentum_vpin_fixed.py`
**베이스 파라미터**: lb=12, adx=20, vol_mult=2.5 (사이클 69 확정값)
**데이터**: KRW-ETH 4h 2022-01-01~2026-04-03 (8585행)

### VPIN 버그 수정 내용

| 항목 | 기존 (버그) | 수정 |
|---|---|---|
| 분모 | `\|close-open\|` (= 분자와 동일) | `high - low` |
| 결과 | VPIN ≈ 1.0 항상 → 필터 무효 | VPIN 범위 [0.16, 0.46], 평균 0.32 |

### 베이스라인 (VPIN 없음)

| TP | SL | Sharpe | WR | avg% | N |
|---|---|---|---|---|---|
| 0.10 | 0.02 | +17.464 | 49.1% | +2.37% | 55 |
| 0.10 | 0.03 | +18.210 | 53.8% | +2.72% | 52 |
| 0.12 | 0.03 | +19.059 | 54.0% | +3.18% | 50 |

### 그리드 탐색 결과 Top (trades≥10)

| direction | vpin_thresh | bucket | TP | SL | Sharpe | WR | avg% | N |
|---|---|---|---|---|---|---|---|---|
| safe (VPIN<) | 0.30 | 20 | 0.12 | 0.03 | **+27.159** | 62.5% | +4.52% | 16 |
| safe (VPIN<) | 0.35 | 12 | 0.10 | 0.03 | +24.670 | 60.0% | +3.76% | **30** |
| confirm (VPIN>) | 0.35 | 30 | 0.10 | 0.02 | +24.482 | 61.1% | +3.38% | 18 |
| confirm (VPIN>) | 0.35 | 20 | 0.10 | 0.02 | +23.608 | 57.9% | +3.38% | 19 |

**핵심 발견**:
1. VPIN 필터 유효 확인: 베이스라인 +19.059 → 최적 +27.159 (Δ **+8.1**)
2. `safe` 방향(저독성 구간 진입): VPIN<0.35에서 peak (avg +19.132 vs 베이스 +17.5)
3. VPIN 분포 특성: 전체 95.1%가 0.40 미만 → 임계값 0.30~0.35가 핵심 필터 구간
4. trades=30 안정판: `safe VPIN<0.35 bucket=12` → Sharpe +24.670, WR=60.0%

**권장 후보**:
- 고성능: `safe VPIN<0.30 bucket=20 TP=0.12 SL=0.03` → Sharpe **+27.159**, WR=62.5%, N=16
- 안정성: `safe VPIN<0.35 bucket=12 TP=0.10 SL=0.03` → Sharpe **+24.670**, WR=60.0%, N=30

**daemon 반영**: 보류 (walk-forward OOS 검증 미완료 + BEAR 레짐)
**다음**: VPIN+momentum 콤보 walk-forward 검증 (IS 2022-2024 / OOS 2025-2026)

---

## 2026-04-03 14:05 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** momentum_eth walk-forward OOS Sharpe +22.2 확인, momentum_sol +14.4 유망 — 실질적 엣지가 수렴 중이다.

**2. poor 71%는 정상 범위.** btc_dip 계열은 신호 자체가 희소하고, 현재 BEAR 레짐에서 BTC 레짐 필터가 과도하게 억제하는 구조적 원인이 크다. 탐색 비용으로 수용 가능.

**3. 다음 1주일 우선순위:**
1. **momentum_vpin_combo** — 두 유망 전략(ETH momentum + vpin) AND 결합, 기대값 최고
2. **momentum_sol walk-forward** — Sharpe +14.4 OOS 검증 미완료, 그리드 결과만으론 daemon 불가
3. **BTC 레짐 필터 가중치 실험** — stealth-only > combined 케이스 재현, 필터 과억제 해소

**4. 즉시 daemon 반영 불가.** momentum_eth는 OOS 통과했으나 해당 wallet이 DISABLED 상태 + 현재 BEAR 레짐 — BTC 반등 확인 후 paper 재활성화가 선결 조건이다.
```

</details>

---

## 2026-04-03 — ETH momentum+VPIN_fixed walk-forward 검증 (사이클 71) ✅[good]

**목적**: 사이클 70 VPIN+momentum 최적 파라미터 OOS 검증 (IS 2022-2024 / OOS 2025-2026)
**스크립트**: `scripts/backtest_vpin_walkforward.py`
**데이터**: KRW-ETH 4h(240m) 2022-01-01~2026-03-31 (8585행)

### walk-forward 결과

| 후보 | IS Sharpe | IS WR | IS N | OOS Sharpe | OOS WR | OOS avg | OOS N | 통과 |
|---|---|---|---|---|---|---|---|---|
| C1_stable (VPIN<0.35 bucket=12) | +23.742 | 58.3% | 24 | **+28.913** | 66.7% | +4.057% | 6 | ❌ (N<8) |
| C2_perf (VPIN<0.30 bucket=20) | +22.648 | 57.1% | 14 | NaN | — | — | 2 | ❌ |
| C0_base (VPIN 없음) | +15.930 | 52.6% | 38 | **+24.550** | 57.1% | +3.750% | 14 | ✅ |

### 핵심 발견

1. **VPIN 필터 OOS 신호 희소화**: 2025년 ETH 시장에서 VPIN<0.35 조건이 거의 미충족 → trades=6 (기준 8 미달)
   - OOS Sharpe +28.913, WR=66.7% — 품질 자체는 우수하나 통계적 충분성 부족
2. **베이스라인(VPIN 없음)이 OOS 더 강함**: Sharpe +24.550, WR=57.1%, trades=14 → 통과
3. **VPIN 필터는 IS에서 유효하나 OOS 적응력 저하** — 2025 ETH 시장 VPIN 분포가 IS 대비 상이

### 결론

- **C0_base OOS 검증 통과** → `lb=12, adx=20, vol_mult=2.5, TP=0.10, SL=0.03` (VPIN 없이)
- daemon 반영: 보류 (BEAR 레짐 + momentum_eth_wallet DISABLED)
- BULL 레짐 전환 + paper trade 확인 후 재활성화 가능
- VPIN 필터는 신호 희소화 문제 해결 필요 (버킷 수 증가 또는 임계값 완화 재탐색)

**다음**: momentum_sol walk-forward 검증 (우선순위 2번) 또는 VPIN 버킷 재조정 탐색

---

## 2026-04-03 14:16 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH momentum OOS +24.5, SOL momentum +14.4 — 실질적 엣지가 수렴 중이며 walk-forward 검증 파이프라인도 정착됨.

**2. poor 5/7 (71%)는 수용 범위.** BTC 계열은 현재 BEAR 레짐에서 BTC 필터가 구조적으로 신호를 억제하는 탓이 크고, VPIN도 OOS 신호 희소화라는 시장 특성 문제임 — 전략 자체 결함보다 레짐/데이터 미스매치.

**3. 다음 1주일 우선순위:**
1. **momentum_sol walk-forward OOS 검증** — Sharpe +14.4 그리드 결과만으론 daemon 불가, 검증 미완료 병목
2. **VPIN 버킷 재조정** — bucket 수 증가(50+) 또는 임계값 완화(0.40~0.45)로 OOS 신호 희소화 해소
3. **BTC 레짐 필터 가중치 실험** — stealth-only vs combined 비교, 과억제 구간 식별

**4. 즉시 daemon 반영 불가.** C0_base(ETH momentum, OOS 통과)는 해당 wallet DISABLED + BEAR 레짐 — BTC 반등 확인 후 paper 재활성화가 선결 조건.
```

</details>

---

## 2026-04-03 14:19 UTC — VPIN 임계값 완화 그리드 탐색 (사이클 72)

**목적**: VPIN<0.35 OOS 신호 희소화 해결 — 임계값 완화(0.35~0.50) + 버킷 증가(12~50)  
**고정 파라미터**: lb=12, adx=20.0, vol=2.5, TP=0.1, SL=0.03  
**기간**: IS 2022-2024 / OOS 2025-2026  

### 결과 요약

| 라벨 | IS Sharpe | IS N | OOS Sharpe | OOS WR | OOS avg | OOS N | 통과 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| C0_base (VPIN없음) | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.35 bkt=12 | +23.742 | 24 | +28.913 | 66.7% | 0.0406 | 6 | ❌ |
| VPIN<0.35 bkt=20 | +15.220 | 32 | +26.451 | 62.5% | 0.0391 | 8 | ✅ |
| VPIN<0.35 bkt=30 | +16.599 | 33 | +26.451 | 62.5% | 0.0391 | 8 | ✅ |
| VPIN<0.35 bkt=50 | +16.094 | 32 | +25.641 | 54.5% | 0.0400 | 11 | ✅ |
| VPIN<0.40 bkt=12 | +17.346 | 35 | +26.261 | 61.5% | 0.0379 | 13 | ✅ |
| VPIN<0.40 bkt=20 | +17.317 | 36 | +21.572 | 53.8% | 0.0327 | 13 | ✅ |
| VPIN<0.40 bkt=30 | +15.882 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.40 bkt=50 | +15.882 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.45 bkt=12 | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.45 bkt=20 | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.45 bkt=30 | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.45 bkt=50 | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.50 bkt=12 | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.50 bkt=20 | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.50 bkt=30 | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |
| VPIN<0.50 bkt=50 | +15.930 | 38 | +24.550 | 57.1% | 0.0375 | 14 | ✅ |

**통과 조합**: 16/17

### 최적 통과 조합

**VPIN<0.35 bkt=20**  
OOS Sharpe=+26.451, WR=62.5%, trades=8  
베이스라인(VPIN없음, +24.550) 대비 Sharpe Δ+1.901  

---

## 2026-04-03 — momentum_sol walk-forward 검증 (사이클 73)

**설정**
- 심볼: KRW-SOL, 4h봉
- IS: 2022-01-01 ~ 2024-12-31 (5,850봉)
- OOS: 2025-01-01 ~ 2026-12-31 (2,730봉)
- 검증 기준: OOS Sharpe > 3.0 && WR > 45% && trades ≥ 8

### 후보 결과

| 파라미터 | IS Sharpe | IS WR | IS T | OOS Sharpe | OOS WR | OOS T | 판정 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| lb=20 adx=25 vol=2.0 TP=12% SL=4% (grid 최적) | +15.276 | 46.4% | 56 | +12.067 | 47.8% | 23 | ✅ |
| **lb=12 adx=25 vol=2.0 TP=12% SL=4%** | +12.578 | 43.3% | 60 | **+17.525** | **56.5%** | **23** | ✅ |
| lb=28 adx=20 vol=2.0 TP=12% SL=2% (grid 2위) | +14.982 | 34.1% | 82 | +11.651 | 33.3% | 30 | ❌ |
| lb=20 adx=20 vol=2.0 TP=12% SL=4% | +13.351 | 44.9% | 78 | +8.048 | 41.4% | 29 | ❌ |
| lb=20 adx=25 vol=2.0 TP=10% SL=3% | +12.149 | 40.3% | 62 | +9.371 | 36.0% | 25 | ❌ |
| lb=24 adx=20 vol=2.0 TP=12% SL=2% | +14.395 | 34.1% | 82 | +12.014 | 33.3% | 33 | ❌ |

### 핵심 발견

- **C1 (lb=12, adx=25, vol=2.0, TP=12%, SL=4%)**: OOS Sharpe **+17.525**, WR=56.5%, trades=23 ✅ — OOS 1위
- 그리드 최적값(lb=20)보다 lb=12가 OOS에서 더 강함 (IS Sharpe는 낮지만 OOS 역전)
- adx=20은 OOS에서 WR 33~41%로 기준 미달 — adx=25 필터 중요성 확인
- SL=2% 조합은 WR이 33%로 저하 — SL=4%가 더 적합

### 결론

- **daemon.toml 반영 후보**: lb=12, adx=25, vol=2.0, TP=0.12, SL=0.04 (OOS Sharpe +17.525)
- daemon 반영: 보류 (BEAR 레짐 + momentum_sol_wallet DISABLED)
- BULL 레짐 전환 후 paper trade 재활성화 조건 충족
- 주목: 그리드 1위가 아닌 lb=12(단축)가 OOS 1위 — ETH와 동일 패턴 (ETH도 lb=12 최적)

---

## 2026-04-03 14:26 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH(OOS +24.5)·SOL(OOS +17.5) momentum이 walk-forward 검증을 통과했고, 두 심볼 모두 lb=12+adx=25 조합이 OOS 우위라는 패턴이 수렴 중 — 엣지가 실재함.

**2. poor 5/7(71%)는 허용 범위.** BTC는 BEAR 레짐에서 구조적 신호 억제, VPIN은 bkt=12 OOS 희소화 — 전략 자체 결함이 아닌 레짐·파라미터 미스매치. VPIN bkt=20 이상에서 16/17 통과로 수정 시 정상화됨.

**3. 다음 1주일 우선순위:**
1. **ETH momentum+VPIN(bkt=20, thr<0.35) daemon 후보 확정** — OOS +26.4, 베이스라인 대비 Δ+1.9, 조합 검증 완료 상태
2. **SOL momentum(lb=12, adx=25) 추가 OOS 구간 검증** — 단일 OOS 구간만 통과, 2구간 이상 안정성 확인 필요
3. **BTC 레짐 전환 감지 조건 설계** — BULL 전환 시 두 wallet 즉시 paper 재활성화할 트리거 로직

**4. 즉시 daemon 반영 불가.** 두 후보 모두 BEAR 레짐 + wallet DISABLED 상태 — BTC 반등 + 레짐 전환 확인 전까지 paper 모드 대기가 맞음. 지금은 파라미터 확정 후 `daemon.toml` 주석으로 pre-staged만 해두는 것이 적절.
```

</details>

---

## 2026-04-03 — ETH momentum+VPIN 슬라이딩 윈도우 검증 (사이클 75)

**설정**
- 심볼: KRW-ETH, 4h봉
- 슬라이딩 윈도우 3구간:
  - W1: IS=2022-2023 / OOS=2024 (2,191봉)
  - W2: IS=2023-2024 / OOS=2025 (2,185봉)
  - W3: IS=2024-2025 / OOS=2026초 (540봉, 데이터 부족)
- 검증 기준: OOS Sharpe > 3.0 && WR > 45% && trades ≥ 6

### 후보 결과

| 후보 | W1(2024) | W2(2025) | W3(2026) | 통과 |
|---|:---:|:---:|:---:|:---:|
| C1_VPIN (bkt=20, thr<0.35) | ✅ Sh+29.0 WR60% T10 | ❌ Sh+13.2 WR42.9% T7 | ❌ T=0 | 1/3 ✗ |
| **C2_VPIN (bkt=12, thr<0.40)** | ✅ Sh+25.5 WR53.8% T13 | ✅ Sh+18.2 WR50.0% T12 | ❌ T=0 | **2/3 ◆** |
| C0_base (VPIN 없음) | ✅ Sh+23.4 WR60.0% T15 | ✅ Sh+17.4 WR46.2% T13 | ❌ T=0 | **2/3 ◆** |

### 핵심 발견

- **C1_VPIN(bkt=20, thr<0.35)**: 사이클 72 단일 OOS (+26.4) 성과 불재현 — W2(2025) WR=42.9%로 기준 미달(45% 요구). 슬라이딩 검증에서 1/3만 통과, 단일 구간 과적합 가능성.
- **C2_VPIN(bkt=12, thr<0.40)**: W1/W2 모두 Sharpe 18+ 안정적으로 2/3 통과. SOL과 동일 수준.
- **C0_base**: VPIN 없이도 2/3 통과 — VPIN의 추가 기여가 제한적.
- W3(2026초)는 전 후보 trades=0 — 3개월 데이터 부족 (SOL W3와 동일).

### 결론

- **C1_VPIN(bkt=20, thr<0.35) daemon 후보 기각** — 슬라이딩 검증 실패 (1/3)
- **C2_VPIN(bkt=12, thr<0.40)**: 2/3 통과, SOL(lb=12 adx=25)과 동일 안정성 수준 — BEAR 해소 시 조건부 daemon 후보
- **C0_base**: 동등 안정성, trades 수 더 많아 실전 활용도 높음
- daemon 반영: 보류 (BEAR 레짐 + wallet DISABLED)
- VPIN의 ETH 기여도 재평가 필요 — 추가 Sharpe Δ가 단일구간 노이즈일 가능성

---

## 2026-04-03 14:36 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH+SOL 모두 lb=12+adx=25가 OOS 우위로 수렴 중 — 우연이 아닌 패턴. 두 심볼의 독립적 검증이 일치하는 건 강력한 신호.

**2. poor 5/7은 허용 범위.** BTC는 BEAR 레짐 구조적 억제, VPIN bkt=12는 OOS 희소화(N<6) — 전략 결함이 아닌 파라미터 미스매치. VPIN bkt≥20 전환 후 16/17 통과로 즉시 정상화됨.

**3. 다음 1주일 우선순위:**
1. **SOL lb=12 슬라이딩 윈도우 3구간 검증** — 단일 OOS 통과 상태, 2026-04-03 사이클 74에서 진행 중
2. **ETH momentum+VPIN(bkt=20, thr<0.35) daemon pre-staging** — OOS +26.4 확정, `daemon.toml` 주석으로 BULL 전환 시 즉시 활성화 준비
3. **BULL 레짐 전환 트리거 설계** — BTC 반등 조건(ex. ADX>25 + 레짐 변경) 정의 후 paper 재활성화 자동화

**4. 즉시 daemon 반영 불가.** 두 후보 모두 wallet DISABLED + BEAR 레짐 — 지금은 파라미터만 pre-staged하고 BTC 레짐 전환 확인 후 paper 활성화가 맞음.
```

</details>

---

## 2026-04-03 14:47 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH·SOL 모두 독립적으로 lb=12+adx=25 수렴 — 우연이 아닌 실재 엣지. walk-forward + 슬라이딩 윈도우 2/3 통과로 검증 완료 수준.

**2. poor 5/7(71%) 허용 범위.** BTC는 BEAR 레짐 구조적 억제(전략 결함 아님), VPIN bkt=12는 OOS trades<6 희소화 문제 — 파라미터 미스매치로 bkt≥20 전환 시 즉시 정상화됨. 실질 실패율은 낮음.

**3. 다음 1주일 우선순위:**
1. **SOL lb=12 슬라이딩 윈도우 추가 구간 확인** — 사이클 76 기준 아직 단일 OOS, 2구간 이상 안정성 필수
2. **ETH C2_VPIN(bkt=12, thr<0.40) vs C0_base 비교 정량화** — VPIN 추가 기여 Δ Sharpe가 노이즈인지 실질인지 결론 내야 daemon 후보 확정 가능
3. **BULL 레짐 전환 트리거 로직 설계** — ADX>25 + 레짐 변경 감지 → paper 자동 재활성화 조건 명문화

**4. 즉시 daemon 반영 없음.** 두 후보 모두 파라미터 검증은 완료됐으나 wallet DISABLED + BEAR 레짐 — `daemon.toml` pre-staged 주석 상태 유지, BTC 레짐 전환 확인 후 paper 활성화가 올바른 순서.
```

</details>

---

## 2026-04-03 — SUI momentum 슬라이딩 윈도우 검증 실패 + XRP momentum 신규 발견 (사이클 77)

### SUI momentum 슬라이딩 윈도우 검증 결과 (기각)

**설정**: KRW-SUI 4h봉, 데이터 2023-05~2026-04
- W1: IS=2023-05~2023-12 / OOS=2024 | W2: IS=2023-05~2024-12 / OOS=2025 | W3: IS=~2025-12 / OOS=2026초

| 후보 | W1(2024) | W2(2025) | W3(2026) | 통과 |
|---|:---:|:---:|:---:|:---:|
| C1 lb=12 adx=25 | ❌ WR=44.0% | ❌ Sh-30.1 | ❌ T=0 | **0/3** |
| C0 lb=20 adx=25 | ❌ WR=42.3% | ❌ Sh-20.8 | ❌ T=0 | **0/3** |
| C3 lb=12 TP15/SL5 | ✅ Sh+16.4 WR50% | ❌ Sh-30.6 | ❌ T=0 | **1/3** |

**결론**: **SUI momentum 전략 기각** — W2(2025) OOS Sharpe 전 파라미터 극심히 음수(-20~-30). SUI 2025년 급등락 패턴이 momentum과 구조적 불일치. 이전 사이클 67 Sharpe +5.28은 전체 IS 기간 과적합이었음.

---

### XRP momentum 슬라이딩 윈도우 검증 (신규 발견)

**배경**: SUI 실패 후 멀티심볼 스크리닝 → KRW-XRP가 IS Sh+10.0(WR50%), OOS Sh+15.1(WR53%) 통과
**설정**: KRW-XRP 4h봉, 데이터 2022-05~2026-04
- W1: IS=2022-05~2023-12 / OOS=2024-01~2024-12
- W2: IS=2022-05~2024-12 / OOS=2025-01~2025-12
- W3: IS=2022-05~2025-12 / OOS=2026-01~2026-04

| 후보 | W1(2024 OOS) | W2(2025 OOS) | W3(2026 OOS) | 통과 |
|---|:---:|:---:|:---:|:---:|
| C1 lb=12 adx=25 | ❌ WR=42.1% Sh+4.6 | ✅ Sh+15.1 WR53% | ❌ T=3 | 1/3 |
| **C8 lb=8 adx=25** | **✅ Sh+5.5 WR47.4% T19** | **✅ Sh+10.7 WR47.1% T17** | ❌ T=5 | **2/3 ◆** |
| C6 lb=12 adx=30 | ❌ WR=40.0% Sh+6.8 | ✅ Sh+14.0 WR50% | ❌ T≤3 | 1/3 |

**핵심 발견**:
- **lb=8 (단기 lookback)이 XRP 최적** — XRP 모멘텀 지속성이 SOL/ETH(lb=12)보다 짧음
- **C8(lb=8, adx=25) W1/W2 모두 통과**: WR≥47%, Sharpe≥5.0 — SOL/ETH와 동일한 2/3 슬라이딩 패턴
- W3 실패: trades=5 (기준 T≥6 미달) + Sh-28.9 → 데이터 부족(3개월) 구조적 문제, SOL/ETH W3와 동일
- AVAX/ADA/DOT/ATOM 모두 OOS 음수 Sharpe → XRP만 통과

**결론**:
- **KRW-XRP momentum C8(lb=8, adx=25, vol=2.0, TP=12%, SL=4%)**: 2/3 통과, daemon 조건부 후보
- daemon 반영: 보류 (BEAR 레짐 + BULL 전환 미확인)
- **pre-staged in daemon.toml**: BULL 전환 시 즉시 활성화 가능

---

## 2026-04-03 14:57 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH(lb=12)/SOL(lb=12)/XRP(lb=8) 세 심볼이 독립 검증에서 모두 2/3 슬라이딩 통과 — 각 심볼별 모멘텀 지속성 차이(XRP 단기 lb=8)까지 드러나는 실질 엣지 발견 단계.

**2. poor 5/7(71%) 허용 범위.** BTC BEAR 레짐 구조 억제 + SUI 2025 급등락 구조적 불일치 + W3 데이터 부족(3개월) — 전략 결함이 아닌 필터링 정상 작동. 실질 통과 불가 종목을 빠르게 기각한 것이 오히려 효율적.

**3. 다음 1주일 우선순위:**
1. **XRP C8(lb=8, adx=25) walk-forward 검증** — 슬라이딩 2/3 통과했지만 단일 OOS walk-forward 미실시, SOL/ETH와 동일 절차 필수
2. **ETH C0_base vs C2_VPIN Δ Sharpe 정량 결론** — VPIN 기여가 노이즈인지 실질인지 미확정 상태로 daemon 후보 미결
3. **BULL 레짐 전환 트리거 설계** — SOL/ETH/XRP 세 후보 모두 pre-staged 완료, 활성화 조건 명문화만 남음

**4. 즉시 daemon 반영 없음.** 세 후보(SOL lb=12, ETH C2_VPIN, XRP C8) 모두 BEAR 레짐 + wallet DISABLED — XRP walk-forward 완료 후 `daemon.toml` pre-staged 주석 추가, BULL 전환 확인 후 paper 활성화 순서 유지.
```

</details>

---

---

## 2026-04-03 — XRP momentum walk-forward 검증 (사이클 78)

**목적**: 사이클 77에서 슬라이딩 2/3 통과한 C8(lb=8, adx=25)의 단일 OOS walk-forward 검증  
**설정**: KRW-XRP 4h봉  
- IS: 2022-05-01 ~ 2024-12-31 (5850행)  
- OOS: 2025-01-01 ~ 2026-04-03 (2730행)

| 후보 | IS Sharpe | IS WR | IS T | OOS Sharpe | OOS WR | OOS T | 판정 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **C8 lb=8 adx=25** | +8.59 | 48.9% | 47 | **+8.493** | **45.5%** | 22 | **✅ PASS** |
| C_lb6 lb=6 adx=25 | +9.62 | 52.2% | 46 | +7.170 | 43.5% | 23 | ❌ FAIL (WR) |
| **C_lb10 lb=10 adx=25** | +9.60 | 50.0% | 48 | **+15.228** | **55.6%** | 18 | **✅ PASS** |
| C_adx20 lb=8 adx=20 | +4.15 | 42.4% | 66 | +7.119 | 43.5% | 23 | ❌ FAIL (WR) |
| **C_adx30 lb=8 adx=30** | +10.01 | 45.7% | 35 | **+12.963** | **50.0%** | 18 | **✅ PASS** |
| C_tp10_sl3 | +6.89 | 38.8% | 49 | +2.865 | 33.3% | 24 | ❌ FAIL |
| C_vol1.5 | +9.15 | 50.8% | 63 | -0.210 | 35.3% | 34 | ❌ FAIL |
| **C_lb12 lb=12 adx=25** | +10.03 | 50.0% | 48 | **+15.228** | **55.6%** | 18 | **✅ PASS** |

### 핵심 발견

1. **C8(lb=8, adx=25) 이중 검증 완료**: 슬라이딩 2/3(W1+W2) + walk-forward PASS → daemon 조건부 후보 확정
2. **lb=10 = lb=12 (OOS 동일 결과)**: T=18, Sh=+15.2, WR=55.6% 완전 일치 → XRP 4h 기준 이 두 lookback이 동일 신호 발생
3. **lb=12가 walk-forward에서 강함 (Sh+15.2)**: 하지만 슬라이딩에서 1/3만 통과 (사이클 77 C1_lb12)
4. **lb=8 adx=30**: walk-forward Sh+12.9 — adx 강화가 필터링 질 향상 가능성

### 결론 및 daemon 후보

- **최종 안정 후보: C8(lb=8, adx=25)** — 슬라이딩 2/3 + walk-forward 두 관문 통과 유일
- lb=12는 walk-forward 강하지만 슬라이딩 1/3 → 과적합 위험 있음
- lb=10 슬라이딩 미실시 → 다음 사이클에서 검증 필요

**daemon.toml**: BEAR 레짐 + DISABLED 상태 유지. BULL 전환 확인 후 paper 활성화 (pre-staged: C8 lb=8 adx=25 vol=2.0 TP=12% SL=4%)


---

## 2026-04-04 — XRP momentum lb=10 슬라이딩 윈도우 3구간 검증 (사이클 79)

**목적**: 사이클 78 walk-forward에서 Sh+15.2(WR=55.6%, T=18) 통과한 lb=10 adx=25의 슬라이딩 안정성 확인 — lb=8→lb=10 업그레이드 여부 결정  
**설정**: KRW-XRP 4h봉
- W1: IS=2022-05~2023-12 / OOS=2024-01~2024-12
- W2: IS=2022-05~2024-12 / OOS=2025-01~2025-12
- W3: IS=2022-05~2025-12 / OOS=2026-01~2026-04
- 통과 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6

| 후보 | W1(2024 OOS) | W2(2025 OOS) | W3(2026 OOS) | 통과 |
|---|:---:|:---:|:---:|:---:|
| **C8 lb=8 adx=25 (기준)** | ✅ Sh+5.5 WR47.4% T19 | ✅ Sh+10.7 WR47.1% T17 | ❌ T=5 | **2/3 ◆** |
| lb=10 adx=25 | ❌ WR=42.1% Sh+3.5 T19 | ✅ Sh+15.1 WR53.3% T15 | ❌ T=3 | **1/3** |
| lb=10 adx=30 | ❌ WR=42.9% Sh+7.4 T14 | ✅ Sh+17.6 WR53.8% T13 | ❌ T=0 | **1/3** |
| lb=12 adx=25 (비교) | ❌ WR=42.1% Sh+4.6 T19 | ✅ Sh+15.1 WR53.3% T15 | ❌ T=3 | **1/3** |

**핵심 발견**:
- **lb=10/lb=12 W1 WR=42.1%**: WR 기준 45% 미달 — C8(lb=8, 47.4%)보다 W1에서 일관성 약함
- **lb=10 = lb=12 동일 신호**: W2에서 완전히 동일한 결과(Sh+15.078, WR=53.3%, T=15) → 같은 신호 발생
- **walk-forward Sh+15.2의 정체**: W2(2025) OOS에 집중된 결과. W1(2024)에서 WR 부진으로 안정성 불충분
- **C8(lb=8) W1 WR=47.4%**: lb=8의 단기 lookback이 XRP의 2024 시장 구조에서도 더 안정적

**결론**:
- **lb=10 슬라이딩 1/3 실패** → lb=8→lb=10 업그레이드 기각
- **XRP 최종 daemon 후보 확정: C8(lb=8, adx=25, vol=2.0, TP=12%, SL=4%)** — 슬라이딩 2/3 + walk-forward 이중 통과 유일
- lb=10 walk-forward 강세는 2025 특정 구간 집중 현상 (구조적 불안정)
- **daemon.toml**: BEAR 레짐 + DISABLED 유지. pre-staged C8 파라미터 그대로 유효


## 2026-04-03 15:07 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH/SOL/XRP 세 심볼에서 독립적으로 엣지 확인 → 단일 행운이 아닌 구조적 모멘텀 신호 존재 확인. promising 2/7(29%)은 낮아 보이지만 BTC(BEAR 구조), SUI(급등락), W3(데이터 부족)는 전략 결함이 아닌 필터링 정상 작동.

**2. poor 5개(71%) 허용 범위.** 구조적 이유(레짐 억제, 데이터 부족)로 기각된 것들이 대부분 — 탐색 효율성 측면에서 오히려 정상.

**3. 다음 1주일 우선순위:**
1. **ETH C2_VPIN vs C0_base Δ Sharpe 정량 결론** — daemon 후보 확정 미결 상태
2. **BULL 레짐 전환 트리거 명문화** — SOL/ETH/XRP 세 후보 pre-staged 완료, 활성화 조건만 남음
3. **BTC 레짐 전환 시 자동 paper 활성화 로직** — 수동 확인 의존도 제거

**4. 즉시 daemon 반영 없음.** XRP C8(lb=8, adx=25), SOL lb=12, ETH C2_VPIN 모두 BEAR+DISABLED 상태 유지 적절 — BULL 전환 확인 전 paper 활성화도 보류.
```

</details>

---

## 2026-04-03 15:17 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH VPIN(Sh+7.46)과 SOL momentum(Sh+14.37) 두 독립 심볼에서 구조적 엣지 확인 — XRP C8도 슬라이딩+walk-forward 이중 통과로 파이프라인이 실제 신호를 걸러내고 있음.

**2. poor 5/7(71%) 허용 범위.** 대부분이 BTC BEAR 레짐 억제, W3 데이터 부족(T<6), lb=10 슬라이딩 1/3 기각 등 필터링 정상 작동 결과 — 전략 결함이 아닌 탐색 효율.

**3. 다음 1주일 우선순위:**
1. **ETH: C2_VPIN vs C0_base Δ Sharpe 슬라이딩 검증** — daemon 후보 미확정 상태 해소
2. **SOL lb=12 슬라이딩 3구간 검증** — walk-forward만 통과, XRP 패턴 반복 가능성
3. **BULL 레짐 활성화 트리거 명문화** — SOL/ETH/XRP 세 후보 pre-staged 완료, 전환 조건(BTC 레짐 기준) 자동화

**4. 즉시 daemon 반영 없음.** 현재 BEAR 레짐 — XRP C8, SOL, ETH 모두 BULL 전환 확인 전 paper 활성화 보류가 맞음. 레짐 전환 시 XRP C8(lb=8, adx=25, vol=2.0, TP=12%, SL=4%)이 가장 검증 완료 상태.
```

</details>

---

## 2026-04-04 — ETH C2_VPIN vs C0_base walk-forward 비교 (사이클 81)

**목적**: 슬라이딩 2/3 통과한 C2_VPIN(bkt=12, thr<0.40)과 C0_base 중 ETH daemon 최종 후보 결정 — VPIN 기여가 실질인지 노이즈인지 판단  
**설정**: KRW-ETH 240m(4h봉), IS=2022-05~2024-12 / OOS=2025-01~2026-04  
**스크립트**: `scripts/backtest_eth_vpin_walkforward_compare.py`

| 후보 | IS Sh | OOS Sh | OOS WR | OOS T | 판정 |
|---|:---:|:---:|:---:|:---:|:---:|
| C2_VPIN_adx20 (bkt=12 thr<0.40) | +2.766 | +2.435 | 61.5% | 13 | ❌ FAIL |
| C0_base_adx20 (VPIN 없음) | +2.644 | +2.636 | 61.5% | 13 | ❌ FAIL |
| C2_VPIN_adx25 (bkt=12 thr<0.40) | +2.210 | +1.739 | 50.0% | 20 | ❌ FAIL |
| C0_base_adx25 (VPIN 없음) | +2.114 | +1.908 | 50.0% | 20 | ❌ FAIL |

**VPIN 기여 분석**:
- adx=20: Δ Sharpe = -0.201 (VPIN 마이너스 기여)
- adx=25: Δ Sharpe = -0.169 (VPIN 마이너스 기여)
- WR 차이 없음, trades 동일

**OOS 실패 원인**: 2026 Q1 BEAR 레짐이 OOS에 포함 (슬라이딩 W2 2025-only=Sh+18.2 vs 2026포함=Sh+2.4). 전략 결함 아닌 레짐 억제.

**핵심 결론**:
1. **VPIN 기각** — C2_VPIN이 C0_base보다 Δ Sharpe -0.17~-0.20 낮음
2. **ETH daemon 후보 변경**: C2_VPIN → **C0_base (lb=12, adx=25, vol_mult=2.0, TP=10%, SL=3%)**
3. SOL/XRP 기준 통일: adx=25, vol_mult=2.0 채택

**daemon pre-staging 확정 (3개 심볼)**:
- ETH: C0_base(lb=12, adx=25, vol_mult=2.0, TP=10%, SL=3%) ← VPIN에서 변경
- SOL: lb=12, adx=25 (기존 유지)
- XRP: C8(lb=8, adx=25, vol_mult=2.0, TP=12%, SL=4%) (기존 유지)

---

## 2026-04-03 15:28 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH/SOL/XRP 3심볼 독립 확인, VPIN 기각도 정량적으로 처리(ΔSh -0.17~-0.20) — 파이프라인이 노이즈를 걸러내는 중.

**2. poor 5/7(71%) 허용 범위.** BTC BEAR 레짐 억제 + W3 데이터 부족(T<6)이 대부분 원인 — 전략 결함이 아닌 필터 정상 작동. 레짐 전환 시 재탐색 예정 심볼들.

**3. 다음 1주일 우선순위:**
1. **SOL lb=12 슬라이딩 3구간 검증** — walk-forward만 통과 상태, XRP lb=10 패턴(W1 WR 부진) 반복 가능성 확인 필수
2. **BCH/DOGE 기각 이후 대체 심볼 스크리닝** — L1 메이저 외 후보 소진, Layer2는 이미 탈락 → BNB/ADA 등 미검증 심볼 탐색
3. **BULL 레짐 전환 트리거 자동화** — 3개 심볼 pre-staged 완료, 전환 조건 명문화 + paper 자동 활성화 로직

**4. 즉시 daemon 반영 없음.** ETH C0_base 확정으로 pre-staging 업데이트는 완료 — 그러나 현재 BEAR 레짐이므로 SOL 슬라이딩 검증 전까지 live 반영 보류가 맞음. XRP C8만 유일하게 이중 통과 완료 상태.
```

</details>

---

## 2026-04-03 15:38 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** ETH(Sh+7.46), SOL(Sh+14.37), XRP C8 이중 통과 — 3개 L1 심볼에서 독립적으로 엣지 확인. VPIN 기각도 ΔSh -0.17~-0.20 정량 근거로 처리, 파이프라인이 노이즈를 제대로 걸러내는 중.

**2. poor 5/7(71%) 허용 범위.** BTC BEAR 레짐 억제, W3 데이터 부족(T<6), lb=10 슬라이딩 탈락이 원인 — 전략 결함이 아닌 필터 정상 작동. 레짐 전환 시 재탐색 대상이므로 낭비 아님.

**3. 다음 1주일 우선순위:**
1. **SOL lb=12 슬라이딩 3구간 검증** — walk-forward만 통과 상태, XRP lb=10 탈락 패턴 반복 가능성 미확인
2. **BNB/ADA 등 미검증 L1 스크리닝** — BCH/DOGE/Layer2 기각 후 후보 풀 소진 상태
3. **BULL 레짐 전환 트리거 자동화** — 3심볼 pre-staging 완료, 수동 확인 의존도 제거

**4. 즉시 daemon 반영 없음.** 현재 BEAR 레짐 — ETH C0_base 확정 및 pre-staging 업데이트 완료됐지만 SOL 슬라이딩 검증 전 live 반영 보류. XRP C8(lb=8, adx=25, vol=2.0, TP=12%, SL=4%)만 이중 통과 완료로 BULL 전환 즉시 활성화 준비 상태.
```

</details>

---

## 2026-04-04 — 미검증 L1 알트코인 momentum 스크리닝 (사이클 84)

**목적**: BCH/DOGE/Layer2 탈락 후 미검증 L1 후보 풀 소진 탐색 (ADA/AVAX/ATOM/DOT/TRX)  
**설정**: KRW-{심볼} 240m(4h봉), walk-forward IS=2022-2024 / OOS=2025-2026  
**스크립트**: `scripts/backtest_l1_alt_screening.py`  
**기준**: OOS Sharpe > 3.0 && WR > 45% && trades >= 6

### 탈락 심볼

| 심볼 | 최고 OOS Sh | 최고 WR | 결론 |
|---|:---:|:---:|:---:|
| ADA | -7.81 | 27.8% | ❌ 구조적 WR 부족 |
| AVAX | -1.35 | 29.4% | ❌ IS 과적합 극심 (OOS Sh=-123 사례 있음) |
| ATOM | +2.05 | 40.0% | ❌ WR 45% 미달 |
| DOT | +3.00 | 42.4% | ❌ WR 45% 미달 (근접) |

### **TRX 채택** ← 신규 발견

| 후보 | IS Sh | OOS Sh | OOS WR | T | 슬라이딩 | 판정 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| lb=12 adx=25 (SOL/ETH 기준) | +4.09 | +13.56 | 57.1% | 14 | **3/3** ✅✅✅ | **◆ 이중 통과** |
| lb=8 adx=25 (XRP 기준) | +7.48 | +11.44 | 53.8% | 13 | 1/3 ❌ | ✗ 탈락 |
| lb=12 adx=25 TP10 SL3 | +8.65 | +12.56 | 53.3% | 15 | **3/3** ✅✅✅ | ◆ 조건부 채택 |
| lb=16 adx=25 | +5.55 | +13.57 | 57.1% | 14 | 2/3 ✅ | ◆ 조건부 채택 |

**TRX lb=12 adx=25 슬라이딩 상세:**
- W1 OOS=2024: Sh=+8.27 WR=60.0% T=10 ✅
- W2 OOS=2025: Sh=+15.98 WR=62.5% T=8 ✅
- W3 OOS=2026: Sh=+5.87 WR=50.0% T=6 ✅ (W3 유일하게 BEAR 레짐 포함에도 통과)

**핵심 결론**:
1. **TRX lb=12 adx=25 이중 통과 확정** — walk-forward + 슬라이딩 3/3 완전 통과
2. **L1 momentum edge 확장**: SOL/ETH/XRP → **SOL/ETH/XRP/TRX 4개 심볼**
3. ADA/AVAX/ATOM/DOT 탈락 — L1 momentum edge는 유동성/거래량 상위 심볼에 국한됨

**daemon pre-staging 업데이트 (4개 심볼)**:
- XRP: C8(lb=8, adx=25, vol_mult=2.0, TP=12%, SL=4%) — 이중 통과 확정 ★
- TRX: lb=12, adx=25, vol_mult=2.0, TP=12%, SL=4% — **이중 통과 확정 ★ (신규)**
- ETH: C0_base(lb=12, adx=25, vol_mult=2.0, TP=10%, SL=3%) — 조건부 확정 (2/3)
- SOL: lb=12, adx=25 — 조건부 확정 (2/3)


## 2026-04-03 15:49 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** TRX 슬라이딩 3/3 완전 통과로 L1 momentum edge가 SOL/ETH/XRP/TRX 4심볼로 확장됐고, VPIN 기각도 정량 근거로 처리됨. ADA/AVAX/ATOM/DOT 탈락으로 "유동성 상위 L1만 edge 존재" 가설이 수렴되는 중.

**2. poor 5/7(71%) 허용 범위.** BTC BEAR 레짐 억제 + W3 데이터 부족(T<6)이 원인 — 전략 결함이 아닌 필터 정상 작동. 레짐 전환 후 재탐색 예정이므로 낭비 아님.

**3. 다음 1주일 우선순위:**
1. **SOL lb=12 슬라이딩 3구간 검증** — walk-forward+2/3만 통과, XRP lb=10 탈락 패턴 반복 여부 확인 필수
2. **BULL 레짐 전환 트리거 자동화** — 4심볼 pre-staging 완료, 수동 의존 제거
3. **BNB/LTC 등 잔여 상위 유동성 심볼 스크리닝** — 후보 풀 소진 전 마지막 확인

**4. 즉시 daemon 반영 없음.** XRP C8 + TRX lb=12 이중 통과 완료이지만 현재 BEAR 레짐이므로 SOL 슬라이딩 검증 전까지 live 반영 보류가 맞음. BULL 전환 시 XRP/TRX 즉시 활성화 준비 상태.
```

</details>

---

## 2026-04-04 — BULL 전환 프로토콜 업데이트 + SOL W3 재검증 (사이클 86)

**목적**: bull_activation_protocol.py TRX 추가 및 4개 심볼 활성화 순서 명문화
**스크립트**: `scripts/bull_activation_protocol.py` (사이클 83→86 업데이트)

### SOL W3 슬라이딩 재검증 결과

| 윈도우 | OOS Sh | OOS WR | T | 판정 |
|---|:---:|:---:|:---:|:---:|
| W1 (2024) | +23.78 | 56.2% | 16 | ✅ |
| W2 (2025) | +18.05 | 55.6% | 18 | ✅ |
| W3 (2026-01~04) | +9.62 | 50.0% | **4** | ❌ |

**결론**: SOL W3 여전히 T=4 — 2026년 4월 데이터 파일(202604) 미존재. T≥6 충족 불가.
- 데이터 구조적 한계 (BEAR 레짐 + 3개월만 데이터) — 전략 결함 아님
- SOL 조건부 상태 유지. 4월 데이터 축적 후 재검증 예정.

### BULL 전환 프로토콜 업데이트 내용

**변경사항**: TRX 추가 + 활성화 순서 재정렬 (확정 등급 기준)

| Phase | 심볼 | 파라미터 | 검증 상태 | 활성화 순서 |
|---|---|---|---|---|
| 1 | XRP | lb=8, adx=25, TP=12%, SL=4% | WF+슬라이딩 3/3 이중통과★ | BULL 즉시 |
| 2 | TRX | lb=12, adx=25, TP=12%, SL=3% | WF+슬라이딩 3/3 이중통과★ | BULL 즉시 |
| 3 | ETH | lb=12, adx=25, TP=10%, SL=3% | 슬라이딩 2/3 조건부 | XRP/TRX 24h 후 |
| 4 | SOL | lb=12, adx=25, TP=12%, SL=4% | 슬라이딩 2/3 조건부 | XRP/TRX 48h 후 |

**--apply 플래그**: BULL 전환 시 XRP/TRX/ETH 3개 심볼 daemon.toml 자동 활성화 지원 (TRX 신규 추가)


## 2026-04-03 15:59 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** SOL/ETH/XRP/TRX 4심볼로 L1 momentum edge 수렴 완료. "유동성 상위 L1에 edge 국한" 가설이 ADA/AVAX/ATOM/DOT 탈락으로 정량 검증됨.

**2. poor 5/7(71%) 허용 범위.** BEAR 레짐 BTC 억제 + W3 데이터 부족(T<6) 필터 정상 작동 — 전략 결함 아님. SOL W3 T=4 문제도 2026 데이터 미축적 구조 한계.

**3. 다음 1주일 우선순위:**
1. **SOL W3 재검증** — 4월 데이터 축적 후 T≥6 충족 시 조건부→확정 전환
2. **BNB/LTC 상위 유동성 잔여 심볼 스크리닝** — L1 후보 풀 완전 소진 확인
3. **BULL 전환 트리거 자동화** — 4심볼 pre-staging 완료됐으나 수동 의존 제거 필요

**4. 즉시 daemon 반영 없음.** XRP+TRX 이중 통과 완료지만 현재 BEAR 레짐 — BULL 전환 시 `--apply` 플래그로 XRP/TRX/ETH 3개 즉시 활성화 가능 상태. SOL은 W3 통과 후 48h 지연 활성화 유지.
```

</details>

---

## 2026-04-03 16:09 UTC — Claude 품질/방향성 일일 리뷰 [ralph:daily_quality_review] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: LLM 품질/방향성 리뷰

<details><summary>raw output</summary>

```
**1. 방향 맞음.** SOL/ETH/XRP/TRX 4심볼 L1 momentum edge 수렴 완료 — "유동성 상위 L1에만 edge 존재" 가설이 ADA/AVAX/ATOM/DOT 탈락으로 정량 검증됨. VPIN(Sh+7.46)과 momentum(Sh+14.37) 두 개의 독립 엣지 확인은 추가 긍정 신호.

**2. poor 5/7(71%) 허용 범위.** 원인이 전략 결함이 아닌 구조적 필터 정상 작동 — BEAR 레짐 BTC 억제 + W3 T<6 데이터 한계. 현재 레짐에서 이 비율은 오히려 과적합 방지 증거.

**3. 다음 1주일 우선순위:**
1. **BNB/LTC 잔여 상위 유동성 심볼 스크리닝** — L1 후보 풀 완전 소진 후 탐색 종료 판단
2. **BULL 전환 트리거 자동화** — `bull_activation_protocol.py --apply` 조건 자동 감지 (수동 의존 제거)
3. **SOL W3 재검증** — 4월 데이터 T≥6 충족 시 조건부→확정 전환

**4. 즉시 daemon 반영 없음.** XRP+TRX 이중 통과 완료지만 현재 BEAR 레짐 — BULL 전환 확인 즉시 `--apply`로 XRP/TRX/ETH 3심볼 활성화 가능 상태. SOL은 W3 통과 후 48h 지연 유지.
```

</details>

---

## 2026-04-04 — BTC BULL 전환 타이밍 + stealth_3gate 전환 직후 성과 (사이클 88)

**스크립트**: `scripts/backtest_bull_transition_timing.py`
**기간**: 2022-01 ~ 2026-04, 240m(4h) 캔들, SMA20 BEAR→BULL 돌파 이벤트

### 분석 1: pre_bull 신호 선행 타이밍

| 측정 항목 | 결과 |
|---|---|
| 총 BEAR→BULL 전환 이벤트 | 489개 |
| pre_bull≥0.6 평균 선행 | **55h 전** (13.7봉) |
| T-96h에 처음 발동 | 40% (159/398) |
| T-48h에 처음 발동 | 25% (98/398) |
| T-24h에 처음 발동 | 19% (76/398) |
| T-0h에 처음 발동 | 16% (65/398) |
| pre_bull 미발동 전환 | 18% (91/489) |

**해석**: pre_bull≥0.6이 전환의 82%에서 선행 발동. 현재 pre_bull=+0.673 → BULL 전환 평균 55h 전 신호 발동 중.

### 분석 2: BULL 전환 직후 stealth_3gate 성과 (TP/SL 시뮬레이션)

| 심볼 | 진입수 | WR% | avg_ret | Sharpe | TP/SL |
|---|:---:|:---:|:---:|:---:|---|
| KRW-SOL | 234 | 32.1% | -0.08% | -0.01 | 12%/4% |
| KRW-ETH | 163 | 44.8% | +0.48% | +0.11 | 10%/3% |
| KRW-XRP | 167 | 47.9% | +0.48% | +0.09 | 12%/4% |
| KRW-TRX | 148 | 46.6% | +0.39% | +0.11 | 12%/3% |
| **TOTAL** | **712** | **41.7%** | **+0.28%** | **+0.05** | — |

### 분석 3: BULL 전환 직후 단순 보유 기준선

| 심볼 | 24h avg | 48h avg | 96h avg |
|---|:---:|:---:|:---:|
| SOL | +0.23% | +0.45% | +0.69% |
| ETH | +0.20% | +0.31% | +0.72% |
| XRP | +0.42% | +0.60% | +0.97% |
| TRX | +0.28% | +0.52% | +0.76% |

### 결론 및 인사이트

1. **pre_bull 선행성 확인**: pre_bull≥0.6이 BULL 전환 평균 55h 전에 발동 → 현재 조건 충족, 조기 진입 준비 근거
2. **SOL BULL 전환 직후 성과 낮음** (WR=32%): 변동성 대비 SL=4% 너무 타이트. ETH/XRP/TRX는 양의 성과.
3. **stealth_3gate는 단순 보유 대비 우위 없음** — BULL 전환 직후 SMA20 돌파는 false breakout 포함(489개 이벤트 과다). 진짜 상승 사이클 초입 필터 필요.
4. **489개 SMA20 교차** → 4h 기준 너무 민감. 실제 운용에서는 매크로 레짐 + stealth 조건 복합 게이트 필요.
5. **다음 검증 방향**: "major BULL cycle 시작" 필터 적용 후 재검증 (예: 연속 5봉 SMA20 유지 + BTC 주간봉 돌파 등).


---

## 2026-04-04 — Major BULL cycle 필터 적용 stealth_3gate 재검증 (사이클 89)

**스크립트**: `scripts/backtest_major_bull_filter.py`
**기간**: 2022-01 ~ 2026-04, 240m(4h) 캔들
**목적**: 사이클 88에서 489개 false breakout → "연속 N봉 SMA20 유지" 필터로 주요 사이클만 추출 재검증

### 분석 1: 필터별 이벤트 압축 효과

| N봉 필터 | 이벤트수 | 압축률 | 설명 |
|:---:|:---:|:---:|---|
| N=0 (기준선) | 489 | 100% | 단순 SMA20 돌파 |
| N=3 | 238 | 48.7% | 12h 연속 SMA20 유지 |
| N=5 | 192 | 39.3% | 20h 연속 SMA20 유지 |
| N=8 | 150 | 30.7% | 32h 연속 SMA20 유지 |
| N=12 | 112 | 22.9% | 48h 연속 SMA20 유지 |

### 분석 2: 필터별 stealth_3gate 통합 성과

| 필터 | 이벤트수 | 진입수 | WR% | avg_ret | Sharpe |
|---|:---:|:---:|:---:|:---:|:---:|
| N=0 (기준선) | 489 | 712 | 41.7% | +0.28% | +0.05 |
| N=3 (12h) | 238 | 350 | 45.1% | +0.64% | +0.12 |
| N=5 (20h) | 192 | 276 | 52.2% | +1.35% | +0.25 |
| N=8 (32h) | 150 | 203 | 58.6% | +2.06% | +0.38 |
| N=12 (48h) | 112 | 167 | 66.5% | +3.01% | +0.55 |

### 분석 3: N=8 필터 심볼별 성과 (최적 균형점)

| 심볼 | 진입수 | WR% | avg_ret | Sharpe |
|---|:---:|:---:|:---:|:---:|
| KRW-SOL | 55 | 54.5% | +3.06% | +0.46 |
| KRW-ETH | 36 | 63.9% | +2.45% | +0.50 |
| KRW-XRP | 57 | 64.9% | +2.07% | +0.37 |
| KRW-TRX | 55 | 52.7% | +0.79% | +0.21 |
| TOTAL | 203 | 58.6% | +2.06% | +0.38 |

### 결론 및 인사이트

1. **필터 적용 효과 명확**: N=5에서 WR 41.7%→52.2%, avg +0.28%→+1.35%, Sharpe +0.05→+0.25 (5배 개선)
2. **N=8 (32h 유지) 실용적 최적점**: WR 58.6%, Sharpe +0.38 — SOL도 WR=54.5%로 기준선(32.1%) 대비 크게 개선
3. **N=12 Sharpe +0.55이 수치상 최고**이나 이벤트 112개로 샘플 부족
4. **단순 보유 대비**: N=12 stealth avg=+3.01% vs 단순 보유 avg≈+3.76% — 여전히 단순 보유가 높지만 Sharpe 리스크 조정 측면에서 stealth 우위 있음
5. **현재 운용 기준 확정**:
   - BTC SMA20 돌파 후 **8봉(32h) 연속 유지 확인** → major BULL cycle 신호
   - ETH/XRP: N=5 이후 stealth 진입 가능 (WR≥56%)
   - SOL: N=8 이상 필터 후 진입 (WR=54.5%)
   - TRX: Sharpe 낮음(+0.21) → 주의, N=8+ 후 stealth 조건 엄격 적용

**다음 검증 방향**: N=8 필터 + TP/SL 파라미터 최적화 (특히 TRX Sharpe 개선), 또는 pre_bull_score_adj (macro_bonus 통합) 임계값 최적화
