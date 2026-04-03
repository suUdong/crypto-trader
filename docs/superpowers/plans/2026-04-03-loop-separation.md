# Loop Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `autonomous_lab_loop.py`와 `crypto_ralph.py`를 역할 기반으로 명확히 분리하고, 파일명/state/watchdog을 정리한다.

**Architecture:** 시장 감시(`market_scan_loop.py`)와 전략 연구(`strategy_research_loop.py`)를 완전 분리. 각자 독립 state 파일 사용. `loop_watchdog.sh`가 두 루프 모두 감시.

**Tech Stack:** Python 3.12, bash, `.venv/bin/python3`

**Spec:** `docs/superpowers/specs/2026-04-03-loop-separation-design.md`

---

## File Map

| 현재 | 변경 후 | 변경 내용 |
|---|---|---|
| `scripts/autonomous_lab_loop.py` | `scripts/market_scan_loop.py` | STATE_FILE 변경, `_backtest_worker`/`_tournament_worker` 제거 |
| `scripts/crypto_ralph.py` | `scripts/strategy_research_loop.py` | STATE_FILE 변경, 키 이름 변경, pipeline 태스크 2개 추가 |
| `scripts/ralph_watchdog.sh` | `scripts/loop_watchdog.sh` | 두 루프 감시, 로그 경로 수정 |
| (신규) | `state/market_scan.state.json` | market_scan_loop 전용 state |
| (신규) | `state/strategy_research.state.json` | strategy_research_loop 전용 state |

---

## Task 1: state 디렉토리 생성 + state 마이그레이션

**Files:**
- Create: `state/market_scan.state.json`
- Create: `state/strategy_research.state.json`

- [ ] **Step 1: state/ 디렉토리 생성**

```bash
mkdir -p state
```

- [ ] **Step 2: state 마이그레이션 스크립트 실행**

```python
# 터미널에서 직접 실행
import json
from pathlib import Path

old = json.loads(Path("ralph-loop.state.json").read_text())

# market_scan state
Path("state/market_scan.state.json").write_text(json.dumps({
    "current_cycle": old.get("current_cycle", 0),
    "history": old.get("history", []),
}, indent=2))

# strategy_research state
Path("state/strategy_research.state.json").write_text(json.dumps({
    "cycle": old.get("ralph_cycle", 0),
    "done": old.get("ralph_done", []),
    "last_run": old.get("ralph_last_run", None),
}, indent=2))

print("마이그레이션 완료")
print("market_scan cycle:", old.get("current_cycle", 0))
print("strategy_research cycle:", old.get("ralph_cycle", 0))
print("strategy_research done:", old.get("ralph_done", []))
```

실행:
```bash
.venv/bin/python3 -c "
import json
from pathlib import Path

old = json.loads(Path('ralph-loop.state.json').read_text())

Path('state/market_scan.state.json').write_text(json.dumps({
    'current_cycle': old.get('current_cycle', 0),
    'history': old.get('history', []),
}, indent=2))

Path('state/strategy_research.state.json').write_text(json.dumps({
    'cycle': old.get('ralph_cycle', 0),
    'done': old.get('ralph_done', []),
    'last_run': old.get('ralph_last_run', None),
}, indent=2))
print('done')
"
```

예상 출력: `done`

- [ ] **Step 3: 마이그레이션 확인**

```bash
cat state/market_scan.state.json
cat state/strategy_research.state.json
```

예상: `current_cycle`이 66 이상, `done: []`

- [ ] **Step 4: 커밋**

```bash
git add state/
git commit -m "feat: create state/ dir and migrate ralph-loop.state.json"
```

---

## Task 2: market_scan_loop.py 생성

**Files:**
- Create: `scripts/market_scan_loop.py` (autonomous_lab_loop.py 기반)
- 현재 파일은 Task 5에서 삭제

변경 포인트:
1. `STATE_FILE` 경로 변경
2. `_backtest_worker` 함수 제거 (lines 316-334)
3. `_tournament_worker` 함수 제거 (lines 337-359)
4. `main()` 에서 threading import + bg 스레드 2개 제거 (lines 365-371)

- [ ] **Step 1: autonomous_lab_loop.py 복사 후 STATE_FILE 변경**

```bash
cp scripts/autonomous_lab_loop.py scripts/market_scan_loop.py
```

그 다음 `scripts/market_scan_loop.py` 편집:

```python
# 변경 전 (line 19):
STATE_FILE = Path("ralph-loop.state.json")

# 변경 후:
STATE_FILE = Path("state/market_scan.state.json")
```

- [ ] **Step 2: threading import 제거**

```python
# 변경 전 (line 5):
import threading

# 이 줄 삭제 (threading은 이제 사용하지 않음)
```

- [ ] **Step 3: `_backtest_worker` 함수 제거**

아래 블록 전체 삭제 (lines 316-334):
```python
def _backtest_worker() -> None:
    """6시간마다 Alpha 예측력 백테스트를 백그라운드에서 실행합니다."""
    backtest_script = _project_root / "scripts" / "backtest_alpha_filter.py"
    while True:
        time.sleep(6 * 3600)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Running GPU Alpha backtest...")
        try:
            result = subprocess.run(
                [sys.executable, str(backtest_script)],
                timeout=600,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Backtest done. See artifacts/alpha-backtest-result.md")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Backtest error: {result.stderr[-200:]}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Backtest failed: {e}")
```

- [ ] **Step 4: `_tournament_worker` 함수 제거**

아래 블록 전체 삭제 (lines 337-359):
```python
def _tournament_worker() -> None:
    """6시간마다 GPU Strategy Tournament를 백그라운드에서 실행합니다."""
    gpu_script = _project_root / "scripts" / "gpu_tournament.py"
    cpu_script = _project_root / "scripts" / "strategy_tournament.py"
    while True:
        time.sleep(6 * 3600)
        script = gpu_script if gpu_script.exists() else cpu_script
        label  = "GPU" if script == gpu_script else "CPU"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Running {label} Strategy Tournament...")
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                timeout=1200,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Tournament done → docs/strategy_leaderboard.md")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Tournament error: {result.stderr[-300:]}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Tournament failed: {e}")
```

- [ ] **Step 5: `main()` 에서 bg 스레드 4줄 제거**

```python
# 변경 전 main() 시작 부분:
def main() -> None:
    print("♾️ Lab Mode: PARALLEL ALPHA HUNTER (RTX 3080 Batch) Engaged.")
    # 백그라운드 GPU 백테스트 스레드 시작 (6시간마다)
    bg = threading.Thread(target=_backtest_worker, daemon=True)
    bg.start()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Background GPU backtest thread started (6h interval).")
    # 백그라운드 Strategy Tournament 스레드 시작 (24시간마다)
    bg_t = threading.Thread(target=_tournament_worker, daemon=True)
    bg_t.start()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Background Strategy Tournament thread started (24h interval).")
    while True:

# 변경 후:
def main() -> None:
    print("♾️ Market Scan Loop: PARALLEL ALPHA HUNTER (RTX 3080 Batch) Engaged.")
    while True:
```

- [ ] **Step 6: 문법 체크**

```bash
.venv/bin/python3 -c "import ast; ast.parse(open('scripts/market_scan_loop.py').read()); print('OK')"
```

예상 출력: `OK`

- [ ] **Step 7: 커밋**

```bash
git add scripts/market_scan_loop.py
git commit -m "feat: add market_scan_loop.py (market monitoring only, no backtest threads)"
```

---

## Task 3: strategy_research_loop.py 생성

**Files:**
- Create: `scripts/strategy_research_loop.py` (crypto_ralph.py 기반)

변경 포인트:
1. `STATE_FILE` 경로 변경
2. state 키 이름 변경: `ralph_cycle` → `cycle`, `ralph_done` → `done`, `ralph_last_run` → `last_run`
3. PIPELINE에 `alpha_backtest`, `strategy_tournament` 태스크 추가
4. 로그 prefix `[ralph]` → `[research]`

- [ ] **Step 1: crypto_ralph.py 복사**

```bash
cp scripts/crypto_ralph.py scripts/strategy_research_loop.py
```

- [ ] **Step 2: STATE_FILE 경로 변경**

```python
# 변경 전 (line 38):
STATE_FILE = ROOT / "ralph-loop.state.json"

# 변경 후:
STATE_FILE = ROOT / "state" / "strategy_research.state.json"
```

- [ ] **Step 3: PIPELINE에 태스크 2개 추가**

```python
# 기존 PIPELINE 마지막 항목 바로 앞에 추가 (new_strategy_hypothesis 앞):
    {
        "id": "alpha_backtest",
        "type": "backtest",
        "desc": "GPU Alpha filter 백테스트 (market_scan_loop에서 이전)",
        "script": "backtest_alpha_filter.py",
        "requires_torch": True,
        "notify_on_significant": True,
    },
    {
        "id": "strategy_tournament",
        "type": "backtest",
        "desc": "GPU Strategy Tournament (market_scan_loop에서 이전)",
        "script": "gpu_tournament.py",
        "notify_on_significant": True,
    },
```

- [ ] **Step 4: `load_state` 키 이름 변경**

```python
# 변경 전:
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            data.setdefault("ralph_cycle", 0)
            data.setdefault("ralph_done", [])
            data.setdefault("ralph_last_run", None)
            return data
        except Exception:
            pass
    return {"ralph_cycle": 0, "ralph_done": [], "ralph_last_run": None}

# 변경 후:
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            data.setdefault("cycle", 0)
            data.setdefault("done", [])
            data.setdefault("last_run", None)
            return data
        except Exception:
            pass
    return {"cycle": 0, "done": [], "last_run": None}
```

- [ ] **Step 5: `save_state` 키 이름 변경**

```python
# 변경 전:
def save_state(state: dict) -> None:
    existing: dict = {}
    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    existing.update({
        "ralph_cycle": state["ralph_cycle"],
        "ralph_done": state["ralph_done"],
        "ralph_last_run": state["ralph_last_run"],
    })
    STATE_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

# 변경 후:
def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "cycle": state["cycle"],
        "done": state["done"],
        "last_run": state["last_run"],
    }, indent=2, ensure_ascii=False))
```

- [ ] **Step 6: `pick_next_task`, `run_cycle`, `main` 의 키 이름 전체 치환**

`state["ralph_done"]` → `state["done"]`
`state["ralph_cycle"]` → `state["cycle"]`
`state["ralph_last_run"]` → `state["last_run"]`
`state['ralph_done']` → `state['done']`

```bash
sed -i \
  "s/state\[.ralph_cycle.\]/state['cycle']/g; \
   s/state\[.ralph_done.\]/state['done']/g; \
   s/state\[.ralph_last_run.\]/state['last_run']/g" \
  scripts/strategy_research_loop.py
```

- [ ] **Step 7: `[ralph]` 프린트 prefix 변경**

```bash
sed -i 's/\[ralph\]/[research]/g' scripts/strategy_research_loop.py
```

- [ ] **Step 8: `--reset` 핸들러도 키 업데이트 확인**

`scripts/strategy_research_loop.py` 내 `args.reset` 블록이 다음과 같아야 함:
```python
if args.reset:
    state["done"] = []
    save_state(state)
    print("[research] done 목록 초기화 완료")
    return
```

`ralph_done` 잔재가 없는지 확인:
```bash
grep "ralph_" scripts/strategy_research_loop.py
```

예상 출력: (없음)

- [ ] **Step 9: 문법 체크**

```bash
.venv/bin/python3 -c "import ast; ast.parse(open('scripts/strategy_research_loop.py').read()); print('OK')"
```

예상 출력: `OK`

- [ ] **Step 10: dry-run 테스트**

```bash
.venv/bin/python3 scripts/strategy_research_loop.py --dry-run
```

예상 출력: 파이프라인 태스크 7개 목록 (alpha_backtest, strategy_tournament 포함)

- [ ] **Step 11: 커밋**

```bash
git add scripts/strategy_research_loop.py
git commit -m "feat: add strategy_research_loop.py (backtest pipeline, independent state)"
```

---

## Task 4: loop_watchdog.sh 생성

**Files:**
- Create: `scripts/loop_watchdog.sh`

- [ ] **Step 1: loop_watchdog.sh 작성**

```bash
cat > scripts/loop_watchdog.sh << 'EOF'
#!/usr/bin/env bash
# loop_watchdog.sh: market_scan_loop + strategy_research_loop 감시 및 자동 재시작
set -euo pipefail

ROOT="/home/wdsr88/workspace/crypto-trader"
PYTHON="$ROOT/.venv/bin/python3"
LOG_DIR="$ROOT/logs"

mkdir -p "$LOG_DIR"

cd "$ROOT"

echo "[$(date)] loop_watchdog started" >> "$LOG_DIR/watchdog.log"

while true; do
    # market_scan_loop 감시
    if ! pgrep -f "market_scan_loop.py" > /dev/null; then
        echo "[$(date)] market_scan_loop 중단됨. 재시작..." >> "$LOG_DIR/watchdog.log"
        nohup "$PYTHON" -u scripts/market_scan_loop.py >> "$LOG_DIR/market_scan.log" 2>&1 &
        echo "[$(date)] market_scan_loop 재시작 PID=$!" >> "$LOG_DIR/watchdog.log"
    fi

    # strategy_research_loop 감시
    if ! pgrep -f "strategy_research_loop.py" > /dev/null; then
        echo "[$(date)] strategy_research_loop 중단됨. 재시작..." >> "$LOG_DIR/watchdog.log"
        nohup "$PYTHON" -u scripts/strategy_research_loop.py >> "$LOG_DIR/strategy_research.log" 2>&1 &
        echo "[$(date)] strategy_research_loop 재시작 PID=$!" >> "$LOG_DIR/watchdog.log"
    fi

    sleep 30
done
EOF
chmod +x scripts/loop_watchdog.sh
```

- [ ] **Step 2: 문법 체크**

```bash
bash -n scripts/loop_watchdog.sh && echo "OK"
```

예상 출력: `OK`

- [ ] **Step 3: 커밋**

```bash
git add scripts/loop_watchdog.sh
git commit -m "feat: add loop_watchdog.sh (watches both market_scan + strategy_research loops)"
```

---

## Task 5: 전환 — 기존 루프 종료 후 신규 루프 시작

- [ ] **Step 1: 현재 실행 중인 autonomous_lab_loop 종료**

```bash
pkill -f "autonomous_lab_loop.py" && echo "stopped" || echo "not running"
```

- [ ] **Step 2: market_scan_loop 시작**

```bash
nohup .venv/bin/python3 -u scripts/market_scan_loop.py >> logs/market_scan.log 2>&1 &
echo "market_scan_loop PID: $!"
```

- [ ] **Step 3: strategy_research_loop 시작**

```bash
nohup .venv/bin/python3 -u scripts/strategy_research_loop.py >> logs/strategy_research.log 2>&1 &
echo "strategy_research_loop PID: $!"
```

- [ ] **Step 4: loop_watchdog 시작**

```bash
nohup bash scripts/loop_watchdog.sh >> logs/watchdog.log 2>&1 &
echo "loop_watchdog PID: $!"
```

- [ ] **Step 5: 30초 후 동작 확인**

```bash
sleep 30
ps aux | grep -E "market_scan|strategy_research|loop_watchdog" | grep -v grep
tail -5 logs/market_scan.log
tail -5 logs/strategy_research.log
```

예상: 세 프로세스 모두 실행 중, market_scan.log에 Cycle START 로그 확인

- [ ] **Step 6: 구버전 스크립트 삭제 및 최종 커밋**

```bash
git rm scripts/autonomous_lab_loop.py scripts/crypto_ralph.py scripts/ralph_watchdog.sh
git add -A
git commit -m "refactor: remove old loop scripts (replaced by market_scan_loop + strategy_research_loop)"
```

---

## 검증 체크리스트

- [ ] `state/market_scan.state.json` 존재, `current_cycle` 값 정상
- [ ] `state/strategy_research.state.json` 존재, `done: []`, `cycle: 0`
- [ ] `market_scan_loop.py` 내 `threading` import 없음
- [ ] `market_scan_loop.py` 내 `_backtest_worker`, `_tournament_worker` 없음
- [ ] `strategy_research_loop.py` 내 `ralph_` 키 잔재 없음
- [ ] `strategy_research_loop.py` PIPELINE에 `alpha_backtest`, `strategy_tournament` 포함
- [ ] `loop_watchdog.sh` — 두 루프 모두 pgrep 감시
- [ ] 세 프로세스 동시 실행 확인
