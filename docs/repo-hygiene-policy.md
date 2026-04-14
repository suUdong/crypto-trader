# Repo Hygiene Policy

## Purpose

Keep active product/runtime code reviewable while allowing research-heavy exploration to continue without burying real changes in noise.

## Active vs Generated Surfaces

### Actively maintained code

- `src/`
- `dashboard/`
- selected entrypoints in `scripts/`
- `tests/`
- focused plans under `.omx/plans/`

Changes in these paths should stay small, reviewable, and directly tied to a roadmap or PRD.

### Generated or operator-local outputs

- `artifacts/`
- `.omx/state/`
- `.omx/context/`
- `logs/`
- config backups such as `config/daemon.toml.bak.*`
- session handoff notes such as `docs/SESSION_HANDOFF.md` and `docs/session-handoff-*.md`

These should not be relied on as the canonical source of project behavior.

### Research history

- dated research notes under `docs/research/`
- one-off experiment scripts under `scripts/` that exist only to capture a single cycle or validation pass

Research history is useful, but it must not dominate the active maintenance surface.

## Placement Rules

1. New production/runtime behavior belongs in `src/`, not in loop scripts.
2. New dashboard data shaping belongs in reusable modules, not only inside `dashboard/app.py`.
3. One-off experiment outputs should prefer:
   - `docs/research/<date>-<topic>/`
   - `artifacts/`
   - archived research scripts or manifest-driven runners
4. Local backups and handoff files should remain untracked unless explicitly promoted into durable documentation.
5. If a plan is superseded, add that fact to a roadmap index instead of leaving overlapping PRDs ambiguous.

## Review Rules

1. Before broad cleanup, capture the current worktree state.
2. Before refactoring active code, lock behavior with targeted tests when behavior is not already protected.
3. Prefer extracting reusable logic from `scripts/` into `src/` before adding more script-specific branches.
4. Prefer deletion over keeping duplicate historical helpers in active paths.

## Immediate Follow-Ups

1. Maintain a roadmap status index under `.omx/plans/`.
2. Keep ignore patterns narrow and limited to clearly local or backup artifacts.
3. Reduce the number of “active” top-level scripts by moving repeated patterns behind shared runners or manifests.

