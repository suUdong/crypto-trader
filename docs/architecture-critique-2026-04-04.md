# 자동매매 시스템 아키텍처 비판 분석
> 작성: 2026-04-04 | 검토자: Opus 4.6, Codex GPT-5.4 (코드 직접 리뷰)

---

## 🔴 CRITICAL — 즉시 수정 필요

### 1. 백테스트 전체가 현재 매크로 레짐으로 오염됨 (Codex 발견)

**위치:** `src/crypto_trader/macro/adapter.py:42-58`

백테스트 엔진이 과거 바를 시뮬레이션하는 동안 `adapter.get_position_multiplier()`가 실시간 매크로 서버(`http://127.0.0.1:8000/regime/current`)를 호출한다. 캐시 키가 현재 시각 기준이므로 2000개 과거 바 전부에 **오늘의 레짐**이 적용된다.

**결과:**
- Sharpe 5.0 — 오염된 숫자
- Walk-Forward 2/3 통과 — 오염된 결과
- 130 사이클 전체 배포 결정 — 오염된 근거

**수정:** `adapter.py`에 `historical_timestamp` 파라미터 추가, 매크로 레짐 시계열 로그 저장 후 백테스트 시 재생(replay) 구조로 변경.

---

### 2. 백테스트 엔진 1봉 선행 편향 (Codex 발견)

**위치:** `src/crypto_trader/backtest/engine.py:~135`

```python
fill_price = candle['close']  # 진입가를 현재 봉의 종가로 처리
```

실거래에서 해당 종가는 이미 지나간 가격. 실제 진입은 다음 봉 시가. 모든 전략에 1봉 선행 편향 적용됨.

---

### 3. daemon.toml 무잠금 동시 쓰기 (Codex 발견)

**위치:** `scripts/wallet_auto_updater.py:~45-65`, `scripts/market_scan_loop.py:~195-210`

ralph, research_loop, market_scan 세 루프가 `daemon.toml`을 파일 락 없이 동시 쓰기 가능. `multi_runtime.py`의 30초 config watcher와 충돌 시 파티셜 TOML 로드 → 크래시 또는 잘못된 설정 적용.

**수정:** `os.replace()` 원자적 쓰기 + `fcntl.flock` 추가.

---

## 🟠 HIGH — 구조적 설계 결함

### 4. stealth_3gate는 사실 듀얼 모멘텀 전략 (Opus + Codex)

**위치:** `src/crypto_trader/strategy/stealth_3gate.py`

"스텔스 매집 감지"라는 이름과 달리 실제 로직:
- Gate 1: BTC > 20봉 EMA → BTC 상승추세 (모멘텀)
- Gate 2: volume_ratio > 1.2 AND 강세 캔들 바디 비율 → 강한 캔들 (모멘텀 확인)
- Gate 3: 알트의 BTC 대비 상대 모멘텀 → 알트 아웃퍼폼 (상대 모멘텀)
- Gate 4: btc_trend_pos (BTC 10봉 수익률 > 0) → 또 BTC 모멘텀

진짜 매집 감지는 오더북 흡수, CVD, 다크풀 프린트가 필요. 현재 구현은 BTC 강세장에서만 알트 추종 매수. Bear/Sideways 레짐에서는 진입 없음 → 그 기간 성과 미검증.

### 5. 신호들이 독립적이지 않음 — 같은 팩터를 3번 측정 (Opus)

다음 셋은 모두 "BTC가 올랐냐"의 다른 표현:
- 로컬 레짐 detector (short_lookback=10)
- BTC > SMA20
- btc_trend_pos (BTC 10봉 수익률 > 0)

멀티팩터처럼 보이지만 실제로는 단일 팩터 과신. 진짜 독립 팩터 조합 필요.

### 6. 3루프 아키텍처 — 조율 실패 구조 (Opus)

ralph / strategy_research_loop / market_scan_loop 은:
- 공유 상태 계약 없음
- 같은 전략을 다른 파라미터로 동시 백테스트 가능
- 서로 충돌하는 daemon.toml 변경 동시 시도 가능
- 사용자가 수동으로 개입해야 조율이 되는 구조

**이건 마이크로서비스가 아니라 공유 가변 상태를 두고 싸우는 3개 프로세스.**

### 7. Sharpe 5.0 기준이 통계적으로 무의미 (Codex)

- 다중 가설 검정 보정(Bonferroni) 없음
- 50개 가설 중 최고를 선택해도 Sharpe 5.0 달성 가능
- 샘플 수 정규화 없음 (n=20 vs n=4000이 같은 기준 적용)
- Walk-Forward 2/3 통과 = BTC 강세장에서 2개 구간이 올랐냐 → 당연한 결과

### 8. 포트폴리오 관리 부재 (Opus)

- 지갑들이 서로의 포지션을 모름 → 상관관계 높은 알트 동시 다중 매수 가능
- 상관관계 클러스터 하드코딩, 업데이트 안 됨 (crypto crash 시 모든 코인 상관=1.0)
- CapitalAllocator의 Sharpe 계산이 근사값 (`daily_vol = max(abs(daily_ret) * 2, 0.1)`) → 실제 Sharpe 아님
- 포트폴리오 레벨 최적화 없음 (Markowitz, Risk Parity 등)

---

## 🟡 MEDIUM — 보완 필요

### 9. macro adapter fail-closed가 기회비용을 측정 안 함

매크로 서버 다운 → 모든 진입 차단. 차단된 기회비용 측정/알림 없음. 얼마나 자주 차단되는지 모름.

### 10. 알파 가설이 전략별로 명시되지 않음

각 전략이 어떤 시장 비효율성을 이용하는지, 그 비효율성이 왜 존재하는지, 왜 지속될 것인지에 대한 명확한 가설이 없음. 백테스트 결과가 좋은 것이 알파 존재의 증거가 아님.

### 11. 페이퍼 트레이딩 결과가 경고 신호

> "vpin_eth only profitable wallet" (daemon.toml 주석)

백테스트 Sharpe 5~12인 전략들이 페이퍼에서 대부분 실패. 이것은 overfitting의 교과서적 신호.

### 12. 거래량 기반 슬리피지 모델 없음

백테스트: `slippage_pct = 0.0005` (0.05%) 고정
실제: 얇은 알트(DOOD, TREE) 시장충격 0.5~2%
→ 백테스트 수익이 실거래에서 사라질 수 있음

---

## 📋 우선순위별 수정 로드맵

| 우선순위 | 항목 | 임팩트 | 난이도 |
|---------|------|--------|--------|
| P0 | 매크로 어댑터 역사적 재생(replay) 구조 | 🔴 전체 백테스트 신뢰도 | 상 |
| P0 | 백테스트 1봉 선행 편향 수정 | 🔴 모든 Sharpe 재계산 | 중 |
| P1 | daemon.toml 원자적 쓰기 + 파일 락 | 🔴 운영 안정성 | 하 |
| P1 | 매크로 서버 차단 시간 측정/알림 | 🟠 기회비용 가시화 | 하 |
| P2 | 3루프 → 단일 이벤트 드리븐 파이프라인 | 🟠 아키텍처 정합성 | 상 |
| P2 | 포트폴리오 레벨 최적화 도입 | 🟠 수익성 | 상 |
| P2 | 다중 가설 검정 보정 (Bonferroni) | 🟠 배포 의사결정 | 중 |
| P3 | 거래량 기반 동적 슬리피지 모델 | 🟡 백테스트 현실성 | 중 |
| P3 | 전략별 알파 가설 문서화 | 🟡 연구 방향성 | 하 |
| P3 | 배포 전략 성과 decay 자동 감지 | 🟡 포트폴리오 건전성 | 중 |

---

## 결론 (Opus)

> "The core alpha-generation process has no structural defense against overfitting. The multi-loop architecture compounds this by allowing uncoordinated exploration. The regime detection creates an illusion of multi-factor robustness while actually measuring one thing (BTC trend) three different ways."

## 결론 (Codex GPT-5.4)

> "The Sharpe 5.0 threshold, the 2/3 walk-forward criterion, and the 130-cycle autonomous loop are all downstream of this single poisoned root (macro regime contamination). None of the other flaws matter as much as the fact that the optimiser has been training and validating on a label it cannot have at training time."
