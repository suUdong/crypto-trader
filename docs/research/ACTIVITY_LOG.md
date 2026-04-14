# Research Activity Log

세션 간 작업 연속성 확보용. 매 세션마다 한 줄 이상 추가. **위가 최신.**

## 2026-04-10

- **세션 (전략 리뷰)** — Codex가 현재 자동매매 전략군을 코드/설정/paper-trades/strategy-runs 기준으로 재평가. 결과 문서 `docs/research/2026-04-10-codex-strategy-review/00_README.md` 추가. 결론: VPIN은 범용 최강이 아니라 ONDO/SOL 중심의 조건부 우위 계열이며, 현재 돌파구는 새 지표보다 `bb_squeeze insufficient_data`, `vpin_mana/bat/pundix/orbs` 미실행 같은 런타임 병목 해소와 VPIN 출구 구조 정리.

## 2026-04-07

- **세션 (저녁)** — 일일 매매 리뷰 (`docs/research/2026-04-07-daily-review/00_README.md`): 30거래 WR 3.3% −₩18,196. **vpin_doge_wallet 비활성화** — atr_sl 완화 후에도 6/6 손절(진입 신호 자체 결함). vpin_mana/bat/pundix/orbs 4개 신규 월렛이 daemon 로드는 됐지만 tick 0건 = "유령 월렛" 버그 발견 (별도 디버그 필요). vpin_eth ratchet_stop 4회 또 발생, vpin_ondo 어제 흑자→오늘 −2% (운빨 가설 강화).
- **세션 (오후/feature/db-introduction)** — DB Phase 1 worktree 시작. SqliteStore + WAL + dedup-aware UNIQUE, JSONL→SQLite 마이그레이션 (실데이터 156 inserted/13 dup/2 malformed), DuckDB AnalyticsView (stage1a를 SQL 1쿼리로 재현), CLI script, Codex 적대적 리뷰 P1 5건 fix (errors 모듈, TradeRow validation, query 필터, 멀티프로세스 동시성 테스트). 30 tests passing. 2차 Codex 리뷰 진행 중 (task-mno8ud2c).
- **세션 (오후)** — 신규 전략 연구 Stage 1a~1d, Stage 2 가설 생성 완료. 7개 신규 paper 월렛 배포(vpin_mana/bat/pundix/orbs, bb_mr_doge/xrp/avax). 이중 daemon 버그 수정(`wallet_auto_updater.restart_daemon`). market_scan_loop에 stealth-watchlist fallback 추가. vpin atr_sl_multiplier 0.3→1.0 완화. 라이브 인프라 연구는 Codex(task-mno6pwjm-9wkgpu)에 위임 — 진행 중. DB 미존재 진단 — Phase 1 SQLite+DuckDB, Phase 2 PostgreSQL 권장. docs/research/ 구조 확립.
- **세션 (이른 오후)** — vpin_doge 박스권 11회 손실 진단 후 atr_sl_multiplier 완화. systemd daemon 재시작. strategy_research_loop 1시간 주기로 시작. 이중 daemon 발견 → wallet_auto_updater.restart_daemon이 systemctl 우회 Popen 사용하던 버그 수정.
- **세션 (오전)** — 일찍 daemon 모니터링. 거래 패턴 분석 (paper-trades.jsonl 169건).

## 이전 세션 (요약)

- 2026-04-06: 대시보드 수정, daemon 중복 해결, 누적매매 탭 추가
- 2026-04-05: 과최적화 함정 critical pivot — 자동 루프 중단, paper 데이터 축적 모드 전환
- 2026-04-04: backtest integrity fixes, regime-aware wallet workflow 설계
