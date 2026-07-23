# Research Phase + Skill Release Checklist

This checklist is for releasing Research video frame pagination/range playback, Phase Annotation, and Skill Assessment in this repository. It intentionally stops before destructive rollback decisions and assumes the production database is PostgreSQL from `docker-compose.yml`.

## A. Pre-Release

1. Schedule a maintenance window and block new annotation writes before migration.
2. Record the exact code state:
   - `git rev-parse HEAD`
   - `git status --short`
   - `git diff --stat`
3. Record the Alembic state without upgrading:
   - `cd backend`
   - `../../conda_envs/sam/bin/python -m alembic -c alembic.ini heads`
   - `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 ../../conda_envs/sam/bin/python -m alembic -c alembic.ini current`
4. Confirm the production database target from runtime environment, not from memory:
   - `docker compose ps`
   - `docker compose exec -T db psql -U "${POSTGRES_USER:-med_annotate}" -d "${POSTGRES_DB:-med_annotate}" -c "select current_database(), inet_server_addr(), inet_server_port();"`
5. Record database size:
   - `docker compose exec -T db psql -U "${POSTGRES_USER:-med_annotate}" -d "${POSTGRES_DB:-med_annotate}" -c "select pg_size_pretty(pg_database_size(current_database()));"`
6. Check available disk space for database and backup destinations:
   - `df -h . backups storage`
   - `docker compose exec -T db df -h /var/lib/postgresql/data`
7. Record running services:
   - `docker compose ps`
   - `./scripts/backend_tmux_status.sh`
   - `ss -ltnp | grep ':8000\|:5173\|:5433'`
8. Export a compose config summary without secrets:
   - `docker compose config --services`
   - `docker compose config | sed -E 's/(POSTGRES_PASSWORD: ).*/\1<redacted>/'`
9. Confirm no active annotation writes with the team. Do not rely on frontend inactivity alone.

## B. Backup

PostgreSQL production backup is the expected path for this repository:

1. Stop or block application writes. Prefer maintenance mode plus stopping backend writes before `pg_dump`.
2. Create a timestamped backup under a controlled backup path, for example:
   - `mkdir -p backups/release_$(date +%Y%m%d_%H%M%S)`
   - `docker compose exec -T db pg_dump -U "${POSTGRES_USER:-med_annotate}" -d "${POSTGRES_DB:-med_annotate}" --format=custom --file=/tmp/med_annotate_phase_skill_release.dump`
   - `docker cp med-annotate-gpu-db:/tmp/med_annotate_phase_skill_release.dump backups/.../med_annotate_phase_skill_release.dump`
3. Verify the backup is readable:
   - `pg_restore --list backups/.../med_annotate_phase_skill_release.dump | head`
4. Record checksum:
   - `sha256sum backups/.../med_annotate_phase_skill_release.dump > backups/.../SHA256SUMS`
5. Verify the backup revision by restoring to an isolated database or by separately recording production `alembic current`.

If a future deployment uses SQLite instead of this compose Postgres:

1. Fully stop writes before copying.
2. Prefer SQLite backup API: `sqlite3 production.db ".backup 'backups/.../production.db'"`.
3. If copying files directly, copy `production.db`, `production.db-wal`, and `production.db-shm` together while writes are stopped.
4. Run `sqlite3 backups/.../production.db "pragma integrity_check;"`.
5. Record `sha256sum` for all copied files.
6. Verify `select version_num from alembic_version;` on the backup.

Do not perform a production backup as part of a dry run.

## C. Migration

Expected Alembic head after release: `20260722_0015`.

Safe stepwise path:

1. Check heads:
   - `cd backend`
   - `../../conda_envs/sam/bin/python -m alembic -c alembic.ini heads`
2. Check current:
   - `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 ../../conda_envs/sam/bin/python -m alembic -c alembic.ini current`
3. Upgrade Phase migration:
   - `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 ../../conda_envs/sam/bin/python -m alembic -c alembic.ini upgrade 20260722_0014`
4. Verify Phase tables and defaults:
   - `research_phase_protocols`
   - `research_phase_labels`
   - `research_phase_annotation_sets`
   - `research_phase_segments`
   - `select count(*) from research_phase_protocols;`
   - `select count(*) from research_phase_labels;` must be `13`.
5. Upgrade Skill migration:
   - `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 ../../conda_envs/sam/bin/python -m alembic -c alembic.ini upgrade 20260722_0015`
6. Verify Skill tables:
   - `research_skill_rubrics`
   - `research_skill_criteria`
   - `research_skill_criterion_phase_labels`
   - `research_skill_assessments`
   - `research_skill_scores`
   - `research_skill_evidence`
7. Confirm Skill default rubric count is `0`:
   - `select count(*) from research_skill_rubrics;`
8. Confirm current is head:
   - `../../conda_envs/sam/bin/python -m alembic -c alembic.ini current`
9. Run the read-only verifier:
   - `PYTHONPATH=. ../../conda_envs/sam/bin/python scripts/verify_research_phase_skill_release.py`

Single-command migration is acceptable only after backup and write blocking:

```bash
cd backend
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 ../../conda_envs/sam/bin/python -m alembic -c alembic.ini upgrade head
PYTHONPATH=. ../../conda_envs/sam/bin/python scripts/verify_research_phase_skill_release.py
```

## D. Deployment Order

Recommended order for this repository:

1. Enter maintenance mode or otherwise block writes.
2. Backup database and verify the backup.
3. Run migrations to `20260722_0015`.
4. Restart backend via tmux script:
   - `./scripts/backend_tmux_stop.sh`
   - `SKIP_ALEMBIC=true ./scripts/backend_tmux_start.sh`
5. Verify backend health and OpenAPI:
   - `curl -fsS http://127.0.0.1:8000/`
   - `curl -fsS http://127.0.0.1:8000/openapi.json | grep '/api/research'`
6. Build and restart frontend service:
   - `docker compose build frontend`
   - `docker compose up -d frontend`
7. Frame smoke test:
   - Research video list loads.
   - Video file returns HTTP `206` with `Content-Range`.
   - Frame metadata uses `/frames?offset=&limit=`.
   - Existing rectangle/polygon annotations still display.
8. Phase smoke test:
   - Open `/research/videos/{videoId}/phases`.
   - Create/open annotation set.
   - Transition, validate, export JSON.
9. Skill smoke test:
   - Open `/research/videos/{videoId}/skills`.
   - Open Rubric Manager.
   - Confirm no default Skill rubric exists unless created by a user.
10. Restore writes after smoke tests pass.

## E. Post-Release Checks

Run:

```bash
cd backend
PYTHONPATH=. ../../conda_envs/sam/bin/python scripts/verify_research_phase_skill_release.py
```

Also verify:

1. `alembic current` is `20260722_0015`.
2. Phase Protocol count is at least `1`.
3. Phase Label count is exactly `13`.
4. Skill Rubric count is expected for the site. Fresh migration should be `0`.
5. Existing video count is unchanged.
6. Existing frame/spatial annotation counts are unchanged.
7. Frame page loads and video Range returns `206`.
8. Phase page loads without requesting spatial annotation APIs.
9. Skill page loads without requesting spatial annotation APIs.
10. JSON/CSV exports download with UTF-8 filenames.
11. Backend logs show no startup traceback.
12. Browser console has no uncaught exception.

## F. Rollback

Decision tree:

1. Frontend-only issue:
   - Roll back frontend image/source and run `docker compose up -d frontend`.
   - Keep migrated database unchanged.
2. Backend code issue with migrations already applied:
   - Prefer rolling back backend code or disabling new UI entry points.
   - Keep Phase/Skill tables if any user may have written new data.
3. Migration issue before any Phase/Skill data is written:
   - Consider `alembic downgrade 20260722_0014` to remove Skill tables.
   - Consider `alembic downgrade 20260630_0013` to remove Phase and Skill tables.
4. Migration issue after Phase/Skill data is written:
   - Do not downgrade just to remove tables; it will drop user data.
   - Prefer code rollback while preserving new tables.
   - Restore from backup only if the release owner accepts losing post-backup writes.
5. Full database restore:
   - Stop writes and backend.
   - Restore the verified backup into a clean database.
   - Verify checksum/listing and Alembic revision.
   - Restart backend and frontend.

Never run downgrade on production without confirming whether new Phase/Skill data exists.
