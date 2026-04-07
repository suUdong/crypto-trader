# Storage Step1 적대적 코드 리뷰 (Codex)

## A. 동시성/안전성

### [P1] WAL+`synchronous=NORMAL` 조합은 다중 daemon에서 내구성과 락 회복력이 부족함
- **문제**: 초기화에서 `journal_mode=WAL`과 `synchronous=NORMAL`만 설정하고(`sqlite_store.py:108-109`), `busy_timeout`/재시도 정책이 없다.  
  구체 interleaving: `daemon-A`가 write 트랜잭션을 점유한 동안 `daemon-B`가 `insert_trade()`를 호출하면(`sqlite_store.py:124`) 락 대기/재시도 정책 없이 즉시 실패 경로로 전파될 수 있다.
- **영향**: 락 경합이 곧바로 write 실패로 노출되어 누락/재시도 폭증 위험이 생긴다. `NORMAL`은 전원 장애 시 최근 커밋 유실 가능성을 남긴다.
- **권장 수정**: 연결 시 `timeout`/`PRAGMA busy_timeout` 명시, write 경로에 bounded retry(backoff) 추가, 내구성 요구가 높으면 `synchronous=FULL` 분기 도입.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:96

### [P1] `connection()` 매 호출 open/close가 고빈도 write에서 비용과 락 churn을 키움
- **문제**: `connection()`이 매번 새 연결을 열고 닫으며(`sqlite_store.py:95-102`), `insert_trade()`/`query_trades()`가 호출마다 이를 사용한다(`sqlite_store.py:124`, `177`).
- **영향**: 고빈도 호출에서 연결 생성/해제 오버헤드와 락 획득 반복으로 처리량/지연이 악화될 수 있다.
- **권장 수정**: 프로세스 단위 장수명 연결(또는 writer 전용 연결)과 트랜잭션 배치 API 제공.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:95

### [P0] `IntegrityError`를 전부 중복으로 취급해 데이터 오류를 은닉할 수 있음
- **문제**: `insert_trade()`는 모든 `sqlite3.IntegrityError`를 잡은 뒤 자연키 `SELECT`가 성공하면 기존 id를 반환한다(`sqlite_store.py:151-168`). 이 경로는 UNIQUE 충돌뿐 아니라 `NOT NULL` 등 다른 무결성 위반도 함께 흡수한다.
- **영향**: malformed payload가 들어와도(동일 자연키 기존 행 존재 시) 호출자는 성공으로 오인한다. 데이터 품질 오류가 운영에서 침묵한다.
- **권장 수정**: `ON CONFLICT(... ) DO NOTHING RETURNING`으로 중복 경로만 분리하거나, UNIQUE 위반만 선별 처리.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:151

### [P1] `_initialise()` 동시 실행 시 락 실패 복구 경로가 없음
- **문제**: 생성자에서 즉시 `_initialise()`를 호출하고(`sqlite_store.py:88`), 내부에서 PRAGMA/DDL을 실행하지만(`sqlite_store.py:106-113`) 락 실패 재시도 로직이 없다.
- **영향**: 다중 daemon 동시 기동 타이밍에서 초기화 실패가 직접 노출될 수 있다.
- **권장 수정**: init 전용 retry/backoff와 `database is locked` 분기 처리 추가.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:106

## B. 데이터 무결성

### [P1] 자연키가 거래 식별자를 충분히 보장하지 못할 수 있음
- **문제**: UNIQUE 키가 `(wallet, symbol, entry_time, exit_time, session_id)`로 고정되어 있고(`sqlite_store.py:43`), 가격/수량/청산사유는 키에서 제외되어 있다.
- **영향**: 동일 세션/동일 시각 키를 공유하는 상이한 레코드가 발생하면 후행 입력이 중복 처리로 소실될 수 있다.
- **권장 수정**: 불변 `trade_id` 도입 또는 키 가정(불변성)을 코드 검증/문서 계약으로 강제.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:43

### [P1] 시간 문자열 형식/순서 검증이 없어 시계열 정렬 가정이 깨질 수 있음
- **문제**: `entry_time`/`exit_time`은 단순 `str`이며(`sqlite_store.py:65-66`) 삽입 시 ISO 형식/선후관계 검증이 없다. 조회는 문자열 정렬에 의존한다(`sqlite_store.py:176`).
- **영향**: invalid timestamp 또는 `entry_time > exit_time`이 저장되어 분석 결과가 왜곡될 수 있다.
- **권장 수정**: 삽입 전 ISO 파싱 검증 + `entry_time <= exit_time` 제약(앱/DB 병행).
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:65

### [P1] `pnl`, `pnl_pct`, `quantity` 유한성 검증 부재로 NaN/Inf 오염 가능
- **문제**: 실수 필드는 `REAL NOT NULL`만 있고(`sqlite_store.py:36-38`), `TradeRow`/insert 경로에서 `isfinite` 검증이 없다(`sqlite_store.py:67-71`, `124-149`).
- **영향**: NaN/Inf 유입 시 집계/비교 결과가 비정상화되어 성과 지표 신뢰도가 하락한다.
- **권장 수정**: 삽입 전 유한성/범위 검증 추가.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:36

### [P1] `position_side='long'` 기본값 + 제약 부재로 short 오분류가 은닉됨
- **문제**: 기본값이 `'long'`(`sqlite_store.py:74`)이고 DB `CHECK` 제약이 없다(`sqlite_store.py:41`).
- **영향**: short 거래에서 필드 누락 시 long으로 저장되어 방향 통계가 오염된다. 오타 문자열도 저장된다.
- **권장 수정**: 입력 검증(`long|short`) + DB `CHECK` 추가.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:74

## C. 테스트 충분성

### [P1] 동시 삽입/race 테스트가 없음
- **문제**: 10개 테스트가 단일 fixture 기반 순차 호출만 수행한다(`test_sqlite_store.py:17-20`, `75-121`).
- **영향**: 멀티 daemon 경합 회귀(락/중복/초기화)가 사전 검출되지 않는다.
- **권장 수정**: 멀티스레드/멀티프로세스 동시 insert 및 동시 init 테스트 추가.
- **영향 라인**: tests/storage/test_sqlite_store.py:17

### [P1] 큰 트랜잭션 롤백/원자성 테스트가 없음
- **문제**: 테스트가 단건 insert/query 위주이며 배치 실패 시 부분 반영 여부를 검증하지 않는다(`test_sqlite_store.py:74-121`).
- **영향**: 배치 도입 시 부분 커밋 회귀를 놓칠 수 있다.
- **권장 수정**: 명시적 트랜잭션 실패 후 row count 불변 테스트 추가.
- **영향 라인**: tests/storage/test_sqlite_store.py:74

### [P1] malformed input, 시간 역전 케이스 테스트가 없음
- **문제**: 샘플 입력이 모두 정상값만 사용한다(`test_sqlite_store.py:23-45`).
- **영향**: 입력 오염 경로가 테스트 없이 운영으로 유입될 수 있다.
- **권장 수정**: invalid timestamp/NaN/Inf/None/역전 시간에 대한 실패 테스트 추가.
- **영향 라인**: tests/storage/test_sqlite_store.py:23

### [P2] property-based/fuzz 테스트 부재
- **문제**: 자연키/시간/수치 조합의 경계 탐색 테스트가 없다.
- **영향**: 희귀 조합 결함이 장기간 잠복할 수 있다.
- **권장 수정**: 생성형 테스트(Hypothesis 등)로 key 충돌 및 수치 경계 자동 탐색.
- **영향 라인**: tests/storage/test_sqlite_store.py:23

## D. API 디자인

### [P2] `query_trades()` 필터가 `wallet`만 지원
- **문제**: 시그니처가 `wallet` 단일 필터로 제한된다(`sqlite_store.py:170-175`).
- **영향**: 시간/사유/PnL 기준 질의가 불가해 상위 계층의 비효율적 후처리 유도.
- **권장 수정**: 시간 범위, `exit_reason`, `pnl/pnl_pct` 임계 필터 추가.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:170

### [P1] `fetchall()` + 전건 `list[TradeRow]` 반환으로 메모리 폭주 위험
- **문제**: 전건 `fetchall()` 후 dataclass 리스트로 즉시 물질화한다(`sqlite_store.py:178-194`).
- **영향**: 대용량 데이터에서 메모리 급증 및 성능 저하.
- **권장 수정**: iterator/streaming 또는 페이지네이션 API 도입.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:178

### [P2] `path` 노출이 캡슐화를 약화
- **문제**: 내부 DB 경로를 `path` 프로퍼티로 외부에 노출한다(`sqlite_store.py:90-92`).
- **영향**: 외부 모듈이 파일 경로에 결합되어 backend 교체 시 영향 범위 확장.
- **권장 수정**: 데이터소스 인터페이스 분리, 경로 대신 명시적 adapter 전달.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:90

## E. Phase 2 PostgreSQL 전환 안전성

### [P1] 구현이 SQLite 전용 가정에 강결합
- **문제**: `sqlite3.connect`, `PRAGMA`, `AUTOINCREMENT`, `datetime('now')`, `sqlite3.Row`에 직접 결합되어 있다(`sqlite_store.py:29`, `42`, `96-109`, `97`).
- **영향**: “connection/DDL 교체만”으로는 이식 불가, 예외/트랜잭션/row 매핑까지 재설계 필요.
- **권장 수정**: 저장소 인터페이스 + backend별 dialect/exception mapper 분리.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:96

### [P2] DDL 상수는 있으나 버전드 마이그레이션 자산으로 미흡
- **문제**: `_TRADES_DDL` 단일 문자열 기반이며 스키마 버전/업그레이드 경로가 없다(`sqlite_store.py:27-45`).
- **영향**: 이력 기반 마이그레이션 운영(roll-forward/rollback) 난이도 상승.
- **권장 수정**: 버전드 migration 파일 체계 및 backend별 DDL 분리.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:27

## F. 누락된 기본

### [P2] 로깅 부재
- **문제**: 스토리지 모듈에서 로깅 import/호출이 없다(`sqlite_store.py` 전체).
- **영향**: 락/무결성/초기화 실패의 운영 포렌식이 어려움.
- **권장 수정**: 실패 경로 중심 구조화 로그 추가.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:1

### [P2] `__init__.py` 재수출 표면이 넓음
- **문제**: store/row/migration API를 패키지 루트에서 동시 노출한다(`storage/__init__.py:10-21`).
- **영향**: 모듈 경계 희석, API 안정성 관리 비용 증가.
- **권장 수정**: 루트 export 최소화, 서브모듈 명시 import 기본화.
- **영향 라인**: src/crypto_trader/storage/__init__.py:10

### [P2] `params` 타입 힌트가 비구체적
- **문제**: `params: tuple = ()`로 선언되어 타입 정보가 소실된다(`sqlite_store.py:172`).
- **영향**: 정적 타입 검사 효용 저하.
- **권장 수정**: `tuple[object, ...]` 등 구체 타입으로 명시.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:172

### [P1] 사용자 정의 예외 계층 부재
- **문제**: DB 예외를 도메인 예외로 매핑하지 않고 raw 예외가 누출된다(`sqlite_store.py:151`, `167`).
- **영향**: 상위 계층이 DB 구현 세부사항에 결합되고 backend 교체 시 예외 처리 파손 가능.
- **권장 수정**: `StorageError` 계층 및 세부 예외 매핑 도입.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:151

## G. 디자인 문서 일치

### [P1] 지정된 디자인 문서가 현재 브랜치에 없음
- **문제**: `docs/research/2026-04-07-infra/03_db_design.md`가 워크트리/HEAD에서 확인되지 않는다.
- **영향**: 문서-구현 정합성 검증이 불가능해 설계 누락을 코드 리뷰에서 확정할 수 없다.
- **권장 수정**: 문서 경로를 브랜치에 포함하거나 유효 경로로 고정.
- **영향 라인**: docs/research/2026-04-07-infra/03_db_design.md:1

### [P1] 현재 구현은 `trades` 단일 테이블만 제공
- **문제**: 스키마 초기화가 `trades` 1개 + 인덱스 3개로 제한된다(`sqlite_store.py:27-51`, `106-113`).
- **영향**: `wallets`/`positions`/`pnl_snapshots`/`wallet_changes` 확장 시 참조 무결성/조인 계약이 선행 검증되지 않는다.
- **권장 수정**: 단계 분할 의도와 미구현 엔터티 도입 시점을 코드/문서에 명시하고 마이그레이션 골격 제공.
- **영향 라인**: src/crypto_trader/storage/sqlite_store.py:27

### [P2] DuckDB 연동은 `trades` 고정 가정에 묶여 확장 검증이 부족
- **문제**: DuckDB attach는 구현되어 있으나(`analytics.py:45`), 쿼리가 `opdb.trades` 고정이다(`analytics.py:61`, `82`, `104`).
- **영향**: 다중 테이블 단계에서 조인/정합성 경로 검증 공백이 남는다.
- **권장 수정**: 멀티테이블 attach/조인 테스트와 스키마 버전 호환성 체크 추가.
- **영향 라인**: src/crypto_trader/storage/analytics.py:61
[2026-04-07T06:30:04.800Z] Turn completed.

[2026-04-07T06:30:04.817Z] Final output
`read-only filesystem` 제약으로 아래 경로에 파일을 생성하지 못했습니다.  
요청한 리포트 본문을 그대로 제공합니다.

대상 경로: `/home/wdsr88/workspace/crypto-trader/.worktrees/db-introduction/docs/reviews/2026-04-07-storage-step1-codex-review.md`
