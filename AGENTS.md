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

## Verification And Reports

Run focused tests and the relevant full suite where feasible. Frontend changes require frontend tests, `vue-tsc`, build, and `git diff --check`. Migration changes require the migration test matrix.

Every deployment report must state app version, Git commit, Alembic revision, backup path and verification, migration and storage-migration status, backend/frontend health, tests, and `git status`.
