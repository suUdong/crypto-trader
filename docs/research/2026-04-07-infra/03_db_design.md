# 03 — DB 도입 설계 (Phase 1)

작성일: 2026-04-07
상태: 구현 진행 중 (`feature/db-introduction`, 12 커밋)
관련 리뷰: `docs/reviews/2026-04-07-storage-step1-codex-review.md`

## 0. 문제 정의

현재 crypto-trader 의 paper/live 거래 기록은 append-only JSONL 파일로만 보관된다:
- `artifacts/paper-trades.jsonl`
- `artifacts/strategy-runs.jsonl`
- `artifacts/positions.json` (현재 포지션 snapshot)
- `artifacts/daily-performance.json` (일일 집계)

JSONL 기반의 한계:
1. **쿼리 비용** — 대시보드가 매번 전체 파일을 파싱 (O(N) 매 refresh)
2. **집계 지연** — `strategy_report.py`, `evaluator_loop.py` 등이 같은 파일을 반복 로드
3. **데이터 이상 감지 불가** — 2026-04-07 듀얼 daemon 사고에서 29 중복 row 생성 후에야 인지
4. **동시성 취약** — 여러 프로세스가 flock 없이 append 하면 레코드 손상 위험
5. **스키마 진화 어려움** — JSON 자유 형식이라 validator 없이 필드 오타가 누적

## 1. 목표

Phase 1 에서 **JSONL 을 source of truth 로 유지한 채**, 옆에 SQLite mirror 를 구축한다. Phase 2 에서 PostgreSQL 로 전환할 때 스토리지 인터페이스만 갈아끼우면 되도록 설계한다.

비목표 (YAGNI):
- ORM 도입 (pydantic/SQLAlchemy)
- 이벤트 소싱 / 스트림 재생
- 다중 테이블 조인 기반 분석 (Phase 1 step 6 이후)
- Phase 2 추상화 레이어 선행 작성

## 2. 아키텍처

```
  ┌─────────────────────┐
  │ MultiWalletDaemon   │    매 tick
  │  _persist_journal   │
  └──────────┬──────────┘
             │
             ├──→ PaperTradeJournal    → artifacts/paper-trades.jsonl  (SOT)
             │
             └──→ SqliteStore          → artifacts/paper-trades.db     (mirror)
                  dual-write
                  (best-effort,
                   error-swallowing)

  ┌──────────────┐                    ┌──────────────┐
  │ Dashboard    │  ← edge_analysis ─ │ SqliteStore  │ (read preferred)
  │ (streamlit)  │  ← 나머지 ──────── │ JSONL        │ (fallback)
  └──────────────┘                    └──────────────┘
```

- **Dual-write 는 best-effort**: SQLite 쓰기 실패는 로그 후 swallow → 데몬 tick 절대 중단 없음
- **JSONL 이 source of truth**: SQLite 손상 시 마이그레이션 CLI 로 재구축 가능
- **Reader 전환은 점진적**: 각 consumer 가 필요한 컬럼만 SQLite 에 있으면 전환

## 3. 스키마

### 3.1. `trades` 테이블 (현재)

```sql
CREATE TABLE trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet        TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    entry_time    TEXT NOT NULL,             -- ISO-8601 UTC
    exit_time     TEXT NOT NULL,
    entry_price   REAL NOT NULL,
    exit_price    REAL NOT NULL,
    quantity      REAL NOT NULL,
    pnl           REAL NOT NULL,
    pnl_pct       REAL NOT NULL,
    exit_reason   TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    position_side TEXT NOT NULL DEFAULT 'long',
    inserted_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (wallet, symbol, entry_time, exit_time, session_id)
);

CREATE INDEX idx_trades_wallet      ON trades(wallet);
CREATE INDEX idx_trades_exit_time   ON trades(exit_time);
CREATE INDEX idx_trades_exit_reason ON trades(exit_reason);
```

### 3.2. 자연키 선택

UNIQUE 키 = `(wallet, symbol, entry_time, exit_time, session_id)`

**설계 근거**:
- 2026-04-07 듀얼 daemon 사고는 서로 다른 session_id 로 동일 거래가 중복 기록됨 → 이 경우는 **두 row 를 모두 남기고 DuckDB 분석에서 flag** 하는 것이 은닉보다 낫다고 판단
- 가격/수량/exit_reason 은 키에서 제외 → 같은 시간대 중복 레코드의 추가 fingerprinting 은 application 책임

**남은 약점** (Codex 리뷰 P1 B):
- 동일 session 내에서 이론상 충돌 가능 (short position 반복 진입 등)
- 해결 방향: 불변 `trade_id` UUID 도입 — Phase 1 step 7 에서 검토

### 3.3. 제외된 컬럼 (의도적)

현재 JSONL 에는 있지만 SQLite 에는 아직 없는 필드:

| 필드 | 계획 |
|---|---|
| `entry_confidence` | step 6 추가 — dashboard 전략 신호 분석에 필요 |
| `entry_order_type`, `exit_order_type` | step 6 |
| `entry_fee_paid`, `exit_fee_paid`, `entry_fee_rate` | step 6 |
| `entry_slippage_pct`, `exit_slippage_pct` | step 6 |
| `entry_reference_price`, `exit_reference_price` | step 6 |

**의도**: Phase 1 은 스키마 최소화로 시작, 대시보드 consumer 별로 실제 필요 컬럼이 확인되면 그때 확장 (grounded design, YAGNI 와 실제 운영 요구 사이 절충).

**주의**: 이 때문에 대시보드의 일부 consumer 는 여전히 JSONL 을 읽는다. step 6 까지는 **두 reader 가 공존하는 것이 정상 상태**.

## 4. 동시성

### 4.1. SQLite WAL 모드

- `journal_mode = WAL` — 다중 reader / 단일 writer 기본 보장
- `synchronous = NORMAL` — fsync 비용 대폭 감소, 전원 장애 시 최근 커밋 유실 허용 (JSONL 이 SOT 이므로 복구 가능)
- `busy_timeout = 5000ms` — 드라이버 레벨 wait

### 4.2. Application 레이어 retry

`_retry_on_lock()` 은 `sqlite3.OperationalError` 메시지에 `locked` / `busy` 포함된 경우만 retry:
- 최대 5회 시도
- Exponential backoff (base 50 ms, cap 500 ms)
- Jitter 25 % — 다중 daemon thundering herd 완화
- 타 OperationalError (no such table 등) 는 즉시 raise → 진짜 버그가 transient 로 위장되지 않음

**Verified**:
- `tests/storage/test_sqlite_store.py::TestConcurrency::test_multiple_processes_can_insert_concurrently` — 4 process × 20 unique trades 성공
- `test_connection_sets_busy_timeout`, `test_insert_trade_retries_on_transient_lock` 등 4개 유닛

### 4.3. Phase 2 에서 달라질 것

PostgreSQL 로 전환하면 `busy_timeout` / retry 는 connection pool 의 `statement_timeout` + deadlock retry 로 대체된다. `_retry_on_lock()` 은 SQLite 전용 레이어로 문서화되어 있음 (`sqlite_store.py:34-91`).

## 5. 데이터 무결성

### 5.1. TradeRow `__post_init__` 검증

모든 row 는 DB 에 도달하기 전에 다음을 통과:
- 모든 숫자 필드 `math.isfinite()` (NaN/Inf 거부)
- `entry_price`, `exit_price`, `quantity` ≥ 0
- `exit_time >= entry_time` (lexical compare — ISO-8601 이 보장)

위반 시 `ValidationError` (also subclass `ValueError`) raise, DB 호출 전에 차단.

### 5.2. 예외 계층

```
StorageError
├── ValidationError  (inputs)
└── IntegrityError   (DB 제약 위반, UNIQUE 제외)
```

`insert_trade()` 는 `sqlite3.IntegrityError` 를 UNIQUE 충돌 / 기타로 구분:
- UNIQUE 충돌 + 자연키로 기존 row 찾기 성공 → 기존 id 반환 (idempotent)
- 그 외 → `IntegrityError` 로 변환 후 raise

원시 `sqlite3.*` 예외는 public API 를 벗어나지 않음.

### 5.3. 남은 약점

| Finding | 상태 |
|---|---|
| 불변 `trade_id` 부재 | 보류 (step 7 검토) |
| `position_side` CHECK 제약 부재 | 보류 (step 6 에 포함) |
| `exit_reason` enum 부재 | YAGNI — 전략마다 자유로이 추가 중 |

## 6. 마이그레이션 파이프라인

### 6.1. One-shot 백필

`scripts/migrate_paper_trades_to_sqlite.py`

- JSONL line-by-line 파싱, TradeRow 로 변환 후 `insert_trade()` 호출
- Idempotent — 이미 이중 쓰기 중이어도 재실행 안전
- 출력: `total_lines`, `inserted`, `skipped_duplicate`, `skipped_malformed`
- 2026-04-07 실행 결과: 172 lines → 157 inserted, 13 dup, 2 malformed

### 6.2. 이중 쓰기 활성화 경로

1. ✅ `PaperTradingOperations.sync()` — 단일 월렛 runtime
2. ✅ `MultiWalletDaemon._persist_journal()` — 다중 월렛 daemon
3. ✅ `RuntimeConfig.paper_trade_sqlite_path` 옵트인
4. ✅ `config/daemon.toml` 활성화 커밋 (`3d71d2a`)
5. ⏳ daemon 재시작 — 사용자 승인 대기

### 6.3. 롤백

SQLite 파일 삭제 후 재마이그레이션:
```bash
rm /var/lib/crypto-trader/artifacts/paper-trades.db
python scripts/migrate_paper_trades_to_sqlite.py \
  --jsonl /var/lib/crypto-trader/artifacts/paper-trades.jsonl \
  --db    /var/lib/crypto-trader/artifacts/paper-trades.db
```

JSONL 이 살아있는 한 SQLite 손상은 치명적이지 않음.

## 7. DuckDB 분석 뷰

`src/crypto_trader/storage/analytics.py`:
- SQLite 파일을 DuckDB `ATTACH` (read-only)
- `opdb.trades` 뷰 → `wallet_pnl_summary`, `daily_pnl`, `worst_drawdowns` 등 집계 함수
- Streamlit / Jupyter 에서 동일 쿼리 재사용

**Phase 1 제약**: `opdb.trades` 단일 테이블 가정. Phase 1 step 6+ 에서 `positions`, `pnl_snapshots` 테이블 추가 시 조인 호환성 검증 필요.

## 8. Phase 1 체크리스트

### 완료
- [x] SqliteStore + WAL + 자연키 UNIQUE
- [x] JSONL → SQLite 마이그레이션 함수 + CLI
- [x] DuckDB 분석 뷰
- [x] Custom 예외 계층 (`StorageError`, `ValidationError`, `IntegrityError`)
- [x] `TradeRow.__post_init__` 유한성/순서 validation
- [x] `query_trades()` 필터 확장 (wallet, exit_reason, since, until, limit)
- [x] 멀티프로세스 동시 insert 테스트
- [x] Codex 적대적 리뷰 + P1 대응 문서
- [x] `busy_timeout` + bounded exponential retry
- [x] `PaperTradingOperations` dual-write 배선
- [x] `MultiWalletDaemon._persist_journal` dual-write 배선
- [x] `RuntimeConfig.paper_trade_sqlite_path` 설정 항목
- [x] 대시보드 `load_edge_analysis()` SQLite-preferred reader
- [x] `config/daemon.toml` 활성화 + 백필

### 진행 중 / 대기
- [ ] daemon 재시작 (사용자 승인 대기)
- [ ] 장수명 connection / batch insert API (Codex P1 A, 성능 최적화)
- [ ] 불변 `trade_id` UUID (Codex P1 B)
- [ ] `position_side` CHECK 제약 + validation (Codex P1 B)
- [ ] 트랜잭션 롤백/원자성 테스트 (Codex P1 C)
- [ ] Malformed input/시간 역전 실패 테스트 (Codex P1 C)
- [ ] Streaming `iter_trades()` pagination (Codex P1 D)
- [ ] 스키마 확장 (fee/slippage/confidence 컬럼) → 대시보드 전면 전환

### Phase 2 (PostgreSQL) 에서 처리
- [ ] `StorageBackend` 인터페이스 추출 + SQLite/PG dialect 분리
- [ ] 버전드 migration 자산 (alembic 등)
- [ ] Connection pool / async I/O
- [ ] 다중 테이블 (wallets, positions, pnl_snapshots, wallet_changes)

## 9. 참고 커밋

- `b45a695` SqliteStore 최초 도입
- `1151b9c` JSONL → SQLite 마이그레이션
- `2f5323a` DuckDB 분석 뷰
- `45397b6` 마이그레이션 CLI
- `2ed0fd6` Codex P1 리뷰 대응 (5건)
- `1304001` PaperTradingOperations dual-write
- `d011aeb` RuntimeConfig + daemon/cli 배선
- `510b506` busy_timeout + retry
- `f9800fc` 대시보드 edge_analysis SQLite reader
- `3d71d2a` daemon.toml 활성화 + 백필 (157 rows)
