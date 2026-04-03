# FIRE 로드맵 (Opus 분석, 2026-04-03)

## 핵심 병목 요약

| 병목 | 현재 | 해결 후 |
|---|---|---|
| stealth_3gate 미활용 | 2심볼, ₩100만 | 10+심볼, ₩200만, Sharpe +4.7 |
| vpin_eth 과잉 배분 | ₩350만, 실제 Sharpe 마이너스 | ₩200만으로 축소 |
| 베어장 매매 정지 | F&G=8 전면 차단 | stealth 조건부 진입 허용 |
| 롱 온리 편향 | 하락장 수익=0 | mean_reversion/etf_flow 추가 |
| 단일 심볼 집중 | ETH/SOL/BTC 3개 | 10+ 심볼 동적 로테이션 |

## FIRE 현실 체크
- ₩500만으로 월 생활비 ₩200만 커버 = 월수익률 40% → 비현실적
- **현실 타겟**: ₩5,000만 기준 월수익률 4~5% = ₩200만
- 자본 투입 가속이 전략 개선만큼 중요

## P0: 즉시 할 것 (임팩트 최대)

### 1. stealth_3gate 독립 전략 클래스 구현
- accumulation_breakout 내부에 간접 적용 → 정식 전략으로 승격
- market_scan watchlist 상위 N개 심볼 동적 배정
- 파일: `src/crypto_trader/strategy/stealth_3gate.py`

### 2. 자본 재배분
- vpin_eth: ₩350만 → ₩200만 (실제 수익성 마이너스)
- stealth_3gate 지갑 확장: ₩50만×2 → ₩100만×2 이상

### 3. stealth 조건부 진입 허용
- BTC stealth 신호 발동 시 F&G 차단 우회 (포지션 50% 축소)
- 파일: `src/crypto_trader/macro/adapter.py`

## P1: 베어장 대응

### 활성화 가능한 기존 전략
- `bollinger_mean_reversion`: 구현됨, daemon 주석 처리 상태
- `etf_flow_admission`: bear 레짐 가중치 1.6 (설계 의도가 하락장 특화)
- `consensus`: 완성됨, research-only 라벨

## 2주 액션 플랜

### Week 1 (4/3~4/10)
1. stealth_3gate 전략 클래스 구현
2. 자본 재배분 (vpin_eth 축소)
3. stealth 조건부 진입 허용 (macro/adapter.py)
4. cross-wallet 동시 포지션 제한

### Week 2 (4/10~4/17)
1. bollinger_mean_reversion 백테스트 + 활성화
2. etf_flow_admission 백테스트 (하락장 특화)
3. 라이브 전환 promotion gate 자동화

---

# Codex 기술 분석 (2026-04-03)

## 1. stealth_3gate 독립 지갑 배포

**결론**: 전략 클래스 없음 — 백테스트 스크립트에만 존재

TODO:
1. `src/crypto_trader/strategy/stealth_3gate.py` 신규 — `Stealth3GateStrategy` 클래스
2. `src/crypto_trader/strategy/__init__.py` — `create_strategy()`에 `"stealth_3gate"` 매핑 추가
3. `src/crypto_trader/config.py` — stealth_3gate 파라미터 필드 추가
4. `config/daemon.toml` — `[[wallets]]` 블록 추가
5. `tests/test_stealth_3gate.py` 신규

## 2. vpin_eth EMA 버그

**결론**: `ema_trend_down`은 코드에 없음 — 실제 버그는 `ema_trend_up` 단독 하드 차단

Root cause: `vpin.py` `evaluate()`에서 `ema_trend_up=False`이면 무조건 HOLD 반환.
ETH 4h 기준 12/26 EMA = 48h/104h 윈도우 → 횡보/하락 구간 전부 차단.

TODO:
1. `src/crypto_trader/strategy/vpin.py` — `if not ema_trend_up: return HOLD` → 가중치 조정으로 변경
2. `src/crypto_trader/config.py` — `ema_filter_mode: str = "weight"` 필드 추가
3. `config/daemon.toml` — `ema_fast_period=20, ema_slow_period=50` + `ema_filter_mode="weight"`
4. `scripts/backtest_vpin_eth_grid.py` — `ema_filter_mode` 그리드 추가

## 3. 베어장 수익화

**결론**: Upbit 현물 전용 → 숏/ETF/이자 불가. 현실적 대안만 존재.

| 기능 | 상태 |
|---|---|
| BTC 인버스 ETF | ❌ Upbit 미지원 |
| 스테이블 이자 | ❌ Upbit 이자 상품 없음 |
| 현물 매도 후 현금 보유 | ✅ 가능 |
| 선물 숏 | 새 브로커 클래스 필요 (Binance) |

TODO:
1. `src/crypto_trader/strategy/btc_regime_rotation.py` — 베어 감지 시 현금화 시그널
2. `src/crypto_trader/multi_runtime.py` — 레짐 전환 시 자동 현금화 비율 파라미터

## 4. Alpha Calibration 개선

**결론**: 가중치 하드코딩 + 레짐 conditioning 없음 + z-score 분포 불일치

TODO:
1. `src/crypto_trader/strategy/alpha_calibrator.py` — 가중치 config-driven으로
2. `compute_alpha_score()` — 레짐별 가중치 테이블 추가
3. `scripts/gpu_features.py` — z-score 윈도우 24h → 90일 고정
4. `scripts/backtest_alpha_filter.py` — bull/bear threshold 분리 탐색
5. `scripts/calibrate_alpha_weights.py` 신규 — Sharpe 극대화 weight grid-search
