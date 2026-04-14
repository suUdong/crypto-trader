# SESSION HANDOFF: 2026-04-14 15:30 KST

**last_commit**: ca7f6a6
**updated_at**: 2026-04-14T15:30:00+09:00

## 1. 실행 상태

| 프로세스 | PID | 상태 |
|---|---|---|
| crypto_trader daemon | 2160904 | 실행 중 (paper, 20 지갑) |
| streamlit dashboard | 2843246 | 실행 중 (port 8502) |
| cloudflared tunnel | 1782299 | 실행 중 (ICN 4연결) |
| strategy_research_loop | - | 미확인 |
| market_scan_loop | - | 미확인 |

## 2. 이번 세션 주요 작업

### ATR 이중경로 버그 수정
- `atr_stop_multiplier=0.0`만으로는 regime-adaptive 경로(`atr_sl_multiplier`/`atr_tp_multiplier`)가 여전히 ATR 스탑 발동
- vpin 전 지갑(sol, xrp, avax, mana, bat, pundix, orbs) `atr_sl_multiplier=0.0`, `atr_tp_multiplier=0.0`으로 변경
- `market_data_closed_only`를 `_COMMON_WALLET_OVERRIDE_FIELDS`에 추가 (전 전략 허용)

### 대시보드 개선 3건
1. **실시간 가격**: pyupbit 현재가 오버레이 (10초 캐시) — 포지션 카드 현재가/미실현PnL 갱신
2. **수익률 역산**: 체크포인트 equity 의존 → 거래이력 pnl 합산 기반으로 변경 (vpin_mana +18% 뻥튀기 해결)
3. **전체 이력**: session-only 필터 → `load_all_paper_trades()` 전체 이력 기반

### SQLite DB 전환 + 프로덕션 하드닝
- 대시보드 데이터 소스를 JSONL → **SQLite** (`paper-trades.db`)로 전환 (JSONL fallback 유지)
- `PRAGMA busy_timeout=5000` 추가 — 데몬 쓰기 중 대시보드 읽기 lock 방지
- 복합 인덱스 추가: `(wallet, exit_time)`, `(session_id)`
- `integrity_check`는 init에서 제거 (O(N) 스캔이 lock 잡아 성능 저하) — 별도 operator 스크립트로 분리 예정
- dead code 제거 (`callable()` 불필요 가드, 미사용 `paper_trades` 변수)

### 코드 리뷰 (3-agent 병렬)
- CLAUDE.md 준수, 버그 스캔, 동시성 리뷰 실행
- 발견 이슈 3건 즉시 수정, false positive 2건 확인, 미수정 2건 인지

### 인프라
- cloudflared 터널 재시작
- Lightsail ct-prod-01 서버 상태 확인 (살아있음, Python 3.12, crypto 유저 생성됨, 서비스 미등록)

## 3. Git 커밋

| SHA | 내용 |
|---|---|
| 067c4a4 | ATR dual-path fix + dashboard live prices + trade-history equity |
| ad8518c | SQLite hardening — busy_timeout, integrity check, indexes |
| ca7f6a6 | Code review fixes — busy_timeout pragma, remove integrity_check, clean dead code |

## 4. 다음 세션 우선순위

1. **Lightsail 배포 구현** — P0: `$ARTIFACTS_ROOT` env 보간, bootstrap.sh, systemd 유닛, backup.sh
2. **v1 리스크 수정 효과 모니터링** — ATR 이중경로 수정 후 atr_stop_loss 발동 빈도 확인
3. **ARE 전략 첫 거래 대기** — pdh_pdl, vwm 시장 반등 시 진입 여부
4. **대시보드 health degraded 개선** — Upbit API 간헐 실패로 연속 에러 카운터 상승 → degraded 표시 문제
5. **30건 축적 후 전략별 평가** — 실현PnL 플러스 전환 지갑이 나오면 라이브 후보

## 5. 주의사항

- **과최적화 금지 원칙 유지** — 파라미터 튜닝 금지, paper 데이터 축적 대기
- `SAFE_DEFAULT_MAX_POSITION_PCT = 0.50`은 paper 전용. live 전환 시 반드시 0.10 이하로 하향
- `risk_per_trade_pct = 0.50`도 paper 전용. live 전환 시 0.01~0.02로 복귀
- daemon.toml 수정 시 TOML 주석 블록 주의 (파싱 에러 이력 있음)
- SQLite는 JSONL fallback 유지 중. JSONL 삭제하지 말 것
