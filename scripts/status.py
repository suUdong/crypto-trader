#!/usr/bin/env python3
"""
crypto-trader 상태 대시보드 (Rich 버전)

사용법:
  python scripts/status.py          # 1회 출력
  python scripts/status.py --watch  # 30초마다 자동 갱신
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

# ── 모니터링 대상 프로세스 ────────────────────────────────────────────────────

PROCESSES = [
    {"name": "daemon",        "pattern": "run-multi.*daemon.toml",     "state": None},
    {"name": "ralph",         "pattern": "crypto_ralph.sh",            "state": "ralph-loop.state.json"},
    {"name": "research_loop", "pattern": "strategy_research_loop.py",  "state": "state/strategy_research.state.json"},
    {"name": "evaluator",     "pattern": "strategy_evaluator_loop.py", "state": None},
    {"name": "market_scan",   "pattern": "market_scan_loop.py",        "state": "state/market_scan.state.json"},
]


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def load_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def last_lines(path: str, n: int = 5) -> list[str]:
    try:
        with open(path) as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except Exception:
        return []


def time_ago(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 60:    return f"{s}초 전"
        if s < 3600:  return f"{s//60}분 전"
        if s < 86400: return f"{s//3600}시간 전"
        return f"{s//86400}일 전"
    except Exception:
        return "?"


def fmt_krw(val: float) -> str:
    return f"₩{val:,.0f}"


def pnl_text(val: float, show_sign: bool = True) -> Text:
    sign = "+" if val >= 0 else ""
    color = "bold green" if val > 0 else ("bold red" if val < 0 else "dim")
    return Text(f"{sign}{fmt_krw(val)}", style=color)


def pct_text(val: float) -> Text:
    sign = "+" if val >= 0 else ""
    color = "bold green" if val > 0 else ("bold red" if val < 0 else "dim")
    return Text(f"{sign}{val:.3f}%", style=color)


def alpha_text(val: float) -> Text:
    color = "bold green" if val >= 1.5 else ("yellow" if val >= 1.0 else "dim")
    return Text(f"{val:+.3f}", style=color)


def find_procs(pattern: str) -> list[dict]:
    """pgrep -af 패턴으로 PID 조회. 여러 개면 중복 감지."""
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
                results.append({"pid": int(parts[0])})
        return results
    except Exception:
        return []


def proc_uptime(pid: int) -> tuple[str, str]:
    """PID의 elapsed time + CPU%를 ps로 조회."""
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
            if secs < 60:      elapsed = f"{secs}초"
            elif secs < 3600:  elapsed = f"{secs // 60}분"
            elif secs < 86400: elapsed = f"{secs // 3600}시간"
            else:              elapsed = f"{secs // 86400}일"
            return elapsed, f"{cpu}%"
        return "?", "?"
    except Exception:
        return "?", "?"


# ── 섹션별 렌더러 ──────────────────────────────────────────────────────────────

def render_portfolio() -> Panel:
    hp = load_json("artifacts/health.json")
    dp = load_json("artifacts/daily-performance.json")

    equity   = dp.get("mark_to_market_equity", hp.get("total_equity", 0))
    rpnl     = dp.get("realized_pnl", 0)
    ret_pct  = dp.get("portfolio_return_pct", 0)
    trades   = dp.get("trade_count", 0)
    wr       = dp.get("win_rate", 0)
    open_pos = dp.get("open_position_count", 0)
    mdd      = dp.get("portfolio_mdd_pct", 0)
    status   = hp.get("status", "?")
    mode     = hp.get("mode", "?")
    last_ok  = time_ago(hp.get("last_success_at", ""))

    s_color = "bold green" if status == "healthy" else "bold red"

    t = Table.grid(padding=(0, 2))
    t.add_column()
    t.add_column()
    t.add_column()
    t.add_column()

    t.add_row(
        Text("총 자산", style="dim"),
        Text(fmt_krw(equity), style="bold white"),
        pnl_text(rpnl),
        pct_text(ret_pct),
    )
    t.add_row(
        Text("상태", style="dim"),
        Text(f"{status.upper()}  ({mode})", style=s_color),
        Text(f"MDD", style="dim"),
        Text(f"-{mdd:.3f}%", style="bold red" if mdd > 0 else "dim"),
    )
    t.add_row(
        Text("오늘거래", style="dim"),
        Text(f"{trades}건"),
        Text(f"승률 {wr:.0f}%  오픈 {open_pos}개"),
        Text(f"마지막 {last_ok}", style="dim"),
    )

    return Panel(t, title="[bold cyan]📊 포트폴리오[/]", border_style="cyan", padding=(0, 1))


def render_wallets() -> Panel:
    dr = load_json("artifacts/daily-report.json")
    wallets = dr.get("wallets", [])

    tbl = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1))
    tbl.add_column("지갑", style="cyan", no_wrap=True, min_width=26)
    tbl.add_column("전략", style="dim", min_width=12)
    tbl.add_column("자산", justify="right", style="white", min_width=12)
    tbl.add_column("수익률", justify="right", min_width=8)
    tbl.add_column("실현P&L", justify="right", min_width=12)
    tbl.add_column("거래", justify="right", style="dim", min_width=4)

    for w in wallets:
        name  = w.get("wallet", "?")
        strat = w.get("strategy", "?")
        eq    = w.get("ending_equity", 0)
        ret   = w.get("return_pct", 0)
        pnl   = w.get("realized_pnl", 0)
        tc    = w.get("trade_count", 0)
        tbl.add_row(name, strat, fmt_krw(eq), pct_text(ret), pnl_text(pnl), str(tc))

    if not wallets:
        tbl.add_row("[dim]데이터 없음[/]", "", "", "", "", "")

    return Panel(tbl, title="[bold cyan]💼 지갑 현황[/]", border_style="blue", padding=(0, 1))


def render_positions() -> Panel:
    pos_data  = load_json("artifacts/positions.json")
    positions = pos_data.get("positions", [])

    if not positions:
        content = Text("없음", style="dim")
    else:
        tbl = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1))
        tbl.add_column("심볼", style="bold white")
        tbl.add_column("수량", justify="right")
        tbl.add_column("진입가", justify="right", style="cyan")
        tbl.add_column("현재가", justify="right", style="cyan")
        tbl.add_column("수익률", justify="right")
        tbl.add_column("미실현P&L", justify="right")
        for p in positions:
            sym   = p.get("symbol", "?")
            qty   = p.get("quantity", 0)
            entry = p.get("entry_price", 0)
            curr  = p.get("current_price", entry)
            upnl  = p.get("unrealized_pnl", 0)
            upct  = (curr - entry) / entry * 100 if entry else 0
            tbl.add_row(sym, f"{qty:.4f}", fmt_krw(entry), fmt_krw(curr), pct_text(upct), pnl_text(upnl))
        content = tbl

    return Panel(content, title="[bold cyan]📌 오픈 포지션[/]", border_style="blue", padding=(0, 1))


def render_kill_switch() -> Text:
    ks       = load_json("artifacts/kill-switch.json")
    state    = ks.get("state", "inactive")
    reason   = ks.get("trigger_reason", "")
    color    = "bold red" if state != "inactive" else "bold green"
    t = Text()
    t.append("🛡  킬스위치  ", style="bold")
    t.append(state.upper(), style=color)
    if reason:
        t.append(f"  {reason}", style="yellow")
    return t


def render_watchlist() -> Panel:
    wl    = load_json("artifacts/alpha-watchlist.json")
    top   = wl.get("top_symbols", [])
    cycle = wl.get("cycle", "?")
    ago   = time_ago(wl.get("updated_at", ""))

    # BTC stealth gate status
    sw = load_json("artifacts/stealth-watchlist.json")
    if sw:
        btc_bull = sw.get("btc_bull_regime")
        sw_ago   = time_ago(sw.get("updated_at", ""))
        if btc_bull is True:
            btc_label = Text("BTC 🟢 BULL", style="bold green")
        elif btc_bull is False:
            btc_label = Text("BTC 🔴 BEAR", style="bold red")
        else:
            btc_label = Text("BTC ⚪ N/A", style="dim")
        btc_row = Text.assemble(btc_label, Text(f"  stealth gate | {sw_ago}", style="dim"))
    else:
        btc_row = Text("BTC stealth-watchlist 없음 (다음 사이클 대기)", style="dim")

    tbl = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1))
    tbl.add_column("#", style="dim", justify="right")
    tbl.add_column("심볼", style="bold white")
    tbl.add_column("Alpha", justify="right")

    if top:
        for i, s in enumerate(top, 1):
            tbl.add_row(str(i), s.get("symbol", "?"), alpha_text(s.get("alpha", 0)))
    else:
        tbl.add_row("", "[dim](threshold 미달)[/]", "")

    from rich.console import Group
    content = Group(btc_row, tbl)

    return Panel(
        content,
        title=f"[bold cyan]🔍 Alpha 워치리스트[/]  [dim]Cycle {cycle} | {ago}[/]",
        border_style="magenta",
        padding=(0, 1),
    )


def render_prebull() -> Panel:
    pb = load_json("artifacts/pre-bull-signals.json")
    latest = pb.get("latest", {})
    if not latest:
        return Panel(Text("대기 중 (다음 사이클 후 생성)", style="dim"), title="[bold cyan]🧭 Pre-Bull Signal[/]", border_style="yellow", padding=(0, 1))

    history = pb.get("history", [])
    cycle   = history[-1].get("cycle", "?") if history else "?"
    ago     = time_ago(pb.get("updated_at", ""))
    score   = latest.get("pre_bull_score", 0)
    adj     = latest.get("pre_bull_score_adj", score)
    bonus   = latest.get("macro_bonus", 0)
    btc_reg = latest.get("btc_bull_regime", False)
    btc_ret = latest.get("btc_raw_ret", 0)
    btc_acc = latest.get("btc_acc", 0)
    btc_cvd = latest.get("btc_cvd_slope", 0)
    st_cnt  = latest.get("stealth_acc_count", 0)
    total   = latest.get("total_coins_scanned", 0)
    st_rat  = latest.get("stealth_acc_ratio", 0)

    score_color = "bold green" if adj >= 0.8 else ("yellow" if adj >= 0.5 else "bold red")
    btc_label   = Text("BULL", style="bold green") if btc_reg else Text("BEAR", style="bold red")

    t = Table.grid(padding=(0, 2))
    t.add_column(); t.add_column(); t.add_column(); t.add_column()

    t.add_row(
        Text("Pre-Bull", style="dim"),
        Text(f"{adj:+.3f}", style=score_color),
        Text("macro_bonus", style="dim"),
        Text(f"{bonus:+.3f}", style="dim green" if bonus > 0 else "dim"),
    )
    t.add_row(
        Text("BTC", style="dim"),
        btc_label,
        Text(f"ret={btc_ret:+.4f}  acc={btc_acc:.3f}  cvd={btc_cvd:+.3f}", style="dim"),
        Text(""),
    )
    t.add_row(
        Text("Stealth", style="dim"),
        Text(f"{st_cnt}/{total}", style="bold white"),
        Text(f"({st_rat*100:.1f}%)", style="dim"),
        Text(""),
    )

    sw = load_json("artifacts/stealth-watchlist.json")
    wl_coins = sw.get("stealth_coins", [])
    if wl_coins:
        names = [c if isinstance(c, str) else c.get("symbol", "?") for c in wl_coins[:6]]
        t.add_row(Text("Watchlist", style="dim"), Text(", ".join(names), style="cyan"), Text(""), Text(""))

    title = f"[bold cyan]🧭 Pre-Bull Signal[/]  [dim]Cycle {cycle} | {ago}[/]"
    return Panel(t, title=title, border_style="yellow", padding=(0, 1))


def render_calibration() -> Panel:
    cal = load_json("artifacts/alpha-calibration.json")
    if not cal:
        content = Text("대기 중 (첫 백테스트 후 생성)", style="dim")
    else:
        verdict = cal.get("verdict", "unknown")
        th      = cal.get("threshold", 1.0)
        edge    = cal.get("avg_edge_6b_pct", 0)
        v_color = "bold green" if verdict == "valid" else ("yellow" if verdict == "weak" else "bold red")
        ago     = time_ago(cal.get("updated_at", ""))

        t = Table.grid(padding=(0, 2))
        t.add_column(); t.add_column(); t.add_column(); t.add_column()
        t.add_row(
            Text("Verdict", style="dim"),
            Text(verdict, style=v_color),
            Text("Threshold", style="dim"),
            Text(f"{th:.2f}"),
        )
        t.add_row(
            Text("Edge", style="dim"),
            pct_text(edge),
            Text("Updated", style="dim"),
            Text(ago, style="dim"),
        )
        t.add_row(
            Text("Weights", style="dim"),
            Text(f"RS={cal.get('rs_weight',0.4):.2f}  Acc={cal.get('acc_weight',0.3):.2f}  CVD={cal.get('cvd_weight',0.3):.2f}"),
            "", "",
        )
        content = t

    return Panel(content, title="[bold cyan]🧬 Alpha Calibration[/]", border_style="magenta", padding=(0, 1))


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

        # ralph hang 감지: 로그에서 "Claude 실행 중" + 30분 경과
        status_icon = Text("🟢", style="bold green")
        if proc["name"] == "ralph":
            ralph_lines = last_lines("logs/crypto_ralph.log", 3)
            if ralph_lines and "Claude 실행 중" in ralph_lines[-1]:
                m = re.search(
                    r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]',
                    ralph_lines[-1],
                )
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
                em = re.search(r'cycles=(\d+)/(\d+)', ev_lines[-1])
                if em:
                    status_icon = Text("🟡 대기", style="yellow")
                    detail = f"cycles:{em.group(1)}/{em.group(2)}"

        tbl.add_row(proc["name"], str(pid), elapsed, cpu, status_icon, detail)

    return Panel(
        tbl,
        title="[bold cyan]🖥  시스템 프로세스[/]",
        border_style="green",
        padding=(0, 1),
    )


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
    for line in reversed(daemon_lines):
        m = re.search(r'market_regime=(\w+)', line)
        if m:
            regime = m.group(1)
            c = re.search(r'confidence=(\d+%)', line)
            if c:
                confidence = c.group(1)
            mr = re.search(r'Macro regime=(\w+)', line)
            if mr:
                macro = mr.group(1)
            break

    regime_color = {
        "bull": "bold green", "sideways": "yellow", "bear": "bold red",
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
        pb_color = (
            "bold green" if pre_bull >= 0.8
            else ("yellow" if pre_bull >= 0.5 else "bold red")
        )
        t.add_row(
            Text("Pre-Bull", style="dim"),
            Text(f"{pre_bull:+.3f}", style=pb_color),
            Text(f"BTC: {btc_regime}", style="dim"),
            Text(""),
        )

    # daemon.toml에서 지갑별 active_regimes 게이트 상태
    blocked = 0
    active: list[str] = []
    try:
        import tomllib
        with open("config/daemon.toml", "rb") as f_toml:
            cfg = tomllib.load(f_toml)
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
            Text(
                f"차단 {blocked}/{total}",
                style="bold red" if blocked > 0 else "green",
            ),
            Text(f"활성: {active_names}", style="dim green"),
            Text(""),
        )

    return Panel(
        t,
        title="[bold cyan]🌡  Market Regime[/]",
        border_style="yellow",
        padding=(0, 1),
    )


def render_logs() -> Panel:
    lab_lines    = last_lines("logs/market_scan.log", 4)
    daemon_lines = last_lines("artifacts/daemon.log", 4)

    import re
    _ansi = re.compile(r'\x1b\[[0-9;]*m')

    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(style="dim cyan", no_wrap=True, min_width=6)
    tbl.add_column(style="dim", overflow="ellipsis", no_wrap=True)

    for l in lab_lines:
        tbl.add_row("Lab", l[-100:])

    # 데몬 로그: ANSI 제거 + [HH:MM:SS] 타임스탬프로 시작하는 줄만 표시
    _ts = re.compile(r'^\[?\d{2}:\d{2}:\d{2}\]?')
    daemon_clean = [
        _ansi.sub("", l).strip()
        for l in last_lines("artifacts/daemon.log", 30)
        if _ts.match(_ansi.sub("", l).strip())
    ]
    for l in daemon_clean[-4:]:
        tbl.add_row("Daemon", l[:90])

    return Panel(tbl, title="[bold cyan]📋 최근 로그[/]", border_style="dim", padding=(0, 1))


# ── 메인 드로우 ────────────────────────────────────────────────────────────────

def draw() -> None:
    now_kst = datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")

    console.print()
    console.rule(f"[bold cyan]CRYPTO TRADER  LIVE STATUS[/]  [dim]{now_kst}[/]")
    console.print()

    # 시스템 상태 (최상단)
    console.print(Columns(
        [render_systems(), render_regime()], equal=True, expand=True,
    ))

    console.print(render_portfolio())
    console.print(render_wallets())

    # 포지션 + 킬스위치를 나란히
    console.print(render_positions())
    console.print(render_kill_switch())
    console.print()

    # Pre-Bull 전체 너비
    console.print(render_prebull())

    # 워치리스트 + Calibration 나란히
    console.print(Columns([render_watchlist(), render_calibration()], equal=True, expand=True))

    console.print(render_logs())
    console.rule("[dim]q: 종료 | Ctrl+C: 중단[/]")
    console.print()


def main() -> None:
    watch    = "--watch" in sys.argv or "-w" in sys.argv
    interval = 30

    if watch:
        console.print(f"[dim]Watch 모드 (매 {interval}초 갱신). Ctrl+C로 종료.[/]")
        try:
            while True:
                console.clear()
                draw()
                time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[dim]종료.[/]")
    else:
        draw()


if __name__ == "__main__":
    main()
