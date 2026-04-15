# CI/CD Pipeline Design: Lightsail Auto-Deploy

**Date:** 2026-04-14
**Status:** Approved

## Overview

master push 시 CI 통과 후 Lightsail ct-prod-01에 자동 배포하는 CD 파이프라인.
컷오버 전까지 비활성화 상태로 준비.

## Architecture

```
push to master
  → CI job (lint + type + test)  [기존 ci.yml]
  → Deploy job (rsync → pip install → restart)  [신규 deploy.yml]
```

## CI (기존 유지)

`ci.yml` 변경 없음. ruff + mypy (continue-on-error) + pytest blacklist 방식.

## CD: deploy.yml

### Trigger

- `push` to `master`, CI `test` job 통과 후 (`needs: test`)

### Steps

1. **Checkout** — actions/checkout
2. **SSH key setup** — GitHub Secret → `~/.ssh/deploy_key`
3. **rsync** — 소스 동기화 to `crypto@52.78.228.194:/home/crypto/crypto-trader/`
4. **Remote commands** (ssh):
   - `cd /home/crypto/crypto-trader && pip install -e .`
   - `sudo systemctl restart crypto-trader`
5. **Health check** — 10초 대기 후 `systemctl is-active crypto-trader` 확인

### rsync Exclude List (`scripts/deploy/rsync-exclude.txt`)

```
.git/
.github/
.claude/
.worktrees/
tests/
docs/
dashboard/
scripts/hooks/
config/daemon.toml
*.db
*.jsonl
__pycache__/
.mypy_cache/
.ruff_cache/
*.pyc
.env
프롬프트
```

### GitHub Secrets

| Secret | Value |
|---|---|
| `LIGHTSAIL_SSH_KEY` | `~/.ssh/lightsail_crypto_trader.pem` 내용 |
| `LIGHTSAIL_HOST` | `52.78.228.194` |
| `LIGHTSAIL_USER` | `crypto` |

### Safety

- CI 실패 → 배포 안 함 (`needs: test`)
- `concurrency: group: deploy, cancel-in-progress: false` — 동시 배포 방지, 진행 중이면 큐잉
- 서버 config/데이터 파일 rsync exclude로 보호
- 컷오버 전: `if: false` 주석으로 비활성화

## File Changes

| File | Action |
|---|---|
| `.github/workflows/deploy.yml` | 신규 생성 |
| `scripts/deploy/rsync-exclude.txt` | 신규 생성 |
| `.github/workflows/ci.yml` | 변경 없음 |
