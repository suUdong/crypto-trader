"""Load artifact JSON/JSONL/MD files for the dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"

# ── 종목코드 → 한글명 매핑 ──────────────────────────────────
SYMBOL_KR: dict[str, str] = {
    "KRW-BTC": "비트코인",
    "KRW-ETH": "이더리움",
    "KRW-XRP": "리플",
    "KRW-SOL": "솔라나",
    "KRW-DOGE": "도지코인",
    "KRW-ADA": "에이다",
    "KRW-AVAX": "아발란체",
    "KRW-DOT": "폴카닷",
    "KRW-MATIC": "폴리곤",
    "KRW-LINK": "체인링크",
    "KRW-ATOM": "코스모스",
    "KRW-TRX": "트론",
    "KRW-ETC": "이더리움클래식",
    "KRW-BCH": "비트코인캐시",
    "KRW-SAND": "샌드박스",
    "KRW-SHIB": "시바이누",
    "KRW-NEAR": "니어프로토콜",
    "KRW-ARB": "아비트럼",
    "KRW-OP": "옵티미즘",
    "KRW-APT": "앱토스",
    "KRW-SUI": "수이",
    "KRW-SEI": "세이",
    "KRW-STX": "스택스",
    "KRW-HBAR": "헤데라",
    "KRW-EOS": "이오스",
}

# ── 전략명 → 한글명 매핑 ──────────────────────────────────
STRATEGY_KR: dict[str, str] = {
    "momentum": "모멘텀",
    "mean_reversion": "평균회귀",
    "composite": "복합전략",
    "kimchi_premium": "김치프리미엄",
    "obi": "호가불균형(OBI)",
    "vpin": "거래량독성(VPIN)",
    "volatility_breakout": "변동성돌파",
    "vbreak": "변동성돌파",
    "ema_crossover": "EMA크로스",
    "consensus": "합의전략",
}

REGIME_KR: dict[str, str] = {
    "bull": "상승장",
    "sideways": "횡보장",
    "bear": "하락장",
}


def symbol_kr(code: str) -> str:
    """KRW-BTC → '비트코인 (BTC)'"""
    ticker = code.replace("KRW-", "")
    name = SYMBOL_KR.get(code, ticker)
    return f"{name} ({ticker})"


def strategy_kr(name: str) -> str:
    """momentum_btc_wallet → '모멘텀 (BTC)', kimchi_premium_wallet → '김치프리미엄'"""
    key = name.replace("_wallet", "")
    # Try direct match first (e.g. kimchi_premium_wallet → kimchi_premium)
    if key in STRATEGY_KR:
        return STRATEGY_KR[key]
    # Try extracting strategy from per-symbol wallet (e.g. momentum_btc → momentum)
    for strategy_name, kr_name in STRATEGY_KR.items():
        if key.startswith(strategy_name + "_"):
            suffix = key[len(strategy_name) + 1:].upper()
            return f"{kr_name} ({suffix})"
    return key.replace("_", " ").title()


def regime_kr(regime: str) -> str:
    return REGIME_KR.get(regime, regime.upper())


def _load_json(filename: str) -> dict[str, Any] | None:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        return cast(dict[str, Any], json.load(f))


def _load_jsonl(filename: str) -> list[dict[str, Any]]:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _load_md(filename: str) -> str | None:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def load_checkpoint() -> dict[str, Any] | None:
    return _load_json("runtime-checkpoint.json")


def load_positions() -> dict[str, Any] | None:
    return _load_json("positions.json")


def load_health() -> dict[str, Any] | None:
    return _load_json("health.json")


def load_regime_report() -> dict[str, Any] | None:
    return _load_json("regime-report.json")


def load_drift_report() -> dict[str, Any] | None:
    return _load_json("drift-report.json")


def load_promotion_gate() -> dict[str, Any] | None:
    return _load_json("promotion-gate.json")


def load_drift_calibration() -> dict[str, Any] | None:
    return _load_json("drift-calibration.json")


def load_backtest_baseline() -> dict[str, Any] | None:
    return _load_json("backtest-baseline.json")


def load_daily_performance() -> dict[str, Any] | None:
    return _load_json("daily-performance.json")


def load_strategy_runs() -> list[dict[str, Any]]:
    return _load_jsonl("strategy-runs.jsonl")


def load_daily_memo() -> str | None:
    return _load_md("daily-memo.md")


def load_operator_report() -> str | None:
    return _load_md("operator-report.md")


def load_daemon_heartbeat() -> dict[str, Any] | None:
    return _load_json("daemon-heartbeat.json")
