from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime

from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.logging import RichHandler
from rich.theme import Theme


# ── 트레이딩 전용 하이라이터 ───────────────────────────────────────────────────
class TradingHighlighter(RegexHighlighter):
    """매매 로그에서 핵심 키워드를 자동으로 색상 처리합니다."""

    base_style = "trading."
    highlights = [
        # 지갑명  [xxx_wallet]
        r"(?P<wallet>\[[\w_]+wallet\])",
        # 매수 신호
        r"(?P<buy>signal=buy)",
        # 매도 신호
        r"(?P<sell>signal=sell)",
        # 홀드 신호
        r"(?P<hold>signal=hold)",
        # 가격
        r"(?P<price>price=[\d,]+\.?\d*)",
        # reason= 이후 텍스트
        r"(?P<reason>reason=[\w_:. ()=]+)",
        # 수익/손실 (+ -)
        r"(?P<profit>\+[\d,.]+[%₩]?)",
        r"(?P<loss>-[\d,.]+[%₩]?)",
        # 레짐
        r"(?P<regime>regime=\w+)",
        r"(?P<fear>extreme_fear|fear)",
        r"(?P<greed>extreme_greed|greed)",
        # 주문 상태
        r"(?P<filled>order_status=filled)",
        r"(?P<rejected>order_status=rejected)",
        # side=buy / side=sell
        r"(?P<side_buy>side=buy)",
        r"(?P<side_sell>side=sell)",
        # 수량 / 체결가
        r"(?P<qty>qty=[\d.]+)",
        r"(?P<fill>fill=[\d,.]+)",
        # 퍼센트
        r"(?P<pct>[\d.]+%)",
        # 심볼  KRW-XXX
        r"(?P<symbol>KRW-[A-Z0-9]+)",
    ]


_TRADING_THEME = Theme(
    {
        "trading.wallet":    "bold cyan",
        "trading.buy":       "bold green",
        "trading.sell":      "bold red",
        "trading.hold":      "dim",
        "trading.price":     "bright_cyan",
        "trading.reason":    "yellow",
        "trading.profit":    "bold green",
        "trading.loss":      "bold red",
        "trading.regime":    "magenta",
        "trading.fear":      "bold red",
        "trading.greed":     "bold green",
        "trading.pct":       "bright_white",
        "trading.symbol":    "bold white",
        "trading.filled":    "bold green on dark_green",
        "trading.rejected":  "bold red on dark_red",
        "trading.side_buy":  "bold green",
        "trading.side_sell": "bold red",
        "trading.qty":       "bright_white",
        "trading.fill":      "bright_cyan",
        # RichHandler 기본 레벨 색상 오버라이드
        "logging.level.info":     "bright_blue",
        "logging.level.warning":  "bold yellow",
        "logging.level.error":    "bold red",
        "logging.level.critical": "bold white on red",
        "logging.level.debug":    "dim",
    }
)

_console = Console(theme=_TRADING_THEME, highlight=False)


class JSONFormatter(logging.Formatter):
    """파일용: 단일 JSON 라인 포맷."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str, json_format: bool = False) -> None:
    """콘솔 핸들러를 설정합니다.

    json_format=True 이면 기존 JSON 포맷(CI/서버용).
    기본값은 Rich 컬러 콘솔 출력.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    if json_format:
        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
    else:
        handler = RichHandler(
            console=_console,
            highlighter=TradingHighlighter(),
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            show_path=False,
            omit_repeated_times=False,
            log_time_format="[%H:%M:%S]",
        )

    root.addHandler(handler)


def setup_file_logging(
    path: str,
    level: str = "INFO",
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
) -> None:
    """파일 핸들러 추가 (JSON 포맷, 로테이팅)."""
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler.setFormatter(JSONFormatter())
    logging.getLogger().addHandler(handler)
