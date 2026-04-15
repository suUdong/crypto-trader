# SESSION HANDOFF: 2026-04-15 23:30 KST

**last_commit**: 2955e17
**updated_at**: 2026-04-15T23:30:00+09:00

## 1. 실행 상태

| 프로세스 | PID | 상태 |
|---|---|---|
| crypto_trader daemon | 309 | 실행 중 (paper, 20 지갑) |
| streamlit dashboard | 311 | 실행 중 (port 8502) |
| cloudflared tunnel | - | 미확인 |

## 2. 이번 세션 주요 작업

### ATR 스탑 전면 비활성화
- paper 데이터 분석: `atr_stop_loss` 101건 WR 0%, ₩-149,908 (전체 손실 75%)
- 글로벌 `atr_stop_multiplier` 3.0→0.0, 개별 지갑 4개 1.5→0.0
- 전 지갑 고정 % `stop_loss_pct`로 전환
- 11시간 모니터링: atr_stop_loss 0건 확인, 포지션 유지 시간 증가

### Lightsail 배포 인프라 완성
- `CT_ARTIFACTS_ROOT` env 보간 (config.py + 테스트 3건) — 동일 daemon.toml 로컬/서버 사용
- `scripts/lightsail_bootstrap.sh` — idempotent 서버 셋업 (clone, venv, pip, chown)
- `scripts/backup.sh` — nightly SQLite .backup + JSONL copy + 7일 prune
- `.github/workflows/deploy.yml` — CI + deploy (`if:false` 비활성)
- `scripts/deploy/rsync-exclude.txt` + README
- **서버 통합 테스트**: bootstrap 전체 실행 → backup 검증 → teardown 초기상태 원복 완료

### 라이브 전환 안전 수정 (11건)
**CRITICAL 수정:**
- C1/C4: LiveBroker fill timeout fail-closed (팬텀 포지션 방지)
- C2: 주문 retry 중복 방지 (exception 시 즉시 중단)
- C3: 거래소 잔고 동기화 (`reconcile_with_exchange()` 추가)
- C5: `HARD_MAX_RISK_PER_TRADE_PCT=0.05` 하드캡 + preflight
- C6: `SAFE_LIVE_MAX_POSITION_PCT=0.10` 라이브 전용 캡

**IMPORTANT 수정:**
- I1: Kill switch 틱 내 재검사 (mid-tick break)
- I2: Kill switch 수동 재개 필수화 (live: `.reset` 파일 대기)
- I4: 보호 매도 1회 재시도 (stop_loss, kill_switch)
- I5: 텔레그램 라이브 필수화 (preflight ERROR)
- I6: `go_live_wallets` 초기화 (`[]`)
- I7: Dust 매도 최소금액 검사 + 전량 전환

**리뷰 후 추가 수정:**
- Preflight error level 대소문자 불일치 (`"error"` → `"ERROR"`) — 새 검증이 무시되던 버그
- Kill switch reset loop에 `_shutdown_requested` 체크 추가
- Cancelled order partial fill 처리 추가
- `risk_per_trade_pct` clamp를 paper에서 제거 (preflight에서만 live 검증)

## 3. Git 커밋

| SHA | 내용 |
|---|---|
| 3e086e3 | test: CT_ARTIFACTS_ROOT 테스트 (red) |
| a866927 | feat: CT_ARTIFACTS_ROOT env prefix override |
| 6afab5b | ci: Lightsail deploy.yml + rsync-exclude |
| 28821cf | feat: lightsail_bootstrap.sh |
| 21c8d73 | feat: backup.sh |
| 39e4c00 | fix: bootstrap.sh chown 순서 수정 |
| 5916050 | fix: ATR 스탑 전면 비활성화 |
| 779a831 | docs: 설계문서 + 구현계획 |
| 3d123af | fix: LiveBroker fail-closed, 중복주문 방지 |
| b8306d4 | fix: Config 안전 캡 + go_live_wallets |
| 31a088f | fix: Kill switch 강화 |
| 9e05bce | fix: 보호 매도 강화 |
| 507402d | feat: 거래소 잔고 동기화 (C3) |
| 2955e17 | fix: 리뷰 수정 — preflight 대소문자, shutdown-aware reset |

## 4. 다음 세션 우선순위

1. **라이브 전환 테스트 커버리지** — 새 safety 코드 테스트 추가 (preflight, kill switch mid-tick, dust sell, reconcile)
2. **I3: Limit→market 무음 변환** — 구조 변경 필요, 별도 설계
3. **ATR 스탑 비활성화 효과 모니터링** — 며칠 더 데이터 축적 필요
4. **대시보드 health degraded 개선**
5. **30건 축적 후 전략별 평가** — stealth_3gate (WR 12%), vpin_bat (WR 0%) 비활성화 검토
6. **실배포**: bootstrap 재실행 → secrets 주입 → systemctl start

## 5. 주의사항

- **과최적화 금지 원칙 유지**
- `SAFE_DEFAULT_MAX_POSITION_PCT = 0.50`은 paper 전용 (live는 preflight에서 0.10 캡)
- `risk_per_trade_pct = 0.50`도 paper 전용 (live는 preflight에서 0.05 캡)
- 서버 ct-prod-01은 teardown 상태 — 실배포 시 bootstrap 재실행 필요
- `go_live_wallets = []` — 라이브 전환 시 명시적으로 지갑 지정 필요
- Kill switch live mode: `.reset` 파일 touch 필요 (자동 재개 안 됨)
