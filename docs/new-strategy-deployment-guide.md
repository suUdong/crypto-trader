# 신규 전략 배포 가이드

auto-research-engine에서 발견된 전략을 crypto-trader에 배포하는 절차.

## 전제 조건

- auto-research-engine에서 Tier 1 후보로 승격됨
- parity spec 문서가 작성됨 (`auto-research-engine/docs/specs/`)
- forward-paper bundle이 생성됨 (`auto-research-engine/artifacts/candidates/`)

## 배포 절차

### 1. 전략 클래스 구현 (또는 확인)

- parity spec의 signal 알고리즘, gates, exit rule을 그대로 구현
- `src/crypto_trader/strategy/<strategy_name>.py` 파일 생성
- `StrategyProtocol` 준수: `evaluate(candles, position=None, *, symbol="") -> Signal`
- 테스트용 `generate_signals(candles) -> list[SignalResult]` 메서드 추가
- `@register("<strategy_name>", override_fields=frozenset({...}))` 데코레이터로 등록
- `strategy/__init__.py`에서 import (side-effect로 registry 등록)

### 2. Parity 테스트 작성

- `tests/test_parity_<strategy_name>.py` 생성
- parity spec의 fixture를 그대로 구현 (synthetic candle series)
- 허용 오차: `1e-6` absolute score tolerance
- warmup bar 검증 (HOLD, score=0.0)
- signal 개수 = candle 개수 검증
- `pytest tests/test_parity_<name>.py -v` 전부 PASS 확인

### 3. daemon.toml 지갑 등록

```toml
# ── <strategy_name> (ARE Candidate X) — paper-only ──
[[wallets]]
name = "<strategy_name>_wallet"
strategy = "<strategy_name>"
initial_capital = 1_000_000.0
paper_trading = true
symbols = ["KRW-BTC", "KRW-ETH", ...]  # 넓게 시작

[wallets.strategy_overrides]
# parity spec의 Candidate 파라미터 그대로 복사
param1 = value1
param2 = value2

[wallets.risk_overrides]
stop_loss_pct = ...
take_profit_pct = ...
risk_per_trade_pct = 0.50  # paper는 50%로 자본 활용
```

규칙:
- `initial_capital = 1_000_000.0` 고정 (100만원)
- `paper_trading = true` 필수
- symbols는 넓게 시작 (데이터 수집 목적)
- strategy_overrides에 ARE Candidate 파라미터 정확히 복사

### 4. 대시보드 등록

`dashboard/data.py`의 `STRATEGY_KR` dict에 한글 이름 추가:

```python
STRATEGY_KR: dict[str, str] = {
    ...
    "<strategy_name>": "한글이름",
}
```

### 5. 테스트 + 재시작

```bash
# 전체 테스트
pytest tests/test_parity_<name>.py tests/test_config.py -v

# daemon 재시작
kill <PID>
nohup .venv/bin/python -m crypto_trader.cli run-multi --config config/daemon.toml > logs/daemon.log 2>&1 &

# 로그 확인
grep "<strategy_name>" logs/daemon.log | tail -10
```

### 6. 검증

- daemon 로그에서 새 지갑이 signal 출력하는지 확인
- 대시보드에서 새 지갑 표시되는지 확인
- `docs/backtest_history.md`에 배포 기록 추가

### 7. 30거래 축적 후 평가

- paper 30건+ 누적 전까지 파라미터 변경 금지
- 30건 도달 후 실현 PnL, WR, Sharpe로 판단
- live 전환은 사람이 수동으로 결정 (자동화 금지)

## 체크리스트

- [ ] 전략 클래스 구현 + `__init__.py` import
- [ ] parity 테스트 작성 + PASS
- [ ] daemon.toml 지갑 추가 (initial_capital=1M, paper=true)
- [ ] `STRATEGY_KR` 한글 이름 등록
- [ ] pytest + test_config PASS
- [ ] daemon 재시작 + 로그 확인
- [ ] 대시보드 표시 확인
- [ ] `docs/backtest_history.md` 기록
- [ ] 30거래 축적 대기

## 금지 사항

- paper 30건 미달 상태에서 파라미터 변경
- forward paper 결과를 auto-research-engine optimizer에 피드백 (P15)
- daemon.toml 자동 수정 (P2)
- live 전환 자동화 (P2)
