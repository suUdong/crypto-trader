# v1 리스크 구조 3대 수정 설계

**Date**: 2026-04-13
**Context**: paper 280건 분석 + Codex 리뷰 결과, ATR 스탑로스 123건 0% WR (-127,392원)이 전체 손실 주범. 근본 원인 3가지 확인됨.

## 배경: 왜 ATR 스탑이 123번 걸렸나

1. **열린 봉 평가**: 60분봉 전략이 1분마다 미완성 봉 평가 → 47건이 진입 즉시 청산
2. **가변 ATR**: 진입 시점 ATR이 아닌 현재 ATR로 스탑 계산 → 변동성 감소 시 스탑 조임
3. **전략-리스크 분리**: 전략의 exit 의도와 무관하게 전역 ATR 스탑 발동

## Fix 1: 닫힌 봉 강제 (`market_data_closed_only`)

### 문제
- `wallet.py:383`에서 `market_data_closed_only` 기본값 false
- daemon.toml 19개 활성 지갑 중 0개가 true
- 60분봉이 확정되기 전 노이즈 데이터로 진입/청산 판단
- ATR 스탑 123건 중 47건이 entry_time == exit_time (same-tick churn)

### 해결
- daemon.toml `[trading]` 섹션에 글로벌 설정 추가: `market_data_closed_only = true`
- 또는 모든 60분봉 지갑의 `strategy_overrides`에 `market_data_closed_only = true`

### 검증
- daemon 재시작 후 로그에서 same-tick 진입/청산 0건 확인
- 시그널 평가 주기가 60분 간격으로 변경됨 확인

## Fix 2: Entry ATR 고정

### 문제
- `RiskManager.check_exit()`가 매 tick마다 ATR 재계산 (`manager.py:449`)
- `Position` dataclass에 `entry_atr` 필드 없음 (`models.py:69`)
- 진입 후 변동성 감소 → 스탑 거리 축소 → 의도치 않은 조기 청산

### 해결

**models.py**:
```python
@dataclass(slots=True)
class Position:
    ...
    entry_atr: float = 0.0  # ATR at entry time, frozen for stop calculation
```

**wallet.py** (진입 시):
```python
# 진입 시점 ATR 계산 후 Position에 저장
entry_atr = self.risk_manager.calculate_atr(candles)
position = Position(..., entry_atr=entry_atr)
```

**manager.py** (스탑 체크 시):
```python
# 변경 전: atr = self._calculate_atr(candles)
# 변경 후:
atr = position.entry_atr if position.entry_atr > 0 else self._calculate_atr(candles)
stop_price = position.entry_price - (atr * self._config.atr_stop_multiplier)
```

### 검증
- 기존 테스트 통과 (entry_atr=0.0 fallback으로 하위 호환)
- 신규 테스트: entry_atr 설정된 포지션은 ATR 변동에도 스탑 고정 확인

## Fix 3: 전략-리스크 계약 정리

### 문제
- 자체 exit 로직이 있는 전략 (pdh_pdl, vwm, bb_squeeze)에도 전역 ATR 스탑이 중복 적용
- `wallet.py:787`에서 전략 SELL 시그널보다 리스크 매니저 exit이 먼저 발동 가능
- exit 체계가 이중으로 걸려 예측 불가능한 청산 발생

### 해결
daemon.toml에서 자체 exit 전략의 지갑에 `atr_stop_multiplier = 0.0` 설정:

| 전략 | 자체 exit | 전역 ATR 스탑 |
|---|---|---|
| pdh_pdl_sweep_reclaim | trailing stop | 비활성 (0.0) |
| volume_weighted_momentum | fixed TP/SL | 비활성 (0.0) |
| bb_squeeze_independent | 자체 exit | 비활성 (0.0) |
| bollinger_mr | 자체 exit | 비활성 (0.0) |
| vpin | 없음 (RiskManager 의존) | 활성 (3.0) |
| momentum | 없음 | 활성 (3.0) |
| volume_spike | 없음 | 활성 (3.0) |
| stealth_3gate | 없음 | 활성 (3.0) |
| accumulation_breakout | 없음 | 활성 (3.0) |

### 검증
- 자체 exit 전략의 로그에서 `atr_stop_loss` 사유 0건 확인
- vpin 등 전역 스탑 전략은 entry_atr 기반 스탑 정상 작동 확인

## 변경 파일 요약

| 파일 | 변경 내용 |
|---|---|
| `config/daemon.toml` | Fix 1 (closed_only) + Fix 3 (per-wallet atr override) |
| `src/crypto_trader/models.py` | Fix 2 (Position.entry_atr 필드) |
| `src/crypto_trader/risk/manager.py` | Fix 2 (entry_atr 기반 스탑 계산) |
| `src/crypto_trader/wallet.py` | Fix 2 (진입 시 entry_atr 저장) |
| `tests/test_risk_*.py` | Fix 2 검증 테스트 추가 |

## 하지 않는 것

- 전략 시그널 로직 변경 (v2 범위)
- 포지션 사이징 변경 (별도 작업)
- confidence 스케일 표준화 (별도 작업)
- 백테스트 재실행 (paper 데이터로 검증)

## 성공 기준

1. same-tick churn (entry_time == exit_time) 0건
2. ATR 스탑 발동 시 entry_atr 기반 (가변 아님)
3. 자체 exit 전략에서 전역 ATR 스탑 0건
4. 기존 테스트 전부 통과
