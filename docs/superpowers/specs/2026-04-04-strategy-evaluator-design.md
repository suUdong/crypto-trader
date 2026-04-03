# Strategy Evaluator — Design Spec

**날짜:** 2026-04-04  
**상태:** 승인 대기  
**목적:** Ralph/Codex 작업자들의 결과를 전문 심사관 LLM이 자율적으로 검토하고, 구조화된 방향을 다시 작업자들과 사용자에게 제공하는 독립 평가 시스템

---

## 1. 개요

### 문제

Ralph 루프가 사이클을 반복하며 백테스트 결과를 쌓지만, 결과를 "읽는" 주체가 없다. Claude/Codex는 각 사이클에서 이전 사이클 요약만 참고하여 다음 작업을 결정한다. 전문적 시각으로 누적 결과를 종합 분석하고 방향을 잡아주는 레이어가 없다.

### 해결

**StrategyEvaluator** — 독립적으로 동작하는 자율 심사관. 주기적으로 작업자 결과를 수집하고, 스스로 "검토할 만한 상태인가"를 판단한 뒤, Opus를 호출해 전문 심사를 수행한다. 자신의 평가 이력을 독립적으로 관리하며, 히스토리를 분석해 개입 타이밍을 자기조정한다.

---

## 2. 아키텍처

```
작업자들 (Ralph Loop / Codex)
    ↓ 결과 생성
state/ralph-loop.state.json
state/strategy_research.state.json  
docs/backtest_history.md
config/daemon.toml (live 성과)
    ↓
[StrategyEvaluator Loop]   ← 독립 프로세스 (scripts/strategy_evaluator_loop.py)
    │
    ├─ Step 1. 준비도 판단 (자기조정 threshold)
    ├─ Step 2. 데이터 수집 & Trait 번들 결정
    ├─ Step 3. Opus 호출 → 전문 심사
    ├─ Step 4. 평가 결과 기록 (evaluator_history.json)
    ├─ Step 5. 히스토리 분석 → threshold 자기조정
    └─ Step 6. 출력
         ├─ state/evaluator_report.json   → 작업자 (기계 판독)
         └─ Telegram 요약                 → 사용자 (최상위 평가자)
```

### 프로세스 격리 원칙

- Ralph 루프와 **완전히 별개 프로세스**로 실행 — 평가자가 느려도 Ralph에 영향 없음
- `evaluator_report.json`을 통한 단방향 인터페이스 — Ralph가 다음 사이클 시작 전 읽음
- 평가자는 상태를 쓰기만 함, Ralph는 읽기만 함

---

## 3. Trait 시스템

결과 데이터 특징에 따라 자동으로 Trait 번들 구성. Opus는 활성화된 Trait 렌즈로 심사.

| Trait | 활성화 조건 | 전문 역할 |
|-------|------------|----------|
| **Statistical Auditor** | 항상 (기본값) | n_trades 충분성, Sharpe 통계적 유의성, OOS 윈도우 중복 여부 |
| **Slippage Stress Tester** | 슬리피지 구간별 결과 2개+ 존재 | 슬리피지-Sharpe 곡선 분석, 실전 적용 가능성 판정 |
| **Regime Specialist** | BULL/BEAR 구간 성과 분리 데이터 존재 | 레짐별 엣지 실재 여부, Gate 효과성, 조건부 배포 타당성 |
| **Comparative Analyst** | 비교 가능한 유사 전략 2개+ 이력 | 전략 간 순위, buy-and-hold 대비, 잉여 전략 식별 |
| **Live Monitor** | daemon 실행 중 전략 존재 | 백테스트 vs 실제 성과 괴리, 교체 트리거 판단 |
| **Opportunity Scout** | 마지막 평가 이후 미탐색 영역 감지 | 히스토리 공백 분석, 다음 유망 방향 3개 제안 |

**Statistical Auditor는 항상 실행**. 나머지는 조건 충족 시 자동 추가. Opus가 심사 중 추가 trait이 필요하다고 판단하면 자유롭게 활성화 가능.

---

## 4. 자기조정 Threshold

### 초기값

```python
INITIAL_MIN_CYCLES = 5       # 마지막 평가 이후 Ralph 최소 사이클 수
INITIAL_MIN_BACKTESTS = 2    # 마지막 평가 이후 신규 백테스트 수
```

두 조건 중 하나라도 충족 + 마지막 평가로부터 최소 30분 경과 시 검토 개시.

### 자기조정 로직

매 평가 후 `evaluator_history.json`에 기록:
- 평가 시점의 threshold
- 해당 평가에서 실제로 유의미한 방향이 나왔는지 (actionable 여부)
- 이후 Ralph 루프가 그 방향을 채택했는지

10회 평가 누적 후:
- actionable 비율 < 50% → threshold 상향 (너무 일찍 개입)
- actionable 비율 > 80% + 평가 간격이 길었음 → threshold 하향 (너무 늦게 개입)
- 그 외 → 유지

threshold 범위: min_cycles [3, 20], min_backtests [1, 10].

---

## 5. 독립 히스토리 스키마

`state/evaluator_history.json`

```json
{
  "schema_version": 1,
  "threshold": {
    "min_cycles": 5,
    "min_backtests": 2,
    "min_interval_minutes": 30,
    "last_adjusted": "2026-04-04T00:00:00"
  },
  "evaluations": [
    {
      "id": "eval-001",
      "timestamp": "2026-04-04T08:00:00",
      "ralph_cycle_at_eval": 127,
      "traits_activated": ["statistical_auditor", "slippage_stress_tester", "regime_specialist"],
      "input_summary": {
        "new_backtests_since_last": 3,
        "cycles_since_last": 7,
        "strategies_in_daemon": ["momentum_sol", "vpin_eth", "vpin_ondo"]
      },
      "verdict": {
        "overall_grade": "promising | poor | deploy_ready | investigate",
        "key_findings": ["..."],
        "direction": "다음 작업자에게 전달할 구체적 방향",
        "blockers": ["daemon 반영 전 해결 필요 사항"]
      },
      "actionable": true,
      "adopted_by_ralph": null
    }
  ],
  "self_review": {
    "total_evaluations": 1,
    "actionable_rate": 1.0,
    "last_threshold_adjustment": null
  }
}
```

---

## 6. 출력 포맷

### state/evaluator_report.json (작업자용)

```json
{
  "generated_at": "2026-04-04T08:00:00",
  "eval_id": "eval-001",
  "for_ralph_cycle": 128,
  "priority": "high | normal | low",
  "directives": [
    {
      "type": "explore | avoid | deploy | monitor | investigate",
      "target": "BB bounce ETH 240m",
      "reason": "슬리피지 0.10% 통과 but 0.20% 탈락 — 내성 개선 여지 있음",
      "suggested_action": "TP 축소(8%→5%) + SL 타이트(3%→2%) 재탐색"
    }
  ],
  "summary_for_human": "...",
  "expires_at": "다음 평가 전까지 유효"
}
```

### Telegram 요약 (사용자용)

```
[평가자 리포트 #eval-001]
활성 Trait: Statistical + Slippage + Regime
Ralph 사이클: 127 기준

📊 핵심 발견
• BB bounce: 슬리피지 내성 취약 (0.10% 통과 / 0.20% 탈락)
• ONDO vpin: BULL 구간 강력, 현재 BEAR → Gate 대기 중 정상
• vpin_eth: W1/W2 모두 안정 — 현행 유지 적절

🎯 다음 방향 (작업자에게 전달됨)
1. BB bounce TP/SL 조정 재탐색
2. BEAR 환경 mean-reversion 계열 탐색 계속
3. momentum_sol 슬리피지 0.20%~0.30% 내성 확인 필요

⚙️ Threshold: 5사이클 / 2백테스트 (자동조정 중)
```

---

## 7. 파일 맵

| 파일 | 유형 | 역할 |
|------|------|------|
| `scripts/strategy_evaluator_loop.py` | 신규 | 메인 평가자 루프 |
| `state/evaluator_history.json` | 신규 | 평가자 독립 히스토리 |
| `state/evaluator_report.json` | 신규 | 작업자 방향 출력 |
| `scripts/crypto_ralph.sh` | 수정 | 사이클 시작 전 report 읽기 추가 |

---

## 8. 완료 기준

- [ ] 평가자 루프가 Ralph와 독립적으로 실행됨
- [ ] Trait 자동 분류가 결과 데이터 특징에 따라 올바르게 동작함
- [ ] 10회 평가 후 threshold 자기조정 동작 확인
- [ ] evaluator_history.json에 평가 이력 누적 확인
- [ ] Ralph 루프가 evaluator_report.json을 읽고 다음 사이클 방향에 반영함
- [ ] Telegram으로 평가 요약 전송 확인
- [ ] 사용자(최상위 평가자)가 보고서 내용으로 방향 판단 가능한 수준의 요약 품질
