# Strategy Evaluator v2 — 플러그인 기반 정량 평가 파이프라인

## 배경 & 동기

### 기존 evaluator v1 문제점

1. **actionable_rate 100%** — Opus가 모든 입력에 "조치 필요" 응답, 필터링 무의미
2. **adopted_by_ralph = null (전부)** — Ralph이 결과를 한 번도 소비하지 않음
3. **Opus 비용 대비 ROI 0** — 15회 호출 전부 실질적 가치 없음
4. **CLAUDE.md 규칙 4 위반** — "시스템 위에 시스템" 금지 원칙 위배 (LLM이 판단)
5. **모놀리식 구조** — 데이터 수집, 판정, 출력이 하나의 스크립트에 결합

### 개선 원칙

- **판단은 코드, 표현은 LLM** — 정량 기준으로 pass/fail 결정 후 Opus는 포맷팅만
- **플러그인 확장** — 새 평가 항목은 파일 하나 추가로 등록
- **기존 operator 코드 재사용** — `strategy_perf_report.py`, `promotion.py`, `verdicts.py` 등
- **CLAUDE.md 준수** — LLM이 전략적 판단을 하지 않음

## 아키텍처

```
scripts/strategy_evaluator_v2.py     # 엔트리포인트 (루프 + 트리거)
src/crypto_trader/evaluator/
    __init__.py
    engine.py                        # 파이프라인 엔진 (check 로드 → 실행 → 집계)
    models.py                        # CheckResult, EvaluationReport 데이터 모델
    formatter.py                     # Opus 호출 → 사람용 리포트 생성
    checks/                          # 플러그인 디렉토리
        __init__.py
        base.py                      # BaseCheck ABC
        backtest_quality.py          # 백테스트 품질 검사
        strategy_health.py           # daemon 활성 전략 건강도
        portfolio_risk.py            # 포트폴리오 리스크 집중도
        research_progress.py         # research loop 신규 결과 평가
```

### 데이터 흐름

```
[데이터 소스]                    [평가 엔진]              [출력]
backtest_history.md ─┐
daemon.toml ─────────┤
strategy_research    ─┼─→ Engine ─→ checks/* ─→ aggregate ─→ Opus formatter ─→ Telegram
  .state.json        │       │                      │                          JSON report
market_scan          ─┤       │                      │
  .state.json        │       └── grade 결정 ─────────┘
runtime-checkpoint ──┤              (코드 규칙)
  .json              │
journal / logs ──────┘
```

## 핵심 모델

### CheckResult

각 check 플러그인의 반환 타입:

```python
@dataclass(frozen=True)
class CheckResult:
    check_name: str                           # e.g. "backtest_quality"
    grade: Grade                              # PASS | WARN | FAIL | SKIP
    score: float                              # 0.0 ~ 1.0 정규화 점수
    findings: list[str]                       # 사람이 읽을 발견 사항
    metrics: dict[str, float | int | str]     # 정량 메트릭 (JSON 직렬화 가능)
    suggestions: list[str]                    # 개선 제안 (선택적)

class Grade(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"      # 데이터 부족 등으로 평가 불가
```

### EvaluationReport

전체 평가 결과 집계:

```python
@dataclass
class EvaluationReport:
    eval_id: str                              # uuid
    timestamp: str                            # ISO 8601
    overall_grade: Grade                      # 최악 grade 기준 (any FAIL → FAIL)
    overall_score: float                      # 가중 평균 score
    check_results: list[CheckResult]          # 개별 check 결과
    data_sources_used: list[str]              # 어떤 소스를 읽었는지
    trigger_reason: str                       # "scheduled" | "file_change:xxx"
```

## Check 플러그인 인터페이스

### BaseCheck ABC

```python
class BaseCheck(ABC):
    """모든 check 플러그인이 구현해야 하는 인터페이스."""

    @property
    @abstractmethod
    def name(self) -> str:
        """고유 check 이름 (e.g. 'backtest_quality')."""

    @property
    def weight(self) -> float:
        """overall_score 계산 시 가중치. 기본 1.0."""
        return 1.0

    @abstractmethod
    def run(self, ctx: EvalContext) -> CheckResult:
        """평가 실행. 데이터가 없으면 Grade.SKIP 반환."""
```

### EvalContext

check에 주입되는 컨텍스트:

```python
@dataclass
class EvalContext:
    backtest_history_tail: str                # 최근 120줄
    daemon_strategies: list[str]              # daemon.toml 활성 전략
    daemon_config_path: Path
    research_state: dict | None               # strategy_research.state.json
    market_scan_state: dict | None            # market_scan.state.json
    checkpoint: dict | None                   # runtime-checkpoint.json
    journal_trades: list[dict]                # journal JSONL 파싱 결과
    prev_report: EvaluationReport | None      # 이전 평가 결과 (변화 감지용)
```

### 자동 등록

`engine.py`가 `checks/` 패키지에서 `BaseCheck` 서브클래스를 자동 발견:

```python
def discover_checks() -> list[BaseCheck]:
    """checks/ 패키지에서 BaseCheck 서브클래스를 자동 발견 및 인스턴스화."""
    import importlib
    import pkgutil
    from crypto_trader.evaluator import checks as checks_pkg

    found = []
    for info in pkgutil.iter_modules(checks_pkg.__path__):
        if info.name == "base":
            continue
        mod = importlib.import_module(f"crypto_trader.evaluator.checks.{info.name}")
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if isinstance(obj, type) and issubclass(obj, BaseCheck) and obj is not BaseCheck:
                found.append(obj())
    return found
```

## 초기 Check 구현 (4개)

### 1. backtest_quality

`backtest_history.md` 최근 결과에서:
- **n_trades 충분성**: n < 30 → WARN, n < 10 → FAIL
- **Sharpe 유의성**: Sharpe / sqrt(n) < 0.5 → WARN (통계적 유의성 부족)
- **OOS 효율**: walk-forward efficiency < 0.3 → FAIL
- **슬리피지 내성**: 0.10% → 0.20% 전환 시 Sharpe 50%+ 하락 → WARN

기존 코드 재사용: `_compute_risk_adjusted_score()` from `strategy_perf_report.py`

### 2. strategy_health

daemon.toml 활성 전략 + runtime-checkpoint:
- **전략별 수익률**: 지갑 equity vs initial_capital
- **연속 손실**: max_consecutive_losses >= SAFE_MAX(3) → FAIL
- **MDD 초과**: drawdown > 10% → WARN, > 20% → FAIL
- **유휴 전략 식별**: 최근 7일 거래 0건 → WARN

기존 코드 재사용: `StrategyVerdictEngine`, `MicroLiveCriteria`

### 3. portfolio_risk

포트폴리오 전체 관점:
- **전략 집중도**: 단일 전략 자본 비중 > 40% → WARN
- **활성 레짐 커버리지**: BEAR에서 가동 가능 전략 < 2개 → WARN
- **상관 위험**: (향후 확장) 전략 간 수익률 상관 > 0.7 → WARN

### 4. research_progress

`strategy_research.state.json` + `market_scan.state.json`:
- **research 사이클 진행**: 마지막 평가 이후 새 완료 항목 수
- **유망 후보 식별**: done 리스트에서 Sharpe 키워드 파싱, 상위 후보 추출
- **market scan 이상 감지**: watchlist 변동폭 급변 → WARN

## 트리거 시스템

### 이벤트 + 최소 간격

```python
TRIGGER_FILES = [
    "state/strategy_research.state.json",
    "state/market_scan.state.json",
    "docs/backtest_history.md",
    "artifacts/runtime-checkpoint.json",
]
MIN_INTERVAL_SECONDS = 1800   # 최소 30분 간격
POLL_SECONDS = 60             # mtime 확인 주기
```

동작:
1. 매 60초마다 `TRIGGER_FILES`의 mtime 확인
2. 마지막 평가 이후 변경된 파일이 있으면 → 평가 후보
3. 마지막 평가로부터 MIN_INTERVAL_SECONDS 경과했으면 → 실행
4. 변경 없으면 → 스킵

fallback: `--once` 플래그로 1회 실행, `--force` 플래그로 간격 무시 강제 실행

### config/loop_throttle.toml 연동

기존 throttle 파일과 호환:
```toml
[evaluator_v2]
min_interval_seconds = 1800
poll_seconds = 60
```

## Opus Formatter

### 역할 한정

Opus는 **판정을 하지 않음**. 입력으로 `EvaluationReport`(정량 결과 확정)를 받아:
1. 사람이 읽기 좋은 한국어 요약 생성
2. Telegram 메시지 포맷 (5-8줄, 이모지 포함)
3. JSON report의 `summary_for_human` 필드 채움

### 프롬프트 구조

```
당신은 트레이딩 전략 평가 결과를 정리하는 리포터입니다.
아래 정량 평가 결과를 사람이 읽기 좋은 한국어 요약으로 변환하세요.

## 판정 결과 (변경 금지)
{overall_grade}: {overall_score}
{각 check의 grade, score, findings, metrics를 구조화하여 전달}

## 지시사항
- 위 판정 결과를 그대로 전달하세요. 등급을 변경하거나 재해석하지 마세요.
- 핵심 수치는 반드시 포함하세요.
- telegram_summary: 5-8줄, 이모지 포함, 한국어
- detailed_summary: 섹션별 분석, 마크다운
```

### fallback

Opus 호출 실패 시 → 정량 결과를 템플릿 기반으로 직접 포맷팅 (LLM 없이도 리포트 생성 가능)

```python
def fallback_format(report: EvaluationReport) -> str:
    """Opus 호출 실패 시 템플릿 기반 포맷팅."""
    lines = [f"[평가 {report.eval_id}] {report.timestamp[:16]}"]
    lines.append(f"종합: {report.overall_grade.value} (score={report.overall_score:.2f})")
    for cr in report.check_results:
        lines.append(f"  {cr.check_name}: {cr.grade.value} — {'; '.join(cr.findings[:2])}")
    return "\n".join(lines)
```

## 출력

### state/evaluator_report.json

기존 v1과 호환되는 구조 + 확장:

```json
{
  "schema_version": 2,
  "generated_at": "2026-04-13T12:00:00+00:00",
  "eval_id": "eval-abcd1234",
  "trigger_reason": "file_change:strategy_research.state.json",
  "overall_grade": "warn",
  "overall_score": 0.65,
  "check_results": [
    {
      "check_name": "backtest_quality",
      "grade": "pass",
      "score": 0.82,
      "findings": ["최근 백테스트 n=86, Sharpe 통계 유의"],
      "metrics": {"avg_n_trades": 86, "avg_sharpe": 7.15},
      "suggestions": []
    }
  ],
  "summary_for_human": "Opus가 생성한 한국어 요약",
  "telegram_summary": "Opus가 생성한 Telegram 요약"
}
```

### state/evaluator_history.json

기존 v1 히스토리와 별도. 최대 100개 유지:

```json
{
  "schema_version": 2,
  "evaluations": [
    {
      "eval_id": "eval-abcd1234",
      "timestamp": "...",
      "overall_grade": "warn",
      "overall_score": 0.65,
      "trigger_reason": "file_change:...",
      "check_summary": {"backtest_quality": "pass", "strategy_health": "warn"}
    }
  ]
}
```

### Telegram

기존 `notify()` 함수 재사용. `CT_TELEGRAM_TOKEN` + `CT_TELEGRAM_CHAT_ID` 환경변수.

## 기존 코드와의 관계

### 재사용

| 기존 모듈 | 사용처 |
|---|---|
| `strategy_perf_report._compute_risk_adjusted_score()` | `backtest_quality` check |
| `promotion.MicroLiveCriteria` | `strategy_health` check |
| `verdicts.StrategyVerdictEngine` | `strategy_health` check (연속 실패 판정) |
| `models.BacktestResult` | 백테스트 결과 파싱 |

### 대체

`scripts/strategy_evaluator_loop.py` → `scripts/strategy_evaluator_v2.py`로 대체.
v1 파일은 삭제하지 않고 deprecated 주석 추가.

### 미변경

- `crypto_ralph.sh`의 `get_evaluator_report()` — v2 JSON도 동일 경로(`state/evaluator_report.json`)에 쓰므로 호환
- `config/loop_throttle.toml` — `[evaluator_v2]` 섹션 추가

## 확장 가이드

새 check 추가 시:

1. `src/crypto_trader/evaluator/checks/` 에 파일 생성
2. `BaseCheck`를 상속하고 `name`, `run()` 구현
3. 끝 — `discover_checks()`가 자동 발견

예시: correlation check 추가

```python
# src/crypto_trader/evaluator/checks/correlation.py
class CorrelationCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "correlation"

    def run(self, ctx: EvalContext) -> CheckResult:
        # 전략 간 상관관계 분석 로직
        ...
```

## 테스트 전략

- 각 check는 독립 단위 테스트 (`tests/test_evaluator_checks.py`)
- engine 통합 테스트: mock EvalContext → 파이프라인 실행 → EvaluationReport 검증
- formatter 테스트: Opus 호출 mock → 출력 포맷 검증
- 기존 `pytest` + `mypy` + `ruff` 게이트 통과 필수
