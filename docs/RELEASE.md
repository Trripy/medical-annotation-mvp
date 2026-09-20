# Releases and Production Updates

This repository serves real medical annotation data. A normal development task is never a production release. Only an explicit request to deploy, release, update, publish, or roll out production code permits the workflow below.

## Version model

`VERSION` is SemVer (`MAJOR.MINOR.PATCH`). During the MVP period, use `0.x.y`: patches are compatible fixes and minors are additive features or schema additions. A formal Git tag must be `v` plus the exact `VERSION`; validate it with `scripts/release/check_version_tag.sh`. Record user-facing changes in `CHANGELOG.md` and use `.github/RELEASE_TEMPLATE.md` for release notes.

## Architecture

Production PostgreSQL and the frontend run through Docker Compose. The FastAPI backend runs on the host Conda environment in tmux, with host SAM2 and FFmpeg. `LOCAL_STORAGE_ROOT` contains irreplaceable files. Runtime configuration is loaded from the existing backend environment; release scripts do not print secrets or copy `.env`.

## Release types

1. **Code-only**: compatible frontend/backend change with no migration or storage change.
2. **Additive database**: additive table, nullable column, or index. It requires a verified database backup and an explicit production deployment request.
3. **Data or storage migration**: renames, moves, deletes, rebuilds, or rewrites data/files. This is highest risk and requires separate explicit approval, a full verified storage snapshot, a rollback plan, and `STORAGE_MIGRATION=1`.

Never use Alembic downgrade as a substitute for restoring production data.

## Standard deployment

`scripts/release/deploy.sh` assumes the working tree already contains the release code. It never pulls, checks out, resets, cleans, tags, or pushes Git. It obtains an exclusive `flock`, runs precheck, creates and verifies a PostgreSQL custom-format dump, stops the backend to prevent writes, updates dependencies, runs `alembic upgrade head`, deploys frontend/backend, then runs read-only smoke tests. A failure stops the workflow and records a result beside the backup; it never auto-restores a database.

```bash
scripts/release/precheck.sh
scripts/release/deploy.sh --target-version "$(cat VERSION)"
```

Production deploy defaults to `REQUIRE_DEEP_BACKUP_VERIFY=1`. A dirty worktree fails precheck. `ALLOW_DIRTY_RELEASE=1` is only for an explicitly approved exceptional release.

## Backup and verification

`backup.sh` writes to `backups/releases/<timestamp>_v<version>/` and creates a PostgreSQL `pg_dump -Fc` file plus a non-sensitive `manifest.json`. The manifest records version, Git metadata, DB revisions, database name, storage path, and reason, never passwords or `.env` values.

```bash
scripts/release/backup.sh --reason "pre-release v$(cat VERSION)"
scripts/release/verify_backup.sh backups/releases/<timestamp>_v<version>
scripts/release/verify_backup.sh --deep backups/releases/<timestamp>_v<version>
```

Normal verification reads the custom dump catalogue. Deep verification restores into a generated temporary database, checks Alembic and key tables, and removes only that generated test database. Do not run backups or deep verification against production merely to test a script without an explicit request.

Storage is not copied by default. `--storage-manifest` records its size and file count. `--storage-full` requires `CONFIRM_STORAGE_BACKUP=YES`; a storage-changing release additionally requires an explicitly supplied full-backup manifest.

## Smoke test and version metadata

`scripts/release/smoke_test.sh` is read-only and checks `/api/v1/health`, `/api/v1/version`, the frontend SPA, frontend Compose service, and backend tmux session. `GET /api/v1/version` returns best-effort version, Git, current DB revision, and code DB head; missing Git metadata returns `null` or `APP_GIT_COMMIT` fallback rather than a 500.

## Rollback and disaster recovery

`scripts/release/rollback_code.sh --check <git-ref>` is inspection-only. Verify DB compatibility before a human performs any code checkout and redeploy.

`restore_database.sh` is a guarded disaster-recovery tool, not a normal release command. It requires the exact environment confirmation `CONFIRM_PRODUCTION_DB_RESTORE=RESTORE_PRODUCTION_DATABASE`, requires the backend to be stopped, creates an emergency logical backup first, and restores only the selected database dump. It does not restore storage or start services afterwards.

## Staging

Use a separately configured staging environment before risky releases where practical, for example frontend `5174`, backend `8001`, and PostgreSQL `5434`. Staging is deliberately not created by these scripts.

## Dry runs

`DRY_RUN=1` is available for precheck, backup planning, deploy planning, and restore planning. It must never stop services, write backups, run migrations, or change data.
