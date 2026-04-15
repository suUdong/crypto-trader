# CI/CD Deploy Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** master push 시 CI 통과 후 Lightsail ct-prod-01에 rsync 자동 배포하는 CD 파이프라인 구축 (컷오버 전 비활성화 상태로 준비).

**Architecture:** 기존 `ci.yml`의 `test` job을 재사용하고, 새 `deploy.yml` workflow에서 `test` job 통과 후 rsync → pip install → systemctl restart 순서로 배포. rsync exclude 파일로 서버 config/데이터 보호.

**Tech Stack:** GitHub Actions, rsync, SSH, systemd

---

## File Structure

| File | Responsibility |
|---|---|
| `.github/workflows/deploy.yml` | CD workflow — CI 재사용 + deploy job |
| `scripts/deploy/rsync-exclude.txt` | rsync 제외 목록 (서버 config/데이터 보호) |

---

### Task 1: rsync exclude 파일 생성

**Files:**
- Create: `scripts/deploy/rsync-exclude.txt`

- [ ] **Step 1: Create the exclude file**

```bash
mkdir -p scripts/deploy
```

Write `scripts/deploy/rsync-exclude.txt`:

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

- [ ] **Step 2: Verify the file**

```bash
cat scripts/deploy/rsync-exclude.txt
wc -l scripts/deploy/rsync-exclude.txt
```

Expected: 17 lines, readable content.

- [ ] **Step 3: Commit**

```bash
git add scripts/deploy/rsync-exclude.txt
git commit -m "chore(deploy): add rsync exclude list for Lightsail deploy"
```

---

### Task 2: deploy.yml workflow 생성

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Create the deploy workflow**

Write `.github/workflows/deploy.yml`:

```yaml
name: deploy

on:
  push:
    branches: [master]

permissions:
  contents: read

concurrency:
  group: deploy
  cancel-in-progress: false

jobs:
  test:
    name: lint + type + test
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2

      - name: Setup Python
        uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Lint (ruff)
        run: ruff check src/ tests/

      - name: Type check (mypy, warnings only)
        run: mypy src/
        continue-on-error: true

      - name: Test (all except blacklist)
        run: |
          pytest tests/ \
            --ignore=tests/test_backtest_all_cli.py \
            --ignore=tests/test_backtest_engine.py \
            --ignore=tests/test_backtest_engine_entry.py \
            --ignore=tests/test_backtest_strategy_sweep.py \
            --ignore=tests/test_walk_forward.py \
            --ignore=tests/test_walk_forward_cli.py \
            --ignore=tests/test_walk_forward_summary.py \
            --ignore=tests/test_default_walk_forward_all.py \
            --ignore=tests/test_grid_search.py \
            --ignore=tests/test_grid_wf.py \
            --ignore=tests/test_gpu_backtest.py \
            --ignore=tests/test_gpu_correlation.py \
            --ignore=tests/test_gpu_features.py \
            --ignore=tests/test_extended_alpha.py \
            --ignore=tests/test_dashboard.py \
            --ignore=tests/test_regime_report.py \
            --ignore=tests/test_ml_regime.py \
            -q

  deploy:
    name: deploy to lightsail
    needs: test
    runs-on: ubuntu-latest
    # ── DISABLED until cutover ──
    # Remove `if: false` when ct-prod-01 is ready for production traffic.
    if: false
    timeout-minutes: 5

    steps:
      - name: Checkout
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2

      - name: Setup SSH key
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.LIGHTSAIL_SSH_KEY }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan -H ${{ secrets.LIGHTSAIL_HOST }} >> ~/.ssh/known_hosts

      - name: Rsync to server
        run: |
          rsync -azP --delete \
            --exclude-from=scripts/deploy/rsync-exclude.txt \
            ./ \
            ${{ secrets.LIGHTSAIL_USER }}@${{ secrets.LIGHTSAIL_HOST }}:/home/${{ secrets.LIGHTSAIL_USER }}/crypto-trader/
        env:
          RSYNC_RSH: "ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=no"

      - name: Install and restart
        run: |
          ssh -i ~/.ssh/deploy_key \
            ${{ secrets.LIGHTSAIL_USER }}@${{ secrets.LIGHTSAIL_HOST }} \
            'cd /home/${{ secrets.LIGHTSAIL_USER }}/crypto-trader && \
             pip install -e . && \
             sudo systemctl restart crypto-trader'

      - name: Health check
        run: |
          sleep 10
          ssh -i ~/.ssh/deploy_key \
            ${{ secrets.LIGHTSAIL_USER }}@${{ secrets.LIGHTSAIL_HOST }} \
            'systemctl is-active crypto-trader'
```

- [ ] **Step 2: Validate YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))"
```

Expected: no error (Python yaml parses without exception).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci(deploy): add Lightsail auto-deploy workflow (disabled until cutover)"
```

---

### Task 3: GitHub Secrets 설정 안내 문서

**Files:**
- Create: `scripts/deploy/README.md`

- [ ] **Step 1: Write the setup guide**

Write `scripts/deploy/README.md`:

```markdown
# Lightsail Deploy Setup

## GitHub Secrets (required)

Go to repo Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `LIGHTSAIL_SSH_KEY` | Contents of `~/.ssh/lightsail_crypto_trader.pem` |
| `LIGHTSAIL_HOST` | `52.78.228.194` |
| `LIGHTSAIL_USER` | `crypto` |

## Server prerequisites

1. `crypto` user exists with sudo access for `systemctl restart crypto-trader`
2. `crypto-trader.service` systemd unit installed
3. Python 3.12 venv active for `crypto` user
4. rsync installed (`sudo apt install rsync`)

## Activating deployment

Remove `if: false` from `.github/workflows/deploy.yml` deploy job when ready.
```

- [ ] **Step 2: Commit**

```bash
git add scripts/deploy/README.md
git commit -m "docs(deploy): add Lightsail deploy setup guide"
```

---

### Task 4: 검증

- [ ] **Step 1: CI workflow 로컬 검증 — YAML 파싱**

```bash
python -c "
import yaml
for f in ['.github/workflows/ci.yml', '.github/workflows/deploy.yml']:
    yaml.safe_load(open(f))
    print(f'{f}: OK')
"
```

Expected: both OK.

- [ ] **Step 2: rsync dry-run 로컬 테스트**

```bash
rsync -azPn --delete \
  --exclude-from=scripts/deploy/rsync-exclude.txt \
  ./ /tmp/crypto-trader-deploy-test/ 2>&1 | tail -5
```

Expected: dry-run shows file list without `.git/`, `tests/`, `*.db`, `config/daemon.toml` etc.

- [ ] **Step 3: Confirm deploy job is disabled**

```bash
grep -n "if: false" .github/workflows/deploy.yml
```

Expected: line with `if: false` found in deploy job.

- [ ] **Step 4: Run existing CI checks**

```bash
ruff check src/ tests/ && pytest tests/ -x -q --ignore=tests/test_backtest_all_cli.py --ignore=tests/test_backtest_engine.py --ignore=tests/test_backtest_engine_entry.py --ignore=tests/test_backtest_strategy_sweep.py --ignore=tests/test_walk_forward.py --ignore=tests/test_walk_forward_cli.py --ignore=tests/test_walk_forward_summary.py --ignore=tests/test_default_walk_forward_all.py --ignore=tests/test_grid_search.py --ignore=tests/test_grid_wf.py --ignore=tests/test_gpu_backtest.py --ignore=tests/test_gpu_correlation.py --ignore=tests/test_gpu_features.py --ignore=tests/test_extended_alpha.py --ignore=tests/test_dashboard.py --ignore=tests/test_regime_report.py --ignore=tests/test_ml_regime.py
```

Expected: all pass, no regressions.
