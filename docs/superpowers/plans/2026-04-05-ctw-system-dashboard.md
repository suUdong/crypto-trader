# ctw 시스템 대시보드 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/status.py`에 프로세스 헬스 + 레짐 게이트 패널 2개를 추가하여 전체 시스템 상태를 한눈에 모니터링

**Architecture:** 기존 `render_*()` 패턴을 따라 `render_systems()`, `render_regime()` 함수 추가. 프로세스 확인은 `subprocess.run(["pgrep"])` + state JSON 타임스탬프 하이브리드. `draw()`에서 최상단에 두 패널을 `Columns`로 나란히 배치.

**Tech Stack:** Python 3.12, Rich (이미 의존성), subprocess (stdlib), state JSON 파일들

---

## Task 1: render_systems() — 프로세스 헬스 패널

**Files:**
- Modify: `scripts/status.py:25-55` (유틸 영역에 헬퍼 추가)
- Modify: `scripts/status.py:322-348` (render_logs 위에 새 함수 추가)

- [ ] **Step 1: 프로세스 탐지 헬퍼 함수 추가**

`scripts/status.py`의 `# ── 유틸 ──` 블록 끝 (`fmt_krw` 위)에 추가:

```python
import subprocess


# 모니터링 대상 프로세스 정의
PROCESSES = [
    {"name": "daemon",        "pattern": "run-multi.*daemon.toml",     "state": None},
    {"name": "ralph",         "pattern": "crypto_ralph.sh",            "state": "ralph-loop.state.json"},
    {"name": "research_loop", "pattern": "strategy_research_loop.py",  "state": "state/strategy_research.state.json"},
    {"name": "evaluator",     "pattern": "strategy_evaluator_loop.py", "state": None},
    {"name": "market_scan",   "pattern": "market_scan_loop.py",        "state": "state/market_scan.state.json"},
]


def find_procs(pattern: str) -> list[dict]:
    """pgrep -af 패턴으로 PID, CPU%, 시작시간 조회. 여러 개면 중복 감지."""
    try:
        r = subprocess.run(
            ["pgrep", "-af", pattern],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return []
        results = []
        for line in r.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if parts:
                pid = int(parts[0])
                results.append({"pid": pid})
        return results
    except Exception:
        return []


def proc_uptime(pid: int) -> str:
    """PID의 elapsed time을 ps로 조회."""
    try:
        r = subprocess.run(
            ["ps", "-o", "etimes=,pcpu=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return "?", "?"
        parts = r.stdout.strip().split()
        if len(parts) >= 2:
            secs = int(parts[0])
            cpu = parts[1]
            if secs < 60:     elapsed = f"{secs}초"
            elif secs < 3600: elapsed = f"{secs // 60}분"
            elif secs < 86400: elapsed = f"{secs // 3600}시간"
            else:             elapsed = f"{secs // 86400}일"
            return elapsed, f"{cpu}%"
        return "?", "?"
    except Exception:
        return "?", "?"
```

- [ ] **Step 2: render_systems() 함수 추가**

`render_logs()` 바로 위에 추가:

```python
def render_systems() -> Panel:
    tbl = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1))
    tbl.add_column("프로세스", style="cyan", no_wrap=True, min_width=16)
    tbl.add_column("PID", justify="right", style="dim", min_width=8)
    tbl.add_column("Uptime", justify="right", min_width=6)
    tbl.add_column("CPU", justify="right", min_width=5)
    tbl.add_column("상태", min_width=6)
    tbl.add_column("상세", style="dim", min_width=20)

    for proc in PROCESSES:
        matches = find_procs(proc["pattern"])
        if not matches:
            tbl.add_row(
                proc["name"], "-", "-", "-",
                Text("🔴 중단", style="bold red"), "",
            )
            continue

        if len(matches) > 1:
            pids = ",".join(str(m["pid"]) for m in matches)
            tbl.add_row(
                proc["name"], pids, "-", "-",
                Text("⚠️  중복", style="bold yellow"),
                f"{len(matches)}개 실행 중",
            )
            continue

        pid = matches[0]["pid"]
        elapsed, cpu = proc_uptime(pid)

        # state 파일에서 추가 정보
        detail = ""
        if proc["state"]:
            st = load_json(proc["state"])
            cycle = st.get("cycle", st.get("current_cycle"))
            if cycle is not None:
                detail += f"cycle:{cycle}"
            last = st.get("last_run") or st.get("last_change_ts")
            if last:
                detail += f"  {time_ago(last)}"

        # ralph hang 감지: 로그 마지막 줄에서 "Claude 실행 중" + 30분 경과
        status_icon = Text("🟢", style="bold green")
        if proc["name"] == "ralph":
            ralph_lines = last_lines("logs/crypto_ralph.log", 3)
            if ralph_lines and "Claude 실행 중" in ralph_lines[-1]:
                # 마지막 로그 타임스탬프 확인
                import re
                m = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', ralph_lines[-1])
                if m:
                    log_ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    mins = (datetime.now() - log_ts).total_seconds() / 60
                    if mins > 30:
                        status_icon = Text("🔴 hang", style="bold red")
                        detail = f"{int(mins)}분 무응답"
                    else:
                        status_icon = Text("🟡 실행중", style="yellow")
                        detail = f"Claude {int(mins)}분째"

        # evaluator 대기 상태 감지
        if proc["name"] == "evaluator":
            ev_lines = last_lines("logs/strategy_evaluator.log", 3)
            if ev_lines and "준비 미달" in ev_lines[-1]:
                import re
                m = re.search(r'cycles=(\d+)/(\d+)', ev_lines[-1])
                if m:
                    status_icon = Text("🟡 대기", style="yellow")
                    detail = f"cycles:{m.group(1)}/{m.group(2)}"

        tbl.add_row(proc["name"], str(pid), elapsed, cpu, status_icon, detail)

    return Panel(
        tbl,
        title="[bold cyan]🖥  시스템 프로세스[/]",
        border_style="green",
        padding=(0, 1),
    )
```

- [ ] **Step 3: 실행 확인**

```bash
cd /home/wdsr88/workspace/crypto-trader && .venv/bin/python scripts/status.py 2>&1 | head -30
```

Expected: 시스템 프로세스 패널이 표시되고 에러 없음

- [ ] **Step 4: 커밋**

```bash
git add scripts/status.py
git commit -m "feat: ctw 시스템 프로세스 패널 — 5개 프로세스 헬스, hang/중복 감지"
```

---

## Task 2: render_regime() — 레짐 & 게이트 패널

**Files:**
- Modify: `scripts/status.py` (render_systems 뒤에 추가)

- [ ] **Step 1: render_regime() 함수 추가**

`render_systems()` 바로 뒤에 추가:

```python
def render_regime() -> Panel:
    t = Table.grid(padding=(0, 2))
    t.add_column()
    t.add_column()
    t.add_column()
    t.add_column()

    # daemon 로그에서 마지막 regime 라인 파싱
    regime = "?"
    confidence = "?"
    macro = "?"
    daemon_lines = last_lines("logs/daemon.log", 50)
    import re
    for line in reversed(daemon_lines):
        m = re.search(
            r'market_regime=(\w+)',
            line,
        )
        if m:
            regime = m.group(1)
            # 같은 줄에서 confidence, macro 추출
            c = re.search(r'confidence=(\d+%)', line)
            if c:
                confidence = c.group(1)
            mr = re.search(r'Macro regime=(\w+)', line)
            if mr:
                macro = mr.group(1)
            break

    regime_color = {
        "bull": "bold green",
        "sideways": "yellow",
        "bear": "bold red",
    }.get(regime, "dim")

    # market_scan에서 pre_bull_score
    ms = load_json("state/market_scan.state.json")
    pre_bull = ms.get("pre_bull_score", ms.get("pre_bull_score_adj"))
    btc_regime = ms.get("btc_regime", "?")

    t.add_row(
        Text("Market Regime", style="dim"),
        Text(regime.upper(), style=regime_color),
        Text(f"confidence: {confidence}", style="dim"),
        Text(f"macro: {macro}", style="dim"),
    )

    if pre_bull is not None:
        pb_color = "bold green" if pre_bull >= 0.8 else ("yellow" if pre_bull >= 0.5 else "bold red")
        t.add_row(
            Text("Pre-Bull", style="dim"),
            Text(f"{pre_bull:+.3f}", style=pb_color),
            Text(f"BTC: {btc_regime}", style="dim"),
            Text(""),
        )

    # daemon.toml에서 지갑별 active_regimes 게이트 상태 계산
    blocked = 0
    active = []
    try:
        import tomllib
        with open("config/daemon.toml", "rb") as f:
            cfg = tomllib.load(f)
        for w in cfg.get("wallets", []):
            name = w.get("name", "?")
            so = w.get("strategy_overrides", {})
            ar = so.get("active_regimes", ["bull"])
            if regime in ar or regime == "?":
                active.append(name.replace("_wallet", ""))
            else:
                blocked += 1
    except Exception:
        pass

    total = blocked + len(active)
    if total > 0:
        active_names = ", ".join(active[:4])
        if len(active) > 4:
            active_names += f" +{len(active) - 4}"
        t.add_row(
            Text("Gate", style="dim"),
            Text(f"차단 {blocked}/{total}", style="bold red" if blocked > 0 else "green"),
            Text(f"활성: {active_names}", style="dim green"),
            Text(""),
        )

    return Panel(
        t,
        title="[bold cyan]🌡  Market Regime[/]",
        border_style="yellow",
        padding=(0, 1),
    )
```

- [ ] **Step 2: 실행 확인**

```bash
cd /home/wdsr88/workspace/crypto-trader && .venv/bin/python scripts/status.py 2>&1 | head -40
```

Expected: 레짐 패널에 현재 regime, confidence, 차단 지갑 수 표시

- [ ] **Step 3: 커밋**

```bash
git add scripts/status.py
git commit -m "feat: ctw 레짐 & 게이트 패널 — regime/confidence/차단지갑 표시"
```

---

## Task 3: draw() 레이아웃 통합

**Files:**
- Modify: `scripts/status.py:353-376` (`draw()` 함수)

- [ ] **Step 1: draw() 수정**

현재:
```python
def draw() -> None:
    now_kst = datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")

    console.print()
    console.rule(f"[bold cyan]CRYPTO TRADER  LIVE STATUS[/]  [dim]{now_kst}[/]")
    console.print()

    console.print(render_portfolio())
    console.print(render_wallets())
```

변경:
```python
def draw() -> None:
    now_kst = datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")

    console.print()
    console.rule(f"[bold cyan]CRYPTO TRADER  LIVE STATUS[/]  [dim]{now_kst}[/]")
    console.print()

    # 시스템 상태 (최상단)
    console.print(Columns([render_systems(), render_regime()], equal=True, expand=True))

    console.print(render_portfolio())
    console.print(render_wallets())
```

- [ ] **Step 2: 전체 실행 확인**

```bash
cd /home/wdsr88/workspace/crypto-trader && .venv/bin/python scripts/status.py
```

Expected: 시스템+레짐 패널이 최상단에 나란히 표시, 기존 패널 모두 정상

- [ ] **Step 3: watch 모드 확인**

```bash
cd /home/wdsr88/workspace/crypto-trader && timeout 35 .venv/bin/python scripts/status.py --watch
```

Expected: 30초 후 자동 갱신, 에러 없음

- [ ] **Step 4: 최종 커밋**

```bash
git add scripts/status.py
git commit -m "feat: ctw 대시보드 — 시스템+레짐 패널 최상단 배치 완료"
```

---

## 완료 기준

- [ ] `python scripts/status.py` 에러 없이 전체 패널 렌더링
- [ ] 시스템 프로세스: 5개 프로세스 alive/dead/중복/hang 표시
- [ ] 레짐 패널: 현재 regime, confidence, 차단 지갑 수 표시
- [ ] `--watch` 모드 30초 갱신 정상 동작
- [ ] 기존 패널 (포트폴리오, 지갑, 포지션 등) 깨짐 없음
