# Scripts Surface Map

이 디렉터리에는 운영 진입점, 연구용 유틸리티, 그리고 과거 실험 스크립트가 섞여 있습니다.  
현재 유지보수 우선순위는 아래 구분을 기준으로 판단합니다.

## Active Operational Entrypoints

이 스크립트들은 현재 운영 흐름이나 수동 운영 절차에서 직접 호출될 수 있는 표면입니다.

- `market_scan_loop.py`
  - 알파 스캔, watchlist 산출, accumulation rotation 후보 갱신
- `strategy_research_loop.py`
  - 전략 연구/백테스트 파이프라인 루프
- `wallet_auto_updater.py`
  - daemon config 심볼/파라미터 반영과 변경 이력 기록
- `apply_alpha_to_daemon.py`
  - alpha watchlist를 daemon config에 수동 반영
- `restart_daemon.sh`
  - daemon 재시작 진입점
- `loop_watchdog.sh`
  - scan/research 루프 감시
- `status.py`
  - 운영 상태 조회
- `generate_handoff.py`
  - 세션 handoff 생성

이 표면의 변경은 테스트, compile, changed-file lint/typecheck를 우선 적용합니다.

## Active Research Utilities

현재도 직접 참고하거나 수동 실행할 수 있지만, 운영 핵심 표면은 아닙니다.

- `backtest_all.py`
- `auto_tune.py`
- `strategy_tournament.py`
- `check_bull_trigger.py`

이 범주는 점진적으로 공용 라이브러리/manifest 기반 runner로 흡수하는 것이 목표입니다.

## Historical / Experimental Scripts

`backtest_cycle*.py`, `backtest_*`의 상당수는 특정 연구 사이클 결과를 보존한 역사 자산입니다.  
새 기능을 여기에 계속 누적하지 말고, 가능하면 다음 우선순위를 따릅니다.

1. 공용 로직은 `src/`로 이동
2. 반복 가능한 실행은 manifest 또는 runner에 등록
3. 단발성 실험은 역사 기록으로 남기고 active entrypoint로 승격하지 않음

## Maintenance Rules

1. 새로운 운영 기능은 먼저 `src/` 모듈로 만들고, `scripts/`는 thin entrypoint로 유지합니다.
2. 새 스크립트를 추가할 때는 이 문서에 분류를 반영합니다.
3. 운영 표면과 연구 역사 자산을 같은 품질 기대치로 섞어 관리하지 않습니다.
4. 실험 결과 보존이 목적이면 `docs/research/` 또는 `artifacts/`를 우선 검토합니다.

