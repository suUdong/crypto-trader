from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib import request


def telegram_credentials_from_env(
    env: Mapping[str, str] | None = None,
) -> tuple[str, str] | None:
    source = env or {}
    token = source.get("CT_TELEGRAM_BOT_TOKEN", "")
    chat_id = source.get("CT_TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        return token, chat_id
    return None


def send_telegram_message(
    *,
    token: str,
    chat_id: str,
    text: str,
    timeout: int = 10,
    urlopen_fn: Any = request.urlopen,
) -> None:
    payload = __import__("json").dumps({"chat_id": chat_id, "text": text}).encode()
    req = request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urlopen_fn(req, timeout=timeout)


def notify_research(
    msg: str,
    *,
    env: Mapping[str, str] | None = None,
    print_fn: Any = print,
    urlopen_fn: Any = request.urlopen,
) -> str:
    full_msg = f"[crypto-ralph] {msg}"
    print_fn(f"\n{'='*60}\n🔔 {full_msg}\n{'='*60}\n")

    creds = telegram_credentials_from_env(env)
    if creds:
        token, chat_id = creds
        try:
            send_telegram_message(
                token=token,
                chat_id=chat_id,
                text=full_msg,
                urlopen_fn=urlopen_fn,
            )
        except Exception as exc:
            print_fn(f"[research] 텔레그램 전송 실패: {exc}")
    return full_msg


def run_claude_cli(
    prompt: str,
    *,
    cwd: Path,
    timeout: int = 120,
    runner: Any = subprocess.run,
) -> str:
    try:
        result = runner(
            ["claude", "--dangerously-skip-permissions", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return str(result.stdout).strip()
    except Exception:
        return ""
