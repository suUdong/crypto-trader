from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from crypto_trader.operator.research_io import (
    notify_research,
    run_claude_cli,
    send_telegram_message,
    telegram_credentials_from_env,
)


def test_telegram_credentials_from_env_reads_expected_keys() -> None:
    creds = telegram_credentials_from_env(
        {
            "CT_TELEGRAM_BOT_TOKEN": "token",
            "CT_TELEGRAM_CHAT_ID": "chat",
        }
    )
    missing = telegram_credentials_from_env({})

    assert creds == ("token", "chat")
    assert missing is None


def test_send_telegram_message_builds_expected_request() -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout: int) -> None:
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["timeout"] = timeout

    send_telegram_message(
        token="token",
        chat_id="chat",
        text="hello",
        urlopen_fn=_fake_urlopen,
    )

    assert captured["url"] == "https://api.telegram.org/bottoken/sendMessage"
    assert b'"chat_id": "chat"' in captured["data"]
    assert b'"text": "hello"' in captured["data"]
    assert captured["timeout"] == 10


def test_notify_research_prints_and_swallows_telegram_failure() -> None:
    outputs: list[str] = []

    def _print(value: str) -> None:
        outputs.append(value)

    def _boom(*args, **kwargs) -> None:
        raise RuntimeError("network")

    full_msg = notify_research(
        "message",
        env={"CT_TELEGRAM_BOT_TOKEN": "token", "CT_TELEGRAM_CHAT_ID": "chat"},
        print_fn=_print,
        urlopen_fn=_boom,
    )

    assert full_msg == "[crypto-ralph] message"
    assert any("[crypto-ralph] message" in line for line in outputs)
    assert any("텔레그램 전송 실패" in line for line in outputs)


def test_run_claude_cli_returns_stdout_or_empty_string() -> None:
    ok = run_claude_cli(
        "prompt",
        cwd=Path("."),
        runner=lambda *args, **kwargs: SimpleNamespace(stdout="hello\n"),
    )
    failed = run_claude_cli(
        "prompt",
        cwd=Path("."),
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert ok == "hello"
    assert failed == ""
