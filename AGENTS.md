# Medical Annotation MVP Codex Instructions

## Repository

This repository is deployed at `/data1/zhangyuzhu/code/autoannotate/medical-annotation-mvp-gpu` and stores real medical annotation data in production.

## Production Data

Production data is irreplaceable. Never automatically delete annotations, videos, storage, user files, tables, or databases. Never run destructive migrations, `git reset --hard`, or `git clean`.

## Git

Never commit, push, tag, stash, reset, clean, or rewrite history unless the user explicitly requests it. Preserve unrelated dirty worktree changes.

## Database

Before a schema change, inspect Alembic current and heads, require one head, prefer additive migrations, and test from-scratch, previous-to-new, downgrade, and re-upgrade in a temporary database. Never edit `alembic_version` manually. Production migrations require an explicit deployment request.

See `backend/AGENTS.md` for backend-specific data rules.

## Production Releases

Only deploy when the user explicitly requests deployment, release, update, publish, or rollout to production. Ordinary development completion is not a deployment request.

For an explicit production release, use the repository workflow in `docs/RELEASE.md` and these scripts instead of inventing an ad-hoc command sequence:

1. `scripts/release/precheck.sh`
2. `scripts/release/backup.sh`
3. `scripts/release/verify_backup.sh`
4. `scripts/release/deploy.sh`
5. `scripts/release/smoke_test.sh`

Before a production database migration, a verified backup is mandatory. Do not use `ALLOW_DIRTY_RELEASE=1` unless the user explicitly approves it.

## Storage

`LOCAL_STORAGE_ROOT` contains user data. Code-only releases must not modify storage files. Any move, rename, deletion, rebuild, or layout change is a Storage Migration and requires explicit approval, a storage backup or snapshot, and a rollback plan before production execution.

## Rollback

Prefer code rollback for code-only regressions when the schema remains compatible. Do not assume Alembic downgrade restores data. Production database restore requires explicit user confirmation and a verified pre-release backup.

## Test Strategy

Use staged testing to avoid unnecessary runtime and context usage while preserving release quality.

### During Development

Run the smallest test set that can falsify the current change.

- Run only tests directly related to the files or feature being changed.
- Prefer targeted unit, component, API, or integration tests first.
- For TypeScript and Vue changes, run `vue-tsc` after meaningful code changes, not after every tiny edit.
- Do not repeatedly run the full frontend or backend suite after every small change.
- Do not repeatedly rebuild unchanged containers just to rerun a small unit test when a lighter local or container test path is available.

### Before Declaring A Feature Complete

Run broader validation once the feature is stabilizing. Use this order where applicable:

1. targeted tests for the changed feature;
2. type checking;
3. the relevant full test suite once;
4. one production build;
5. `git diff --check`.

For an ordinary frontend feature, the default completion path is:

1. targeted frontend test or tests;
2. `vue-tsc`;
3. full frontend suite once;
4. frontend build once;
5. `git diff --check`.

For an ordinary backend feature, the default completion path is:

1. targeted backend test or tests;
2. relevant integration tests;
3. full backend suite once;
4. `git diff --check`.

For a migration feature, keep the stricter database validation path:

1. targeted backend tests;
2. migration matrix;
3. full backend suite once;
4. `git diff --check`.

Migration work must still include from-scratch, previous-to-new, downgrade, and re-upgrade validation in a temporary database. Do not reduce database safety, migration validation, production release safety, storage safety, or data integrity checks for speed.

### Production Release Validation

When the user explicitly requests a production release, deployment, update, publish, or rollout, run the required full backend and frontend suites again, run the required production build, run release precheck, run backup and backup verification, and run smoke tests after deployment.

A second frontend build is not a default development requirement. Only run a second build when validating release reproducibility, investigating a flaky build, following an explicit release checklist, or when the user explicitly requests it.

### Test Output And Context Efficiency

Prefer quiet test output. Use `pytest -q` or equivalent concise modes when practical.

Do not stream verbose successful test logs into the conversation. On success, summarize only the important result, for example:

- `Frontend: 282 passed`
- `Backend: 417 passed`
- `vue-tsc: passed`
- `Build: passed`

On failure, inspect and report only the relevant failing section and enough surrounding context to diagnose the issue. Use targeted reruns, `tail`, or `grep` when that is the fastest way to isolate the problem.

Context efficiency is not a reason to ignore failures. If a test fails, find the cause, rerun targeted checks when useful, fix the issue, and verify the fix. Avoid repeatedly rereading successful logs that are already known, and avoid rerunning the same expensive full-suite validation multiple times in one development cycle unless code changed in a way that justifies it.

## Verification And Reports

Every deployment report must state app version, Git commit, Alembic revision, backup path and verification, migration and storage-migration status, backend/frontend health, tests, and `git status`.
