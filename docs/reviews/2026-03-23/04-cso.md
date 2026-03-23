# /cso — Security Posture Report

Status: DONE_WITH_CONCERNS
Date: 2026-03-23
Scope: full current codebase

## Executive Summary

This codebase currently has a **low direct attack surface** because it is:

- a local/runtime CLI, not a public web service
- paper-trading only
- not exposing authentication, session, or multi-tenant data boundaries

I found **no CRITICAL or HIGH confidence application vulnerabilities** in the current implementation.

I found **one MEDIUM-confidence supply-chain finding** that matters because this project is intended for financial operations.

## Attack Surface Map

```
Public endpoints:       0
Authenticated routes:   0
Admin-only routes:      0
File upload points:     0
WebSocket channels:     0
Background jobs:        0
External integrations:  2
  - Upbit market data via pyupbit
  - Telegram Bot API outbound notifications
```

## Findings

### Finding 1: Non-deterministic production dependency resolution

- Severity: MEDIUM
- Confidence: 8/10
- Category: Supply chain / software integrity
- OWASP: A08, A06
- File: `pyproject.toml:14`, `Dockerfile:12-13`

Description:

The production container installs the `live` extra at build time, and that extra allows any `pyupbit` version at or above `0.2.33`. This means a later upstream release can silently change the runtime dependency set for future builds without any review or lock step.

Exploit scenario:

1. An attacker compromises the upstream package or a malicious release is published.
2. A later `docker build` runs `pip install .[live]`.
3. The build pulls the new dependency version automatically.
4. The compromised package executes in the runtime environment of a financial trading system.

Impact:

- unreviewed code enters production builds
- behavior can drift between builds
- a compromised dependency could exfiltrate environment secrets or alter trading behavior

Recommendation:

- pin live/runtime dependency versions exactly or via a reviewed lock file
- make container builds reproducible
- treat dependency upgrades as explicit reviewed changes, not background drift

## What I Explicitly Did Not Report

These did not meet the zero-noise threshold for a real vulnerability in the current codebase:

- missing rate limits
- missing auth/session controls
- missing admin audit logs
- SSRF on Telegram URLs
- generic “live trading secret management” concerns while live trading is disabled

Those are future concerns if the product becomes a network-facing or live-execution system. They are not current unlocked doors.

## Security Posture Assessment

### Strong choices

- paper mode is enforced rather than implied
- API keys are expected via environment/config, not hardcoded
- attack surface is outbound-only today
- current runtime is single-tenant and operator-local in shape

### Watch items for the next product stage

1. Reproducible dependency locking before any real-money mode
2. Secret rotation and storage policy before any live execution path
3. Durable audit trail for every operator action and trade-state transition
4. Clear separation between market-data credentials, execution credentials, and notification credentials

## Verdict

Current posture:

> acceptable for a paper-trading prototype with one medium supply-chain concern to fix before the system graduates into anything capital-sensitive

## Disclaimer

This audit reviewed the codebase and build/config surfaces available locally. It did not include dynamic penetration testing, live exchange interaction, or external infrastructure verification.
