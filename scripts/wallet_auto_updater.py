"""
wallet_auto_updater.py — daemon.toml 자동 업데이트 + 히스토리 기록

두 가지 업데이트 트리거:
  A) 심볼 교체 (market_scan_loop → alpha watchlist 변경 시)
  B) 파라미터 업데이트 (strategy_research_loop → 백테스트 Sharpe 초과 시)

히스토리:
  artifacts/wallet_changes.jsonl  — 기계 처리용 (JSON Lines)
  docs/wallet_changes.md          — 사람이 읽는 변경 이력
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAEMON_CONFIG = ROOT / "config" / "daemon.toml"
BACKUP_DIR = ROOT / "artifacts" / "daemon-backups"
CHANGES_JSONL = ROOT / "artifacts" / "wallet_changes.jsonl"
CHANGES_MD = ROOT / "docs" / "wallet_changes.md"

# 자동 파라미터 적용 임계값 (이 이상 Sharpe여야 daemon.toml에 반영)
AUTO_APPLY_SHARPE = 5.0

# 전략 ID → daemon.toml 지갑명 매핑
STRATEGY_TO_WALLET: dict[str, str] = {
    "momentum_sol_grid": "momentum_sol_wallet",
    "vpin_eth_grid": "vpin_eth_wallet",
}

# 전략별 파라미터 파싱 패턴 (★ 최적: ... 라인)
# key: strategy_id, value: regex → group dict
_PARAM_PATTERNS: dict[str, re.Pattern] = {
    "momentum_sol_grid": re.compile(
        r"★ 최적: lookback=(?P<momentum_lookback>\S+) adx=(?P<adx_threshold>\S+) "
        r"vol=(?P<volume_filter_mult>\S+) TP=(?P<tp>\S+) SL=(?P<sl>\S+)"
    ),
    "vpin_eth_grid": re.compile(
        r"★ 최적: vpin_high=(?P<vpin_high_threshold>\S+) vpin_mom=(?P<vpin_momentum_threshold>\S+) "
        r"max_hold=(?P<max_holding_bars>\S+) TP=(?P<tp>\S+) SL=(?P<sl>\S+)"
    ),
}


# ── daemon.toml 수정 ───────────────────────────────────────────────────────────

def _backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"daemon_{ts}.toml"
    shutil.copy2(DAEMON_CONFIG, dst)
    return dst


def _read_config() -> str:
    return DAEMON_CONFIG.read_text(encoding="utf-8")


def _write_config(content: str) -> None:
    """daemon.toml을 원자적으로 쓴다. 쓰기 중 다른 프로세스의 파셜 읽기 방지."""
    tmp = DAEMON_CONFIG.with_suffix(".toml.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, DAEMON_CONFIG)


def _get_current_symbol(wallet_name: str) -> str | None:
    """daemon.toml에서 해당 지갑의 현재 symbol 반환."""
    content = _read_config()
    lines = content.splitlines()
    in_wallet = False
    for line in lines:
        if f'name = "{wallet_name}"' in line:
            in_wallet = True
        if in_wallet and line.strip().startswith("symbols = ["):
            m = re.search(r'"([^"]+)"', line)
            return m.group(1) if m else None
    return None


def update_symbols(wallet_name: str, new_symbol: str) -> dict | None:
    """
    지갑의 symbols를 new_symbol로 교체.
    변경이 없으면 None 반환, 변경 시 {"before": ..., "after": ...} 반환.
    """
    old_symbol = _get_current_symbol(wallet_name)
    if old_symbol == new_symbol:
        return None

    content = _read_config()
    lines = content.splitlines()
    in_wallet = False
    for i, line in enumerate(lines):
        if f'name = "{wallet_name}"' in line:
            in_wallet = True
        if in_wallet and line.strip().startswith("symbols = ["):
            lines[i] = re.sub(r'symbols = \[.*?\]', f'symbols = ["{new_symbol}"]', line)
            in_wallet = False
            break

    _write_config("\n".join(lines))
    return {"before": old_symbol, "after": new_symbol}


def _get_current_params(wallet_name: str) -> dict:
    """daemon.toml에서 해당 지갑의 strategy_overrides + risk_overrides 반환."""
    content = _read_config()
    lines = content.splitlines()
    in_wallet = False
    in_overrides = False
    params = {}
    for line in lines:
        if f'name = "{wallet_name}"' in line:
            in_wallet = True
        if in_wallet and ("[wallets.strategy_overrides]" in line or "[wallets.risk_overrides]" in line):
            in_overrides = True
            continue
        if in_overrides:
            if line.startswith("[[") or (line.startswith("[") and "wallets" not in line):
                break
            m = re.match(r"(\w+)\s*=\s*(.+)", line.strip())
            if m:
                params[m.group(1)] = m.group(2).strip()
    return params


def update_strategy_params(wallet_name: str, new_params: dict) -> dict | None:
    """
    지갑의 strategy_overrides / risk_overrides 파라미터 업데이트.
    tp → take_profit_pct, sl → stop_loss_pct 로 매핑.

    변경이 없으면 None, 변경 시 {"before": ..., "after": ..., "changed": [...]} 반환.
    """
    # tp/sl 키 매핑
    param_map = {
        "tp": "take_profit_pct",
        "sl": "stop_loss_pct",
    }
    mapped: dict[str, str] = {}
    for k, v in new_params.items():
        mapped[param_map.get(k, k)] = str(v)

    old_params = _get_current_params(wallet_name)
    changed_keys = [k for k, v in mapped.items() if old_params.get(k) != v]
    if not changed_keys:
        return None

    content = _read_config()
    lines = content.splitlines()
    in_wallet = False
    in_overrides = False

    for i, line in enumerate(lines):
        if f'name = "{wallet_name}"' in line:
            in_wallet = True
        if in_wallet and ("[wallets.strategy_overrides]" in line or "[wallets.risk_overrides]" in line):
            in_overrides = True
            continue
        if in_overrides:
            if line.startswith("[[") or (line.startswith("[") and "wallets" not in line):
                in_overrides = False
                break
            m = re.match(r"(\w+)\s*=\s*(.+)", line.strip())
            if m and m.group(1) in mapped:
                key = m.group(1)
                indent = len(line) - len(line.lstrip())
                lines[i] = " " * indent + f"{key} = {mapped[key]}"

    _write_config("\n".join(lines))
    return {
        "before": {k: old_params.get(k) for k in changed_keys},
        "after": {k: mapped[k] for k in changed_keys},
        "changed": changed_keys,
    }


# ── 파라미터 파싱 ──────────────────────────────────────────────────────────────

def parse_best_params(strategy_id: str, output: str) -> dict | None:
    """백테스트 stdout에서 ★ 최적 파라미터 파싱."""
    pattern = _PARAM_PATTERNS.get(strategy_id)
    if not pattern:
        return None
    m = pattern.search(output)
    if not m:
        return None
    return m.groupdict()


# ── daemon 재시작 ──────────────────────────────────────────────────────────────

def reload_daemon() -> int | None:
    """
    SIGHUP으로 daemon에 wallet 심볼 hot-reload 요청. 재시작 없이 다음 tick부터 반영.
    systemd MainPID를 찾아 SIGHUP 전송. 성공 시 0, 실패(미관리/오류) 시 None.
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", "crypto-trader.service",
             "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        pid_text = (result.stdout or "").strip()
        if not pid_text or pid_text == "0":
            return None
        pid = int(pid_text)
        os.kill(pid, signal.SIGHUP)
        print(f"[updater] daemon hot-reload SIGHUP → PID {pid}")
        return 0
    except Exception as exc:
        print(f"[updater] SIGHUP hot-reload 실패: {exc}")
        return None


def restart_daemon() -> int | None:
    """
    scripts/restart_daemon.sh 를 호출해 daemon을 재시작.
    systemd-managed 환경을 고려해 systemctl 경로를 타도록 위임한다.
    2026-04-07: 직접 Popen 하던 구현이 systemd daemon과 이중 실행을 유발해 수정.
    성공 시 0, 실패 시 None.
    """
    script = ROOT / "scripts" / "restart_daemon.sh"
    if not script.exists():
        print(f"[updater] restart_daemon.sh 없음: {script}")
        return None
    try:
        result = subprocess.run(
            ["bash", str(script), "config/daemon.toml"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"[updater] restart_daemon.sh 실패 (rc={result.returncode}): {result.stderr[-400:]}")
            return None
        print("[updater] daemon 재시작 완료 (systemctl 경유)")
        return 0
    except subprocess.TimeoutExpired:
        print("[updater] restart_daemon.sh 타임아웃")
        return None
    except Exception as exc:
        print(f"[updater] restart_daemon.sh 호출 오류: {exc}")
        return None


# ── 히스토리 기록 ──────────────────────────────────────────────────────────────

def _ensure_md_header() -> None:
    if not CHANGES_MD.exists():
        CHANGES_MD.write_text(
            "# Wallet Change History\n\n"
            "자동 업데이트 이력. market_scan_loop (심볼 교체) + strategy_research_loop (파라미터 갱신).\n\n"
            "---\n\n",
            encoding="utf-8",
        )


def log_change(
    change_type: str,          # "symbol_rotation" | "param_update"
    wallet_name: str,
    diff: dict,                # {"before": ..., "after": ...}
    trigger: str,              # 트리거 설명 (e.g. "cycle=68 alpha=0.82" or "Sharpe=+14.367")
    sharpe_before: float | None = None,
    sharpe_after: float | None = None,
    daemon_restarted: bool = False,
) -> None:
    """JSONL + Markdown 히스토리 기록."""
    CHANGES_MD.parent.mkdir(parents=True, exist_ok=True)
    CHANGES_JSONL.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).isoformat()
    ts_display = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    record = {
        "ts": ts,
        "type": change_type,
        "wallet": wallet_name,
        "diff": diff,
        "trigger": trigger,
        "sharpe_before": sharpe_before,
        "sharpe_after": sharpe_after,
        "daemon_restarted": daemon_restarted,
    }

    # JSONL append
    with CHANGES_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Markdown append
    _ensure_md_header()
    type_label = "심볼 교체" if change_type == "symbol_rotation" else "파라미터 갱신"
    sharpe_line = ""
    if sharpe_before is not None or sharpe_after is not None:
        sharpe_line = f"\n- Sharpe: {sharpe_before} → **{sharpe_after}**"

    if change_type == "symbol_rotation":
        diff_str = f"`{diff.get('before', '?')}` → `{diff.get('after', '?')}`"
    else:
        before = diff.get("before", {})
        after = diff.get("after", {})
        changed = diff.get("changed", list(after.keys()))
        diff_str = " | ".join(f"`{k}`: {before.get(k, '?')} → **{after.get(k, '?')}**" for k in changed)

    restart_line = "✅ daemon 재시작됨" if daemon_restarted else "⚠️ daemon 재시작 안됨"

    entry = (
        f"## {ts_display} — {type_label}: {wallet_name}\n\n"
        f"- 트리거: `{trigger}`\n"
        f"- 변경: {diff_str}{sharpe_line}\n"
        f"- {restart_line}\n\n"
        f"---\n\n"
    )
    with CHANGES_MD.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(f"[updater] 히스토리 기록: {change_type} / {wallet_name} / {trigger}")


# ── 공개 API ───────────────────────────────────────────────────────────────────

def apply_symbol_rotation(
    wallet_assignments: list[tuple[str, str]],  # [(wallet_name, new_symbol), ...]
    trigger: str,
    restart: bool = True,
) -> bool:
    """
    심볼 교체 + 히스토리 기록 + daemon 재시작.
    변경이 하나라도 있으면 True 반환.
    """
    backup = _backup()
    any_changed = False
    pending_changes: list[tuple[str, dict]] = []

    for wallet_name, new_symbol in wallet_assignments:
        diff = update_symbols(wallet_name, new_symbol)
        if diff is None:
            print(f"[updater] {wallet_name}: 변경 없음 ({new_symbol})")
            continue
        any_changed = True
        pending_changes.append((wallet_name, diff))
        print(f"[updater] {wallet_name}: {diff['before']} → {diff['after']}")

    if not any_changed:
        backup.unlink(missing_ok=True)
        return False

    # 모든 wallet 업데이트 후 단 한 번만 daemon에 알림.
    # SIGHUP hot-reload 우선 시도, 실패 시에만 전체 재시작 fallback.
    daemon_notified = False
    if restart:
        if reload_daemon() == 0:
            daemon_notified = True
        else:
            new_pid = restart_daemon()
            daemon_notified = new_pid is not None

    for wallet_name, diff in pending_changes:
        log_change(
            change_type="symbol_rotation",
            wallet_name=wallet_name,
            diff=diff,
            trigger=trigger,
            daemon_restarted=daemon_notified,
        )

    return True


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

    # Gate 2: 최소 거래 수 (n<30 배포 차단 — Opus/Codex 리뷰)
    _MIN_DEPLOY_TRADES = 30
    if n_trades is not None and n_trades < _MIN_DEPLOY_TRADES:
        print(f"[updater] {strategy_id}: n={n_trades} < {_MIN_DEPLOY_TRADES} — 샘플 부족, 배포 차단")
        return False

    wallet_name = STRATEGY_TO_WALLET.get(strategy_id)
    if not wallet_name:
        print(f"[updater] {strategy_id}: 매핑된 지갑 없음 — 스킵")
        return False

    params = parse_best_params(strategy_id, output)
    if not params:
        print(f"[updater] {strategy_id}: ★ 최적 파싱 실패 — 스킵")
        return False

    backup = _backup()
    diff = update_strategy_params(wallet_name, params)
    if diff is None:
        print(f"[updater] {wallet_name}: 파라미터 변경 없음")
        backup.unlink(missing_ok=True)
        return False

    new_pid = restart_daemon() if restart else None
    log_change(
        change_type="param_update",
        wallet_name=wallet_name,
        diff=diff,
        trigger=trigger,
        sharpe_after=best_sharpe,
        daemon_restarted=new_pid is not None,
    )
    print(f"[updater] {wallet_name} 파라미터 적용 완료: {diff['changed']}")
    return True
