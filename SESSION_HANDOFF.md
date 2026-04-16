# SESSION HANDOFF: 2026-04-17 08:00 KST

**last_commit**: 14b8ff4
**updated_at**: 2026-04-17T08:00:00+09:00

## 1. 실행 상태

| 프로세스 | PID | 상태 |
|---|---|---|
| crypto_trader daemon | 4005743 | 실행 중 (paper, 16 지갑) |
| streamlit dashboard | 311 | 실행 중 (port 8502) |
| cloudflared tunnel | - | 미확인 |

## 2. 이번 세션 주요 작업 (2026-04-15~16)

### ATR 스탑 전면 비활성화
- paper 데이터 분석: `atr_stop_loss` 101건 WR 0%, ₩-149,908 (전체 손실 75%)
- 글로벌 `atr_stop_multiplier` 3.0→0.0, 개별 지갑 4개 1.5→0.0
- **효과**: ATR OFF 후 15건 WR 67%, 실현 PnL ₩+11,396 (양수 전환)

### Lightsail 배포 인프라 완성
- `CT_ARTIFACTS_ROOT` env 보간 (config.py + 테스트 3건)
- `scripts/lightsail_bootstrap.sh` — 서버 실행 검증 + teardown 완료
- `scripts/backup.sh` — nightly SQLite .backup + JSONL copy
- `.github/workflows/deploy.yml` — CI + deploy (`if:false`)
- 서버 통합 테스트: bootstrap → backup → teardown 초기상태 원복

### 라이브 전환 안전 수정 (15건)
- C1/C2/C4: LiveBroker fail-closed, 중복주문 방지, cancel 처리
- C3: 거래소 잔고 동기화 (`reconcile_with_exchange()`)
- C5/C6: 하드캡 (`HARD_MAX_RISK_PER_TRADE_PCT=0.05`, `SAFE_LIVE_MAX_POSITION_PCT=0.10`)
- I1/I2: Kill switch 틱 내 재검사 + live 수동 재개
- I4/I5/I6/I7: 보호 매도 재시도, 텔레그램 필수화, go_live_wallets 정리, dust 매도 검사
- 리뷰 후 추가 수정: preflight 대소문자, shutdown-aware reset, partial fill 처리

### 전략 리뷰 + 부진 지갑 비활성화
- Codex + Opus 병렬 리뷰: 근본 원인 3가지 (SL/TP 비대칭, 레짐 불일치, VPIN 집중)
- 비활성화: stealth_3gate (75건 16%), vpin_bat, vpin_mana, vpin_orbs
- 활성 지갑: 20→16개

### CLI 리더보드 + 테스트 커버리지
- `scripts/leaderboard.py` — 전 지갑 순위표 (상태, WR, PnL, 포지션)
- safety 테스트 9건 추가 (preflight, fill timeout, dust sell) + 버그 수정 1건

## 3. Git 커밋

| SHA | 내용 |
|---|---|
| 3e086e3 | test: CT_ARTIFACTS_ROOT 테스트 |
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
| 96e6229 | docs: session handoff 갱신 |
| a994cfc | docs: 전략 수익성 리뷰 |
| eab39f7 | feat: leaderboard.py |
| bc09959 | config: 부진 4지갑 비활성화 |
| 14b8ff4 | test: safety 테스트 9건 추가 |

## 4. 다음 세션 우선순위

1. **B3: VPIN stop_loss_pct 0.8%→2.5%** — 과최적화 경계, 사용자 승인 필요
2. **B4: accumulation_dood TP 15%→7%** — 과최적화 경계, 사용자 승인 필요
3. **A2: Limit→market 경고 로그** — LiveBroker에서 limit order 무음 변환 경고
4. **A3: 대시보드 리더보드 탭** — leaderboard.py 로직 Streamlit 반영
5. **A4: health degraded 개선** — Upbit API 간헐 실패 에러 카운터 문제
6. **실배포**: bootstrap 재실행 → secrets 주입 → systemctl start
7. **ATR OFF 효과 지속 모니터링** — 30건+ 축적 후 최종 평가

## 5. 주의사항

- **과최적화 금지 원칙 유지** — B3/B4는 paper 데이터 기반이나 튜닝 영역
- `SAFE_DEFAULT_MAX_POSITION_PCT = 0.50`은 paper 전용 (live preflight에서 0.10 캡)
- `risk_per_trade_pct = 0.50`도 paper 전용 (live preflight에서 0.05 캡)
- 서버 ct-prod-01은 teardown 상태 — 실배포 시 bootstrap 재실행 필요
- `go_live_wallets = []` — 라이브 전환 시 명시적으로 지갑 지정 필요
- Kill switch live mode: `.reset` 파일 touch 필요 (자동 재개 안 됨)
- 비활성화된 지갑 4개: stealth_3gate, vpin_bat, vpin_mana, vpin_orbs (주석처리, 삭제 아님)
- 전략 리뷰 문서: `docs/strategy-review-2026-04-16.md`
