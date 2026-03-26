"""Helpers for artifact freshness and consistency summaries."""
from __future__ import annotations

from datetime import datetime

from crypto_trader.operator.pnl_report import PortfolioPnLReport


def parse_iso8601(timestamp: str) -> datetime | None:
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_age(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def compute_artifact_age_seconds(report_generated_at: str, artifact_generated_at: str) -> float | None:
    report_dt = parse_iso8601(report_generated_at)
    artifact_dt = parse_iso8601(artifact_generated_at)
    if report_dt is None or artifact_dt is None:
        return None
    return max(0.0, (report_dt - artifact_dt).total_seconds())


def summarize_artifact_health(report: PortfolioPnLReport) -> dict[str, float | str | int | bool]:
    heartbeat_age_seconds = compute_artifact_age_seconds(report.generated_at, report.heartbeat_generated_at)
    checkpoint_age_seconds = compute_artifact_age_seconds(report.generated_at, report.source_generated_at)
    heartbeat_threshold = max(300, report.heartbeat_poll_interval_seconds * 5) if report.heartbeat_poll_interval_seconds > 0 else 300
    checkpoint_threshold = max(900, report.heartbeat_poll_interval_seconds * 15) if report.heartbeat_poll_interval_seconds > 0 else 900

    heartbeat_freshness = (
        "unknown" if heartbeat_age_seconds is None else
        "stale" if heartbeat_age_seconds > heartbeat_threshold else
        "fresh"
    )
    checkpoint_freshness = (
        "unknown" if checkpoint_age_seconds is None else
        "stale" if checkpoint_age_seconds > checkpoint_threshold else
        "fresh"
    )

    if heartbeat_freshness == "stale" and checkpoint_freshness == "stale":
        freshness_status = "stale_artifacts"
        freshness_reason = "checkpoint and heartbeat are older than freshness thresholds"
    elif heartbeat_freshness == "stale":
        freshness_status = "stale_heartbeat"
        freshness_reason = "heartbeat is older than freshness threshold"
    elif checkpoint_freshness == "stale":
        freshness_status = "stale_checkpoint"
        freshness_reason = "checkpoint is older than freshness threshold"
    else:
        freshness_status = "fresh"
        freshness_reason = "checkpoint and heartbeat are within freshness thresholds"

    consistency_status = report.artifact_consistency_status or "unknown"
    consistency_ok = consistency_status == "consistent"
    healthy = consistency_ok and freshness_status == "fresh"
    headline_status = consistency_status if not consistency_ok else freshness_status

    return {
        "healthy": healthy,
        "headline_status": headline_status,
        "consistency_status": consistency_status,
        "consistency_reason": report.artifact_consistency_reason or "n/a",
        "checkpoint_age_seconds": checkpoint_age_seconds if checkpoint_age_seconds is not None else -1.0,
        "heartbeat_age_seconds": heartbeat_age_seconds if heartbeat_age_seconds is not None else -1.0,
        "checkpoint_age_display": format_age(checkpoint_age_seconds),
        "heartbeat_age_display": format_age(heartbeat_age_seconds),
        "checkpoint_freshness": checkpoint_freshness,
        "heartbeat_freshness": heartbeat_freshness,
        "freshness_status": freshness_status,
        "freshness_reason": freshness_reason,
        "heartbeat_poll_interval_seconds": report.heartbeat_poll_interval_seconds,
    }
