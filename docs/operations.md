# 운영 가이드

## 1. 데몬 시작/중지

### 시작

```bash
# 기본 (daemon.toml)
scripts/restart_daemon.sh

# 특정 설정 파일
scripts/restart_daemon.sh config/live.toml
```

restart 스크립트 동작:
1. 기존 데몬 PID 확인 후 SIGTERM (30초 대기, 실패 시 SIGKILL)
2. 체크포인트 확인 (월렛 수, 오픈 포지션 수)
3. `python -m crypto_trader.cli run-multi --config <config>` 실행 (nohup)
4. 하트비트 확인 (최대 30초)
5. 포지션 복원 검증

### 중지

```bash
# PID 확인
cat artifacts/daemon-heartbeat.json | python3 -c "import sys,json; print(json.load(sys.stdin)['pid'])"

# 정상 종료 (체크포인트 저장됨)
kill -TERM <PID>
```

### 상태 확인

```bash
# 하트비트
cat artifacts/daemon-heartbeat.json

# 로그 실시간
tail -f artifacts/daemon.log

# 헬스체크
cat artifacts/health.json
```

## 2. 설정 및 파라미터 변경

### 설정 파일

```
config/
├── daemon.toml      # 프로덕션 데몬 (13개 월렛)
├── live.toml        # 마이크로 라이브 (소액 실매매)
├── example.toml     # 템플릿
├── optimized.toml   # 그리드 서치 결과
└── validated.toml   # 검증 완료 파라미터
```

### 설정 레이어

1. TOML 파일 (기본: `config/example.toml`)
2. 환경 변수 (`CT_` 접두사)

주요 환경 변수:
- `CT_PAPER_TRADING` — 페이퍼 트레이딩 모드
- `CT_UPBIT_ACCESS_KEY` / `CT_UPBIT_SECRET_KEY` — Upbit API 키
- `CT_TELEGRAM_BOT_TOKEN` / `CT_TELEGRAM_CHAT_ID` — Telegram 알림
- `CT_SLACK_WEBHOOK_URL` — Slack 알림
- `CT_POLL_INTERVAL_SECONDS` — 폴링 주기
- `CT_HEALTHCHECK_PATH` — 헬스체크 경로

### 월렛별 전략 파라미터

`config/daemon.toml`의 `[wallets.strategy_overrides]`에서 월렛별 수정:

```toml
[[wallets]]
name = "momentum_btc_wallet"
strategy = "momentum"
initial_capital = 1_000_000.0
symbols = ["KRW-BTC"]

[wallets.strategy_overrides]
momentum_lookback = 15          # 모멘텀 관찰 기간 (캔들 수)
momentum_entry_threshold = 0.002 # 진입 임계값
rsi_period = 14                  # RSI 기간
rsi_overbought = 72.0           # RSI 과매수 기준
max_holding_bars = 48            # 최대 보유 기간
adx_threshold = 20.0             # ADX 추세 강도 필터

[wallets.risk_overrides]
stop_loss_pct = 0.04             # 손절 %
take_profit_pct = 0.08           # 익절 %
risk_per_trade_pct = 0.008       # 트레이드당 리스크
```

### 전역 리스크 파라미터

```toml
[risk]
risk_per_trade_pct = 0.01        # 트레이드당 리스크 비율
stop_loss_pct = 0.03             # 기본 손절
take_profit_pct = 0.10           # 기본 익절
max_concurrent_positions = 4     # 최대 동시 포지션
```

### Kill Switch

기본값 (`src/crypto_trader/risk/kill_switch.py`):
- 포트폴리오 최대 낙폭: **15%** (7.5%에서 경고)
- 일일 최대 손실: **5%** (3.75%에서 감축)
- 연속 손실 최대: **5회**
- 쿨다운: **60분**

### 파라미터 변경 적용

```bash
# 설정 수정 후 데몬 재시작 — 체크포인트로 포지션 안전 복구
scripts/restart_daemon.sh config/daemon.toml
```

### 파라미터 최적화

```bash
python -m crypto_trader.cli grid-wf --config config/daemon.toml   # 그리드 서치
python scripts/walk_forward.py                                      # Walk-forward
python scripts/auto_tune.py                                         # 자동 튜닝
```

## 3. 모니터링

### 아티팩트 파일

| 파일 | 용도 | 갱신 주기 |
|------|------|----------|
| `daemon-heartbeat.json` | PID, 마지막 하트비트 | 매 틱 (60초) |
| `health.json` | 시스템 헬스 (성공 플래그, 에러, 잔고) | 매 틱 |
| `runtime-checkpoint.json` | 월렛 상태, 포지션, 자본 (재시작 복구용) | 매 틱 |
| `strategy-runs.jsonl` | 전략 평가 기록 (시그널 + 컨텍스트) | 시그널 발생 시 |
| `paper-trades.jsonl` | 클로즈된 트레이드 저널 | 트레이드 종료 시 |
| `positions.json` | 현재 오픈 포지션 스냅샷 | 매 틱 |
| `daily-performance.json` | P&L, 승률, 트레이드 수 | 일간 |
| `drift-report.json` | 전략 드리프트 (라이브 vs 백테스트) | 매 시간 |
| `promotion-gate.json` | 라이브 전환 준비 상태 | 매 시간 |
| `regime-report.json` | 시장 레짐 (bull/bear/sideways) | 매 시간 |
| `daily-memo.md` | 일간 요약 (사람용) | 일간 |
| `strategy-report.md` | 전략 비교 리포트 | 매 시간 |

### 드리프트 감지

라이브 성과가 백테스트 기준선에서 벗어나면 자동 감지:
- 레짐별 수익률 허용 범위: bull 15%, sideways 8%, bear 5%
- 오류율 임계값: bull 25%, sideways 20%, bear 10%
- 초과 시 verdict 변경: continue → reduce → pause

### Correlation Guard

동일 자산 클러스터(BTC/ETH/SOL/XRP)에서 최대 4개 월렛 동시 포지션 허용.

## 4. 대시보드

### 실행

```bash
streamlit run dashboard/app.py
```

기본 접속: `http://localhost:8501`

### 설정 (`.streamlit/config.toml`)

```toml
[server]
headless = true
enableCORS = false

[theme]
primaryColor = "#60a5fa"
backgroundColor = "#0e1117"
secondaryBackgroundColor = "#1a1f2e"
textColor = "#fafafa"
```

### 기능

- 데몬 상태 배지 (하트비트 기반)
- 오픈 포지션 현황
- 일간 P&L 및 승률
- 전략별 성과 비교
- 시장 레짐 표시
- 드리프트 리포트
- 프로모션 게이트 진행
- 트레이드 히스토리
- 60초 자동 새로고침, 모바일 최적화 (한국어 UI)

### 원격 접속

```bash
# SSH 포트 포워딩
ssh -L 8501:localhost:8501 user@server

# 외부 접속 허용
streamlit run dashboard/app.py --server.address 0.0.0.0
```

## 5. 알림 설정

### Telegram

1. [@BotFather](https://t.me/BotFather)에서 봇 생성 → 토큰 획득
2. 봇에게 메시지 전송 후 Chat ID 확인
3. 설정:

```toml
[telegram]
bot_token = "123456:ABC-DEF..."
chat_id = "987654321"
```

또는 환경 변수:
```bash
export CT_TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export CT_TELEGRAM_CHAT_ID="987654321"
```

### Slack

1. Slack 앱 생성 → Incoming Webhook URL 획득
2. 환경 변수:
```bash
export CT_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK"
```

### 알림 이벤트

- 트레이드 진입/청산
- 전략 verdict 변경 (continue/reduce/increase)
- Kill switch 발동
- 포트폴리오 성과 마일스톤

### 비활성화

`bot_token`과 `chat_id`를 빈 문자열로 두면 알림 비활성화 (기본값).

## 6. 배포

- Docker: `live` extra 포함하여 `pyupbit` 사용 가능
- `docker-compose.yml`: `artifacts/` 볼륨 마운트
- GitHub Actions: push/PR마다 lint, typecheck, 유닛 테스트 실행
