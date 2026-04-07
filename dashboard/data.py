"""Load and aggregate artifact data for the dashboard."""

from __future__ import annotations

import json
import logging
import math
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import streamlit as st

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
DEFAULT_INITIAL_CAPITAL = 1_000_000.0
_FUTURE_GRACE = timedelta(minutes=5)
_KST = timezone(timedelta(hours=9))

# Primary data source: files the daemon writes every iteration.
_PRIMARY_FILES = [
    "runtime-checkpoint.json",
    "daemon-heartbeat.json",
    "kill-switch.json",
    "strategy-runs.jsonl",
]


def load_data_freshness() -> dict[str, Any]:
    """Return modification timestamps for key artifact files."""
    now = datetime.now(UTC)
    files_info: dict[str, dict[str, Any]] = {}
    primary_fresh = True

    for fname in _PRIMARY_FILES + [
        "positions.json",
        "health.json",
        "daily-performance.json",
        "daily-report.json",
        "weekly-report.json",
        "regime-report.json",
        "paper-trades.jsonl",
    ]:
        path = ARTIFACTS_DIR / fname
        if not path.exists():
            files_info[fname] = {"exists": False, "is_stale": True}
            if fname in _PRIMARY_FILES:
                primary_fresh = False
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=UTC)
        age = (now - mtime).total_seconds()
        is_stale = age > 300
        files_info[fname] = {
            "exists": True,
            "mtime_iso": mtime.isoformat(),
            "age_seconds": age,
            "is_stale": is_stale,
        }
        if fname in _PRIMARY_FILES and is_stale:
            primary_fresh = False

    return {"files": files_info, "overall_fresh": primary_fresh}


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

STRATEGY_KR: dict[str, str] = {
    "momentum": "모멘텀",
    "momentum_pullback": "모멘텀 눌림목",
    "mean_reversion": "평균회귀",
    "composite": "복합전략",
    "kimchi_premium": "김치프리미엄",
    "obi": "호가불균형(OBI)",
    "vpin": "거래량독성(VPIN)",
    "volatility_breakout": "변동성돌파",
    "vbreak": "변동성돌파",
    "ema_crossover": "EMA크로스",
    "consensus": "합의전략",
    "volume_spike": "거래량급등",
}

REGIME_KR: dict[str, str] = {
    "bull": "상승장",
    "sideways": "횡보장",
    "bear": "하락장",
    "expansionary": "확장",
    "neutral": "중립",
    "contractionary": "수축",
    "risk_on": "리스크온",
    "risk_off": "리스크오프",
}


def symbol_kr(code: str) -> str:
    """KRW-BTC -> '비트코인 (BTC)'."""
    ticker = code.replace("KRW-", "")
    name = SYMBOL_KR.get(code, ticker)
    return f"{name} ({ticker})"


def strategy_kr(name: str) -> str:
    """Return a readable Korean strategy label."""
    key = name.replace("_wallet", "")
    if key in STRATEGY_KR:
        return STRATEGY_KR[key]
    sorted_strategies = sorted(
        STRATEGY_KR.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for strategy_name, kr_name in sorted_strategies:
        if key.startswith(strategy_name + "_"):
            suffix = key[len(strategy_name) + 1 :].upper()
            return f"{kr_name} ({suffix})"
    return key.replace("_", " ").title()


def regime_kr(regime: str) -> str:
    return REGIME_KR.get(regime, regime.upper())


def _load_json(filename: str) -> dict[str, Any] | None:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))
    except (json.JSONDecodeError, ValueError):
        logger.warning("Corrupted JSON: %s", path)
        return None


def _load_jsonl(filename: str) -> list[dict[str, Any]]:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
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


def _read_json_path(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        logger.warning("Corrupted JSON: %s", path)
        return None


def _file_age_seconds(filename: str) -> float | None:
    path = ARTIFACTS_DIR / filename
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return (datetime.now(UTC) - mtime).total_seconds()


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_future_timestamp(
    parsed: datetime | None,
    reference_time: datetime | None = None,
) -> bool:
    baseline = reference_time or datetime.now(UTC)
    return parsed is not None and parsed > baseline + _FUTURE_GRACE


def _active_session_metadata(
    wallet_states: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    heartbeat = load_daemon_heartbeat() or {}
    checkpoint = load_checkpoint() or {}
    wallet_names = {
        str(name)
        for name in (
            heartbeat.get("wallet_names")
            or checkpoint.get("wallet_names")
            or (wallet_states or checkpoint.get("wallet_states", {})).keys()
        )
        if name
    }
    session_id = str(heartbeat.get("session_id") or checkpoint.get("session_id") or "")
    session_start = None
    heartbeat_dt = _parse_dt(heartbeat.get("last_heartbeat"))
    checkpoint_dt = _parse_dt(checkpoint.get("generated_at"))
    try:
        uptime_seconds = float(heartbeat.get("uptime_seconds", 0.0) or 0.0)
    except (TypeError, ValueError):
        uptime_seconds = 0.0
    if heartbeat_dt is not None:
        session_start = heartbeat_dt - timedelta(seconds=max(0.0, uptime_seconds))
    reference_time = heartbeat_dt or checkpoint_dt
    return {
        "session_id": session_id,
        "session_start": session_start,
        "reference_time": reference_time,
        "wallet_names": wallet_names,
    }


def _trade_timestamp(trade: dict[str, Any]) -> datetime | None:
    return _parse_dt(trade.get("exit_time")) or _parse_dt(trade.get("entry_time"))


def _is_current_session_trade(
    trade: dict[str, Any],
    wallet_states: dict[str, dict[str, Any]],
    session_meta: dict[str, Any],
) -> bool:
    raw_wallet_name = str(trade.get("wallet", "") or "")
    active_wallets = cast(set[str], session_meta.get("wallet_names", set()))
    if active_wallets and raw_wallet_name and raw_wallet_name not in active_wallets:
        return False

    wallet_name = _trade_wallet_name(trade, wallet_states)
    if active_wallets and wallet_name not in active_wallets:
        return False

    active_session_id = str(session_meta.get("session_id", "") or "")
    row_session_id = str(trade.get("session_id", "") or "")
    if active_session_id and row_session_id:
        return row_session_id == active_session_id

    session_start = cast(datetime | None, session_meta.get("session_start"))
    reference_time = cast(datetime | None, session_meta.get("reference_time"))
    trade_dt = _trade_timestamp(trade)
    if _is_future_timestamp(trade_dt, reference_time):
        return False
    if session_start is not None and trade_dt is not None:
        return trade_dt >= session_start
    return True


def _is_current_session_run(
    run: dict[str, Any],
    wallet_states: dict[str, dict[str, Any]],
    session_meta: dict[str, Any],
) -> bool:
    raw_wallet_name = str(run.get("wallet_name", "") or "")
    active_wallets = cast(set[str], session_meta.get("wallet_names", set()))
    if active_wallets and raw_wallet_name and raw_wallet_name not in active_wallets:
        return False

    wallet_name = _run_wallet_name(run, wallet_states)
    if active_wallets and wallet_name not in active_wallets:
        return False

    active_session_id = str(session_meta.get("session_id", "") or "")
    row_session_id = str(run.get("session_id", "") or "")
    if active_session_id and row_session_id:
        return row_session_id == active_session_id

    session_start = cast(datetime | None, session_meta.get("session_start"))
    reference_time = cast(datetime | None, session_meta.get("reference_time"))
    run_dt = _parse_dt(run.get("recorded_at"))
    if _is_future_timestamp(run_dt, reference_time):
        return False
    if session_start is not None and run_dt is not None:
        return run_dt >= session_start
    return True


def _first_existing_file(pattern: str, directory: Path) -> Path | None:
    matches = sorted(directory.glob(pattern))
    return matches[-1] if matches else None


def _extract_markdown_field(markdown: str | None, label: str) -> str | None:
    if not markdown:
        return None
    prefix = f"- {label}:"
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip().strip("`")
    return None


def _strategy_key(wallet_name: str, state: dict[str, Any] | None = None) -> str:
    if state:
        strategy_type = state.get("strategy_type")
        if isinstance(strategy_type, str) and strategy_type:
            return strategy_type
    key = wallet_name.replace("_wallet", "")
    for strategy_name in sorted(STRATEGY_KR, key=len, reverse=True):
        if key == strategy_name or key.startswith(strategy_name + "_"):
            return strategy_name
    return key


def _infer_symbol_code(wallet_name: str, state: dict[str, Any] | None = None) -> str | None:
    strategy_name = _strategy_key(wallet_name, state)
    key = wallet_name.replace("_wallet", "")
    if key == strategy_name:
        return None
    if key.startswith(strategy_name + "_"):
        suffix = key[len(strategy_name) + 1 :].upper()
        if suffix:
            return f"KRW-{suffix}"
    return None


def _trade_wallet_name(
    trade: dict[str, Any],
    wallet_states: dict[str, dict[str, Any]],
) -> str:
    wallet_name = str(trade.get("wallet", "unknown") or "unknown")
    if wallet_name in wallet_states:
        return wallet_name

    strategy_name = _strategy_key(wallet_name)
    symbol = trade.get("symbol")
    if isinstance(symbol, str):
        symbol_candidates = [
            candidate
            for candidate, state in wallet_states.items()
            if _strategy_key(candidate, state) == strategy_name
            and _infer_symbol_code(candidate, state) == symbol
        ]
        if len(symbol_candidates) == 1:
            return symbol_candidates[0]

    strategy_candidates = [
        candidate
        for candidate, state in wallet_states.items()
        if _strategy_key(candidate, state) == strategy_name
    ]
    return strategy_candidates[0] if len(strategy_candidates) == 1 else wallet_name


def _run_wallet_name(
    run: dict[str, Any],
    wallet_states: dict[str, dict[str, Any]],
) -> str:
    wallet_name = str(run.get("wallet_name", "") or "")
    if wallet_name in wallet_states:
        return wallet_name

    strategy_name = str(run.get("strategy_type", "") or "")
    symbol = run.get("symbol")
    if strategy_name and isinstance(symbol, str):
        candidates = [
            candidate
            for candidate, state in wallet_states.items()
            if _strategy_key(candidate, state) == strategy_name
            and _infer_symbol_code(candidate, state) == symbol
        ]
        if len(candidates) == 1:
            return candidates[0]
    return wallet_name or "unknown"


def _compute_profit_factor(trades: list[dict[str, Any]]) -> float:
    gross_profit = sum(float(t.get("pnl", 0.0)) for t in trades if float(t.get("pnl", 0.0)) > 0)
    gross_loss = abs(sum(float(t.get("pnl", 0.0)) for t in trades if float(t.get("pnl", 0.0)) <= 0))
    if gross_loss <= 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _compute_max_drawdown_pct(curve: list[float]) -> float:
    if not curve:
        return 0.0
    peak = curve[0]
    max_drawdown = 0.0
    for equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown * 100.0


def _compute_sharpe_ratio(curve: list[float]) -> float:
    if len(curve) < 3:
        return 0.0
    returns = [
        (current / previous) - 1.0
        for previous, current in zip(curve, curve[1:], strict=False)
        if previous > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / (len(returns) - 1)
    std_dev = math.sqrt(max(variance, 0.0))
    if std_dev <= 0:
        return 0.0
    return (mean / std_dev) * math.sqrt(min(len(returns), 252))


def _wallet_initial_capital(state: dict[str, Any]) -> float:
    explicit = state.get("initial_capital")
    if explicit is not None:
        return float(explicit or 0.0)
    realized_pnl = float(state.get("realized_pnl", 0.0) or 0.0)
    cash = float(state.get("cash", 0.0) or 0.0)
    equity = float(state.get("equity", 0.0) or 0.0)
    positions = cast(dict[str, dict[str, Any]], state.get("positions", {}))
    if not positions:
        if cash > 0 and abs(cash - equity) <= 1e-6:
            inferred = cash - realized_pnl
            if inferred > 0:
                return inferred
        return DEFAULT_INITIAL_CAPITAL
    position_cost = sum(
        float(position.get("entry_price", 0.0) or 0.0)
        * float(position.get("quantity", 0.0) or 0.0)
        for position in positions.values()
    )
    inferred = cash + position_cost - realized_pnl
    if inferred > 0:
        return inferred
    return DEFAULT_INITIAL_CAPITAL


def _build_equity_curve(
    *,
    initial_capital: float,
    current_equity: float,
    trades: list[dict[str, Any]],
    generated_at: datetime,
) -> list[dict[str, Any]]:
    if not trades:
        return [
            {"timestamp": generated_at.isoformat(), "equity": current_equity},
        ]

    sorted_trades = sorted(
        trades,
        key=lambda trade: _parse_dt(trade.get("exit_time")) or generated_at,
    )
    first_trade_dt = _parse_dt(sorted_trades[0].get("exit_time")) or generated_at
    points = [{"timestamp": first_trade_dt.isoformat(), "equity": initial_capital}]
    running_equity = initial_capital
    for trade in sorted_trades:
        running_equity += float(trade.get("pnl", 0.0))
        trade_dt = _parse_dt(trade.get("exit_time")) or generated_at
        points.append({"timestamp": trade_dt.isoformat(), "equity": running_equity})
    last_equity = cast(float, points[-1]["equity"])
    if abs(last_equity - current_equity) > 1e-6:
        points.append({"timestamp": generated_at.isoformat(), "equity": current_equity})
    return points


def _extract_research_verdict(markdown: str | None) -> str | None:
    if not markdown:
        return None
    if "## Verdict" not in markdown:
        return None
    verdict = markdown.split("## Verdict", 1)[1].strip()
    return verdict.split("\n\n", 1)[0].replace("\n", " ").strip() or None


def _fetch_macro_snapshot() -> Any | None:
    try:
        from crypto_trader.macro.client import MacroClient

        return MacroClient().get_snapshot()
    except Exception:
        logger.exception("Failed to fetch macro snapshot")
        return None


@st.cache_data(ttl=30)
def load_checkpoint() -> dict[str, Any] | None:
    return _load_json("runtime-checkpoint.json")


@st.cache_data(ttl=30)
def load_positions() -> dict[str, Any] | None:
    return _load_json("positions.json")


@st.cache_data(ttl=30)
def load_health() -> dict[str, Any] | None:
    health = _load_json("health.json")
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return health

    wallet_states = cast(dict[str, dict[str, Any]], checkpoint.get("wallet_states", {}))
    age_seconds = _file_age_seconds("health.json")
    expected_wallet_count = len(wallet_states)
    current_wallet_count = int((health or {}).get("wallet_count", 0) or 0)
    if (
        health is not None
        and age_seconds is not None
        and age_seconds <= 300
        and (expected_wallet_count == 0 or current_wallet_count == expected_wallet_count)
    ):
        return health

    latest_signal = "hold"
    session_meta = _active_session_metadata(wallet_states)
    for run in reversed(load_strategy_runs()[-200:]):
        if not _is_current_session_run(run, wallet_states, session_meta):
            continue
        action = str(run.get("signal_action", "hold") or "hold")
        if action != "hold":
            latest_signal = action
            break

    return {
        "updated_at": checkpoint.get("generated_at") or datetime.now(UTC).isoformat(),
        "success": True,
        "consecutive_failures": 0,
        "last_error": None,
        "last_signal": latest_signal,
        "last_order_status": None,
        "cash": sum(float(state.get("cash", 0.0) or 0.0) for state in wallet_states.values()),
        "open_positions": sum(
            int(state.get("open_positions", 0) or 0) for state in wallet_states.values()
        ),
        "total_equity": sum(
            float(state.get("equity", 0.0) or 0.0) for state in wallet_states.values()
        ),
        "wallet_count": expected_wallet_count,
        "mode": "multi_symbol",
    }


@st.cache_data(ttl=30)
def load_regime_report() -> dict[str, Any] | None:
    return _load_json("regime-report.json")


@st.cache_data(ttl=30)
def load_drift_report() -> dict[str, Any] | None:
    return _load_json("drift-report.json")


@st.cache_data(ttl=30)
def load_promotion_gate() -> dict[str, Any] | None:
    checkpoint = load_checkpoint()
    portfolio_gate = _load_json("portfolio-gate.json")
    if checkpoint is not None:
        wallet_count = len(cast(dict[str, Any], checkpoint.get("wallet_states", {})))
        generated_at = _parse_dt((portfolio_gate or {}).get("generated_at"))
        checkpoint_at = _parse_dt(checkpoint.get("generated_at"))
        if (
            portfolio_gate is None
            or generated_at is None
            or checkpoint_at is None
            or generated_at < checkpoint_at
            or int((portfolio_gate or {}).get("wallet_count", -1)) != wallet_count
        ):
            try:
                from crypto_trader.operator.promotion import PortfolioPromotionGate

                decision = PortfolioPromotionGate().evaluate_from_checkpoint(
                    checkpoint_path=ARTIFACTS_DIR / "runtime-checkpoint.json",
                    journal_path=ARTIFACTS_DIR / "strategy-runs.jsonl",
                )
                return {
                    "generated_at": decision.generated_at,
                    "status": decision.status.value,
                    "reasons": decision.reasons,
                    "wallet_count": decision.wallet_count,
                    "total_equity": decision.total_equity,
                    "total_realized_pnl": decision.total_realized_pnl,
                    "portfolio_return_pct": decision.portfolio_return_pct,
                    "profitable_wallets": decision.profitable_wallets,
                    "total_trades": decision.total_trades,
                    "paper_days": decision.paper_days,
                    "per_wallet": decision.per_wallet,
                }
            except Exception:
                logger.exception("Failed to rebuild portfolio promotion gate")
    if portfolio_gate is not None:
        return portfolio_gate
    return _load_json("promotion-gate.json")


@st.cache_data(ttl=30)
def load_drift_calibration() -> dict[str, Any] | None:
    return _load_json("drift-calibration.json")


@st.cache_data(ttl=30)
def load_backtest_baseline() -> dict[str, Any] | None:
    baseline = _load_json("backtest-baseline.json")
    if baseline is not None:
        return baseline
    return _load_json("backtest-baseline-90d.json")


@st.cache_data(ttl=30)
def load_daily_performance() -> dict[str, Any] | None:
    report = load_daily_report()
    if report is not None:
        return _legacy_daily_performance_from_report(report)
    return _load_json("daily-performance.json")


@st.cache_data(ttl=30)
def load_daily_report() -> dict[str, Any] | None:
    return _load_json("daily-report.json")


@st.cache_data(ttl=30)
def load_weekly_report() -> dict[str, Any] | None:
    return _load_json("weekly-report.json")


@st.cache_data(ttl=30)
def load_strategy_runs() -> list[dict[str, Any]]:
    checkpoint = load_checkpoint() or {}
    wallet_states = cast(dict[str, dict[str, Any]], checkpoint.get("wallet_states", {}))
    session_meta = _active_session_metadata(wallet_states)
    return [
        run
        for run in _load_jsonl("strategy-runs.jsonl")
        if _is_current_session_run(run, wallet_states, session_meta)
    ]


@st.cache_data(ttl=60)
def load_daily_memo() -> str | None:
    return _load_md("daily-memo.md")


@st.cache_data(ttl=60)
def load_operator_report() -> str | None:
    return _load_md("operator-report.md")


@st.cache_data(ttl=15)
def load_daemon_heartbeat() -> dict[str, Any] | None:
    return _load_json("daemon-heartbeat.json")


@st.cache_data(ttl=30)
def load_kill_switch() -> dict[str, Any] | None:
    return _load_json("kill-switch.json")


@st.cache_data(ttl=30)
def load_pnl_report() -> dict[str, Any] | None:
    return _load_json("pnl-report.json")


@st.cache_data(ttl=30)
def load_paper_trades() -> list[dict[str, Any]]:
    checkpoint = load_checkpoint() or {}
    wallet_states = cast(dict[str, dict[str, Any]], checkpoint.get("wallet_states", {}))
    session_meta = _active_session_metadata(wallet_states)
    return [
        trade
        for trade in _load_jsonl("paper-trades.jsonl")
        if _is_current_session_trade(trade, wallet_states, session_meta)
    ]


@st.cache_data(ttl=30)
def load_signal_summary() -> dict[str, Any]:
    """Aggregate hold reasons and action distribution by wallet."""
    checkpoint = load_checkpoint() or {}
    wallet_states = cast(dict[str, dict[str, Any]], checkpoint.get("wallet_states", {}))
    session_meta = _active_session_metadata(wallet_states)
    runs = [
        run
        for run in _load_jsonl("strategy-runs.jsonl")
        if _is_current_session_run(run, wallet_states, session_meta)
    ]
    hold_reasons: dict[str, int] = {}
    by_wallet: dict[str, dict[str, Any]] = {}

    for run in runs:
        action = run.get("signal_action", "hold")
        reason = run.get("signal_reason", "unknown")
        wallet = run.get("wallet_name", "unknown")
        confidence = float(run.get("signal_confidence", 0.0))

        if wallet not in by_wallet:
            by_wallet[wallet] = {
                "buy": 0,
                "sell": 0,
                "hold": 0,
                "total": 0,
                "conf_sum": 0.0,
            }
        wallet_stats = by_wallet[wallet]
        wallet_stats["total"] += 1
        wallet_stats["conf_sum"] += confidence
        if action in ("buy", "sell", "hold"):
            wallet_stats[action] += 1

        if action == "hold":
            hold_reasons[reason] = hold_reasons.get(reason, 0) + 1

    for wallet_stats in by_wallet.values():
        total = wallet_stats["total"]
        wallet_stats["avg_conf"] = wallet_stats["conf_sum"] / total if total > 0 else 0.0
        del wallet_stats["conf_sum"]

    return {"hold_reasons": hold_reasons, "by_wallet": by_wallet}


@st.cache_data(ttl=30)
def load_wallet_analytics() -> dict[str, Any]:
    """Aggregate wallet-level live P&L, Sharpe, MDD, and current signal context."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return {"wallets": [], "portfolio": {}, "timeline": []}

    generated_at = _parse_dt(checkpoint.get("generated_at")) or datetime.now(UTC)
    wallet_states = cast(dict[str, dict[str, Any]], checkpoint.get("wallet_states", {}))
    session_meta = _active_session_metadata(wallet_states)
    strategy_runs = [
        run
        for run in load_strategy_runs()
        if _is_current_session_run(run, wallet_states, session_meta)
    ]
    paper_trades = [
        trade
        for trade in load_paper_trades()
        if _is_current_session_trade(trade, wallet_states, session_meta)
    ]

    trades_by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in paper_trades:
        trades_by_wallet[_trade_wallet_name(trade, wallet_states)].append(trade)

    latest_runs: dict[str, dict[str, Any]] = {}
    latest_prices_by_wallet_symbol: dict[tuple[str, str], tuple[datetime, float]] = {}
    for run in strategy_runs:
        wallet_name = _run_wallet_name(run, wallet_states)
        if wallet_name not in wallet_states:
            continue
        run_dt = _parse_dt(run.get("recorded_at")) or generated_at
        current_run = latest_runs.get(wallet_name, {})
        current_dt = _parse_dt(current_run.get("recorded_at"))
        if current_dt is None or run_dt >= current_dt:
            latest_runs[wallet_name] = run
        symbol = str(run.get("symbol", "") or "")
        latest_price = run.get("latest_price")
        if symbol and isinstance(latest_price, (int, float)):
            key = (wallet_name, symbol)
            previous = latest_prices_by_wallet_symbol.get(key)
            if previous is None or run_dt >= previous[0]:
                latest_prices_by_wallet_symbol[key] = (run_dt, float(latest_price))

    wallets: list[dict[str, Any]] = []
    portfolio_timeline: list[dict[str, Any]] = []
    portfolio_total_equity = 0.0
    portfolio_initial = 0.0
    portfolio_realized = 0.0
    portfolio_unrealized = 0.0

    timeline_events: list[tuple[datetime, float]] = []

    for wallet_name, state in wallet_states.items():
        initial_capital = _wallet_initial_capital(state)
        equity = float(state.get("equity", initial_capital))
        realized_pnl = float(state.get("realized_pnl", 0.0))
        unrealized_pnl = equity - initial_capital - realized_pnl
        trade_count = int(state.get("trade_count", 0))
        position_map = cast(dict[str, dict[str, Any]], state.get("positions", {}))
        open_positions = int(state.get("open_positions", len(position_map)))
        wallet_trades = trades_by_wallet.get(wallet_name, [])
        win_count = sum(1 for trade in wallet_trades if float(trade.get("pnl", 0.0)) > 0)
        loss_count = sum(1 for trade in wallet_trades if float(trade.get("pnl", 0.0)) <= 0)
        win_rate = win_count / max(1, win_count + loss_count)
        equity_curve = _build_equity_curve(
            initial_capital=initial_capital,
            current_equity=equity,
            trades=wallet_trades,
            generated_at=generated_at,
        )
        curve_values = [float(point["equity"]) for point in equity_curve]
        latest_run = latest_runs.get(wallet_name, {})
        inferred_symbol = _infer_symbol_code(wallet_name, state)

        wallet_summary = {
            "wallet_name": wallet_name,
            "display_name": strategy_kr(wallet_name),
            "strategy_type": _strategy_key(wallet_name, state),
            "symbol": inferred_symbol,
            "symbol_display": symbol_kr(inferred_symbol) if inferred_symbol else "멀티-심볼",
            "equity": equity,
            "initial_capital": initial_capital,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "return_pct": ((equity - initial_capital) / initial_capital * 100.0)
            if initial_capital > 0
            else 0.0,
            "trade_count": trade_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "profit_factor": _compute_profit_factor(wallet_trades),
            "sharpe": _compute_sharpe_ratio(curve_values),
            "max_drawdown_pct": _compute_max_drawdown_pct(curve_values),
            "open_positions": open_positions,
            "positions": [
                {
                    "symbol": symbol,
                    "symbol_display": symbol_kr(symbol),
                    "entry_price": float(position.get("entry_price", 0.0)),
                    "quantity": float(position.get("quantity", 0.0)),
                    "latest_price": latest_prices_by_wallet_symbol.get(
                        (wallet_name, symbol),
                        (generated_at, float(position.get("entry_price", 0.0))),
                    )[1],
                }
                for symbol, position in position_map.items()
            ],
            "latest_signal_action": latest_run.get("signal_action", "hold"),
            "latest_signal_reason": latest_run.get("signal_reason", ""),
            "latest_signal_confidence": float(latest_run.get("signal_confidence", 0.0)),
            "latest_price": float(latest_run.get("latest_price", 0.0)),
            "market_regime": latest_run.get("market_regime", ""),
            "order_status": latest_run.get("order_status"),
            "timeline": equity_curve,
        }
        wallets.append(wallet_summary)

        for point in equity_curve:
            point_dt = _parse_dt(point["timestamp"]) or generated_at
            timeline_events.append((point_dt, float(point["equity"])))

        portfolio_total_equity += equity
        portfolio_initial += initial_capital
        portfolio_realized += realized_pnl
        portfolio_unrealized += unrealized_pnl

    wallets.sort(key=lambda wallet: wallet["return_pct"], reverse=True)

    pnl_report = load_pnl_report() or {}
    daily_report = load_daily_report() or {}
    portfolio = {
        "wallet_count": len(wallets),
        "total_equity": portfolio_total_equity,
        "total_initial_capital": portfolio_initial,
        "total_realized_pnl": portfolio_realized,
        "total_unrealized_pnl": portfolio_unrealized,
        "portfolio_return_pct": (
            ((portfolio_total_equity - portfolio_initial) / portfolio_initial) * 100.0
            if portfolio_initial > 0
            else 0.0
        ),
        "portfolio_sharpe": _numeric_value(
            pnl_report.get("portfolio_sharpe"),
            fallback=daily_report.get("portfolio_sharpe"),
        ),
        "portfolio_mdd": _numeric_value(
            pnl_report.get("portfolio_mdd"),
            fallback=daily_report.get("portfolio_mdd_pct"),
        ),
        "top_wallet": wallets[0]["wallet_name"] if wallets else None,
        "bottom_wallet": wallets[-1]["wallet_name"] if wallets else None,
        "generated_at": generated_at.isoformat(),
    }

    for event_dt, equity in sorted(timeline_events, key=lambda item: item[0])[-120:]:
        portfolio_timeline.append({"timestamp": event_dt.isoformat(), "equity": equity})

    return {"wallets": wallets, "portfolio": portfolio, "timeline": portfolio_timeline}


def _legacy_daily_performance_from_report(report: dict[str, Any]) -> dict[str, Any]:
    wallets = report.get("wallets", [])
    if not isinstance(wallets, list):
        wallets = []
    winning = sum(
        int(wallet.get("win_count", 0) or 0) for wallet in wallets if isinstance(wallet, dict)
    )
    losing = sum(
        int(wallet.get("loss_count", 0) or 0) for wallet in wallets if isinstance(wallet, dict)
    )
    total_initial = float(report.get("total_initial_capital", 0.0) or 0.0)
    total_realized = float(report.get("total_realized_pnl", 0.0) or 0.0)
    return {
        "generated_at": report.get("generated_at"),
        "period": report.get("period", "daily"),
        "period_hours": int(report.get("period_hours", 24) or 24),
        "trade_count": int(report.get("portfolio_trades", 0) or 0),
        "winning_trade_count": winning,
        "losing_trade_count": losing,
        "realized_pnl": total_realized,
        "realized_return_pct": (total_realized / total_initial) if total_initial > 0 else 0.0,
        "win_rate": float(report.get("portfolio_win_rate", 0.0) or 0.0),
        "open_position_count": int(report.get("total_open_positions", 0) or 0),
        "mark_to_market_equity": float(report.get("total_equity", 0.0) or 0.0),
        "initial_capital": total_initial,
        "portfolio_return_pct": float(report.get("portfolio_return_pct", 0.0) or 0.0),
        "portfolio_sharpe": float(report.get("portfolio_sharpe", 0.0) or 0.0),
        "portfolio_mdd_pct": float(report.get("portfolio_mdd_pct", 0.0) or 0.0),
        "mode": "multi_symbol",
    }


def _numeric_value(value: Any, *, fallback: Any = 0.0) -> float:
    candidate = value if value is not None else fallback
    try:
        return float(candidate or 0.0)
    except (TypeError, ValueError):
        return 0.0


@st.cache_data(ttl=30)
def load_risk_overview() -> dict[str, Any]:
    """Return dashboard-friendly risk status information."""
    kill_switch = load_kill_switch() or {}
    config = cast(dict[str, Any], kill_switch.get("config", {}))
    penalty = float(kill_switch.get("position_size_penalty", 1.0) or 1.0)
    reduction_active = penalty < 0.999
    if penalty <= 0.5:
        reduction_label = "강한 축소"
    elif reduction_active:
        reduction_label = "축소 중"
    else:
        reduction_label = "정상"

    return {
        "triggered": bool(kill_switch.get("triggered", False)),
        "trigger_reason": kill_switch.get("trigger_reason", ""),
        "warning_active": bool(kill_switch.get("warning_active", False)),
        "consecutive_losses": int(kill_switch.get("consecutive_losses", 0) or 0),
        "portfolio_drawdown_pct": float(kill_switch.get("portfolio_drawdown_pct", 0.0) or 0.0)
        * 100.0,
        "daily_loss_pct": float(kill_switch.get("daily_loss_pct", 0.0) or 0.0) * 100.0,
        "position_size_penalty": penalty,
        "position_size_penalty_pct": penalty * 100.0,
        "reduction_active": reduction_active,
        "reduction_label": reduction_label,
        "max_portfolio_drawdown_pct": float(config.get("max_portfolio_drawdown_pct", 0.0) or 0.0)
        * 100.0,
        "max_daily_loss_pct": float(config.get("max_daily_loss_pct", 0.0) or 0.0) * 100.0,
        "max_consecutive_losses": int(config.get("max_consecutive_losses", 0) or 0),
        "warn_threshold_pct": float(config.get("warn_threshold_pct", 0.0) or 0.0) * 100.0,
        "reduce_threshold_pct": float(config.get("reduce_threshold_pct", 0.0) or 0.0) * 100.0,
    }


@st.cache_data(ttl=60)
def load_macro_summary() -> dict[str, Any] | None:
    """Load macro-intelligence summary and compare it to local regime artifacts."""
    snapshot = _fetch_macro_snapshot()
    regime_report = load_regime_report()
    if snapshot is None and regime_report is None:
        return None

    local_regime = regime_report.get("market_regime") if regime_report else None
    summary = {
        "source_available": snapshot is not None,
        "local_regime": local_regime,
        "local_regime_label": regime_kr(local_regime) if isinstance(local_regime, str) else None,
        "local_symbol": regime_report.get("symbol") if regime_report else None,
        "local_reasons": regime_report.get("reasons", []) if regime_report else [],
    }
    if snapshot is None:
        summary["alignment"] = "local-only"
        return summary

    overall_regime = getattr(snapshot, "overall_regime", "")
    crypto_regime = getattr(snapshot, "crypto_regime", "")
    summary.update(
        {
            "alignment": "aligned"
            if local_regime in {"bull", "sideways", "bear"}
            and (
                (local_regime == "bull" and overall_regime == "expansionary")
                or (local_regime == "sideways" and overall_regime == "neutral")
                or (local_regime == "bear" and overall_regime == "contractionary")
            )
            else "mixed",
            "overall_regime": overall_regime,
            "overall_regime_label": regime_kr(overall_regime),
            "overall_confidence": float(getattr(snapshot, "overall_confidence", 0.0) or 0.0),
            "crypto_regime": crypto_regime,
            "crypto_regime_label": regime_kr(crypto_regime),
            "crypto_confidence": float(getattr(snapshot, "crypto_confidence", 0.0) or 0.0),
            "btc_dominance": getattr(snapshot, "btc_dominance", None),
            "kimchi_premium": getattr(snapshot, "kimchi_premium", None),
            "fear_greed_index": getattr(snapshot, "fear_greed_index", None),
            "layers": [
                {
                    "name": "US",
                    "regime": getattr(snapshot, "us_regime", ""),
                    "label": regime_kr(getattr(snapshot, "us_regime", "")),
                    "confidence": float(getattr(snapshot, "us_confidence", 0.0) or 0.0),
                },
                {
                    "name": "KR",
                    "regime": getattr(snapshot, "kr_regime", ""),
                    "label": regime_kr(getattr(snapshot, "kr_regime", "")),
                    "confidence": float(getattr(snapshot, "kr_confidence", 0.0) or 0.0),
                },
                {
                    "name": "Crypto",
                    "regime": crypto_regime,
                    "label": regime_kr(crypto_regime),
                    "confidence": float(getattr(snapshot, "crypto_confidence", 0.0) or 0.0),
                },
            ],
            "crypto_signals": cast(dict[str, Any], getattr(snapshot, "crypto_signals", {}) or {}),
        }
    )
    return summary


@st.cache_data(ttl=300)
def load_momentum_pullback_research() -> dict[str, Any] | None:
    """Load the latest momentum_pullback research artifact and summarize it."""
    research_path = _first_existing_file("momentum-pullback-research-*.json", ARTIFACTS_DIR)
    if research_path is None:
        return None

    research = _read_json_path(research_path)
    if not isinstance(research, dict):
        return None
    candidates = research.get("candidates", [])
    benchmarks = research.get("benchmarks", [])
    if not isinstance(candidates, list) or not isinstance(benchmarks, list):
        logger.warning("Invalid momentum pullback research payload: %s", research_path)
        return None
    candidates = cast(list[dict[str, Any]], candidates)
    benchmarks = cast(list[dict[str, Any]], benchmarks)
    if not candidates:
        return None

    best_candidate = max(
        candidates,
        key=lambda candidate: float(candidate.get("avg_sharpe", float("-inf"))),
    )
    benchmark_map = {str(item.get("strategy", "")): item for item in benchmarks}
    validation_path = _first_existing_file("momentum-pullback-*-validation.json", ARTIFACTS_DIR)
    validation = None
    if validation_path:
        validation_payload = _read_json_path(validation_path)
        if isinstance(validation_payload, dict):
            validation = validation_payload
    verdict_path = _first_existing_file("momentum-pullback-strategy-*.md", DOCS_DIR)
    verdict = _extract_research_verdict(
        verdict_path.read_text(encoding="utf-8") if verdict_path else None
    )
    best_symbol = max(
        cast(list[dict[str, Any]], best_candidate.get("per_symbol", [])),
        key=lambda item: float(item.get("sharpe", float("-inf"))),
        default=None,
    )

    return {
        "research_path": research_path.name,
        "validation_path": validation_path.name if validation_path else None,
        "best_candidate": best_candidate,
        "benchmarks": benchmarks,
        "benchmark_map": benchmark_map,
        "best_symbol": best_symbol,
        "validation": validation,
        "verdict": verdict,
        "activation_status": "research_only",
    }


@st.cache_data(ttl=300)
def load_funding_rate_research() -> dict[str, Any] | None:
    """Load the latest funding-rate research artifact and deployment review."""
    research_path = _first_existing_file("funding-rate-long-only-review-*.json", ARTIFACTS_DIR)
    if research_path is None:
        return None

    research = _read_json_path(research_path)
    if not isinstance(research, dict):
        return None

    phase1_top5_raw = research.get("phase1_top5", [])
    phase2_top10_raw = research.get("phase2_top10", [])
    phase1_top5 = (
        cast(list[dict[str, Any]], phase1_top5_raw) if isinstance(phase1_top5_raw, list) else []
    )
    phase2_top10 = (
        cast(list[dict[str, Any]], phase2_top10_raw) if isinstance(phase2_top10_raw, list) else []
    )

    best_candidate = research.get("best")
    if not isinstance(best_candidate, dict):
        candidate_pool = phase2_top10 or phase1_top5
        if not candidate_pool:
            return None
        best_candidate = max(
            candidate_pool,
            key=lambda candidate: float(candidate.get("score", float("-inf"))),
        )

    per_symbol_raw = best_candidate.get("per_symbol", [])
    per_symbol = (
        cast(list[dict[str, Any]], per_symbol_raw) if isinstance(per_symbol_raw, list) else []
    )
    best_symbol = max(
        per_symbol,
        key=lambda item: float(item.get("sharpe", float("-inf"))),
        default=None,
    )

    review_path = _first_existing_file("funding-rate-deployment-review-*.md", REPORTS_DIR)
    review_markdown = review_path.read_text(encoding="utf-8") if review_path else None

    return {
        "research_path": research_path.name,
        "review_path": review_path.name if review_path else None,
        "review_markdown": review_markdown,
        "review_date": _extract_markdown_field(review_markdown, "Date"),
        "review_scope": _extract_markdown_field(review_markdown, "Scope"),
        "decision": _extract_markdown_field(review_markdown, "Decision"),
        "phase1_top5": phase1_top5,
        "phase2_top10": phase2_top10,
        "best_candidate": best_candidate,
        "best_symbol": best_symbol,
    }


@st.cache_data(ttl=30)
def load_all_paper_trades() -> list[dict[str, Any]]:
    """Load ALL paper trades without session filtering."""
    trades = []
    for trade in _load_jsonl("paper-trades.jsonl"):
        pnl = _numeric_value(trade.get("pnl"))
        pnl_pct = _numeric_value(trade.get("pnl_pct"))
        exit_dt = _parse_dt(trade.get("exit_time"))
        entry_dt = _parse_dt(trade.get("entry_time"))
        ts = exit_dt or entry_dt
        trades.append({
            "timestamp": ts.astimezone(_KST).strftime("%m/%d %H:%M") if ts else "-",
            "symbol": str(trade.get("symbol", "")),
            "wallet": str(trade.get("wallet", "")),
            "pnl": pnl,
            "pnl_pct": pnl_pct * 100,
            "exit_reason": str(trade.get("exit_reason", "")),
            "session_id": str(trade.get("session_id", "")),
            "win": pnl > 0,
        })
    return trades


@st.cache_data(ttl=30)
def load_cumulative_trade_summary() -> dict[str, Any]:
    """Aggregate all paper trades into wallet-level summary."""
    trades = load_all_paper_trades()
    wallet_stats: dict[str, dict[str, Any]] = {}
    for t in trades:
        w = t["wallet"]
        if w not in wallet_stats:
            wallet_stats[w] = {"count": 0, "wins": 0, "pnl": 0.0}
        wallet_stats[w]["count"] += 1
        wallet_stats[w]["pnl"] += t["pnl"]
        if t["win"]:
            wallet_stats[w]["wins"] += 1

    total_pnl = sum(s["pnl"] for s in wallet_stats.values())
    total_trades = sum(s["count"] for s in wallet_stats.values())
    total_wins = sum(s["wins"] for s in wallet_stats.values())

    rows = []
    for w, s in sorted(wallet_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = s["wins"] / s["count"] * 100 if s["count"] else 0
        rows.append({
            "지갑": strategy_kr(w),
            "거래수": s["count"],
            "승률": f"{wr:.0f}%",
            "누적PnL": s["pnl"],
        })

    return {
        "rows": rows,
        "total_pnl": total_pnl,
        "total_trades": total_trades,
        "win_rate": total_wins / total_trades * 100 if total_trades else 0,
    }


@st.cache_data(ttl=30)
def load_edge_analysis() -> dict[str, Any] | None:
    """Aggregate full trade history into hour-by-symbol edge heatmap data."""
    trades = _load_jsonl("paper-trades.jsonl")
    parsed_rows: list[dict[str, Any]] = []

    for trade in trades:
        symbol = str(trade.get("symbol", "") or "")
        if not symbol:
            continue
        trade_dt = _parse_dt(trade.get("exit_time")) or _parse_dt(trade.get("entry_time"))
        if trade_dt is None:
            continue
        local_dt = trade_dt.astimezone(_KST)
        pnl = _numeric_value(trade.get("pnl"))
        parsed_rows.append(
            {
                "symbol": symbol,
                "symbol_display": symbol_kr(symbol),
                "wallet": str(trade.get("wallet", "") or ""),
                "wallet_display": strategy_kr(str(trade.get("wallet", "") or "")),
                "hour": local_dt.hour,
                "hour_label": f"{local_dt.hour:02d}:00",
                "timestamp": local_dt.isoformat(),
                "pnl": pnl,
                "pnl_pct": _numeric_value(trade.get("pnl_pct")),
                "win": pnl > 0.0,
            }
        )

    if not parsed_rows:
        return None

    hours = list(range(24))
    symbols = sorted({row["symbol"] for row in parsed_rows})
    matrix_total_pnl: list[list[float]] = []
    matrix_trade_count: list[list[int]] = []
    bucket_rows: list[dict[str, Any]] = []

    for hour in hours:
        pnl_row: list[float] = []
        count_row: list[int] = []
        for symbol in symbols:
            bucket = [
                row for row in parsed_rows if row["hour"] == hour and row["symbol"] == symbol
            ]
            total_pnl = sum(float(row["pnl"]) for row in bucket)
            trade_count = len(bucket)
            wins = sum(1 for row in bucket if row["win"])
            avg_pnl = total_pnl / trade_count if trade_count else 0.0
            pnl_row.append(total_pnl)
            count_row.append(trade_count)
            bucket_rows.append(
                {
                    "hour": hour,
                    "hour_label": f"{hour:02d}:00",
                    "symbol": symbol,
                    "symbol_display": symbol_kr(symbol),
                    "trade_count": trade_count,
                    "total_pnl": total_pnl,
                    "avg_pnl": avg_pnl,
                    "win_rate": wins / trade_count if trade_count else 0.0,
                }
            )
        matrix_total_pnl.append(pnl_row)
        matrix_trade_count.append(count_row)

    symbol_summary: list[dict[str, Any]] = []
    for symbol in symbols:
        symbol_rows = [row for row in parsed_rows if row["symbol"] == symbol]
        total_pnl = sum(float(row["pnl"]) for row in symbol_rows)
        trade_count = len(symbol_rows)
        best_hour = max(
            (row for row in bucket_rows if row["symbol"] == symbol),
            key=lambda row: float(row["total_pnl"]),
            default=None,
        )
        symbol_summary.append(
            {
                "symbol": symbol,
                "symbol_display": symbol_kr(symbol),
                "trade_count": trade_count,
                "total_pnl": total_pnl,
                "avg_pnl": total_pnl / trade_count if trade_count else 0.0,
                "win_rate": (sum(1 for row in symbol_rows if row["win"]) / trade_count)
                if trade_count
                else 0.0,
                "best_hour": best_hour["hour_label"] if best_hour else "-",
            }
        )

    hour_summary: list[dict[str, Any]] = []
    for hour in hours:
        hour_rows = [row for row in parsed_rows if row["hour"] == hour]
        trade_count = len(hour_rows)
        total_pnl = sum(float(row["pnl"]) for row in hour_rows)
        hour_summary.append(
            {
                "hour": hour,
                "hour_label": f"{hour:02d}:00",
                "trade_count": trade_count,
                "total_pnl": total_pnl,
                "avg_pnl": total_pnl / trade_count if trade_count else 0.0,
                "win_rate": (sum(1 for row in hour_rows if row["win"]) / trade_count)
                if trade_count
                else 0.0,
            }
        )

    active_bucket_rows = [row for row in bucket_rows if row["trade_count"] > 0]
    best_bucket = max(active_bucket_rows, key=lambda row: float(row["total_pnl"]), default=None)
    worst_bucket = min(active_bucket_rows, key=lambda row: float(row["total_pnl"]), default=None)

    return {
        "timezone": "KST",
        "rows": parsed_rows,
        "hours": hours,
        "hour_labels": [f"{hour:02d}:00" for hour in hours],
        "symbols": symbols,
        "symbol_labels": [symbol_kr(symbol) for symbol in symbols],
        "heatmap_total_pnl": matrix_total_pnl,
        "heatmap_trade_count": matrix_trade_count,
        "bucket_rows": sorted(
            active_bucket_rows,
            key=lambda row: float(row["total_pnl"]),
            reverse=True,
        ),
        "symbol_summary": sorted(
            symbol_summary,
            key=lambda row: float(row["total_pnl"]),
            reverse=True,
        ),
        "hour_summary": sorted(hour_summary, key=lambda row: row["hour"]),
        "total_pnl": sum(float(row["pnl"]) for row in parsed_rows),
        "trade_count": len(parsed_rows),
        "win_rate": sum(1 for row in parsed_rows if row["win"]) / len(parsed_rows),
        "best_bucket": best_bucket,
        "worst_bucket": worst_bucket,
    }


@st.cache_data(ttl=30)
def load_signal_history(limit: int = 300) -> dict[str, Any]:
    """Aggregate signal and alert history for the dashboard."""
    checkpoint = load_checkpoint()
    wallet_states = (
        cast(dict[str, dict[str, Any]], checkpoint.get("wallet_states", {})) if checkpoint else {}
    )
    session_meta = _active_session_metadata(wallet_states)
    runs = [
        run
        for run in load_strategy_runs()
        if _is_current_session_run(run, wallet_states, session_meta)
    ]
    risk = load_risk_overview()
    rows: list[dict[str, Any]] = []

    for run in reversed(runs[-limit:]):
        wallet_name = _run_wallet_name(run, wallet_states)
        recorded_at = _parse_dt(run.get("recorded_at"))
        timestamp = recorded_at.isoformat() if recorded_at else str(run.get("recorded_at", ""))
        regime = str(run.get("market_regime", ""))
        row = {
            "timestamp": timestamp,
            "wallet_name": wallet_name,
            "display_name": strategy_kr(wallet_name) if wallet_name != "unknown" else "미확인",
            "strategy_type": str(run.get("strategy_type", _strategy_key(wallet_name))),
            "action": str(run.get("signal_action", "hold")),
            "symbol": str(run.get("symbol", "")),
            "symbol_display": symbol_kr(str(run.get("symbol", ""))) if run.get("symbol") else "",
            "confidence": float(run.get("signal_confidence", 0.0) or 0.0),
            "reason": str(run.get("signal_reason", "")),
            "regime": regime,
            "regime_label": regime_kr(regime) if regime else "",
            "latest_price": float(run.get("latest_price", 0.0) or 0.0),
            "order_status": run.get("order_status"),
            "verdict_status": run.get("verdict_status"),
        }
        rows.append(row)

    action_counts = {
        "buy": sum(1 for row in rows if row["action"] == "buy"),
        "sell": sum(1 for row in rows if row["action"] == "sell"),
        "hold": sum(1 for row in rows if row["action"] == "hold"),
    }
    high_confidence = sum(1 for row in rows if row["confidence"] >= 0.75)
    regime_counts: dict[str, int] = defaultdict(int)
    wallet_counts: dict[str, int] = defaultdict(int)
    alert_rows: list[dict[str, Any]] = []

    for row in rows:
        if row["regime"]:
            regime_counts[row["regime_label"]] += 1
        wallet_counts[row["display_name"]] += 1
        if row["action"] != "hold" or row["order_status"] not in (None, "", "filled"):
            alert_rows.append(row)

    if risk.get("triggered") or risk.get("reduction_active") or risk.get("warning_active"):
        alert_rows.insert(
            0,
            {
                "timestamp": "",
                "wallet_name": "portfolio",
                "display_name": "포트폴리오 리스크",
                "strategy_type": "risk",
                "action": "risk",
                "symbol": "",
                "symbol_display": "",
                "confidence": 1.0,
                "reason": risk.get("trigger_reason") or risk.get("reduction_label"),
                "regime": "",
                "regime_label": "",
                "latest_price": 0.0,
                "order_status": "active" if risk.get("triggered") else "watch",
                "verdict_status": "kill_switch" if risk.get("triggered") else "reduced",
            },
        )

    return {
        "rows": rows,
        "alert_rows": alert_rows[:100],
        "action_counts": action_counts,
        "high_confidence_count": high_confidence,
        "regime_counts": dict(regime_counts),
        "wallet_counts": dict(wallet_counts),
        "total": len(rows),
    }


# ---------------------------------------------------------------------------
# Dashboard v3: Regime panel, Fear & Greed, Signal monitor
# ---------------------------------------------------------------------------

FEAR_GREED_ZONES: list[tuple[int, int, str, str]] = [
    (0, 20, "극단적 공포", "#ff4444"),
    (20, 40, "공포", "#ff8c42"),
    (40, 60, "중립", "#ffc75f"),
    (60, 80, "탐욕", "#7bc67e"),
    (80, 100, "극단적 탐욕", "#44bb44"),
]


def fear_greed_zone_label(value: int | None) -> str:
    """Return Korean label for Fear & Greed index value."""
    if value is None:
        return "데이터 없음"
    for low, high, label, _color in FEAR_GREED_ZONES:
        if low <= value < high:
            return label
    if value >= 100:
        return "극단적 탐욕"
    return "데이터 없음"


def _compute_macro_adjustment() -> tuple[float, list[str]]:
    """Compute position size multiplier from MacroRegimeAdapter."""
    try:
        from crypto_trader.macro.adapter import MacroRegimeAdapter
        from crypto_trader.macro.client import MacroClient

        snapshot = MacroClient().get_snapshot()
        adapter = MacroRegimeAdapter()
        adjustment = adapter.compute(snapshot)
        return adjustment.position_size_multiplier, adjustment.reasons
    except Exception:
        logger.exception("Failed to compute macro adjustment")
        return 1.0, ["macro adapter unavailable"]


@st.cache_data(ttl=30)
def load_regime_panel_data() -> dict[str, Any]:
    """Load regime data for the dedicated regime status panel."""
    macro = load_macro_summary()
    checkpoint = load_checkpoint() or {}
    is_weekend = bool(checkpoint.get("is_weekend", False))
    multiplier, reasons = _compute_macro_adjustment()
    source_available = bool(macro and macro.get("source_available", False))

    panel: dict[str, Any] = {
        "available": macro is not None,
        "source_available": source_available,
        "is_weekend": is_weekend,
        "position_multiplier": multiplier,
        "multiplier_reasons": reasons,
    }

    if macro is None:
        panel.update({
            "overall_regime": "unknown",
            "overall_regime_label": "데이터 없음",
            "overall_confidence": 0.0,
            "layers": [],
            "fear_greed_index": None,
            "fear_greed_label": "데이터 없음",
            "btc_dominance": None,
            "kimchi_premium": None,
        })
        return panel

    fg = macro.get("fear_greed_index")
    fg_int = int(fg) if fg is not None else None
    overall_regime = str(macro.get("overall_regime") or macro.get("local_regime") or "unknown")
    overall_regime_label = str(
        macro.get("overall_regime_label") or macro.get("local_regime_label") or "알 수 없음"
    )
    panel.update({
        "overall_regime": overall_regime,
        "overall_regime_label": overall_regime_label,
        "overall_confidence": float(macro.get("overall_confidence", 0.0)),
        "layers": macro.get("layers", []),
        "fear_greed_index": fg_int,
        "fear_greed_label": fear_greed_zone_label(fg_int),
        "btc_dominance": macro.get("btc_dominance"),
        "kimchi_premium": macro.get("kimchi_premium"),
        "alignment": macro.get("alignment", "unknown"),
        "local_regime_label": macro.get("local_regime_label"),
    })
    return panel


@st.cache_data(ttl=30)
def load_signal_monitor_data() -> dict[str, Any]:
    """Aggregate per-strategy latest signals with regime context for signal monitor."""
    checkpoint = load_checkpoint()
    wallet_states = (
        cast(dict[str, dict[str, Any]], checkpoint.get("wallet_states", {})) if checkpoint else {}
    )
    session_meta = _active_session_metadata(wallet_states)
    runs = [
        run
        for run in load_strategy_runs()
        if _is_current_session_run(run, wallet_states, session_meta)
    ]

    # Latest signal per wallet
    latest_per_wallet: dict[str, dict[str, Any]] = {}
    for run in runs:
        wallet_name = _run_wallet_name(run, wallet_states)
        run_dt = _parse_dt(run.get("recorded_at"))
        current = latest_per_wallet.get(wallet_name)
        current_dt = _parse_dt(current.get("recorded_at")) if current else None
        if current_dt is None or (run_dt is not None and run_dt >= current_dt):
            latest_per_wallet[wallet_name] = run

    wallet_signals: list[dict[str, Any]] = []
    for wallet_name, run in latest_per_wallet.items():
        recorded_at = _parse_dt(run.get("recorded_at"))
        wallet_signals.append({
            "wallet_name": wallet_name,
            "display_name": strategy_kr(wallet_name),
            "strategy_type": str(run.get("strategy_type", _strategy_key(wallet_name))),
            "action": str(run.get("signal_action", "hold")),
            "confidence": float(run.get("signal_confidence", 0.0) or 0.0),
            "reason": str(run.get("signal_reason", "")),
            "symbol": str(run.get("symbol", "")),
            "symbol_display": symbol_kr(str(run.get("symbol", ""))) if run.get("symbol") else "",
            "regime": str(run.get("market_regime", "")),
            "regime_label": regime_kr(str(run.get("market_regime", "")))
            if run.get("market_regime")
            else "",
            "latest_price": float(run.get("latest_price", 0.0) or 0.0),
            "timestamp": recorded_at.isoformat() if recorded_at else "",
        })

    wallet_signals.sort(key=lambda s: s["timestamp"], reverse=True)

    # Strategy x Regime signal count matrix
    strategy_regime_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for run in runs[-500:]:
        strategy = str(run.get("strategy_type", ""))
        regime = str(run.get("market_regime", ""))
        action = str(run.get("signal_action", "hold"))
        if strategy and regime and action != "hold":
            strategy_regime_matrix[strategy_kr(strategy)][regime_kr(regime)] += 1

    strategies = sorted(strategy_regime_matrix.keys())
    regimes = sorted(
        {regime for counts in strategy_regime_matrix.values() for regime in counts}
    )
    heatmap_z: list[list[int]] = []
    for strategy in strategies:
        heatmap_z.append([strategy_regime_matrix[strategy].get(r, 0) for r in regimes])

    # Signal timeline (last 60 non-hold signals)
    timeline: list[dict[str, Any]] = []
    for run in reversed(runs[-300:]):
        action = str(run.get("signal_action", "hold"))
        if action == "hold":
            continue
        recorded_at = _parse_dt(run.get("recorded_at"))
        wallet_name = _run_wallet_name(run, wallet_states)
        timeline.append({
            "timestamp": recorded_at.isoformat() if recorded_at else "",
            "display_name": strategy_kr(wallet_name),
            "action": action,
            "confidence": float(run.get("signal_confidence", 0.0) or 0.0),
            "symbol_display": symbol_kr(str(run.get("symbol", ""))) if run.get("symbol") else "",
            "regime_label": regime_kr(str(run.get("market_regime", "")))
            if run.get("market_regime")
            else "",
        })
        if len(timeline) >= 60:
            break

    return {
        "wallet_signals": wallet_signals,
        "strategies": strategies,
        "regimes": regimes,
        "heatmap_z": heatmap_z,
        "timeline": timeline,
        "active_buy_count": sum(1 for s in wallet_signals if s["action"] == "buy"),
        "active_sell_count": sum(1 for s in wallet_signals if s["action"] == "sell"),
        "active_hold_count": sum(1 for s in wallet_signals if s["action"] == "hold"),
    }
