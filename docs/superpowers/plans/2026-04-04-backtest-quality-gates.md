# Backtest Quality Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opus/Codex 리뷰 결과를 반영한 백테스트 품질 게이트 추가 — n<30 배포 차단, OOS 레지스트리, 베이스라인 비교 의무화, 슬리피지 표시

**Architecture:** 3-layer 적용. (1) `crypto_ralph.sh` 프롬프트 규칙 추가 → Claude가 스크립트 작성 시 준수. (2) `strategy_research_loop.py` 상수 상향 (MIN_MEANINGFUL_TRADES 15→30). (3) `wallet_auto_updater.apply_param_update`에 하드 게이트 추가 → 자동 배포 경로 차단.

**Tech Stack:** bash, Python 3.12, JSON (oos_window_registry.json)

---

## File Map

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `scripts/crypto_ralph.sh` | Modify | 프롬프트 규칙 4줄 추가 |
| `scripts/strategy_research_loop.py` | Modify | `MIN_MEANINGFUL_TRADES` 15→30 |
| `scripts/wallet_auto_updater.py` | Modify | `apply_param_update`에 n≥30 + 베이스라인 게이트 |
| `artifacts/oos_window_registry.json` | Create | OOS 윈도우 사용 이력 레지스트리 |

---

### Task 1: MIN_MEANINGFUL_TRADES 상향 (15 → 30)

**Files:**
- Modify: `scripts/strategy_research_loop.py:51`

- [ ] **Step 1: 현재 값 확인**

```bash
grep -n "MIN_MEANINGFUL_TRADES" scripts/strategy_research_loop.py
```
Expected: `51:MIN_MEANINGFUL_TRADES = 15`

- [ ] **Step 2: 값 변경**

`scripts/strategy_research_loop.py` line 51:
```python
MIN_MEANINGFUL_TRADES = 30   # Opus/Codex 리뷰: n<30은 통계적으로 불충분
```

- [ ] **Step 3: 변경 확인**

```bash
grep -n "MIN_MEANINGFUL_TRADES" scripts/strategy_research_loop.py
```
Expected: `51:MIN_MEANINGFUL_TRADES = 30`

- [ ] **Step 4: Commit**

```bash
git add scripts/strategy_research_loop.py
git commit -m "fix: MIN_MEANINGFUL_TRADES 15→30 (Codex 리뷰: n<30 통계 불충분)"
```

---

### Task 2: OOS 레지스트리 파일 생성

**Files:**
- Create: `artifacts/oos_window_registry.json`

- [ ] **Step 1: 레지스트리 파일 생성**

`artifacts/oos_window_registry.json`:
```json
{
  "_comment": "Walk-Forward OOS 윈도우 사용 이력. 동일 윈도우 반복 사용 방지용.",
  "used_windows": []
}
```

- [ ] **Step 2: 파일 확인**

```bash
cat artifacts/oos_window_registry.json
```

- [ ] **Step 3: Commit**

```bash
git add artifacts/oos_window_registry.json
git commit -m "feat: OOS window registry 초기화 (Codex 리뷰: 윈도우 재사용 방지)"
```

---

### Task 3: wallet_auto_updater에 하드 게이트 추가

**Files:**
- Modify: `scripts/wallet_auto_updater.py:346-360` (`apply_param_update` 함수 상단)

현재 코드 (line 358):
```python
def apply_param_update(
    strategy_id: str,
    output: str,
    best_sharpe: float,
    trigger: str,
    restart: bool = True,
) -> bool:
    if best_sharpe < AUTO_APPLY_SHARPE:
        print(f"[updater] {strategy_id}: Sharpe={best_sharpe:+.3f} < {AUTO_APPLY_SHARPE} — 자동 적용 스킵")
        return False
```

- [ ] **Step 1: n_trades 파라미터 및 게이트 추가**

`apply_param_update` 함수 시그니처와 첫 번째 게이트를 아래와 같이 변경:

```python
def apply_param_update(
    strategy_id: str,
    output: str,
    best_sharpe: float,
    trigger: str,
    restart: bool = True,
    n_trades: int | None = None,
) -> bool:
    """
    백테스트 결과에서 파라미터 파싱 → daemon.toml 업데이트 + 히스토리 기록.
    Sharpe < AUTO_APPLY_SHARPE 이면 스킵.
    변경이 있으면 True 반환.
    """
    # Gate 1: Sharpe 기준
    if best_sharpe < AUTO_APPLY_SHARPE:
        print(f"[updater] {strategy_id}: Sharpe={best_sharpe:+.3f} < {AUTO_APPLY_SHARPE} — 자동 적용 스킵")
        return False

    # Gate 2: 최소 거래 수 (n<30 배포 차단)
    MIN_DEPLOY_TRADES = 30
    if n_trades is not None and n_trades < MIN_DEPLOY_TRADES:
        print(f"[updater] {strategy_id}: n={n_trades} < {MIN_DEPLOY_TRADES} — 샘플 부족, 배포 차단")
        return False
```

- [ ] **Step 2: strategy_research_loop에서 호출 시 n_trades 전달**

`scripts/strategy_research_loop.py` line 639 근처의 `apply_param_update` 호출:

```python
applied = apply_param_update(
    strategy_id=task["id"],
    output=result["raw_tail"],
    best_sharpe=sharpe,
    trigger=trigger,
    restart=True,
    n_trades=result.get("total_trades"),
)
```

- [ ] **Step 3: 동작 확인 (dry-run 시뮬레이션)**

```bash
cd ~/workspace/crypto-trader
.venv/bin/python -c "
from scripts.wallet_auto_updater import apply_param_update
# n=20이면 차단되어야 함
result = apply_param_update('test_strat', 'Sharpe: 6.0', 6.0, 'test', restart=False, n_trades=20)
print('결과 (False여야 함):', result)
"
```
Expected: `[updater] test_strat: n=20 < 30 — 샘플 부족, 배포 차단` 출력 후 `결과 (False여야 함): False`

- [ ] **Step 4: Commit**

```bash
git add scripts/wallet_auto_updater.py scripts/strategy_research_loop.py
git commit -m "feat: 배포 게이트 추가 — n<30 차단, n_trades 파라미터 전달"
```

---

### Task 4: crypto_ralph.sh 프롬프트 규칙 추가

**Files:**
- Modify: `scripts/crypto_ralph.sh:184-189`

현재 규칙 섹션:
```
### 규칙 (절대 준수)
- Python: .venv/bin/python
- 백테스트 결과 → docs/backtest_history.md 기록
- Safety 상수 변경 금지
- daemon.toml 수정 시 Sharpe > 5.0 근거 필요
- 완료 후 git commit 필수
```

- [ ] **Step 1: 규칙 4줄 추가**

위 섹션을 아래로 교체:
```
### 규칙 (절대 준수)
- Python: .venv/bin/python
- 백테스트 결과 → docs/backtest_history.md 기록
- Safety 상수 변경 금지
- daemon.toml 수정 시 Sharpe > 5.0 근거 필요
- 완료 후 git commit 필수
- n < 30 결과로 daemon 배포 결정 금지 (통계적으로 불충분)
- OOS 윈도우 재사용 금지 — artifacts/oos_window_registry.json 확인 후 새 윈도우 사용, 사용 후 기록
- daemon 반영 전 단순 보유(buy-and-hold) 대비 수익률 비교 필수
- 슬리피지 미포함 백테스트 결과에는 반드시 ★슬리피지미포함 표시
```

- [ ] **Step 2: 변경 확인**

```bash
grep -A 12 "규칙 (절대 준수)" scripts/crypto_ralph.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/crypto_ralph.sh
git commit -m "feat: ralph 프롬프트 품질 규칙 추가 — n<30 금지, OOS 레지스트리, 베이스라인 비교"
```

---

## 완료 기준

- [ ] `MIN_MEANINGFUL_TRADES = 30` 적용됨
- [ ] `artifacts/oos_window_registry.json` 존재
- [ ] n=20으로 `apply_param_update` 호출 시 차단됨
- [ ] `crypto_ralph.sh` 프롬프트에 4개 규칙 포함됨
- [ ] 현재 돌고 있는 ralph 루프 중단 불필요 (다음 사이클부터 적용)
