"""
SESSION_HANDOFF.md 자동 생성기
context_watch_hook.sh에서 호출됨
"""
from __future__ import annotations
import subprocess, json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "SESSION_HANDOFF.md"

def run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, cwd=ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ""

def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 1. 루프 프로세스 상태
    scan_pid     = run("pgrep -f market_scan_loop.py | head -1 || echo '없음'")
    research_pid = run("pgrep -f strategy_research_loop.py | head -1 || echo '없음'")
    watchdog_pid = run("pgrep -f loop_watchdog.sh | head -1 || echo '없음'")
    daemon_pid   = run("pgrep -f 'crypto_trader.cli' | head -1 || echo '없음'")
    scan_tail    = run("tail -20 logs/market_scan.log 2>/dev/null")

    # 2. daemon 상태 (위에서 이미 수집)

    # 3. git status
    git_status = run("git status --short | head -20")
    git_log    = run("git log --oneline -5")

    # 4. 최신 백테스트 결과 (backtest_history.md 마지막 40줄)
    hist_path = ROOT / "docs/backtest_history.md"
    hist_tail = ""
    if hist_path.exists():
        lines = hist_path.read_text().splitlines()
        hist_tail = "\n".join(lines[-40:])

    # 5. market_scan 사이클 상태
    state_path = ROOT / "state" / "market_scan.state.json"
    cycle = "?"
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text())
            cycle = str(data.get("current_cycle", "?"))
        except Exception:
            pass

    # 6. ralph done 히스토리
    ralph_section = ""
    ralph_path = ROOT / "ralph-loop.state.json"
    if ralph_path.exists():
        try:
            rdata = json.loads(ralph_path.read_text())
            done_list = rdata.get("ralph_done", [])
            last_run = rdata.get("ralph_last_run", "없음")
            if done_list:
                lines = "\n".join(
                    f"  사이클 {d['cycle']}: {d['summary']}"
                    for d in done_list[-5:]
                )
                ralph_section = f"\n---\n\n## 6. 크립토 랄프 이전 작업 (최근 5개)\n\n```\n{lines}\n```\n\n마지막 실행: {last_run}\n"
        except Exception:
            pass

    content = f"""# 🔄 SESSION HANDOFF (자동 생성): {now}

## 1. 실행 상태

| 프로세스 | PID |
|---|---|
| `market_scan_loop.py` | {scan_pid} |
| `strategy_research_loop.py` | {research_pid} |
| `loop_watchdog.sh` | {watchdog_pid} |
| `crypto_trader` daemon | {daemon_pid} |
| market_scan 사이클 | {cycle} |

```bash
ct                          # 전체 상태 확인
tail -f logs/market_scan.log      # 마켓스캔 로그
tail -f logs/strategy_research.log  # 전략연구 로그
```

---

## 2. 마켓스캔 마지막 로그

```
{scan_tail}
```

---

## 3. Git 변경사항

```
{git_status}
```

### 최근 커밋
```
{git_log}
```

---

## 4. 최신 백테스트 결과

```
{hist_tail}
```

---

## 5. 다음 세션 우선순위

1. `vpin_eth` 신규 파라미터 48h 페이퍼 모니터링 (TP=6%, SL=0.8%, hold=18)
2. `wallet_changes.md` 이력 기반 성과 추적 루틴 추가
3. `accumulation_breakout` 전략 코드에 `stealth_lookback` 파라미터 실제 반영
4. market 회복 시 진입 신호 확인 (pre_bull score 0.75+, BTC SMA20 돌파 감시)
{ralph_section}"""
    OUT.write_text(content)
    print(f"SESSION_HANDOFF.md 생성 완료: {OUT}")

if __name__ == "__main__":
    main()
